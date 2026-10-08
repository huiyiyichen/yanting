"""知识导入流水线。

发布流程（工程规范第 12.3 节）：
    校验清单 -> 解析 -> 切片 -> 编码 -> 写入暂存快照 -> 数量/维度/过滤/引用校验 -> 激活快照

失败语义：
- 失败时**保留当前有效快照**，新文档保持不可检索并可重试；
- 不发布半成品；
- 停用文档立即排除后续查询，但不删除案件中已引用的历史证据副本。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AnkerAgentError
from app.integrations.embedding_provider import EmbeddingProvider
from app.integrations.qdrant_store import QdrantKnowledgeStore
from app.knowledge.chunking import build_chunk_id, chunk_document
from app.knowledge.parsing import content_hash, parse_markdown
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.schemas import (
    ChunkRecord,
    DocumentEntry,
    IndexManifest,
    KnowledgeManifest,
)
from app.logging_setup import get_logger, log_event

logger = get_logger(__name__)

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".json"}


class IngestError(AnkerAgentError):
    code = "ingest_failed"


@dataclass
class DocumentOutcome:
    document_id: str
    document_version: str
    status: str  # imported | skipped_duplicate | failed | disabled
    chunk_count: int = 0
    error_code: str | None = None
    error_detail: str | None = None


@dataclass
class IngestReport:
    run_id: str
    snapshot_id: str | None
    snapshot_status: str
    collection: str | None
    documents_total: int = 0
    documents_imported: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    chunks_created: int = 0
    vector_dimension: int = 0
    knowledge_base_ids: list[str] = field(default_factory=list)
    outcomes: list[DocumentOutcome] = field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None
    # 切片参数与实际长度的取证字段：用于证明不同配置确实产生不同切片
    chunk_size: int = 0
    chunk_overlap: int = 0
    max_chunk_chars: int = 0
    mean_chunk_chars: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_status": self.snapshot_status,
            "collection": self.collection,
            "documents_total": self.documents_total,
            "documents_imported": self.documents_imported,
            "documents_skipped": self.documents_skipped,
            "documents_failed": self.documents_failed,
            "chunks_created": self.chunks_created,
            "vector_dimension": self.vector_dimension,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "max_chunk_chars": self.max_chunk_chars,
            "mean_chunk_chars": self.mean_chunk_chars,
            "knowledge_base_ids": self.knowledge_base_ids,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "documents": [
                {
                    "document_id": item.document_id,
                    "document_version": item.document_version,
                    "status": item.status,
                    "chunk_count": item.chunk_count,
                    "error_code": item.error_code,
                    "error_detail": item.error_detail,
                }
                for item in self.outcomes
            ],
        }


def load_manifest(path: Path) -> KnowledgeManifest:
    if not path.exists():
        raise IngestError("清单文件不存在", detail=str(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IngestError("清单不是合法 JSON", detail=f"{exc}") from exc
    try:
        return KnowledgeManifest.model_validate(raw)
    except Exception as exc:
        raise IngestError("清单校验失败", detail=str(exc)[:500]) from exc


def _resolve_source(root: Path, entry: DocumentEntry) -> Path:
    """把清单里的相对路径解析到知识根目录内，并再次确认未逃出根目录。"""

    candidate = (root / entry.source_path).resolve()
    root_resolved = root.resolve()
    if not candidate.is_relative_to(root_resolved):
        raise IngestError(
            "source_path 逃出知识根目录",
            detail=f"{entry.source_path} -> {candidate}",
        )
    if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise IngestError(
            "不支持的文件格式",
            detail=f"{entry.source_path}（支持 {sorted(SUPPORTED_SUFFIXES)}）",
        )
    if not candidate.exists():
        raise IngestError("源文件不存在", detail=str(candidate))
    return candidate


def _read_text(path: Path) -> str:
    """只接受 UTF-8；编码失败必须显式报错，不能静默替换字符。"""

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError(
            "源文件不是 UTF-8 编码",
            detail=f"{path.name}: {exc}",
        ) from exc


def _chunk_payload(chunk: ChunkRecord, entry: DocumentEntry, title: str) -> dict[str, object]:
    """Qdrant payload。过滤字段与业务字段分开，便于按适用性/可见范围过滤。"""

    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_version": chunk.document_version,
        "document_title": title,
        "knowledge_base_id": chunk.knowledge_base_id,
        "visibility": chunk.visibility.value,
        "heading_path": chunk.heading_path,
        "source_locator": chunk.source_locator,
        "text": chunk.text,
        "content_hash": chunk.content_hash,
        "parent_group_id": chunk.parent_group_id,
        "product_models": chunk.product_models,
        "regions": chunk.regions,
        "channels": chunk.channels,
        "effective_from": entry.effective_from.isoformat(),
        "effective_to": entry.effective_to.isoformat() if entry.effective_to else None,
    }


def ingest_manifest(
    session: Session,
    *,
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    manifest_path: Path,
    knowledge_root: Path | None = None,
    activate: bool = True,
    restrict_to_manifest: bool = False,
) -> IngestReport:
    """执行一次完整导入，返回可写入台账的报告。"""

    repository = KnowledgeRepository(session)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run_row = repository.create_run(run_id, manifest_path=str(manifest_path))

    root = knowledge_root or manifest_path.parent
    manifest = load_manifest(manifest_path)
    manifest_digest = content_hash(json.dumps(manifest.model_dump(mode="json"), sort_keys=True))

    report = IngestReport(
        run_id=run_id,
        snapshot_id=None,
        snapshot_status="staging",
        collection=None,
        documents_total=len(manifest.documents),
        knowledge_base_ids=[item.knowledge_base_id for item in manifest.enabled_knowledge_bases()],
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    for item in manifest.knowledge_bases:
        repository.upsert_knowledge_base(item)

    # 第一阶段：解析 + 切片（不接触索引）
    staged: list[tuple[DocumentEntry, list[ChunkRecord]]] = []
    stale_chunk_ids: list[str] = []
    for entry in manifest.documents:
        try:
            source = _resolve_source(root, entry)
            text = _read_text(source)
            digest = content_hash(text)

            existing = repository.find_document(
                source_path=entry.source_path,
                document_version=entry.document_version,
                content_hash=digest,
            )
            # 切片/编码配置变化时必须重新切片并生成新快照（工程规范第 12.3 节第 5 条），
            # 因此「内容哈希相同」只在配置一致时才允许跳过。
            config_changed = (
                existing is not None
                and repository.document_chunk_config_version(existing)
                != settings.chunk_config_version
            )
            if existing is not None and existing.index_status == "succeeded" and not config_changed:
                # 同一来源 + 版本 + 哈希 + 相同切片配置：重复导入不复制
                report.documents_skipped += 1
                report.outcomes.append(
                    DocumentOutcome(
                        document_id=entry.document_id,
                        document_version=entry.document_version,
                        status="skipped_duplicate",
                        chunk_count=existing.chunk_count,
                    )
                )
                continue

            document = existing or repository.create_document(
                entry, source_abs_path=str(source), digest=digest
            )
            parsed = parse_markdown(text)
            drafts = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
            chunks = [
                ChunkRecord(
                    chunk_id=build_chunk_id(
                        entry.document_id, entry.document_version, index, draft.text
                    ),
                    document_id=entry.document_id,
                    document_version=entry.document_version,
                    heading_path=" > ".join(item for item in draft.heading_path if item),
                    source_locator=f"{entry.source_path}#L{draft.start_line + 1}-L{draft.end_line + 1}",
                    text=draft.text,
                    content_hash=content_hash(draft.text),
                    parent_group_id=draft.parent_group_id,
                    char_count=len(draft.text),
                    knowledge_base_id=entry.knowledge_base_id,
                    visibility=entry.visibility,
                    product_models=entry.product_models,
                    regions=entry.regions,
                    channels=entry.channels,
                )
                for index, draft in enumerate(drafts)
            ]
            if not chunks:
                raise IngestError("文档未产生任何片段", detail=entry.source_path)

            logger.info(
                json.dumps(
                    {
                        "event": "knowledge_document_chunked",
                        "document_id": entry.document_id,
                        "chunk_size": settings.chunk_size,
                        "chunk_overlap": settings.chunk_overlap,
                        "block_count": len(parsed.blocks),
                        "chunk_count": len(chunks),
                        "max_chunk_chars": max(len(item.text) for item in chunks),
                    },
                    ensure_ascii=False,
                )
            )

            document.char_count = parsed.char_count
            removed_chunk_ids = repository.replace_chunks(document, chunks)
            if removed_chunk_ids:
                stale_chunk_ids.extend(removed_chunk_ids)
            staged.append((entry, chunks))

            report.outcomes.append(
                DocumentOutcome(
                    document_id=entry.document_id,
                    document_version=entry.document_version,
                    status="imported" if entry.enabled else "disabled",
                    chunk_count=len(chunks),
                )
            )
        except IngestError as exc:
            report.documents_failed += 1
            report.outcomes.append(
                DocumentOutcome(
                    document_id=entry.document_id,
                    document_version=entry.document_version,
                    status="failed",
                    error_code=exc.code,
                    error_detail=exc.detail or exc.message,
                )
            )
            log_event(
                logger,
                "knowledge_document_failed",
                document_id=entry.document_id,
                error=exc.message,
            )

    # 第二阶段：编码 + 写入暂存 snapshot 的 collection
    active_snapshot = repository.get_active_snapshot()
    snapshot_id = f"snap-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    store: QdrantKnowledgeStore | None = None
    snapshot_row = None
    try:
        covered_ids = {entry.document_id for entry, _ in staged}
        all_chunks: list[tuple[DocumentEntry, ChunkRecord]] = []
        for entry, chunks in staged:
            if not entry.enabled:
                # 停用文档保留可追溯内容，但不进入索引
                latest = repository.latest_document_version(entry.document_id)
                if latest is not None:
                    # 停用文档不参与检索，其切片配置版本不影响跳过判定
                    repository.mark_document_indexed(latest)
                    latest.enabled = False
                continue
            all_chunks.extend((entry, chunk) for chunk in chunks)

        manifest_ids = {entry.document_id for entry in manifest.documents if entry.enabled}
        stale_config_documents = [
            document
            for document in repository.list_documents()
            if document.enabled
            and (not restrict_to_manifest or document.document_id in manifest_ids)
            and document.index_status == "succeeded"
            and document.document_id not in covered_ids
            and repository.document_chunk_config_version(document) != settings.chunk_config_version
        ]

        # 先收集"沿用已有片段"的文档，再补上重新切片的文档，避免同一文档被计入两次。
        # 被判定为「重复导入」的文档片段已在库中，但必须仍然进入本次快照，
        # 否则新快照会缺内容（历史实现只从 active_documents 取，
        # 在「先导入暂存再激活」与对照实验场景下会得到空集合）。
        for document in repository.list_documents():
            if restrict_to_manifest and document.document_id not in manifest_ids:
                continue
            if document.document_id in covered_ids:
                continue
            if not document.enabled or document.index_status != "succeeded":
                continue
            if document in stale_config_documents:
                continue
            entry = _entry_from_document(document)
            all_chunks.extend((entry, _row_to_chunk(row)) for row in document.chunks)

        if stale_config_documents:
            for document in stale_config_documents:
                entry = _entry_from_document(document)
                source = _resolve_source(root, entry)
                text = _read_text(source)
                parsed = parse_markdown(text)
                drafts = chunk_document(
                    parsed,
                    chunk_size=settings.chunk_size,
                    chunk_overlap=settings.chunk_overlap,
                )
                rows = [
                    ChunkRecord(
                        chunk_id=build_chunk_id(
                            entry.document_id, entry.document_version, index, draft.text
                        ),
                        document_id=entry.document_id,
                        document_version=entry.document_version,
                        heading_path=" > ".join(item for item in draft.heading_path if item),
                        source_locator=(
                            f"{entry.source_path}#L{draft.start_line + 1}-L{draft.end_line + 1}"
                        ),
                        text=draft.text,
                        content_hash=content_hash(draft.text),
                        parent_group_id=draft.parent_group_id,
                        char_count=len(draft.text),
                        knowledge_base_id=entry.knowledge_base_id,
                        visibility=entry.visibility,
                        product_models=entry.product_models,
                        regions=entry.regions,
                        channels=entry.channels,
                    )
                    for index, draft in enumerate(drafts)
                ]
                removed = repository.replace_chunks(document, rows)
                stale_chunk_ids.extend(removed)
                all_chunks.extend((entry, chunk) for chunk in rows)
            log_event(
                logger,
                "knowledge_rechunked_for_config_change",
                documents=len(stale_config_documents),
                chunk_config_version=settings.chunk_config_version,
            )

        if not all_chunks:
            raise IngestError("没有可索引的片段", detail="请检查清单中 enabled 的文档")

        texts = [chunk.text for _, chunk in all_chunks]
        batch = embedding_provider.encode(texts)
        if batch.is_mock:
            raise IngestError(
                "编码后端为 mock，拒绝写入正式索引",
                detail=f"model_id={batch.model_id}；正式导入必须使用真实编码服务",
            )
        if len(batch.dense) != len(all_chunks):
            raise IngestError(
                "编码结果数量与片段数量不一致",
                detail=f"{len(batch.dense)} != {len(all_chunks)}",
            )

        sparse_dimension = max(
            (max(item.indices) + 1 for item in batch.sparse if item.indices), default=0
        )

        manifest_row = IndexManifest(
            snapshot_id=snapshot_id,
            created_at=datetime.now(UTC).isoformat(),
            status="staging",
            embedding_model_id=batch.model_id,
            embedding_revision=batch.model_revision,
            sparse_model_id=batch.sparse_model_id,
            sparse_model_revision=batch.sparse_model_revision,
            tokenizer_revision=batch.tokenizer_revision,
            vector_dimension=batch.dimension,
            chunk_config_version=settings.chunk_config_version,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            sparse_dimension=sparse_dimension,
            document_count=len({chunk.document_id for _, chunk in all_chunks}),
            chunk_count=len(all_chunks),
            knowledge_base_ids=report.knowledge_base_ids,
            manifest_content_hash=manifest_digest,
        )
        collection = QdrantKnowledgeStore.collection_name(snapshot_id)
        snapshot_row = repository.create_snapshot(manifest_row, collection=collection)
        store = QdrantKnowledgeStore(
            settings.qdrant_path_resolved, vector_dimension=batch.dimension
        )
        store.recreate_collection(collection)
        written = store.upsert_chunks(
            collection,
            chunk_ids=[chunk.chunk_id for _, chunk in all_chunks],
            dense=batch.dense,
            sparse=batch.sparse,
            payloads=[_chunk_payload(chunk, entry, entry.title) for entry, chunk in all_chunks],
        )
        # 新集合是从零重建的，被取代的片段自然不会出现；
        # 这里保留显式清理，防止将来改为增量写入时留下孤儿向量。
        if stale_chunk_ids:
            store.delete_chunks(collection, stale_chunk_ids)

        # 校验：数量、维度、引用完整性
        indexed = store.count(collection)
        if indexed != written:
            raise IngestError("索引数量校验失败", detail=f"写入 {written}，实际 {indexed}")
        if batch.dimension != manifest_row.vector_dimension:
            raise IngestError("向量维度校验失败", detail=f"{batch.dimension}")
        missing = [
            chunk.chunk_id
            for _, chunk in all_chunks
            if not chunk.document_id or not chunk.knowledge_base_id
        ]
        if missing:
            raise IngestError("片段引用不完整", detail=f"{len(missing)} 条缺少文档或知识库引用")

        report.chunks_created = written
        report.vector_dimension = batch.dimension
        report.snapshot_id = snapshot_id
        report.collection = collection
        lengths = [len(chunk.text) for _, chunk in all_chunks]
        report.max_chunk_chars = max(lengths) if lengths else 0
        report.mean_chunk_chars = round(sum(lengths) / len(lengths)) if lengths else 0
        for outcome in report.outcomes:
            if outcome.status == "imported":
                report.documents_imported += 1

        if activate:
            repository.activate_snapshot(snapshot_row, collection=collection)
            report.snapshot_status = "active"
        else:
            report.snapshot_status = "staging"

        # 只有真正进入本次索引的文档才标记为索引成功
        indexed_document_ids = {chunk.document_id for _, chunk in all_chunks}
        for document in repository.list_documents():
            if document.document_id in indexed_document_ids:
                repository.mark_document_indexed(
                    document, chunk_config_version=settings.chunk_config_version
                )

        repository.finish_run(run_row, status="succeeded", detail=report.to_dict())
        log_event(
            logger,
            "knowledge_ingest_succeeded",
            run_id=run_id,
            snapshot_id=snapshot_id,
            chunks=written,
            dimension=batch.dimension,
        )
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        detail = getattr(exc, "detail", None) or str(exc)
        report.snapshot_status = "failed"
        report.error_code = str(code)
        report.error_detail = str(detail)[:1000]
        if snapshot_row is not None:
            repository.mark_snapshot_failed(
                snapshot_row, error_code=str(code), error_detail=str(detail)
            )
        elif report.snapshot_id:
            failed = repository.get_snapshot(report.snapshot_id)
            if failed is not None:
                repository.mark_snapshot_failed(
                    failed, error_code=str(code), error_detail=str(detail)
                )
        repository.finish_run(
            run_row,
            status="failed",
            detail=report.to_dict(),
            error_code=str(code),
            error_detail=str(detail)[:1000],
        )
        log_event(logger, "knowledge_ingest_failed", run_id=run_id, error=str(code))
        # 明确报告：当前有效快照未被破坏
        if active_snapshot is not None:
            report.error_detail = (
                f"{report.error_detail}｜当前有效快照仍为 {active_snapshot.snapshot_id}"
            )
    finally:
        # 必须显式释放：Qdrant local 依赖 __del__ 收尾会导致解释器关闭阶段报错
        if store is not None:
            store.close()

    return report


def _entry_from_document(document) -> DocumentEntry:  # type: ignore[no-untyped-def]
    """由已入库的文档行重建清单条目，用于按新切片配置重新切片。"""

    from app.domain.enums import Visibility

    return DocumentEntry(
        document_id=document.document_id,
        knowledge_base_id=document.knowledge_base_id,
        title=document.title,
        document_version=document.document_version,
        source_path=document.source_path,
        visibility=Visibility(document.visibility),
        product_models=json.loads(document.product_models_json),
        regions=json.loads(document.regions_json),
        channels=json.loads(document.channels_json),
        effective_from=document.effective_from,
        effective_to=document.effective_to,
        enabled=document.enabled,
    )


def _row_to_chunk(row) -> ChunkRecord:  # type: ignore[no-untyped-def]
    from app.domain.enums import Visibility

    return ChunkRecord(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version=row.document_version,
        heading_path=row.heading_path,
        source_locator=row.source_locator,
        text=row.text,
        content_hash=row.content_hash,
        parent_group_id=row.parent_group_id,
        char_count=row.char_count,
        knowledge_base_id=row.knowledge_base_id,
        visibility=Visibility(row.visibility),
        product_models=json.loads(row.product_models_json),
        regions=json.loads(row.regions_json),
        channels=json.loads(row.channels_json),
    )


def active_snapshot_summary(session: Session) -> dict[str, object] | None:
    repository = KnowledgeRepository(session)
    snapshot = repository.get_active_snapshot()
    if snapshot is None:
        return None
    return {
        "snapshot_id": snapshot.snapshot_id,
        "status": snapshot.status,
        "embedding_model_id": snapshot.embedding_model_id,
        "embedding_revision": snapshot.embedding_revision,
        "sparse_model_id": snapshot.sparse_model_id,
        "vector_dimension": snapshot.vector_dimension,
        "chunk_config_version": snapshot.chunk_config_version,
        "chunk_size": snapshot.chunk_size,
        "chunk_overlap": snapshot.chunk_overlap,
        "document_count": snapshot.document_count,
        "chunk_count": snapshot.chunk_count,
        "qdrant_collection": snapshot.qdrant_collection,
        "activated_at": snapshot.activated_at.isoformat() if snapshot.activated_at else None,
    }


def today() -> date:
    return datetime.now(UTC).date()
