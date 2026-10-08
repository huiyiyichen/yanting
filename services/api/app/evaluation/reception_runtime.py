"""Port-free reception evaluation with isolated facts, index and real providers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT, Settings
from app.domain.consumer_service.models import AssistantRunRow
from app.domain.platform import settings as platform_settings
from app.domain.platform.models import PromptTemplateRow
from app.runtime import RuntimeContext, build_runtime

SOURCE_SHA256 = "b5ac027e863c5580dab39c8f459e4698d65e9fbec29832c9915448f2087307b7"
SOURCE_PATH = REPO_ROOT / f"data/source/loreal-official-mock/source-{SOURCE_SHA256}.xlsx"
MANIFEST_PATH = REPO_ROOT / "data/knowledge/loreal/manifest.json"
PROMPT_PURPOSES = ("LOREAL_AUTO_REPLY", "LOREAL_ASSISTANT", "LOREAL_SAFETY")
SOURCE_MODULES = (
    "domain/consumer_service/assistant.py",
    "domain/consumer_service/auto_reception.py",
    "domain/consumer_service/grounded_workflow.py",
    "domain/consumer_service/grounding.py",
    "domain/consumer_service/reply_policy.py",
    "domain/consumer_service/image_evidence.py",
    "domain/consumer_service/workspace.py",
    "domain/consumer_service/risk_rules.py",
    "domain/platform/settings.py",
    "schemas/grounding.py",
    "evaluation/reception_runtime.py",
)


@dataclass(frozen=True)
class PromptSnapshot:
    purpose: str
    binding: str | None
    template: dict[str, Any] | None = field(repr=False)


@contextmanager
def readonly_configuration(base: Settings) -> Iterator[Session | None]:
    url = make_url(base.sqlalchemy_url())
    if url.get_backend_name() != "sqlite" or not url.database:
        raise ValueError("Reception evaluation requires the local SQLite configuration")
    database = Path(url.database).resolve()
    if not database.exists():
        yield None
        return
    engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(
        database.as_uri() + "?mode=ro", uri=True,
    ))
    try:
        with Session(engine) as session:
            # SQLite's legacy driver does not start a snapshot transaction for SELECT.
            session.connection().exec_driver_sql("BEGIN")
            yield session
    finally:
        engine.dispose()


def isolated_settings(base: Settings, directory: Path) -> Settings:
    root = directory.resolve()
    runtime_root = (REPO_ROOT / "data/runtime").resolve()
    protected = {base.runtime_path, base.qdrant_path_resolved}
    database = make_url(base.sqlalchemy_url()).database
    if database:
        protected.add(Path(database).resolve().parent)
    protected.discard(runtime_root)
    if root == runtime_root or runtime_root not in root.parents:
        raise ValueError("Evaluation directory must be inside data/runtime")
    if root.exists() or any(root == path or root in path.parents or path in root.parents for path in protected):
        raise ValueError("Evaluation directory must be new and separate from the active runtime")
    return base.model_copy(update={
        "runtime_dir": str(root),
        "database_url": f"sqlite+pysqlite:///{(root / 'evaluation.sqlite3').as_posix()}",
        "qdrant_path": str(root / "qdrant"),
    })


def configured_settings(base: Settings) -> Settings:
    """Read only existing provider settings; do not persist credentials in the fixture."""
    result = base.model_copy()
    with readonly_configuration(base) as session:
        if session is not None:
            from app.runtime import _apply_saved_embedding_settings, _apply_saved_rerank_settings

            # Reuse the same precedence as application startup, against a read-only connection.
            factory = sessionmaker(bind=session.get_bind())
            _apply_saved_embedding_settings(result, factory)
            _apply_saved_rerank_settings(result, factory)
            mapping = {
                platform_settings.BASE_URL_KEY: "llm_base_url",
                platform_settings.API_KEY_KEY: "llm_api_key",
                platform_settings.MODEL_KEY: "llm_model",
                platform_settings.VISION_MODEL_KEY: "llm_vision_model",
            }
            for key, field in mapping.items():
                value = platform_settings.get_setting(session, key)
                if value is not None:
                    setattr(result, field, value)
            active = platform_settings.get_setting(session, platform_settings.ACTIVE_MODEL_KEY)
            if active:
                result.llm_model = active
    return result


def configured_prompts(base: Settings) -> tuple[PromptSnapshot, ...]:
    """Snapshot only effective reception templates, without writes or unrelated settings."""
    snapshots = []
    with readonly_configuration(base) as session:
        for purpose in PROMPT_PURPOSES:
            template = platform_settings.get_enabled_template(session, purpose) if session else None
            binding = platform_settings.get_setting(session, f"prompt.binding.{purpose}") if session else None
            snapshots.append(PromptSnapshot(
                purpose=purpose, binding=binding,
                template={key: getattr(template, key) for key in (
                    "template_id", "code", "name", "scenario", "content", "status", "revision", "is_builtin",
                )} if template else None,
            ))
    return tuple(snapshots)


def apply_prompt_snapshot(session: Session, snapshots: tuple[PromptSnapshot, ...]) -> dict:
    if len(snapshots) != len(PROMPT_PURPOSES) or {s.purpose for s in snapshots} != set(PROMPT_PURPOSES):
        raise ValueError("Prompt snapshot must cover all reception purposes")
    for template in session.scalars(select(PromptTemplateRow).where(
        PromptTemplateRow.code.in_(PROMPT_PURPOSES),
    )):
        template.status = "disabled"
    for snapshot in snapshots:
        if snapshot.template:
            saved = snapshot.template
            row = session.scalar(select(PromptTemplateRow).where(PromptTemplateRow.code == saved["code"]))
            if row is None:
                row = PromptTemplateRow(**saved, updated_by="evaluation-snapshot")
                session.add(row)
            else:
                for key, value in saved.items():
                    setattr(row, key, value)
            session.flush()
        platform_settings.set_setting(
            session, f"prompt.binding.{snapshot.purpose}", snapshot.binding or "", actor="evaluation-snapshot",
        )
    session.flush()
    fingerprints = {}
    for snapshot in snapshots:
        actual = platform_settings.get_enabled_template(session, snapshot.purpose)
        expected = snapshot.template
        if ((actual is None) != (expected is None)
                or (actual is not None and any(getattr(actual, key) != value for key, value in expected.items()))):
            raise ValueError("Effective prompt did not match the saved snapshot")
        fingerprints[snapshot.purpose] = {
            "binding": snapshot.binding,
            "templateId": actual.template_id if actual else None,
            "code": actual.code if actual else None,
            "revision": actual.revision if actual else None,
            "contentSha256": hashlib.sha256(actual.content.encode("utf-8")).hexdigest() if actual else None,
            "selection": "saved_template" if actual else "code_fallback",
        }
    return fingerprints


def source_fingerprints() -> dict[str, str]:
    root = REPO_ROOT / "services/api/app"
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_MODULES}


def prepare_runtime(
    settings: Settings, *, prompt_snapshot: tuple[PromptSnapshot, ...],
) -> tuple[RuntimeContext, dict]:
    from app.domain.consumer_service.importer import import_business_workbook
    from app.knowledge.ingest import ingest_manifest

    if settings.run_mode != "live":
        raise ValueError("Isolated reception requires live configuration")
    if hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Official source fingerprint mismatch")
    context = build_runtime(settings)
    try:
        if not context.model_provider.available():
            raise ValueError("Real model configuration is unavailable")
        description = context.embedding_provider.describe()
        if description.get("backend") == "mock" or not context.embedding_provider.available():
            raise ValueError("Real embedding configuration is unavailable")
        with context.new_session() as session:
            prompt_fingerprints = apply_prompt_snapshot(session, prompt_snapshot)
            import_business_workbook(session, SOURCE_PATH, repo_root=settings.runtime_path)
            session.commit()
            report = ingest_manifest(
                session, settings=settings, embedding_provider=context.embedding_provider,
                manifest_path=MANIFEST_PATH, restrict_to_manifest=True,
            )
            if report.snapshot_status != "active" or report.documents_failed:
                raise ValueError(f"Real knowledge publication failed: {report.error_code}")
            session.commit()
        description = context.embedding_provider.describe()
        metadata = {
            "executionTarget": "isolated_asgi",
            "runtimeDirectory": str(settings.runtime_path.relative_to(REPO_ROOT)),
            "sourceSha256": SOURCE_SHA256,
            "sourceModuleSha256": source_fingerprints(),
            "knowledgeManifestSha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            "knowledge": report.to_dict(),
            "embedding": {
                key: description.get(key) for key in ("backend", "model_id", "model_revision", "dimension")
            },
            "requestedModel": context.model_provider.model_id,
            "promptScope": "saved_effective_templates_with_current_fixed_constraints",
            "prompts": prompt_fingerprints,
            "mainServiceRestarted": False,
        }
        return context, metadata
    except Exception:
        context.close()
        raise


@contextmanager
def reception_client(context: RuntimeContext) -> Iterator:
    from fastapi.testclient import TestClient

    from app.domain.consumer_service.auto_reception import run_reply_worker
    from app.domain.consumer_service.risk_rules import run_risk_monitor
    from app.main import create_app

    app = create_app()

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = context
        workers = [
            asyncio.create_task(run_reply_worker(context)),
            asyncio.create_task(run_risk_monitor(context)),
        ]
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            # Cancelling to_thread does not stop its thread or outstanding provider request.
            await asyncio.get_running_loop().shutdown_default_executor()
            context.close()

    app.router.lifespan_context = lifespan
    try:
        with TestClient(app) as client:
            yield client
    finally:
        context.close()


def run_history(context: RuntimeContext, conversation_id: str) -> list[dict]:
    with context.new_session() as session:
        rows = session.scalars(select(AssistantRunRow).where(
            AssistantRunRow.conversation_id == conversation_id,
        ).order_by(AssistantRunRow.created_at))
        return [{
            "status": row.status, "modelId": row.model_id, "isMock": row.is_mock,
            "workflow": json.loads(row.trace_json), "usage": json.loads(row.usage_json),
        } for row in rows]
