"""P2-1 环境变量前缀 ANKER_AGENT_ → YANTING_。

失败方式：
E1 改前缀后，成员本机 .env 里的旧前缀被静默忽略，live 配置变成空值；
E2 新旧前缀同时存在时旧值覆盖新值；
E3 读取旧前缀时没有弃用提示，旧配置永远不迁移；
E4 默认运行库换名后，已有旧库被丢弃（新建空库）；
E5 运行库保护名单漏掉新文件名，测试误写默认库；
E6 异常基类改名后旧名不可用。
"""

import logging

from app import config
from app.runtime_guard import PROTECTED_FILES


def test_legacy_prefix_is_mirrored_with_deprecation_warning(monkeypatch, caplog):
    monkeypatch.delenv("YANTING_LLM_MODEL", raising=False)
    monkeypatch.setenv("ANKER_AGENT_LLM_MODEL", "legacy-model")
    with caplog.at_level(logging.WARNING, logger="app.config"):
        migrated = config.migrate_legacy_env()
    assert "LLM_MODEL" in migrated
    assert config.Settings().llm_model == "legacy-model"
    assert any("YANTING_LLM_MODEL" in r.getMessage() for r in caplog.records)


def test_new_prefix_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("ANKER_AGENT_LLM_MODEL", "legacy-model")
    monkeypatch.setenv("YANTING_LLM_MODEL", "new-model")
    config.migrate_legacy_env()
    assert config.Settings().llm_model == "new-model"
    assert config.Settings.model_config["env_prefix"] == "YANTING_"


def test_default_database_keeps_existing_legacy_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.default_database_url().endswith("data/runtime/yanting.sqlite3")
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / "data/runtime/anker_agent.sqlite3").write_bytes(b"")
    assert config.default_database_url().endswith("data/runtime/anker_agent.sqlite3")
    (tmp_path / "data/runtime/yanting.sqlite3").write_bytes(b"")
    assert config.default_database_url().endswith("data/runtime/yanting.sqlite3")


def test_runtime_guard_protects_new_default_name():
    assert {"yanting.sqlite3", "anker_agent.sqlite3"} <= PROTECTED_FILES


def test_legacy_error_alias_still_catches_new_errors():
    """E6 异常基类改名后，外部旧代码 except AnkerAgentError 不再捕获。"""
    from app.errors import AnkerAgentError, NotFoundError, YantingError

    assert AnkerAgentError is YantingError
    assert issubclass(NotFoundError, AnkerAgentError)
