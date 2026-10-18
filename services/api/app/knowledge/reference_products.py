"""Seed bounded public references without touching the competition source facts."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.knowledge.document_metadata import DocumentMetadata, write_metadata
from app.knowledge.models import (
    KnowledgeBaseRow,
    KnowledgeDraftRow,
    KnowledgeReferenceProductRow,
)

BASE_ID = "loreal-product-references"
REGISTRY = REPO_ROOT / "data/knowledge/loreal/reference-products.json"
FICTIONAL_BASE_ID = "loreal-fictional-products"
FICTIONAL_REGISTRY = REPO_ROOT / "data/knowledge/loreal/fictional-products.json"


def seed_reference_products(session: Session) -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if session.get(KnowledgeBaseRow, BASE_ID) is None:
        session.add(KnowledgeBaseRow(
            knowledge_base_id=BASE_ID, name="欧莱雅公开商品资料",
            source_type="product_knowledge", enabled=True,
        ))
    for product in registry["products"]:
        key = product["sku"]
        reference = session.get(KnowledgeReferenceProductRow, key)
        if reference is None:
            session.add(KnowledgeReferenceProductRow(
                product_id=key, payload_json=json.dumps(product, ensure_ascii=False),
            ))
        elif product.get("aliases"):
            saved = json.loads(reference.payload_json)
            if (saved.get("name") == product["name"] and saved.get("source_url") == product["source_url"]
                    and "aliases" not in saved):
                # Add identity spellings without replacing saved content or drafts.
                reference.payload_json = json.dumps({**saved, "aliases": product["aliases"]}, ensure_ascii=False)
        document_id = f"loreal-reference-{key.lower()}"
        if session.get(KnowledgeDraftRow, document_id) is not None:
            continue
        session.add(KnowledgeDraftRow(
            document_id=document_id, knowledge_base_id=BASE_ID, title=product["name"],
            content=product["content"], revision=1, status="draft",
        ))
        write_metadata(session, document_id, "draft", DocumentMetadata(
            scope="product_specific", product_sku=key, product_name=product["name"],
            product_aliases=product.get("aliases", []),
            market=product["market"], provenance="official_reference",
            source_label=product["source_label"], source_url=product["source_url"],
        ))
    seed_fictional_products(session)


def seed_fictional_products(session: Session) -> None:
    """官方虚构商品的团队补充资料：货号与订单表一致，发布后按商品专属资料检索。"""
    registry = json.loads(FICTIONAL_REGISTRY.read_text(encoding="utf-8"))
    if session.get(KnowledgeBaseRow, FICTIONAL_BASE_ID) is None:
        session.add(KnowledgeBaseRow(
            knowledge_base_id=FICTIONAL_BASE_ID, name="演示商品资料",
            source_type="product_knowledge", enabled=True,
        ))
    for product in registry["products"]:
        document_id = f"loreal-fictional-{product['sku'].lower()}"
        if session.get(KnowledgeDraftRow, document_id) is not None:
            continue
        session.add(KnowledgeDraftRow(
            document_id=document_id, knowledge_base_id=FICTIONAL_BASE_ID,
            title=f"{product['name']} 商品资料", content=product["content"],
            revision=1, status="draft",
        ))
        write_metadata(session, document_id, "draft", DocumentMetadata(
            scope="product_specific", product_sku=product["sku"], product_name=product["name"],
            product_aliases=product.get("aliases", []), market=product["market"],
            provenance="team_fictional", source_label=product["source_label"],
        ))
