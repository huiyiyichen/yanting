from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.deps import get_context, get_session, require_support
from app.domain.consumer_service.importer import DATASET_ID
from app.domain.consumer_service.models import DatasetRow, ServiceOrderRow
from app.domain.consumer_service.tickets import record_event
from app.domain.enums import KnowledgeSourceType, Visibility
from app.errors import ConflictError, NotFoundError, ValidationRejected
from app.knowledge.chunking import chunk_document
from app.knowledge.document_metadata import (
    DocumentMetadata,
    publication_content,
    read_metadata,
    write_metadata,
)
from app.knowledge.ingest import _entry_from_document, ingest_manifest
from app.knowledge.models import (
    KnowledgeBaseRow,
    KnowledgeDocumentRow,
    KnowledgeDraftRow,
    KnowledgeReferenceProductRow,
)
from app.knowledge.parsing import parse_markdown
from app.knowledge.retrieval import RetrievalRequest, retrieve
from app.knowledge.schemas import DocumentEntry, KnowledgeBase, KnowledgeManifest, RetrievalEvidence
from app.routes.commit import CommitBeforeResponseRoute
from app.runtime import RuntimeContext
from app.schemas.base import ApiModel

router = APIRouter(
    prefix="/api/platform/knowledge", tags=["knowledge-management"],
    route_class=CommitBeforeResponseRoute, dependencies=[Depends(require_support)],
)
_publish_lock = Lock()


class KnowledgeEditRequest(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    knowledge_base_id: str = "loreal-service"
    expected_revision: int = Field(default=0, ge=0)
    metadata: DocumentMetadata | None = None


class KnowledgeChunkView(ApiModel):
    locator: str
    text: str
    char_count: int


class KnowledgeEditorView(ApiModel):
    document_id: str
    knowledge_base_id: str
    title: str
    content: str
    revision: int
    status: str
    enabled: bool
    error: str | None = None
    chunks: list[KnowledgeChunkView]
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


class KnowledgeProductView(ApiModel):
    sku: str
    name: str
    identity_kind: str = "official_fixture"
    market: str = "CN"
    brand: str = ""
    source_url: str = ""
    image_url: str = ""
    aliases: list[str] = Field(default_factory=list)


class KnowledgeToggleRequest(ApiModel):
    enabled: bool


class KnowledgeBaseCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=100)


class KnowledgePublishView(ApiModel):
    ok: bool
    snapshot_id: str | None = None
    chunk_count: int = 0
    message: str


class KnowledgeSearchRequest(ApiModel):
    query: str = Field(min_length=1, max_length=2000)
    knowledge_base_id: str | None = None
    product_sku: str | None = None


class KnowledgeSearchView(ApiModel):
    hit_status: str
    snapshot_id: str | None
    evidence: list[RetrievalEvidence]


def _documents(session: Session) -> dict[str, KnowledgeDocumentRow]:
    rows = session.scalars(select(KnowledgeDocumentRow).where(
        KnowledgeDocumentRow.knowledge_base_id.like("loreal-%"),
    ).order_by(KnowledgeDocumentRow.document_pk))
    return {row.document_id: row for row in rows}


def _read_source(row: KnowledgeDocumentRow, context: RuntimeContext) -> str:
    path = Path(row.source_abs_path).resolve()
    allowed = [(REPO_ROOT / "data/knowledge").resolve(), context.settings.runtime_path]
    if not any(path.is_relative_to(root) for root in allowed):
        raise ValidationRejected("知识源不在允许的资料目录")
    if not path.is_file():
        raise NotFoundError("知识源文件不存在")
    return path.read_text(encoding="utf-8")


def _editor(session: Session, document_id: str, context: RuntimeContext) -> KnowledgeEditorView:
    draft = session.get(KnowledgeDraftRow, document_id)
    row = _documents(session).get(document_id)
    if not draft and not row:
        raise NotFoundError("知识文档不存在")
    content = draft.content if draft else _read_source(row, context)
    metadata = read_metadata(session, document_id, "draft" if draft else row.document_version)
    chunks = chunk_document(
        parse_markdown(publication_content(draft.title, content, metadata) if draft else content),
        chunk_size=context.settings.chunk_size,
        chunk_overlap=context.settings.chunk_overlap,
    )
    return KnowledgeEditorView(
        document_id=document_id,
        knowledge_base_id=draft.knowledge_base_id if draft else row.knowledge_base_id,
        title=draft.title if draft else row.title, content=content,
        revision=draft.revision if draft else 0, status=draft.status if draft else "published",
        enabled=row.enabled if row else True, error=draft.error if draft else None,
        metadata=metadata,
        chunks=[KnowledgeChunkView(
            locator=f"L{item.start_line + 1}-L{item.end_line + 1}",
            text=item.text, char_count=len(item.text),
        ) for item in chunks],
    )


