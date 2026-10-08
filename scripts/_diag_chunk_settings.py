"""诊断：Settings 传入的 chunk_size 是否真正影响到切片结果。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.knowledge.chunking import chunk_document  # noqa: E402
from app.knowledge.parsing import parse_markdown  # noqa: E402

KNOWLEDGE = REPO / "data" / "knowledge"


def main() -> int:
    for size, overlap in ((400, 60), (600, 80), (800, 100)):
        settings = Settings(chunk_size=size, chunk_overlap=overlap)
        print(
            f"Settings(chunk_size={size}) -> settings.chunk_size={settings.chunk_size} "
            f"overlap={settings.chunk_overlap}"
        )
        total = 0
        for path in sorted(KNOWLEDGE.rglob("*.md")):
            parsed = parse_markdown(path.read_text(encoding="utf-8"))
            drafts = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
            total += len(drafts)
        print(f"   按 settings 切片总数 = {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
