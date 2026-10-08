"""知识基础设施的持久化模型。

设计依据（工程规范第 12.1 节）：
- SQL 文档清单与不可变源文件为**权威记录**，Qdrant 索引可从它们重建；
- LangGraph 状态不是知识版本的唯一存储；
- 同一「来源 + 版本 + 哈希」重复导入不复制；
- 停用与解析成功是两种独立状态；
- 解析成功不等于已经可检索（`parse_status` 与 `index_status` 分开）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_base"

    knowledge_base_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeDraftRow(Base):
    __tablename__ = "knowledge_draft"

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class KnowledgeDocumentMetadataRow(Base):
    """Draft metadata uses version 'draft'; published versions retain their own copy."""

    __tablename__ = "knowledge_document_metadata"

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)


class KnowledgeReferenceProductRow(Base):
    """Public brand references are not products/orders imported from the competition."""

    __tablename__ = "knowledge_reference_product"

    product_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)


class KnowledgeDocumentRow(Base):
    """文档身份。`(source_path, document_version, content_hash)` 共同保证导入幂等。"""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        UniqueConstraint(
            "source_path", "document_version", "content_hash", name="uq_document_identity"
        ),
    )

    document_pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    document_version: Mapped[str] = mapped_column(String(32))
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base.knowledge_base_id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))

    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_path: Mapped[str] = mapped_column(String(500))
    source_abs_path: Mapped[str] = mapped_column(String(1000))

    visibility: Mapped[str] = mapped_column(String(32))
    product_models_json: Mapped[str] = mapped_column(Text)
    regions_json: Mapped[str] = mapped_column(Text)
    channels_json: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    index_status: Mapped[str] = mapped_column(String(16), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 该文档当前片段是用哪个切片配置切出来的。配置变更时必须重新切片，
    # 不能因为「源文件内容哈希相同」就跳过（工程规范第 12.3 节第 5 条）。
    index_chunk_config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    chunks: Mapped[list[KnowledgeChunkRow]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunkRow(Base):
    """不可变片段。随文档版本保留，供历史案件复盘。"""

    __tablename__ = "knowledge_chunk"

    chunk_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    document_pk: Mapped[int] = mapped_column(
        ForeignKey("knowledge_document.document_pk"), index=True
    )
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    document_version: Mapped[str] = mapped_column(String(32))
    knowledge_base_id: Mapped[str] = mapped_column(String(64), index=True)
    visibility: Mapped[str] = mapped_column(String(32), index=True)

    heading_path: Mapped[str] = mapped_column(String(500))
    source_locator: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    parent_group_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer)

    product_models_json: Mapped[str] = mapped_column(Text)
    regions_json: Mapped[str] = mapped_column(Text)
    channels_json: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[KnowledgeDocumentRow] = relationship(back_populates="chunks")


class KnowledgeSnapshotRow(Base):
    """索引快照。发布失败时保留当前有效快照，新快照不激活。"""

    __tablename__ = "knowledge_snapshot"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    embedding_model_id: Mapped[str] = mapped_column(String(200))
    embedding_revision: Mapped[str] = mapped_column(String(200))
    sparse_model_id: Mapped[str] = mapped_column(String(200))
    sparse_model_revision: Mapped[str] = mapped_column(String(200))
    tokenizer_revision: Mapped[str] = mapped_column(String(200))
    vector_dimension: Mapped[int] = mapped_column(Integer)
    sparse_dimension: Mapped[int] = mapped_column(Integer)
    chunk_config_version: Mapped[str] = mapped_column(String(64))
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_overlap: Mapped[int] = mapped_column(Integer)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    knowledge_base_ids_json: Mapped[str] = mapped_column(Text)
    manifest_content_hash: Mapped[str] = mapped_column(String(64))
    qdrant_collection: Mapped[str] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeImportRunRow(Base):
    """一次导入运行的可追溯记录。"""

    __tablename__ = "knowledge_import_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    manifest_path: Mapped[str] = mapped_column(String(500))
    documents_total: Mapped[int] = mapped_column(Integer, default=0)
    documents_imported: Mapped[int] = mapped_column(Integer, default=0)
    documents_skipped: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_created: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