@router.get("/documents", response_model=list[KnowledgeEditorView])
def documents(session: Session = Depends(get_session), context: RuntimeContext = Depends(get_context)):
    ids = set(_documents(session))
    ids.update(session.scalars(select(KnowledgeDraftRow.document_id)))
    # Listing does not read source files or call embedding services.
    result = []
    current = _documents(session)
    for document_id in sorted(ids):
        draft = session.get(KnowledgeDraftRow, document_id)
        row = current.get(document_id)
        result.append(KnowledgeEditorView(
            document_id=document_id,
            knowledge_base_id=draft.knowledge_base_id if draft else row.knowledge_base_id,
            title=draft.title if draft else row.title, content="",
            revision=draft.revision if draft else 0, status=draft.status if draft else "published",
            enabled=row.enabled if row else True, error=draft.error if draft else None, chunks=[],
            metadata=read_metadata(session, document_id, "draft" if draft else row.document_version),
        ))
    return result


def _catalog(session: Session) -> list[KnowledgeProductView]:
    dataset = session.get(DatasetRow, DATASET_ID)
    result = [
        KnowledgeProductView(sku=sku, name=name)
        for sku, name in session.execute(
            select(ServiceOrderRow.sku, ServiceOrderRow.product_name)
            .where(ServiceOrderRow.batch_id == (dataset.active_batch_id if dataset else ""),
                   ServiceOrderRow.sku.is_not(None))
            .distinct().order_by(ServiceOrderRow.sku)
        )
    ]
    result.extend(
        KnowledgeProductView.model_validate({
            key: value for key, value in json.loads(row.payload_json).items()
            if key in KnowledgeProductView.model_fields
        })
        for row in session.scalars(select(KnowledgeReferenceProductRow).order_by(
            KnowledgeReferenceProductRow.product_id,
        ))
    )
    return result


@router.get("/products", response_model=list[KnowledgeProductView])
def products(session: Session = Depends(get_session)):
    return _catalog(session)


