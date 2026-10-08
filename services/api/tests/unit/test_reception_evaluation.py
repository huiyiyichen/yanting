import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import REPO_ROOT, Settings
from app.domain.case_state.models import Base
from app.domain.platform.models import PromptTemplateRow, RuntimeSettingRow
from app.domain.platform.settings import (
    ensure_builtin_templates,
    get_enabled_template,
    set_setting,
)
from app.evaluation.reception_runtime import (
    PROMPT_PURPOSES,
    apply_prompt_snapshot,
    configured_prompts,
    configured_settings,
    isolated_settings,
    readonly_configuration,
    source_fingerprints,
)


def test_isolated_evaluation_rejects_existing_outside_and_active_paths(tmp_path):
    base = Settings(run_mode="live")
    for path in [REPO_ROOT / "data/runtime", base.runtime_path, base.qdrant_path_resolved, tmp_path]:
        with pytest.raises(ValueError):
            isolated_settings(base, path)
    existing = REPO_ROOT / "data/runtime"
    with pytest.raises(ValueError):
        isolated_settings(base, existing)


def test_new_runtime_child_is_isolated_without_creating_or_mutating_the_main_directory():
    root = REPO_ROOT / "data/runtime" / f"unit-reception-{uuid4().hex}"
    base = Settings()
    resolved = isolated_settings(base, root)
    assert resolved.runtime_path == root
    assert resolved.qdrant_path_resolved == root / "qdrant"
    assert resolved.sqlalchemy_url() != base.sqlalchemy_url()
    assert not root.exists()


def test_saved_provider_settings_are_read_only_and_not_written_to_another_database(tmp_path):
    path = tmp_path / "config.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE runtime_setting (key TEXT PRIMARY KEY, value TEXT, "
                           "updated_by TEXT, updated_at TEXT)")
        connection.executemany(
            "INSERT INTO runtime_setting VALUES (?, ?, 'test', '2026-10-02 00:00:00')",
            [("llm.api_key", "test-value-not-a-real-secret"), ("llm.active_model", "saved-model"),
             ("llm.base_url", "http://127.0.0.1:9999/v1"), ("embedding.backend", "http"),
             ("embedding.model_id", "saved-embedding"), ("embedding.dimension", "3")],
        )
    before = path.read_bytes()
    base = Settings(database_url=f"sqlite+pysqlite:///{path.as_posix()}", llm_model="environment-model")
    resolved = configured_settings(base)
    assert resolved.llm_model == "saved-model"
    assert resolved.llm_api_key == "test-value-not-a-real-secret"
    assert resolved.embedding_backend == "http" and resolved.embedding_dimension == 3
    assert base.llm_model == "environment-model"
    assert path.read_bytes() == before


def test_source_fingerprints_cover_reception_and_grounding():
    result = source_fingerprints()
    assert "domain/consumer_service/auto_reception.py" in result
    assert "domain/consumer_service/grounding.py" in result
    assert all(len(value) == 64 for value in result.values())


@pytest.fixture
def prompt_databases(tmp_path):
    source_path = tmp_path / "source.sqlite3"
    source = create_engine(f"sqlite+pysqlite:///{source_path.as_posix()}")
    target = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'target.sqlite3').as_posix()}")
    factories = [sessionmaker(bind=engine) for engine in (source, target)]
    for engine, factory in zip((source, target), factories, strict=True):
        Base.metadata.create_all(engine)
        with factory() as session:
            ensure_builtin_templates(session)
            session.commit()
    try:
        yield Settings(database_url=str(source.url)), factories[0], factories[1], source_path
    finally:
        source.dispose()
        target.dispose()


def test_snapshot_copies_saved_content_revision_and_binding_without_credentials(prompt_databases):
    settings, source, target, path = prompt_databases
    with source() as session:
        template = get_enabled_template(session, "LOREAL_AUTO_REPLY")
        template.content = "SAVED-AUTO-PROMPT"
        template.revision = 7
        set_setting(session, "llm.api_key", "test-only-not-a-real-key")
        set_setting(session, "prompt.binding.LOREAL_AUTO_REPLY", template.template_id)
        session.commit()
    before = path.read_bytes()
    snapshots = configured_prompts(settings)
    with target() as session:
        metadata = apply_prompt_snapshot(session, snapshots)
        copied = get_enabled_template(session, "LOREAL_AUTO_REPLY")
        assert copied.content == "SAVED-AUTO-PROMPT" and copied.revision == 7
        assert copied.template_id == snapshots[0].template["template_id"]
        assert session.get(RuntimeSettingRow, "llm.api_key") is None
        session.commit()
    assert path.read_bytes() == before
    assert metadata["LOREAL_AUTO_REPLY"]["contentSha256"] == hashlib.sha256(b"SAVED-AUTO-PROMPT").hexdigest()
    assert "SAVED-AUTO-PROMPT" not in json.dumps(metadata)
    assert "test-only-not-a-real-key" not in json.dumps(metadata)


