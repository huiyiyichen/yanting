"""数据库会话与初始化。

本期使用 SQLite + SQLAlchemy 2.0 维护线。运行数据统一放在 `data/runtime/`，
不入 Git；测试使用独立临时库。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

T = TypeVar("T")

#: 判定「SQLite 写锁竞争」的错误特征。只对这种可重试错误退避重试，
#: 其它 OperationalError（例如语法/约束问题）必须原样抛出，不能掩盖。
_SQLITE_LOCK_MARKERS = ("database is locked", "database table is locked")


def _is_lock_contention(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in _SQLITE_LOCK_MARKERS)


def retry_on_lock(
    operation: Callable[[], T],
    *,
    attempts: int = 6,
    base_delay: float = 0.05,
    max_delay: float = 1.5,
) -> T:
    """在 SQLite 写锁竞争时退避重试。

    为什么需要：一次客户消息处理会在**同一个事务**里写消息、案件事件与审计，
    事务跨越模型与检索调用，持续时间可达秒级。并发请求（多标签页、后台轮询、
    测试并发/refresh）撞上写锁时，SQLite 会抛 `database is locked`；
    仅靠 `busy_timeout` 只能覆盖短竞争，长事务下仍会失败并冒泡成 HTTP 500。

    重试是安全的：失败时事务已回滚，重放的是同一个未提交变更集合。
    这里只重试锁竞争，其它数据库错误立即抛出，避免掩盖真实缺陷。
    """

    last: OperationalError | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except OperationalError as exc:
            if not _is_lock_contention(exc):
                raise
            last = exc
            if attempt == attempts - 1:
                break
            time.sleep(min(base_delay * (2**attempt), max_delay))
    assert last is not None
    raise last


def build_engine(settings: Settings) -> Engine:
    url = settings.sqlalchemy_url()
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True, echo=False)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            # 外键约束在 SQLite 下默认关闭，必须显式打开以保证关联完整性。
            cursor.execute("PRAGMA foreign_keys=ON")
            # 单进程内多个连接共用同一文件，WAL 降低读写互斥。
            cursor.execute("PRAGMA journal_mode=WAL")
            # WAL 只允许「多读 + 单写」：同一会话的并发写会立刻抛
            # `database is locked`（默认 busy_timeout=0，不等待），表现为
            # 客户连发两条消息时第二条 500。这里给足等待时间让写锁排队，
            # 而不是让请求失败——已在并发实测中复现并验证。
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def commit_with_retry(session: Session) -> None:
    """提交事务，遇 SQLite 写锁竞争时回滚并退避重试。

    重试**仅限于提交这一步**：此时事务已结束，回滚后重放整个未提交变更集合
    是安全的。不要在 `flush()` 中途重试——flush 失败会让 SQLAlchemy 把会话
    标记为必须回滚，后续操作会抛 `PendingRollbackError`（已实测）。
    """

    def _commit() -> None:
        session.commit()

    try:
        retry_on_lock(_commit)
    except Exception:
        session.rollback()
        raise


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        commit_with_retry(session)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
