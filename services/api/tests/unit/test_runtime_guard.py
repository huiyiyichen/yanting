"""评测/校准脚本不得写入主运行库或演示库（改进方案 P0-4）。

先列失败方式，再实现 `app.runtime_guard.require_isolated_database`：
G1 默认配置（data/runtime/anker_agent.sqlite3）被放行 -> 必须拒绝。
G2 演示库 demo.sqlite3 或演示快照 demo-snapshot.sqlite3 被放行 -> 必须拒绝。
G3 同一文件换写法（绝对路径、`./` 前缀、`..` 回跳、反斜杠、大小写）绕过检查 -> 必须拒绝。
G4 隔离库 data/runtime/eval-*.sqlite3、临时目录文件、内存库被误拒 -> 必须放行。
G5 拒绝时只抛出异常不说明原因 -> 错误信息须包含被拒绝的库路径，便于改用隔离库。
G6 非 sqlite 地址无法判定 -> 一律拒绝（宁严勿松）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.runtime_guard import ProtectedDatabaseError, require_isolated_database

RUNTIME = REPO_ROOT / "data" / "runtime"


def settings(url: str) -> Settings:
    return Settings(database_url=url)


def test_g1_default_main_database_is_rejected():
    with pytest.raises(ProtectedDatabaseError):
        require_isolated_database(Settings())


@pytest.mark.parametrize("name", ["demo.sqlite3", "demo-snapshot.sqlite3", "anker_agent.sqlite3"])
def test_g2_demo_and_main_files_are_rejected(name):
    with pytest.raises(ProtectedDatabaseError):
        require_isolated_database(settings(f"sqlite+pysqlite:///data/runtime/{name}"))


@pytest.mark.parametrize("url", [
    f"sqlite+pysqlite:///{(RUNTIME / 'anker_agent.sqlite3').as_posix()}",
    "sqlite+pysqlite:///./data/runtime/anker_agent.sqlite3",
    "sqlite+pysqlite:///data/runtime/../runtime/demo.sqlite3",
    "sqlite+pysqlite:///data\\runtime\\demo.sqlite3",
    "sqlite+pysqlite:///data/runtime/DEMO.sqlite3",
    "sqlite:///data/runtime/anker_agent.sqlite3",
])
def test_g3_alternate_spellings_are_rejected(url):
    with pytest.raises(ProtectedDatabaseError):
        require_isolated_database(settings(url))


@pytest.mark.parametrize("url", [
    "sqlite+pysqlite:///data/runtime/eval-20261014.sqlite3",
    "sqlite+pysqlite:///:memory:",
    "sqlite+pysqlite://",
])
def test_g4_isolated_databases_are_allowed(url):
    require_isolated_database(settings(url))


def test_g4_temporary_file_is_allowed(tmp_path: Path):
    require_isolated_database(settings(f"sqlite+pysqlite:///{(tmp_path / 'x.sqlite3').as_posix()}"))


def test_g5_error_names_the_rejected_file():
    with pytest.raises(ProtectedDatabaseError, match=r"demo\.sqlite3"):
        require_isolated_database(settings("sqlite+pysqlite:///data/runtime/demo.sqlite3"))


def test_g6_non_sqlite_url_is_rejected():
    with pytest.raises(ProtectedDatabaseError):
        require_isolated_database(settings("postgresql://localhost/yanting"))
