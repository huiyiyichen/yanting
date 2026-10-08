"""验证 QdrantClient local 在显式 close() 后能否干净退出。

背景：不显式 close() 时，CPython 在解释器关闭阶段的 __del__ 里调用
portalocker.unlock -> import msvcrt，会打印 "import of msvcrt halted"。
本脚本用于确认显式 close() 是否消除该现象，从而决定运行代码是否必须显式 close。
"""

from __future__ import annotations

import contextlib
import sys
import tempfile

from qdrant_client import QdrantClient


def main() -> int:
    path = tempfile.mkdtemp(prefix="qdrant-close-probe-")
    client = QdrantClient(path=path)
    with contextlib.suppress(Exception):
        client.get_collections()
    client.close()
    # 二次 close 必须安全（幂等），否则 FastAPI lifespan 重复关闭会抛错
    try:
        client.close()
        print("double close: OK")
    except Exception as exc:
        print(f"double close: FAIL {type(exc).__name__}: {exc}")
    print("explicit close done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
