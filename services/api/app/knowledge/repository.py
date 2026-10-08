"""知识基础设施的仓储层。

单一事实来源：SQL 文档清单 + 不可变片段。Qdrant 索引可从它们重建。
"""

from __future__ import annotations

import json
from datetime import UTC, date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.models import (
    KnowledgeBaseRow,
    KnowledgeChunkRow,
    KnowledgeDocumentRow,
    KnowledgeImportRunRow,
    KnowledgeSnapshotRow,
)
from app.knowledge.schemas import (
    ChunkRecord,
    DocumentEntry,
    IndexManifest,
    KnowledgeBase,
)


def _dump(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def load_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


class KnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------------------------------------------------------------- 知识库

    def upsert_knowledge_base(self, item: KnowledgeBase) -> KnowledgeBaseRow:
        row = self._session.get(KnowledgeBaseRow, item.knowledge_base_id)
        if row is None:
            row = KnowledgeBaseRow(knowledge_base_id=item.knowledge_base_id)
            self._session.add(row)
        row.name = item.name
        row.source_type = item.source_type.value
        row.enabled = item.enabled
        self._session.flush()
        return row

    # ------------------------------------------------------------------ 文档

    def find_document(
        self,
        *,
        source_path: str,
        document_version: str,
        content_hash: str,
    ) -> KnowledgeDocumentRow | None:
        """幂等判定的核心查询：同一来源 + 版本 + 哈希视为同一份内容。"""

        statement = select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.source_path == source_path,
            KnowledgeDocumentRow.document_version == document_version,
            KnowledgeDocumentRow.content_hash == content_hash,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def latest_document_version(self, document_id: str) -> KnowledgeDocumentRow | None:
        statement = (
            select(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.document_id == document_id)
            .order_by(KnowledgeDocumentRow.document_pk.desc())
        )
        return self._session.execute(statement).scalars().first()

    def document_chunk_config_version(self, document: KnowledgeDocumentRow) -> str | None:
        """该文档片段所属的切片配置版本（索引时记录，不靠推断）。"""

        return document.index_chunk_config_version

    def create_document(
        self,
        entry: DocumentEntry,
        *,
        source_abs_path: str,
        digest: str,
    ) -> KnowledgeDocumentRow:
        row = KnowledgeDocumentRow(
            document_id=entry.document_id,
            document_version=entry.document_version,
            knowledge_base_id=entry.knowledge_base_id,
            title=entry.title,
            content_hash=digest,
            source_path=entry.source_path,
            source_abs_path=source_abs_path,
            visibility=entry.visibility.value,
            product_models_json=_dump(entry.product_models),
            regions_json=_dump(entry.regions),
            channels_json=_dump(entry.channels),
            effective_from=entry.effective_from,
            effective_to=entry.effective_to,
            enabled=entry.enabled,
            disabled_reason=entry.disabled_reason,
            parse_status="pending",
            index_status="pending",
        )
        self._session.add(row)
        self._session.flush()
        return row

    def replace_chunks(
        self, document: KnowledgeDocumentRow, chunks: list[ChunkRecord]
    ) -> list[str]:
        """写入片段，并保持 `document_id + version` 下内容不重复。

        为什么需要去重：同一 `document_id + document_version` 的内容可能变化
        （`(source_path, version, content_hash)` 三元组决定了它是「另一份文档」）。
        此时旧行仍然存在，其 chunk_id 可能与新片段完全相同，直接插入会违反主键约束。
        同一 `document_id + version` 在语义上只有一份内容，因此按 content_hash
        保留最新副本、删除已被取代的片段。

        返回被移除的 chunk_id 列表，供调用方（必要时）从索引中清理。
        """

        all_rows = list(
            self._session.execute(
                select(KnowledgeChunkRow).where(
                    KnowledgeChunkRow.document_id == document.document_id,
                    KnowledgeChunkRow.document_version == document.document_version,
                )
            ).scalars()
        )
        wanted = {chunk.chunk_id: chunk for chunk in chunks}
        removed: list[str] = []
        for row in all_rows:
            kept = wanted.get(row.chunk_id)
            if kept is None or kept.content_hash != row.content_hash:
                removed.append(row.chunk_id)
                self._session.delete(row)
            else:
                # 内容一致：把已有行挂到当前文档行，避免重复插入
                row.document_pk = document.document_pk
                wanted.pop(row.chunk_id, None)
        self._session.flush()

        for chunk in wanted.values():
            self._session.add(
                KnowledgeChunkRow(
                    chunk_id=chunk.chunk_id,
                    document_pk=document.document_pk,
                    document_id=chunk.document_id,
                    document_version=chunk.document_version,
                    knowledge_base_id=chunk.knowledge_base_id,
                    visibility=chunk.visibility.value,
                    heading_path=chunk.heading_path,
                    source_locator=chunk.source_locator,
                    text=chunk.text,
                    content_hash=chunk.content_hash,
                    parent_group_id=chunk.parent_group_id,
                    char_count=chunk.char_count,
                    product_models_json=_dump(chunk.product_models),
                    regions_json=_dump(chunk.regions),
                    channels_json=_dump(chunk.channels),
                )
            )
        document.chunk_count = len(chunks)
        self._session.flush()
        return removed

    def mark_document_failed(
        self, document: KnowledgeDocumentRow, *, error_code: str, error_detail: str
    ) -> None:
        document.parse_status = "failed"
        document.index_status = "failed"
        document.error_code = error_code
        document.error_detail = error_detail[:2000]
        self._session.flush()

    def mark_document_indexed(
        self, document: KnowledgeDocumentRow, *, chunk_config_version: str | None = None
    ) -> None:
        document.parse_status = "succeeded"
        document.index_status = "succeeded"
        document.error_code = None
        document.error_detail = None
        if chunk_config_version:
            document.index_chunk_config_version = chunk_config_version
        self._session.flush()

    def list_documents(self) -> list[KnowledgeDocumentRow]:
        return list(self._session.execute(select(KnowledgeDocumentRow)).scalars())

    def list_retrievable_documents(
        self, *, on_date: date | None = None
    ) -> list[KnowledgeDocumentRow]:
        """可参与新查询的文档：已启用、解析与索引成功、且在有效期内。"""

        today = on_date or date.today()
        statement = select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.enabled.is_(True),
            KnowledgeDocumentRow.parse_status == "succeeded",
            KnowledgeDocumentRow.index_status == "succeeded",
        )
        rows = list(self._session.execute(statement).scalars())
        return [row for row in rows if _effective_on(row, today)]

    def load_chunks(self, document_pks: list[int]) -> list[KnowledgeChunkRow]:
        if not document_pks:
            return []
        statement = select(KnowledgeChunkRow).where(KnowledgeChunkRow.document_pk.in_(document_pks))
        return list(self._session.execute(statement).scalars())

    # ------------------------------------------------------------------ 快照

    def get_active_snapshot(self) -> KnowledgeSnapshotRow | None:
        statement = (
            select(KnowledgeSnapshotRow)
            .where(KnowledgeSnapshotRow.status == "active")
            .order_by(KnowledgeSnapshotRow.activated_at.desc())
        )
        return self._session.execute(statement).scalars().first()

    def create_snapshot(self, manifest: IndexManifest, *, collection: str) -> KnowledgeSnapshotRow:
        """创建快照行。

        `collection` 必须在创建时就写入：暂存快照（staging）虽然未激活，
        但其 collection 已存在于 Qdrant 中，对照评测需要能直接指向它。
        """

        row = KnowledgeSnapshotRow(
            snapshot_id=manifest.snapshot_id,
            status=manifest.status,
            embedding_model_id=manifest.embedding_model_id,
            embedding_revision=manifest.embedding_revision,
            sparse_model_id=manifest.sparse_model_id,
            sparse_model_revision=manifest.sparse_model_revision,
            tokenizer_revision=manifest.tokenizer_revision,
            vector_dimension=manifest.vector_dimension,
            sparse_dimension=manifest.sparse_dimension,
            chunk_config_version=manifest.chunk_config_version,
            chunk_size=manifest.chunk_size,
            chunk_overlap=manifest.chunk_overlap,
            document_count=manifest.document_count,
            chunk_count=manifest.chunk_count,
            knowledge_base_ids_json=_dump(manifest.knowledge_base_ids),
            manifest_content_hash=manifest.manifest_content_hash,
            qdrant_collection=collection,
            error_code=manifest.error_code,
            error_detail=manifest.error_detail,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def activate_snapshot(self, snapshot: KnowledgeSnapshotRow, *, collection: str) -> None:
        """激活新快照，并把旧快照标记为 superseded（历史引用仍可复盘）。"""

        previous = self.get_active_snapshot()
        if previous is not None and previous.snapshot_id != snapshot.snapshot_id:
            previous.status = "superseded"
        snapshot.status = "active"
        snapshot.qdrant_collection = collection
        from datetime import datetime

        snapshot.activated_at = datetime.now(UTC)
        self._session.flush()

    def mark_snapshot_failed(
        self, snapshot: KnowledgeSnapshotRow, *, error_code: str, error_detail: str
    ) -> None:
        snapshot.status = "failed"
        snapshot.error_code = error_code
        snapshot.error_detail = error_detail[:2000]
        self._session.flush()

    def get_snapshot(self, snapshot_id: str) -> KnowledgeSnapshotRow | None:
        return self._session.get(KnowledgeSnapshotRow, snapshot_id)

    # -------------------------------------------------------------- 导入运行

    def create_run(self, run_id: str, *, manifest_path: str) -> KnowledgeImportRunRow:
        row = KnowledgeImportRunRow(run_id=run_id, status="running", manifest_path=manifest_path)
        self._session.add(row)
        self._session.flush()
        return row

    def finish_run(
        self,
        run: KnowledgeImportRunRow,
        *,
        status: str,
        detail: dict[str, object],
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        from datetime import datetime

        run.status = status
        run.finished_at = datetime.now(UTC)
        run.error_code = error_code
        run.error_detail = error_detail
        run.detail_json = json.dumps(detail, ensure_ascii=False)
        run.documents_imported = int(detail.get("documents_imported", 0))  # type: ignore[arg-type]
        run.documents_skipped = int(detail.get("documents_skipped", 0))  # type: ignore[arg-type]
        run.documents_failed = int(detail.get("documents_failed", 0))  # type: ignore[arg-type]
        run.documents_total = int(detail.get("documents_total", 0))  # type: ignore[arg-type]
        run.chunks_created = int(detail.get("chunks_created", 0))  # type: ignore[arg-type]
        snapshot_id = detail.get("snapshot_id")
        run.snapshot_id = str(snapshot_id) if snapshot_id else None
        self._session.flush()


def _effective_on(row: KnowledgeDocumentRow, on_date: date) -> bool:
    if on_date < row.effective_from:
        return False
    return row.effective_to is None or on_date <= row.effective_to
