"""验证文档版本替换与历史证据可复盘。

需求（PRD AC-26 / AC-28）：
- 停用/过期文档排除新查询；
- **旧引用仍可读**：历史案件引用的证据副本在替换索引后依然可复盘。

做法：
1. 记录当前快照与 2.1.0 版本片段的 chunk_id；
2. 把排障文档改成 2.2.0 新内容并重新导入；
3. 断言新查询命中 2.2.0、不命中 2.1.0；
4. 断言 2.1.0 的片段行仍存在于数据库中（历史引用可读）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from sqlalchemy import select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402
from app.domain.enums import Visibility  # noqa: E402
from app.integrations.embedding_provider import build_embedding_provider  # noqa: E402
from app.knowledge.ingest import ingest_manifest  # noqa: E402
from app.knowledge.models import KnowledgeChunkRow  # noqa: E402
from app.knowledge.retrieval import RetrievalRequest, retrieve  # noqa: E402

TARGET = REPO / "data" / "knowledge" / "customer_visible" / "troubleshooting-stick-no-suction.md"
MANIFEST = REPO / "data" / "knowledge" / "manifest.json"
ORIGINAL_DOC_ID = "doc-ts-stick-no-suction"
OLD_VERSION = "2.1.0"
NEW_VERSION = "2.2.0"
MARKER = "版本替换验证专用句子：本条仅存在于 2.2.0 版本，用于确认索引已切换到新版本。"


def main() -> int:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    provider = build_embedding_provider(settings)

    manifest_raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    original_file = TARGET.read_text(encoding="utf-8")
    # 原文整体保存：还原时必须写回原始字节内容，而不是重新序列化解析后的对象
    original_manifest_text = MANIFEST.read_text(encoding="utf-8")
    report: dict[str, object] = {}

    try:
        # 0) 升级清单中的版本号
        for entry in manifest_raw["documents"]:
            if entry["document_id"] == ORIGINAL_DOC_ID:
                entry["document_version"] = NEW_VERSION
        MANIFEST.write_text(
            json.dumps(manifest_raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # 1) 改写源文件为 2.2.0
        TARGET.write_text(
            original_file.replace("## 排查步骤", f"## 排查步骤\n\n{MARKER}\n"),
            encoding="utf-8",
        )

        session = factory()
        try:
            ingest = ingest_manifest(
                session,
                settings=settings,
                embedding_provider=provider,
                manifest_path=MANIFEST,
                knowledge_root=MANIFEST.parent,
                activate=True,
            )
            session.commit()
            report["ingest_status"] = ingest.snapshot_status
            report["ingest_snapshot"] = ingest.snapshot_id

            result = retrieve(
                session,
                settings=settings,
                embedding_provider=provider,
                request=RetrievalRequest(
                    query="吸尘器吸力减弱怎么排查 滤芯晾干",
                    audience=Visibility.CUSTOMER_VISIBLE,
                    product_model="A1 Pro",
                    country_code="CN",
                ),
            )
            versions = {item.document_version for item in result.evidence}
            titles = {item.document_title for item in result.evidence}
            report["retrieved_versions"] = sorted(versions)
            report["retrieved_titles"] = sorted(titles)
            report["new_version_present"] = NEW_VERSION in versions
            report["old_version_absent"] = OLD_VERSION not in versions

            # 2) 历史片段行仍可读
            rows = list(
                session.execute(
                    select(KnowledgeChunkRow).where(
                        KnowledgeChunkRow.document_id == ORIGINAL_DOC_ID,
                        KnowledgeChunkRow.document_version == OLD_VERSION,
                    )
                ).scalars()
            )
            report["historical_chunk_rows"] = len(rows)
            report["historical_readable"] = len(rows) > 0
            report["historical_sample"] = rows[0].chunk_id if rows else None
        finally:
            session.close()
    finally:
        # 还原源文件与清单，保持仓库状态一致
        TARGET.write_text(original_file, encoding="utf-8")
        MANIFEST.write_text(original_manifest_text, encoding="utf-8")
        engine.dispose()

    report["result"] = (
        "PASS"
        if report.get("new_version_present")
        and report.get("old_version_absent")
        and report.get("historical_readable")
        else "FAIL"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
