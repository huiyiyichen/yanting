"""运行库保护：评测、校准与批量脚本只能写隔离库。

主运行库（日常开发）与演示库（路演）里的会话会直接出现在客服队列、客户列表、
工单页和风险页；评测产生的 `QUALITY-…`、`联动检查…` 一类会话曾因此污染演示。
"""

from __future__ import annotations

from pathlib import Path

from app.config import REPO_ROOT, Settings

PROTECTED_FILES = frozenset({"anker_agent.sqlite3", "demo.sqlite3", "demo-snapshot.sqlite3"})
_IN_MEMORY = {"", ":memory:"}


class ProtectedDatabaseError(RuntimeError):
    """目标库是主运行库或演示库。"""


def _sqlite_target(url: str) -> str | None:
    for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix):]
    if url in {"sqlite+pysqlite://", "sqlite://"}:
        return ""
    return None


def require_isolated_database(settings: Settings) -> None:
    """目标库是受保护库或无法判定时抛出 ProtectedDatabaseError。"""

    raw = _sqlite_target(settings.database_url)
    if raw is None:
        raise ProtectedDatabaseError(f"只允许隔离的 SQLite 库：{settings.database_url}")
    if raw.split("?", 1)[0] in _IN_MEMORY:
        return
    path = Path(raw.replace("\\", "/"))
    resolved = (path if path.is_absolute() else REPO_ROOT / path).resolve()
    runtime = (REPO_ROOT / "data" / "runtime").resolve()
    if resolved.name.lower() in PROTECTED_FILES and resolved.parent == runtime:
        raise ProtectedDatabaseError(
            f"拒绝写入受保护的运行库 {resolved}；请用 ANKER_AGENT_DATABASE_URL 指向 "
            "data/runtime/eval-*.sqlite3 或临时目录"
        )
