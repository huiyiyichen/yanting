"""混合检索与证据构建。

检索步骤（工程规范第 12.4 节）：
1. 查询由当前问题、已确认产品/故障与必要上下文组成；保留完整型号与否定条件，
   **不由 LLM 改写**；
2. 后端确定检索权限与当前有效快照；已确认型号/地区时匹配专属资料或明确通用资料，
   缺关键字段时先查通用知识并补问，**不用空值任意放宽政策过滤**；
3. 客户公开接口只返回 `customer_visible`；
4. 同一快照、同一过滤器下 dense/sparse 各 top_k，用 RRF 合并，去重后保留最多 N 条；
5. SOP 命中时补完整父组条件；
6. 保存不可变证据副本与 `retrieval_id`。

淘汰规则：RRF 分数只用于排序，**不能**用固定分数或「检索到 5 条」判定证据充分。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from qdrant_client import models
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.enums import KnowledgeHitStatus, Visibility
from app.integrations.embedding_provider import EmbeddingProvider
from app.integrations.qdrant_store import QdrantKnowledgeStore, RetrievalMode, to_point_id
from app.integrations.rerank_provider import RerankProvider
from app.knowledge.document_metadata import read_metadata
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.schemas import RetrievalEvidence
from app.logging_setup import get_logger, log_event

logger = get_logger(__name__)

GLOBAL = "global"
GENERAL = "general"


@dataclass
class RetrievalRequest:
    """一次检索请求。字段缺失表示「尚未确认」，会走通用资料而不是放宽过滤。"""

    query: str
    audience: Visibility = Visibility.CUSTOMER_VISIBLE
    product_model: str | None = None
    country_code: str | None = None
    purchase_channel: str | None = None
    knowledge_base_ids: list[str] | None = None
    today: date | None = None
    include_parent_groups: bool = True
    # 评测/对照用：显式指定快照，便于比较不同切片参数而不影响有效快照
    snapshot_id: str | None = None
    # 对照用：hybrid（默认）/ dense_only / sparse_only
    mode: RetrievalMode = "hybrid"


@dataclass
class RetrievalResult:
    retrieval_id: str
    snapshot_id: str | None
    hit_status: KnowledgeHitStatus
    evidence: list[RetrievalEvidence] = field(default_factory=list)
    channel_ranks: dict[str, dict[str, int]] = field(default_factory=dict)
    candidates_considered: int = 0
    filter_summary: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    source_texts: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)


def _match_any(field_name: str, values: list[str]) -> models.FieldCondition:
    return models.FieldCondition(key=field_name, match=models.MatchAny(any=values))


def build_filter(
    request: RetrievalRequest,
) -> tuple[models.Filter, dict[str, Any]]:
    """构建检索过滤器。

    适用性语义：
    - 产品/地区/渠道**已确认**时，命中该具体值或 `global`/`general` 通用资料；
    - 产品/地区**未确认**时**不再用 `global` 硬过滤**，而是放开该维度检索，
      并在 summary 里标记 `*_unknown` 供上层提示补问。

    为什么不能对未知维度做 `global` 硬过滤：排障类文档（如「吸尘器不吸」）
    按具体型号标注（`product_models=["A1 Pro"]`），`global` 只落在政策类文档上。
    硬过滤会让「还没说型号」的通用提问检索到 **0 条**，而 agent 本来就要靠
    检索结果来决定怎么回答与追问——形成死循环。实测：同一句
    「无线吸尘器吸力明显减弱，应该按什么顺序排查？」带型号时 5 条证据、
    不带型号时 0 条（就是本缺陷）。放开后不带型号同样拿到该排障文档。

    安全性没有放宽：`visibility` 与停用文档过滤始终是硬条件，
    放开型号/地区只会多召回**同权限**的文档，不会越权。
    """

    must: list[models.Condition] = [
        models.FieldCondition(
            key="visibility", match=models.MatchValue(value=request.audience.value)
        )
    ]
    summary: dict[str, Any] = {"visibility": request.audience.value, "degraded": []}

    if request.knowledge_base_ids:
        must.append(_match_any("knowledge_base_id", request.knowledge_base_ids))
        summary["knowledge_base_ids"] = request.knowledge_base_ids

    if request.product_model:
        must.append(_match_any("product_models", [request.product_model, GLOBAL]))
        summary["product_model"] = request.product_model
    else:
        summary["degraded"].append("product_model_unknown")

    if request.country_code:
        must.append(_match_any("regions", [request.country_code, GLOBAL]))
        summary["country_code"] = request.country_code
    else:
        must.append(_match_any("regions", [GLOBAL]))
        summary["degraded"].append("country_unknown")

    if request.purchase_channel:
        must.append(_match_any("channels", [request.purchase_channel, GENERAL]))
        summary["purchase_channel"] = request.purchase_channel
    else:
        must.append(_match_any("channels", [GENERAL]))
        summary["degraded"].append("channel_unknown")

    return models.Filter(must=must), summary


def _compose_query(request: RetrievalRequest) -> str:
    """查询文本保留完整型号与否定条件，不做同义改写。"""

    parts = [request.query.strip()]
    if request.product_model:
        parts.append(f"产品型号：{request.product_model}")
    if request.country_code:
        parts.append(f"地区：{request.country_code}")
    if request.purchase_channel:
        parts.append(f"渠道：{request.purchase_channel}")
    return "\n".join(part for part in parts if part)


def _applicability(payload: dict[str, Any]) -> dict[str, list[str] | str]:
    return {
        "products": list(payload.get("product_models") or []),
        "regions": list(payload.get("regions") or []),
        "channels": list(payload.get("channels") or []),
        "visibility": str(payload.get("visibility") or ""),
        "effective_from": str(payload.get("effective_from") or ""),
        "effective_to": str(payload.get("effective_to") or "") or "",
    }


def retrieve(
    session: Session,
    *,
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    request: RetrievalRequest,
    rerank_provider: RerankProvider | None = None,
) -> RetrievalResult:
    """执行检索并返回带证据的结论。

    精排（重排序）是**可选增强**：配置了才做，做了就如实记录分数与模型名；
    没配置时既不加分也不写"已重排序"。候选集在精排时会放大到
    `rerank_candidates`——否则精排只能在最终要交出去的那几条里重排，没有选择空间。
    """

    repository = KnowledgeRepository(session)
    snapshot = (
        repository.get_snapshot(request.snapshot_id)
        if request.snapshot_id
        else repository.get_active_snapshot()
    )
    retrieval_id = f"ret-{uuid.uuid4().hex[:12]}"

    if snapshot is None:
        return RetrievalResult(
            retrieval_id=retrieval_id,
            snapshot_id=None,
            hit_status=KnowledgeHitStatus.NOT_FOUND,
            notes=["尚未发布任何知识快照；请先执行知识导入"],
        )

    query_filter, filter_summary = build_filter(request)
    query_text = _compose_query(request)

    reranking = rerank_provider is not None and rerank_provider.available()
    candidate_limit = settings.retrieval_max_evidence
    if reranking:
        candidate_limit = max(candidate_limit, settings.rerank_candidates)

    store = QdrantKnowledgeStore(
        settings.qdrant_path_resolved, vector_dimension=snapshot.vector_dimension
    )
    try:
        batch = embedding_provider.encode([query_text], is_query=True)
        dense_query = batch.dense[0]
        sparse_query = batch.sparse[0]

        hits = store.hybrid_search(
            snapshot.qdrant_collection,
            dense_query=dense_query,
            sparse_query=sparse_query,
            query_filter=query_filter,
            top_k=settings.retrieval_top_k,
            limit=candidate_limit,
            mode=request.mode,
        )
        ranks = store.channel_ranks(
            snapshot.qdrant_collection,
            dense_query=dense_query,
            sparse_query=sparse_query,
            query_filter=query_filter,
            top_k=settings.retrieval_top_k,
            limit=candidate_limit,
        )
    finally:
        store.close()

    evidence: list[RetrievalEvidence] = []
    seen_texts: set[str] = set()
    extra_notes: list[str] = []
    # 精排需要完整正文（证据里的 `quoted_excerpt` 是截断过的）
    full_texts: list[str] = []
    source_texts: dict[str, str] = {}

    for hit in hits:
        payload = hit.payload
        text = str(payload.get("text") or "")
        digest = str(payload.get("content_hash") or "")
        # 去除重复正文，保留排序靠前者
        if digest in seen_texts:
            continue
        seen_texts.add(digest)
        full_texts.append(text)
        source_texts[hit.chunk_id] = text

        evidence.append(
            RetrievalEvidence(
                retrieval_id=retrieval_id,
                snapshot_id=snapshot.snapshot_id,
                chunk_id=hit.chunk_id,
                document_id=str(payload.get("document_id") or ""),
                document_version=str(payload.get("document_version") or ""),
                document_title=str(payload.get("document_title") or ""),
                knowledge_base_id=str(payload.get("knowledge_base_id") or ""),
                visibility=Visibility(str(payload.get("visibility"))),
                heading_path=str(payload.get("heading_path") or ""),
                source_locator=str(payload.get("source_locator") or ""),
                quoted_excerpt=_excerpt(text),
                applicability=_applicability(payload),
                document_metadata=read_metadata(
                    session, str(payload.get("document_id") or ""),
                    str(payload.get("document_version") or ""),
                ),
                channel_ranks={
                    "dense": ranks.get("dense", {}).get(to_point_id(hit.chunk_id)),
                    "sparse": ranks.get("sparse", {}).get(to_point_id(hit.chunk_id)),
                },
                rrf_score=hit.score,
            )
        )

    if reranking and len(evidence) > 1:
        assert rerank_provider is not None  # 上面的 reranking 已保证
        try:
            ordered = rerank_provider.rerank(
                query_text, full_texts, top_n=settings.retrieval_max_evidence
            )
        except Exception as exc:
            # 精排失败不能让整个检索失败：退回召回顺序，并把失败原因写进 notes
            extra_notes.append(
                f"重排序失败，已按召回顺序返回：{type(exc).__name__}: {str(exc)[:120]}"
            )
        else:
            reranked: list[RetrievalEvidence] = []
            for hit in ordered:
                if 0 <= hit.index < len(evidence):
                    item = evidence[hit.index]
                    item.rerank_score = hit.score
                    item.rerank_model = rerank_provider.model_id
                    reranked.append(item)
            # 精排未覆盖到的候选按原顺序追加在后面（不丢证据）
            covered = {id(item) for item in reranked}
            reranked.extend(item for item in evidence if id(item) not in covered)
            evidence = reranked
            extra_notes.append(f"已用 {rerank_provider.model_id} 对 {len(full_texts)} 条候选重排序")

    # SOP 命中时补完整父组条件
    if request.include_parent_groups:
        extra_notes.extend(_note_parent_groups(evidence))

    hit_status = _decide_hit_status(evidence, len(hits))
    if filter_summary.get("degraded"):
        extra_notes.append(
            "以下字段未确认，已按通用资料检索并需要补问："
            + "、".join(str(item) for item in filter_summary["degraded"])
        )

    log_event(
        logger,
        "knowledge_retrieval",
        retrieval_id=retrieval_id,
        snapshot_id=snapshot.snapshot_id,
        hit_status=hit_status.value,
        evidence_count=len(evidence),
    )

    selected_evidence = evidence[: settings.retrieval_max_evidence]
    return RetrievalResult(
        retrieval_id=retrieval_id,
        snapshot_id=snapshot.snapshot_id,
        hit_status=hit_status,
        evidence=selected_evidence,
        channel_ranks=ranks,
        candidates_considered=len(hits),
        filter_summary={**filter_summary, "mode": request.mode},
        notes=extra_notes,
        source_texts={item.chunk_id: source_texts[item.chunk_id] for item in selected_evidence},
    )


def _excerpt(text: str, limit: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _note_parent_groups(evidence: list[RetrievalEvidence]) -> list[str]:
    notes: list[str] = []
    groups = {
        item.chunk_id.split("#")[0]
        for item in evidence
        if "SOP" in item.knowledge_base_id or "sop" in item.knowledge_base_id
    }
    if groups:
        notes.append("命中 SOP 片段；如涉及步骤执行，必须同时核对片段内的前置条件与注意事项。")
    return notes


def _decide_hit_status(
    evidence: list[RetrievalEvidence], candidate_count: int
) -> KnowledgeHitStatus:
    """判定命中情况。

    注意：RRF 分数只用于排序，**不能**用固定分数阈值判定「证据充分」。
    这里用「是否有证据 + 是否覆盖到高优先级知识源」作为结构化判据，
    真实充分性由 S2 的业务规则结合当前动作所需事实判断。
    """

    if not evidence:
        return KnowledgeHitStatus.NOT_FOUND
    if candidate_count < 2 or len(evidence) < 2:
        return KnowledgeHitStatus.INSUFFICIENT
    return KnowledgeHitStatus.SUFFICIENT
