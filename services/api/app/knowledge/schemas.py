"""知识库清单与文档的数据契约。

字段来源：PRD 第 3.5 节与工程规范第 12.2 节。
这些字段在导入时由清单/处理程序填入，**不让聊天模型自由生成**。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import KnowledgeSourceType, Visibility
from app.knowledge.document_metadata import DocumentMetadata

ParseStatus = Literal["pending", "running", "succeeded", "failed"]
IndexStatus = Literal["pending", "running", "succeeded", "failed"]

UNAVAILABLE = "unavailable"


class KnowledgeBase(BaseModel):
    """知识库配置。权限由 source_type 之外的显式字段决定，不靠名称猜测。"""

    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: str
    name: str
    source_type: KnowledgeSourceType
    enabled: bool = True


class DocumentEntry(BaseModel):
    """文档身份、适用条件与处理状态的清单条目。"""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    knowledge_base_id: str
    title: str
    document_version: str
    source_path: str
    visibility: Visibility
    enabled: bool = True

    product_models: list[str] = Field(min_length=1)
    regions: list[str] = Field(min_length=1)
    channels: list[str] = Field(min_length=1)
    effective_from: date
    effective_to: date | None = None

    # 停用原因等说明，不参与检索但保留可追溯信息
    disabled_reason: str | None = None

    @field_validator("source_path")
    @classmethod
    def _reject_directory_escape(cls, value: str) -> str:
        """路径不得逃出知识根目录，也不得是绝对路径。"""

        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized:
            raise ValueError(f"source_path 必须是相对路径：{value!r}")
        parts = [part for part in normalized.split("/") if part]
        if any(part == ".." for part in parts):
            raise ValueError(f"source_path 不得包含 '..'：{value!r}")
        return "/".join(parts)

    @model_validator(mode="after")
    def _check_effective_range(self) -> DocumentEntry:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError(
                f"{self.document_id}: effective_to({self.effective_to}) 早于 "
                f"effective_from({self.effective_from})"
            )
        if "global" in self.regions and len(self.regions) > 1:
            raise ValueError(
                f"{self.document_id}: regions 中 'global' 不能与其他地区并列，否则无法判断适用范围"
            )
        return self

    def is_effective_on(self, on_date: date) -> bool:
        if on_date < self.effective_from:
            return False
        return self.effective_to is None or on_date <= self.effective_to


class KnowledgeManifest(BaseModel):
    """导入清单。"""

    model_config = ConfigDict(extra="forbid")

    manifest_version: str
    generated_note: str | None = None
    data_provenance: dict[str, str] = Field(default_factory=dict)
    knowledge_bases: list[KnowledgeBase]
    documents: list[DocumentEntry]

    @model_validator(mode="after")
    def _check_references(self) -> KnowledgeManifest:
        known = {item.knowledge_base_id for item in self.knowledge_bases}
        unknown = {
            entry.knowledge_base_id
            for entry in self.documents
            if entry.knowledge_base_id not in known
        }
        if unknown:
            raise ValueError(f"文档引用了未声明的知识库：{sorted(unknown)}")
        seen: set[tuple[str, str]] = set()
        for entry in self.documents:
            key = (entry.document_id, entry.document_version)
            if key in seen:
                raise ValueError(f"清单中重复的 document_id + version：{key}")
            seen.add(key)
        return self

    def knowledge_base(self, knowledge_base_id: str) -> KnowledgeBase:
        for item in self.knowledge_bases:
            if item.knowledge_base_id == knowledge_base_id:
                return item
        raise KeyError(knowledge_base_id)

    def enabled_knowledge_bases(self) -> list[KnowledgeBase]:
        return [item for item in self.knowledge_bases if item.enabled]


class ChunkRecord(BaseModel):
    """片段契约（工程规范第 12.2 节「片段」一行）。"""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    document_version: str
    heading_path: str
    source_locator: str
    text: str
    content_hash: str
    parent_group_id: str | None = None
    char_count: int
    knowledge_base_id: str
    visibility: Visibility
    product_models: list[str]
    regions: list[str]
    channels: list[str]


class IndexManifest(BaseModel):
    """索引版本契约（工程规范第 12.2 节「索引版本」一行）。

    两个通道都记录版本；服务不暴露 revision 时记录 `unavailable` 及请求的模型 ID，
    **不能编造**。
    """

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    created_at: str
    status: Literal["staging", "active", "superseded", "failed"]
    embedding_model_id: str
    embedding_revision: str
    sparse_model_id: str
    sparse_model_revision: str
    tokenizer_revision: str
    vector_dimension: int
    chunk_config_version: str
    chunk_size: int
    chunk_overlap: int
    sparse_dimension: int
    document_count: int
    chunk_count: int
    knowledge_base_ids: list[str]
    manifest_content_hash: str
    error_code: str | None = None
    error_detail: str | None = None


class RetrievalEvidence(BaseModel):
    """检索证据契约（工程规范第 12.2 节「检索证据」一行）。"""

    model_config = ConfigDict(extra="forbid")

    retrieval_id: str
    snapshot_id: str
    chunk_id: str
    document_id: str
    document_version: str
    document_title: str
    knowledge_base_id: str
    visibility: Visibility
    heading_path: str
    source_locator: str
    quoted_excerpt: str
    applicability: dict[str, list[str] | str]
    channel_ranks: dict[str, int | None]
    rrf_score: float
    #: 精排分数。未启用重排序时保持为空——不得用 0 假装"排过了"。
    rerank_score: float | None = None
    #: 产生该分数的重排序模型；未启用时为空
    rerank_model: str | None = None
    document_metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
