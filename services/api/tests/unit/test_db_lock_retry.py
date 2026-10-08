"""SQLite 写锁竞争的重试测试。

背景（真实缺陷）：一次客户消息处理在**同一个事务**内写消息、案件事件与审计，
事务跨越模型与检索调用，持锁可达秒级。并发请求撞上 SQLite 写锁时
`sqlite3.OperationalError: database is locked` 会直接冒泡成 HTTP 500
（已在「并发发消息」实测中复现：3 路并发即出现 500）。

这里锁定两条不变量：
1. 锁竞争会被退避重试，而不是立即失败；
2. **其它** OperationalError 必须原样抛出，不能被重试逻辑掩盖。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.db import retry_on_lock


def _lock_error() -> OperationalError:
    return OperationalError("UPDATE conversation SET ...", {}, Exception("database is locked"))


class TestRetryOnLock:
    def test_retries_until_success(self) -> None:
        attempts: list[int] = []

        def _operation() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise _lock_error()
            return "ok"

        assert retry_on_lock(_operation, base_delay=0.0) == "ok"
        assert len(attempts) == 3

    def test_raises_after_exhausting_attempts(self) -> None:
        calls: list[int] = []

        def _always_locked() -> str:
            calls.append(1)
            raise _lock_error()

        with pytest.raises(OperationalError):
            retry_on_lock(_always_locked, attempts=3, base_delay=0.0)
        assert len(calls) == 3

    def test_non_lock_operational_error_is_not_retried(self) -> None:
        calls: list[int] = []

        def _other_error() -> str:
            calls.append(1)
            raise OperationalError("SELECT 1", {}, Exception("no such table: nope"))

        with pytest.raises(OperationalError):
            retry_on_lock(_other_error, attempts=4, base_delay=0.0)
        # 只调用一次：不可重试的错误必须立即抛出
        assert len(calls) == 1

    def test_table_locked_variant_is_retried(self) -> None:
        calls: list[int] = []

        def _table_locked() -> str:
            calls.append(1)
            if len(calls) == 1:
                raise OperationalError("UPDATE t", {}, Exception("database table is locked"))
            return "ok"

        assert retry_on_lock(_table_locked, base_delay=0.0) == "ok"
        assert len(calls) == 2


class TestCommitRetryContract:
    def test_commit_retry_rolls_back_and_reraises_on_persistent_lock(self) -> None:
        """提交阶段持续撞锁时必须回滚并抛出，不能假装成功。"""

        from app.db import commit_with_retry

        class _FakeSession:
            def __init__(self) -> None:
                self.commits = 0
                self.rollbacks = 0

            def commit(self) -> None:
                self.commits += 1
                raise _lock_error()

            def rollback(self) -> None:
                self.rollbacks += 1

        session = _FakeSession()
        with pytest.raises(OperationalError):
            commit_with_retry(session)  # type: ignore[arg-type]
        assert session.commits > 1  # 确实重试过
        assert session.rollbacks == 1  # 失败后清理了事务

    def test_commit_retry_succeeds_without_rollback(self) -> None:
        from app.db import commit_with_retry

        class _FakeSession:
            def __init__(self) -> None:
                self.commits = 0
                self.rollbacks = 0

            def commit(self) -> None:
                self.commits += 1

            def rollback(self) -> None:
                self.rollbacks += 1

        session = _FakeSession()
        commit_with_retry(session)  # type: ignore[arg-type]
        assert session.commits == 1
        assert session.rollbacks == 0