@router.get("/documents/{document_id}", response_model=KnowledgeEditorView)
def document(
    document_id: str, session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    return _editor(session, document_id, context)


def _save(session: Session, document_id: str, payload: KnowledgeEditRequest, context: RuntimeContext):
    if not payload.title.strip() or not payload.content.strip():
        raise ValidationRejected("标题和内容不能为空")
    base = session.get(KnowledgeBaseRow, payload.knowledge_base_id)
    if not base or not base.enabled or not base.knowledge_base_id.startswith("loreal-"):
        raise ValidationRejected("请选择有效的欧莱雅知识库")
    draft = session.get(KnowledgeDraftRow, document_id)
    if (draft.revision if draft else 0) != payload.expected_revision:
        raise ConflictError("文档草稿已更新，请刷新")
    if payload.metadata:
        if payload.metadata.product_sku:
            product = next((p for p in _catalog(session) if p.sku == payload.metadata.product_sku), None)
            if product is None:
                raise ValidationRejected("关联商品不在当前目录")
            payload.metadata.product_name = product.name
            payload.metadata.market = product.market
            payload.metadata.product_aliases = product.aliases
        write_metadata(session, document_id, "draft", payload.metadata)
    elif draft is None:
        existing = _documents(session).get(document_id)
        if existing:
            write_metadata(session, document_id, "draft", read_metadata(
                session, document_id, existing.document_version,
            ))
    if draft is None:
        draft = KnowledgeDraftRow(document_id=document_id, revision=0)
        session.add(draft)
    draft.knowledge_base_id = payload.knowledge_base_id
    draft.title = payload.title.strip()
    draft.content = payload.content
    draft.revision += 1
    draft.status = "draft"
    draft.error = None
    session.flush()
    record_event(session, document_id, "knowledge", "保存草稿", f"v{draft.revision}")
    return _editor(session, document_id, context)


@router.post("/documents", response_model=KnowledgeEditorView)
def create_document(
    payload: KnowledgeEditRequest, session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    return _save(session, f"loreal-doc-{uuid4().hex[:12]}", payload, context)


@router.put("/documents/{document_id}", response_model=KnowledgeEditorView)
def save_document(
    document_id: str, payload: KnowledgeEditRequest, session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    _editor(session, document_id, context)
    return _save(session, document_id, payload, context)


@router.post("/bases")
def create_base(payload: KnowledgeBaseCreateRequest, session: Session = Depends(get_session)):
    if not payload.name.strip():
        raise ValidationRejected("请填写知识库名称")
    row = KnowledgeBaseRow(
        knowledge_base_id=f"loreal-{uuid4().hex[:10]}", name=payload.name.strip(),
        source_type="sop", enabled=True,
    )
    session.add(row)
    session.flush()
    return {"knowledgeBaseId": row.knowledge_base_id, "name": row.name}


@router.post("/documents/{document_id}/status", response_model=KnowledgeEditorView)
def toggle_document(
    document_id: str, payload: KnowledgeToggleRequest, session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    row = _documents(session).get(document_id)
    if row is None:
        raise ValidationRejected("文档尚未发布")
    row.enabled = payload.enabled
    session.flush()
    record_event(session, document_id, "knowledge", "启用" if payload.enabled else "停用", row.title)
    return _editor(session, document_id, context)


@router.post("/publish", response_model=KnowledgePublishView)
def publish(session: Session = Depends(get_session), context: RuntimeContext = Depends(get_context)):
    if not _publish_lock.acquire(blocking=False):
        raise ConflictError("已有知识发布任务正在运行")
    try:
        current = _documents(session)
        drafts = {row.document_id: row for row in session.scalars(select(KnowledgeDraftRow))
                  if row.status != "published"}
        bases = list(session.scalars(select(KnowledgeBaseRow).where(
            KnowledgeBaseRow.knowledge_base_id.like("loreal-%"), KnowledgeBaseRow.enabled.is_(True),
        )))
        base_ids = {row.knowledge_base_id for row in bases}
        root = context.settings.runtime_path / "knowledge-publications" / uuid4().hex
        root.mkdir(parents=True, exist_ok=True)
        entries = []
        for document_id in sorted(set(current) | set(drafts)):
            row, draft = current.get(document_id), drafts.get(document_id)
            if row and not row.enabled:
                continue
            if draft:
                metadata = read_metadata(session, document_id, "draft")
                entry = DocumentEntry(
                    document_id=document_id, knowledge_base_id=draft.knowledge_base_id,
                    title=draft.title, document_version=f"edit-{draft.revision}",
                    source_path=f"workspace/{document_id}/v{draft.revision}.md",
                    visibility=Visibility.INTERNAL, product_models=[metadata.product_sku]
                    if metadata.scope == "product_specific" else ["global"],
                    regions=["global"], channels=["general"], effective_from=date.today(),
                )
                text = publication_content(draft.title, draft.content, metadata)
            else:
                entry = _entry_from_document(row)
                text = _read_source(row, context)
            if entry.knowledge_base_id not in base_ids:
                continue
            destination = (root / entry.source_path).resolve()
            if not destination.is_relative_to(root.resolve()):
                raise ValidationRejected("资料路径无效")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
            entries.append(entry)
        manifest = KnowledgeManifest(
            manifest_version="loreal-editor-v1",
            knowledge_bases=[KnowledgeBase(
                knowledge_base_id=b.knowledge_base_id, name=b.name,
                source_type=KnowledgeSourceType(b.source_type),
            ) for b in bases],
            documents=entries,
        )
        manifest_path = root / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
        with session.begin_nested() as transaction:
            report = ingest_manifest(
                session, settings=context.settings, embedding_provider=context.embedding_provider,
                manifest_path=manifest_path, knowledge_root=root, restrict_to_manifest=True,
            )
            if report.snapshot_status != "active" or report.documents_failed:
                transaction.rollback()
            else:
                versions = {entry.document_id: entry.document_version for entry in entries}
                for row in session.scalars(select(KnowledgeDocumentRow)):
                    if row.document_id in versions and row.document_version != versions[row.document_id]:
                        row.enabled = False
                for draft in drafts.values():
                    if draft.document_id in versions:
                        write_metadata(session, draft.document_id, versions[draft.document_id],
                                       read_metadata(session, draft.document_id, "draft"))
                        draft.status, draft.error = "published", None
        if report.snapshot_status != "active" or report.documents_failed:
            for draft in drafts.values():
                draft.status = "failed"
                draft.error = report.error_detail or "发布失败，原索引保持不变"
            session.flush()
            return KnowledgePublishView(ok=False, message=report.error_detail or "发布失败")
        record_event(session, report.snapshot_id, "knowledge", "发布索引", str(report.chunks_created))
        return KnowledgePublishView(
            ok=True, snapshot_id=report.snapshot_id, chunk_count=report.chunks_created,
            message="发布完成",
        )
    finally:
        _publish_lock.release()


@router.post("/search", response_model=KnowledgeSearchView)
def search(
    payload: KnowledgeSearchRequest, session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    ids = list(session.scalars(select(KnowledgeBaseRow.knowledge_base_id).where(
        KnowledgeBaseRow.knowledge_base_id.like("loreal-%"), KnowledgeBaseRow.enabled.is_(True),
    )))
    if payload.knowledge_base_id:
        if payload.knowledge_base_id not in ids:
            raise ValidationRejected("知识库不可用")
        ids = [payload.knowledge_base_id]
    if not ids:
        return KnowledgeSearchView(hit_status="not_found", snapshot_id=None, evidence=[])
    result = retrieve(
        session, settings=context.settings, embedding_provider=context.embedding_provider,
        rerank_provider=context.rerank_provider,
        request=RetrievalRequest(
            query=payload.query, audience=Visibility.INTERNAL, knowledge_base_ids=ids,
            product_model=payload.product_sku, country_code="CN",
        ),
    )
    return KnowledgeSearchView(
        hit_status=result.hit_status.value, snapshot_id=result.snapshot_id, evidence=result.evidence,
    )