def test_custom_template_shared_by_two_purposes_preserves_effective_selection(prompt_databases):
    settings, source, target, path = prompt_databases
    with source() as session:
        session.add(PromptTemplateRow(
            template_id="custom-shared", code="SHARED_RECEPTION", name="Shared",
            content="CUSTOM-PROMPT", revision=4, status="enabled", is_builtin=False,
        ))
        for purpose in ("LOREAL_AUTO_REPLY", "LOREAL_ASSISTANT"):
            set_setting(session, f"prompt.binding.{purpose}", "custom-shared")
        session.commit()
    before = path.read_bytes()
    snapshots = configured_prompts(settings)
    with target() as session:
        metadata = apply_prompt_snapshot(session, snapshots)
        for purpose in ("LOREAL_AUTO_REPLY", "LOREAL_ASSISTANT"):
            row = get_enabled_template(session, purpose)
            assert row.template_id == "custom-shared" and row.revision == 4
            assert metadata[purpose]["binding"] == "custom-shared"
        assert len(list(session.scalars(select(PromptTemplateRow).where(
            PromptTemplateRow.code == "SHARED_RECEPTION",
        )))) == 1
        session.commit()
    assert path.read_bytes() == before


@pytest.mark.parametrize("binding", ["missing", "disabled"])
def test_invalid_binding_falls_back_to_saved_enabled_default(prompt_databases, binding):
    settings, source, target, _ = prompt_databases
    with source() as session:
        if binding == "disabled":
            session.add(PromptTemplateRow(
                template_id=binding, code="UNUSED", name="Disabled",
                content="DO-NOT-USE", status="disabled",
            ))
        set_setting(session, "prompt.binding.LOREAL_AUTO_REPLY", binding)
        session.commit()
    snapshots = configured_prompts(settings)
    with target() as session:
        metadata = apply_prompt_snapshot(session, snapshots)
        row = get_enabled_template(session, "LOREAL_AUTO_REPLY")
        assert row.code == "LOREAL_AUTO_REPLY"
        assert metadata["LOREAL_AUTO_REPLY"]["binding"] == binding
        assert row.content != "DO-NOT-USE"


def test_disabled_default_without_effective_template_stays_code_fallback(prompt_databases):
    settings, source, target, _ = prompt_databases
    with source() as session:
        get_enabled_template(session, "LOREAL_AUTO_REPLY").status = "disabled"
        session.add(PromptTemplateRow(
            template_id="unbound", code="UNBOUND", name="Unbound",
            content="ENABLED-BUT-UNBOUND", status="enabled",
        ))
        session.commit()
    snapshots = configured_prompts(settings)
    assert snapshots[0].template is None
    with target() as session:
        metadata = apply_prompt_snapshot(session, snapshots)
        ensure_builtin_templates(session)
        assert get_enabled_template(session, "LOREAL_AUTO_REPLY") is None
        assert metadata["LOREAL_AUTO_REPLY"]["selection"] == "code_fallback"
        assert metadata["LOREAL_AUTO_REPLY"]["contentSha256"] is None
        assert session.get(PromptTemplateRow, "unbound") is None


def test_missing_source_database_is_not_created_and_no_saved_template_is_invented(tmp_path):
    path = tmp_path / "missing.sqlite3"
    snapshots = configured_prompts(Settings(database_url=f"sqlite+pysqlite:///{path.as_posix()}"))
    assert {snapshot.purpose for snapshot in snapshots} == set(PROMPT_PURPOSES)
    assert all(snapshot.template is None and snapshot.binding is None for snapshot in snapshots)
    assert not path.exists()


def test_configuration_session_rejects_writes(prompt_databases):
    settings, _, _, path = prompt_databases
    before = path.read_bytes()
    with readonly_configuration(settings) as session, pytest.raises(OperationalError, match="readonly"):
        session.execute(text("UPDATE prompt_template SET content = 'INVALID-WRITE'"))
    assert path.read_bytes() == before
