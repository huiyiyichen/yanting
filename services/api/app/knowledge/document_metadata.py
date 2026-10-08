"""Explicit document applicability and provenance, independent of imported facts."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.knowledge.models import KnowledgeDocumentMetadataRow
from app.schemas.base import ApiModel


class DocumentMetadata(ApiModel):
    scope: Literal["document_context", "general_consumer", "product_specific"] = "document_context"
    product_sku: str | None = Field(default=None, min_length=1, max_length=80)
    product_name: str = Field(default="", max_length=200)
    product_aliases: list[str] = Field(default_factory=list, max_length=6)
    market: Literal["CN", "US", "unknown"] = "unknown"
    provenance: Literal["user_supplied", "official_reference", "team_fictional"] = "user_supplied"
    source_label: str = Field(default="", max_length=160)
    source_url: str = Field(default="", max_length=2000)

    @field_validator("product_sku", "source_label", "source_url")
    @classmethod
    def strip_value(cls, value):
        return value.strip() if value is not None else None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if value:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("来源网址须为不含账号信息的HTTP(S)网址")
        return value

    @field_validator("product_aliases")
    @classmethod
    def validate_aliases(cls, values: list[str]) -> list[str]:
        values = list(dict.fromkeys(value.strip() for value in values))
        if any(not 2 <= len(value) <= 120 for value in values):
            raise ValueError("商品别名长度须为2至120字符")
        return values

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "product_specific":
            if not self.product_sku or not self.source_label:
                raise ValueError("商品资料须选择货号并填写来源")
        elif self.product_sku is not None:
            raise ValueError("只有商品资料可绑定货号")
        if self.provenance == "official_reference" and not self.source_url:
            raise ValueError("官方参考资料须提供来源网址")
        return self


def read_metadata(session: Session, document_id: str, version: str) -> DocumentMetadata:
    row = session.get(KnowledgeDocumentMetadataRow, (document_id, version))
    return DocumentMetadata.model_validate_json(row.payload_json) if row else DocumentMetadata()


def write_metadata(session: Session, document_id: str, version: str, metadata: DocumentMetadata):
    row = session.get(KnowledgeDocumentMetadataRow, (document_id, version))
    if row is None:
        row = KnowledgeDocumentMetadataRow(document_id=document_id, document_version=version)
        session.add(row)
    row.payload_json = metadata.model_dump_json()


def publication_content(title: str, content: str, metadata: DocumentMetadata) -> str:
    if metadata == DocumentMetadata():
        return content
    origin = {
        "user_supplied": "人工提供资料",
        "official_reference": "官方公开参考资料（人工登记）",
        "team_fictional": "团队虚构补充资料",
    }[metadata.provenance]
    scope = {
        "document_context": "文档背景",
        "general_consumer": "通用消费知识，非具体商品依据",
        "product_specific": f"商品专属资料，关联商品标识：{metadata.product_sku}",
    }[metadata.scope]
    lines = [f"# {title}", f"资料范围：{scope}。来源性质：{origin}。"]
    if metadata.product_name:
        lines.append(f"关联商品：{metadata.product_name}")
    if metadata.market != "unknown":
        lines.append(f"参考市场：{'中国大陆' if metadata.market == 'CN' else '美国'}")
    if metadata.source_label:
        lines.append(f"资料来源：{metadata.source_label}")
    if metadata.source_url:
        lines.append(f"来源网址：{metadata.source_url}")
    if metadata.provenance == "team_fictional":
        lines.append("仅描述演示商品，不是官方源数据、真实商品功效评价或临床证据。")
    return "\n\n".join([*lines, content])
