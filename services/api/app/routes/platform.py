"""平台配置接口（模型配置等）。

定位：这是**本机 Demo 的运维视角**，不是生产管理后台——角色仍由服务端校验
（只有 `support` 角色可读），且**不返回任何密钥**：只看得到模型名、网关主机名
与健康状态，密钥永远留在服务端 `.env` 里。

为什么单独一组路由：客户端与客服端都是业务接口；模型配置属于「跑这个 Demo 的人」
视角，混进 `/api/support/*` 会让客服接口的语义变浑（客服工作台不该出现模型密钥配置）。
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field

from app.deps import get_context, get_session, require_support
from app.domain.enums import ViewRole
from app.errors import NotFoundError, ValidationRejected
from app.routes.commit import CommitBeforeResponseRoute
from app.runtime import RuntimeContext
from app.schemas.conversation import ApiModel

router = APIRouter(
    prefix="/api/platform",
    tags=["platform"],
    route_class=CommitBeforeResponseRoute,
)


class ModelProviderView(ApiModel):
    """一行模型配置。`state` 与 `/api/health` 的能力状态同源。"""

    key: str
    label: str
    provider: str
    model: str | None = None
    state: str
    detail: str
    #: 该能力是否已接入（未接入的能力如实标 false，不伪装成可用）
    wired: bool = True
    note: str = ""


class ModelConfigView(ApiModel):
    gateway_host: str | None = None
    run_mode: str
    #: 页面可写的配置（密钥永远只回掩码与「是否已配置」）
    base_url: str = ""
    api_key_masked: str = ""
    has_api_key: bool = False
    text_model: str | None = None
    vision_model: str | None = None
    #: 向量：本地 ONNX 或远端 OpenAI 兼容服务（不再写死"本地"）
    embedding_backend: str = "onnx-local"
    embedding_model: str | None = None
    embedding_path: str = ""
    embedding_base_url: str = ""
    embedding_api_key_masked: str = ""
    has_embedding_api_key: bool = False
    embedding_dimension: int | None = None
    #: 重排序：可选精排，纯 HTTP
    rerank_backend: str = "none"
    rerank_base_url: str = ""
    rerank_api_key_masked: str = ""
    has_rerank_api_key: bool = False
    rerank_model: str | None = None
    #: 页面下拉候选（来自后端常量，不在前端维护第二份清单）
    embedding_model_options: list[str] = Field(default_factory=list)
    rerank_model_options: list[str] = Field(default_factory=list)
    #: 网关上的模型列表（拿不到时为空数组，并给出 `gateway_note`）
    available_models: list[str] = Field(default_factory=list)
    gateway_note: str = ""
    providers: list[ModelProviderView] = Field(default_factory=list)


class TestModelRequest(ApiModel):
    model: str


class TestModelView(ApiModel):
    model: str
    ok: bool
    latency_seconds: float
    message: str


def _mask_host(url: str) -> str | None:
    """只保留主机名：网关地址可能带路径或令牌，不能整串回给前端。"""

    if not url:
        return None
    without_scheme = url.split("//", 1)[-1]
    return without_scheme.split("/", 1)[0]


@router.get("/models", response_model=ModelConfigView)
async def model_config(
    session: Any = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> ModelConfigView:
    """模型配置一览：真实配置 + 真实健康状态 + 网关可用模型列表。"""

    health = context.capabilities()
    settings = context.settings
    provider = context.model_provider

    # Page reads stay local; remote calls belong to explicit connection tests.
    available = list(
        dict.fromkeys(
            value
            for value in [
                provider.model_id,
                settings.llm_model,
                settings.llm_vision_model,
            ]
            if value
        )
    )
    note = ""

    vision_state = "ready" if provider.supports_vision else health.vision.state

    from app.domain.platform.settings import API_KEY_KEY, BASE_URL_KEY, get_setting, mask_secret

    saved_base = get_setting(session, BASE_URL_KEY) or settings.llm_base_url
    saved_key = get_setting(session, API_KEY_KEY) or settings.llm_api_key
    embedding_key = settings.embedding_http_api_key
    rerank_key = settings.rerank_api_key

    from app.integrations.embedding_provider import EMBEDDING_MODEL_OPTIONS
    from app.integrations.rerank_provider import RERANK_MODEL_OPTIONS

    return ModelConfigView(
        gateway_host=_mask_host(saved_base),
        run_mode=settings.run_mode,
        base_url=saved_base,
        api_key_masked=mask_secret(saved_key),
        has_api_key=bool(saved_key),
        text_model=provider.model_id,
        vision_model=settings.llm_vision_model or None,
        embedding_backend=settings.embedding_backend,
        embedding_model=settings.embedding_model_id or None,
        embedding_path=settings.embedding_model_path or "",
        embedding_base_url=settings.embedding_http_base_url or "",
        embedding_api_key_masked=mask_secret(embedding_key),
        has_embedding_api_key=bool(embedding_key),
        embedding_dimension=settings.embedding_dimension,
        rerank_backend=settings.rerank_backend,
        rerank_base_url=settings.rerank_base_url or "",
        rerank_api_key_masked=mask_secret(rerank_key),
        has_rerank_api_key=bool(rerank_key),
        rerank_model=settings.rerank_model or None,
        embedding_model_options=list(EMBEDDING_MODEL_OPTIONS),
        rerank_model_options=list(RERANK_MODEL_OPTIONS),
        available_models=available,
        gateway_note=note,
        providers=[
            ModelProviderView(
                key="llm",
                label="文本模型（LLM）",
                provider="OpenAI 兼容网关",
                model=settings.llm_model or None,
                state=health.llm.state,
                detail=health.llm.detail,
                note="理解与回复都由它生成",
            ),
            ModelProviderView(
                key="vision",
                label="多模态模型",
                provider="OpenAI 兼容网关",
                model=settings.llm_vision_model or None,
                state=vision_state,
                detail=(
                    "已配置多模态模型，可从图片提取可见线索"
                    if provider.supports_vision
                    else "未配置：图片可上传与显示，但无法提取线索，会如实报错"
                ),
                wired=bool(provider.supports_vision),
                note="与文本模型可以是同一个（原生多模态）",
            ),
            ModelProviderView(
                key="embedding",
                label="向量模型（编码）",
                provider=(
                    "本地 ONNX" if settings.embedding_backend == "onnx-local" else "远端 API"
                ),
                model=settings.embedding_model_id or None,
                state=health.embedding.state,
                detail=health.embedding.detail,
                note=(
                    "本地 ONNX：稠密 + 稀疏双通道，改动需重启"
                    if settings.embedding_backend == "onnx-local"
                    else "远端 OpenAI 兼容服务：只有稠密通道，检索退化为单路；改动需重启"
                ),
            ),
            ModelProviderView(
                key="rerank",
                label="重排序模型",
                provider="远端 API" if settings.rerank_backend == "http" else "—",
                model=settings.rerank_model or None,
                state=health.rerank.state,
                detail=health.rerank.detail,
                wired=health.rerank.state == "ready",
                note="精排：对召回候选按相关性重排；未启用时按召回顺序返回",
            ),
            ModelProviderView(
                key="knowledge_index",
                label="知识索引（Qdrant 本地）",
                provider="qdrant-local",
                model=health.knowledge_index.state,
                state=health.knowledge_index.state,
                detail=health.knowledge_index.detail,
                note="向量与元数据分两处存储，隔离环境需同时准备",
            ),
        ],
    )


@router.post("/models/test", response_model=TestModelView)
async def test_model(
    payload: TestModelRequest,
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> TestModelView:
    """对某个模型发一次极小请求，如实返回成功或错误原因。"""

    model = payload.model.strip()
    if not model:
        raise ValidationRejected("请指定要测试的模型")

    # 只允许测试**已配置的模型**或**网关确实提供的模型**：
    # 否则这个接口就成了「任意模型名的代理」，可以拿它试探未授权模型。
    allowed = {context.settings.llm_model, context.settings.llm_vision_model}
    # 拿不到网关列表时仍然允许测已配置的模型；用 suppress 而不是裸 except pass
    with contextlib.suppress(Exception):
        allowed.update(context.model_provider.list_models())
    allowed.discard("")
    if model not in allowed:
        raise ValidationRejected(f"模型 {model} 不在已配置或网关提供的列表中")

    started = time.perf_counter()
    try:
        result = context.model_provider.test_model(model)
    except Exception as exc:
        return TestModelView(
            model=model,
            ok=False,
            latency_seconds=round(time.perf_counter() - started, 3),
            message=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
    return TestModelView(
        model=model,
        ok=True,
        latency_seconds=round(result.latency_seconds or (time.perf_counter() - started), 3),
        message=f"连通（返回 {(result.text or '').strip()[:40] or '空内容'}）",
    )


class TestRerankView(ApiModel):
    model: str
    ok: bool
    latency_seconds: float
    message: str
    #: 实测的排序结果（保持隐私：只用两句固定样例文本，不涉及用户数据）
    ranked: list[str] = Field(default_factory=list)


@router.post("/rerank/test", response_model=TestRerankView)
async def test_rerank(
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> TestRerankView:
    """对当前重排序配置发一次真实请求，如实返回排序结果或失败原因。

    用两句**与查询一强一弱**的固定样例：只回"连通"不能证明它真的在排序，
    因此把两句的先后顺序一起回给页面。
    """

    provider = context.rerank_provider
    if provider is None or not provider.available():
        raise ValidationRejected("尚未配置重排序服务（需要服务地址与模型名）")

    query = "T区容易出油、两颊偏干，底妆容易卡粉，怎么选择资料？"
    documents = [
        "通用分区护理资料：T区出油时避免过度清洁，两颊区域关注舒适度。",
        "商品资料：公开资料明确的轻盈质地说明，可用于比较妆感偏好，不能保证个人适用。",
    ]
    started = time.perf_counter()
    try:
        hits = provider.rerank(query, documents, top_n=len(documents))
    except Exception as exc:
        return TestRerankView(
            model=provider.model_id,
            ok=False,
            latency_seconds=round(time.perf_counter() - started, 3),
            message=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
    ranked = [documents[hit.index] for hit in hits if 0 <= hit.index < len(documents)]
    top_score = hits[0].score if hits else 0.0
    return TestRerankView(
        model=provider.model_id,
        ok=True,
        latency_seconds=round(time.perf_counter() - started, 3),
        message=f"连通（最高相关度 {top_score:.4f}，共 {len(hits)} 条候选）",
        ranked=ranked,
    )


# ── 知识库 / 工单 / Prompt 一览 ────────────────────────────────────────────
# 这三个接口都只读**已有真实数据**：知识库读 knowledge_* 表，工单读会话/案件表，
# Prompt 读代码里当前真正生效的提示词常量。没有数据就不编（空数组 + 说明）。


def _json_list(raw: str | None) -> list[str]:
    """把库里的 JSON 数组列解析成 list[str]（解析失败按空处理）。"""

    import json

    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


class KnowledgeDocumentItem(ApiModel):
    document_id: str
    knowledge_base_id: str = ""
    title: str
    file_name: str
    visibility: str
    version: str
    status: str
    chunk_count: int
    updated_at: str


class KnowledgeOverviewView(ApiModel):
    snapshot_id: str | None = None
    chunk_config_version: str | None = None
    chunk_count: int = 0
    embedding_model: str
    vector_dimension: int
    documents: list[KnowledgeDocumentItem] = Field(default_factory=list)
    note: str = ""


# ── 知识库（按「库」聚合，供左侧库列表 + 右侧文档列表）─────────────────────


class KnowledgeBaseItem(ApiModel):
    knowledge_base_id: str
    name: str
    source_type: str
    enabled: bool
    document_count: int
    chunk_count: int


class KnowledgeOverviewWithBasesView(KnowledgeOverviewView):
    chunk_size: int = 0
    chunk_overlap: int = 0
    knowledge_bases: list[KnowledgeBaseItem] = Field(default_factory=list)


def _knowledge_overview(payload: KnowledgeOverviewView) -> KnowledgeOverviewWithBasesView:
    return KnowledgeOverviewWithBasesView(**payload.model_dump())


class WorkOrderItem(ApiModel):
    #: 工单编号：本期没有独立工单实体，用会话 ID 作为编号（稳定、可追溯）
    work_order_no: str = ""
    conversation_id: str
    case_id: str | None = None
    title: str
    customer_id: str = ""
    #: 分类＝客户意图（没有意图时留空）
    category: str = ""
    #: 优先级：投诉风险或强烈情绪→高；有待确认申请/缺信息→中；其余→低
    priority: str = "低"
    case_status: str | None = None
    service_mode: str | None = None
    emotion_level: str | None = None
    complaint_risk: str | None = None
    pending_request_count: int = 0
    message_count: int = 0
    updated_at: str


class WorkOrderView(ApiModel):
    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
    items: list[WorkOrderItem] = Field(default_factory=list)


class PromptItem(ApiModel):
    code: str
    name: str
    scenario: str
    version: str
    source: str
    content: str
    editable: bool = False
    note: str = ""


class PromptListView(ApiModel):
    items: list[PromptItem] = Field(default_factory=list)
    note: str = ""


@router.get("/knowledge", response_model=KnowledgeOverviewWithBasesView)
async def knowledge_overview(
    session: Any = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> KnowledgeOverviewWithBasesView:
    """知识库总览：当前快照、切片配置、编码模型与逐文档状态。

    数据全部来自真实的 knowledge_* 表：文档的解析/索引状态用表里的
    parse_status / index_status，片段数用文档行上的 chunk_count
    （knowledge_chunk 没有 snapshot 列，按快照再聚合一次是错的）。
    """

    from sqlalchemy import select

    from app.knowledge.models import KnowledgeDocumentRow
    from app.knowledge.repository import KnowledgeRepository

    settings = context.settings
    snapshot = KnowledgeRepository(session).get_active_snapshot()

    rows = (
        session.execute(
            select(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.knowledge_base_id.like("loreal-%"))
            .order_by(KnowledgeDocumentRow.updated_at.desc())
        )
        .scalars()
        .all()
    )

    def state_of(row: Any) -> str:
        if not row.enabled:
            return "已停用"
        if row.parse_status != "succeeded":
            return f"解析：{row.parse_status}"
        if row.index_status != "succeeded":
            return f"未向量化（{row.index_status}）"
        if snapshot is not None and row.index_chunk_config_version != snapshot.chunk_config_version:
            return "切片配置已变更，待重建"
        return "已向量化"

    rows = list({row.document_id: row for row in sorted(rows, key=lambda row: row.document_pk)}.values())
    documents = [
        KnowledgeDocumentItem(
            document_id=row.document_id,
            knowledge_base_id=row.knowledge_base_id,
            title=row.title,
            file_name=row.source_path.rsplit("/", 1)[-1],
            visibility=row.visibility,
            version=row.document_version,
            status=state_of(row),
            chunk_count=int(row.chunk_count or 0),
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
    ]

    from app.knowledge.models import KnowledgeBaseRow

    base_rows = (
        session.execute(
            select(KnowledgeBaseRow).where(KnowledgeBaseRow.knowledge_base_id.like("loreal-%"))
        )
        .scalars()
        .all()
    )
    base_docs: dict[str, int] = {}
    base_chunks: dict[str, int] = {}
    for row in rows:
        base_docs[row.knowledge_base_id] = base_docs.get(row.knowledge_base_id, 0) + 1
        base_chunks[row.knowledge_base_id] = base_chunks.get(row.knowledge_base_id, 0) + int(
            row.chunk_count or 0
        )

    return KnowledgeOverviewWithBasesView(
        snapshot_id=getattr(snapshot, "snapshot_id", None),
        chunk_config_version=getattr(snapshot, "chunk_config_version", None),
        chunk_count=int(getattr(snapshot, "chunk_count", 0) or 0),
        embedding_model=getattr(snapshot, "embedding_model_id", None)
        or settings.embedding_model_id,
        vector_dimension=int(
            getattr(snapshot, "vector_dimension", 0)
            or getattr(context.embedding_provider, "dimension", 0)
            or 0
        ),
        chunk_size=int(getattr(snapshot, "chunk_size", 0) or 0),
        chunk_overlap=int(getattr(snapshot, "chunk_overlap", 0) or 0),
        knowledge_bases=[
            KnowledgeBaseItem(
                knowledge_base_id=row.knowledge_base_id,
                name=row.name,
                source_type=row.source_type,
                enabled=bool(row.enabled),
                document_count=base_docs.get(row.knowledge_base_id, 0),
                chunk_count=base_chunks.get(row.knowledge_base_id, 0),
            )
            for row in base_rows
        ],
        documents=documents,
        note=(
            "" if snapshot is not None else "尚未发布知识快照：请先运行 scripts/ingest_knowledge.py"
        ),
    )


@router.get("/work-orders", response_model=WorkOrderView)
async def work_orders(
    session: Any = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> WorkOrderView:
    """工单管理视图。

    本期没有独立的「工单」实体：一条售后工单就是「会话 + 案件」。这里按
    会话维度聚合真实数据，不新造实体、也不提供不存在的操作（如派单、改单）。
    """

    from sqlalchemy import func, select

    from app.domain.case_state.models import CaseRow, ConversationRow, MessageRow

    conversations = (
        session.execute(
            select(ConversationRow).order_by(ConversationRow.updated_at.desc()).limit(200)
        )
        .scalars()
        .all()
    )
    cases = {row.conversation_id: row for row in session.execute(select(CaseRow)).scalars().all()}
    message_counts = dict(
        session.execute(
            select(MessageRow.conversation_id, func.count()).group_by(MessageRow.conversation_id)
        ).all()
    )

    items: list[WorkOrderItem] = []
    by_status: dict[str, int] = {}
    for row in conversations:
        case = cases.get(row.conversation_id)
        status = case.case_status if case is not None else None
        missing = bool(_json_list(getattr(case, "missing_facts_json", None))) if case else False
        if status:
            by_status[status] = by_status.get(status, 0) + 1
        intents = _json_list(getattr(case, "customer_intents_json", None)) if case else []
        if case is not None and (
            (case.complaint_risk or "unknown") == "flagged"
            or (case.emotion_level or "unknown") in {"angry", "upset"}
        ):
            priority = "高"
        elif case is not None and (missing or (case.rating_status or "") == "pending"):
            priority = "中"
        else:
            priority = "低"
        items.append(
            WorkOrderItem(
                work_order_no=row.conversation_id,
                conversation_id=row.conversation_id,
                customer_id=row.customer_id,
                category="、".join(intents),
                priority=priority,
                case_id=case.case_id if case is not None else None,
                title=row.title or "新会话",
                case_status=status,
                service_mode=row.service_mode,
                emotion_level=case.emotion_level if case is not None else None,
                complaint_risk=case.complaint_risk if case is not None else None,
                pending_request_count=0,
                message_count=int(message_counts.get(row.conversation_id, 0)),
                updated_at=row.updated_at.isoformat(),
            )
        )

    return WorkOrderView(total=len(items), by_status=by_status, items=items)


@router.get("/prompts", response_model=PromptListView)
async def prompt_list(
    _role: ViewRole = Depends(require_support),
) -> PromptListView:
    """当前真正生效的提示词一览（只读）。

    为什么要暴露：模型的行为由提示词决定，改提示词是改行为。本期提示词仍是
    代码常量（版本号随代码走），因此这里**如实展示**内容与版本，并提供复制；
    可编辑/启停需要模板表与版本化，已登记为下一步（DEV-027），不做只能点不能用的假按钮。
    """

    from app.domain.agent import suggestions as suggestion_module
    from app.domain.agent import understanding as understanding_module

    return PromptListView(
        items=[
            PromptItem(
                code="UNDERSTANDING",
                name="售后理解（结构化事实）",
                scenario="每一条客户消息进入 Agent 时调用",
                version=understanding_module.PROMPT_VERSION,
                source="app/domain/agent/understanding.py",
                content=understanding_module.SYSTEM_PROMPT,
                note="输出的枚举会被严格校验，非法取值按 unknown 处理",
            ),
            PromptItem(
                code="REPLY_SUGGEST",
                name="客服回复起草（三版措辞）",
                scenario="客服点「AI 生成回复候选」时调用",
                version=suggestion_module.SUGGESTION_PROMPT_VERSION,
                source="app/domain/agent/suggestions.py",
                content=suggestion_module.SYSTEM_PROMPT,
                note="三版只改措辞，事实与策略一致；采用只写草稿",
            ),
        ],
        note="提示词目前是代码常量：改内容即改行为，需要走代码评审与回归。可编辑/启停（模板表 + 版本化）为下一步。",
    )


class SwitchModelRequest(ApiModel):
    model: str


class SwitchModelView(ApiModel):
    model: str
    persisted: bool
    message: str


@router.post("/models/active", response_model=SwitchModelView)
async def switch_active_model(
    payload: SwitchModelRequest,
    session: Any = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> SwitchModelView:
    """把生效的文本模型切换成另一个，并**持久化**（重启后仍生效）。

    只允许切到「网关确实提供」的模型：否则会把整个 Demo 切到一个不存在的模型上，
    之后所有对话都失败——那比不让切更糟。
    """

    from app.domain.platform.settings import ACTIVE_MODEL_KEY, set_setting

    model = payload.model.strip()
    if not model:
        raise ValidationRejected("请指定要切换的模型")

    # 允许切换的范围 = 网关列表 ∪ 当前已配置的模型。
    # 为什么必须带上已配置的：实测网关 deepseek-chat 能正常调用，但 /v1/models
    # 只返回 deepseek-flash/deepseek-v4-pro —— 只认列表会导致「切走了就切不回来」。
    available = context.model_provider.list_models()
    allowed = {context.settings.llm_model, context.settings.llm_vision_model, *available}
    allowed.discard("")
    if not allowed:
        raise ValidationRejected("拿不到任何可用模型（网关列表为空且未配置模型），已拒绝切换")
    if model not in allowed:
        raise ValidationRejected(
            f"模型 {model} 既不在网关列表中，也不是当前已配置的模型：{', '.join(sorted(allowed))}"
        )

    setter = getattr(context.model_provider, "set_active_model", None)
    if setter is None:
        raise ValidationRejected("当前模型提供者不支持切换生效模型")

    setter(model)
    set_setting(session, ACTIVE_MODEL_KEY, model)
    return SwitchModelView(
        model=model,
        persisted=True,
        message=f"已切换到 {model}；重启后端后仍生效（会话内后续请求立即使用新模型）",
    )


# ── 提示词模板（可写） ────────────────────────────────────────────────────


class PromptTemplateView(ApiModel):
    template_id: str
    code: str
    name: str
    scenario: str
    content: str
    status: str
    revision: int
    is_builtin: bool
    updated_by: str
    updated_at: str
    bound_purposes: list[str] = Field(default_factory=list)


class CreatePromptRequest(ApiModel):
    code: str
    name: str
    scenario: str = ""
    content: str


class UpdatePromptRequest(ApiModel):
    name: str | None = None
    scenario: str | None = None
    content: str | None = None
    expected_revision: int | None = None


class PromptStatusRequest(ApiModel):
    status: str


def _template_view(row: Any, session: Any = None) -> PromptTemplateView:
    from app.domain.platform.settings import get_enabled_template

    return PromptTemplateView(
        template_id=row.template_id,
        code=row.code,
        name=row.name,
        scenario=row.scenario,
        content=row.content,
        status=row.status,
        revision=row.revision,
        is_builtin=row.is_builtin,
        updated_by=row.updated_by,
        updated_at=row.updated_at.isoformat(),
        bound_purposes=[
            purpose for purpose in ("LOREAL_AUTO_REPLY", "LOREAL_ASSISTANT", "LOREAL_SAFETY")
            if session is not None
            and (selected := get_enabled_template(session, purpose)) is not None
            and selected.template_id == row.template_id
        ],
    )


@router.get("/prompt-templates", response_model=list[PromptTemplateView])
async def list_prompt_templates(
    session: Any = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[PromptTemplateView]:
    """提示词模板列表（含内置模板，已从代码常量播种）。"""

    from app.domain.platform.settings import ensure_builtin_templates, list_templates

    # 惰性播种：内置模板来自代码常量，任何环境第一次读列表时都会补齐，
    # 这样不依赖「启动时先跑过 ensure_schema」（测试与隔离库同样成立）。
    ensure_builtin_templates(session)
    return [
        _template_view(row, session)
        for row in list_templates(session)
        if row.code not in {"UNDERSTANDING", "REPLY", "REPLY_SUGGEST"}
    ]


@router.post("/prompt-templates", response_model=PromptTemplateView)
async def create_prompt_template(
    payload: CreatePromptRequest,
    session: Any = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> PromptTemplateView:
    """新增模板。`code` 唯一：同一个用途只允许一条，避免「到底用哪条」说不清。"""

    from app.domain.platform.models import PromptTemplateRow
    from app.domain.platform.settings import (
        ensure_builtin_templates,
        get_enabled_template,
        list_templates,
    )

    # 先补齐内置模板再查重：否则内置 code 会被当成「不重复」而建出第二条
    ensure_builtin_templates(session)
    code = payload.code.strip().upper()
    import re
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
        raise ValidationRejected("编码只允许大写字母、数字和下划线")
    if not code or not payload.name.strip() or not payload.content.strip():
        raise ValidationRejected("编码、名称与内容都不能为空")
    if any(row.code == code for row in list_templates(session)):
        raise ValidationRejected(f"编码 {code} 已存在")

    row = PromptTemplateRow(
        code=code,
        name=payload.name.strip(),
        scenario=payload.scenario.strip(),
        content=payload.content,
        # 新模板默认**停用**：改模型行为必须是一次显式动作，不能建完就生效。
        status="disabled",
        revision=1,
        is_builtin=False,
    )
    session.add(row)
    session.flush()
    if get_enabled_template(session, code) is not None:  # pragma: no cover - 逻辑上不可能
        raise ValidationRejected(f"编码 {code} 已有启用中的模板")
    return _template_view(row)


@router.put("/prompt-templates/{template_id}", response_model=PromptTemplateView)
async def update_prompt_template(
    template_id: str,
    payload: UpdatePromptRequest,
    session: Any = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> PromptTemplateView:
    """编辑模板内容：每次改动 `revision` 自增，便于追溯「当时用的是哪一版」。"""

    from app.domain.platform.settings import get_template

    row = get_template(session, template_id)
    if row is None:
        raise NotFoundError(f"模板不存在：{template_id}")

    from app.errors import ConflictError
    if payload.expected_revision is not None and payload.expected_revision != row.revision:
        raise ConflictError("模板已被更新，请刷新")
    _save_prompt_revision(session, row)
    changed = False
    if payload.name is not None and payload.name.strip() and payload.name != row.name:
        row.name = payload.name.strip()
        changed = True
    if payload.scenario is not None and payload.scenario != row.scenario:
        row.scenario = payload.scenario.strip()
        changed = True
    if payload.content is not None and payload.content != row.content:
        if not payload.content.strip():
            raise ValidationRejected("内容不能为空")
        row.content = payload.content
        changed = True
    if changed:
        row.revision += 1
        row.updated_by = "demo"
        session.flush()
    return _template_view(row, session)


@router.post("/prompt-templates/{template_id}/status", response_model=PromptTemplateView)
async def set_prompt_status(
    template_id: str,
    payload: PromptStatusRequest,
    session: Any = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> PromptTemplateView:
    """启用 / 停用模板。停用后 Agent 回退到**代码常量**（不是空提示词）。"""

    from app.domain.platform.settings import get_template

    if payload.status not in {"enabled", "disabled"}:
        raise ValidationRejected("状态只能是 enabled 或 disabled")
    row = get_template(session, template_id)
    if row is None:
        raise NotFoundError(f"模板不存在：{template_id}")
    row.status = payload.status
    row.updated_by = "demo"
    session.flush()
    return _template_view(row, session)


class PromptBindingRequest(ApiModel):
    purpose: str


class PromptRevisionView(ApiModel):
    revision: int
    content: str
    name: str
    scenario: str
    created_at: str


class PromptRestoreRequest(ApiModel):
    revision: int
    expected_revision: int


def _save_prompt_revision(session: Any, row: Any) -> None:
    from app.domain.platform.models import PromptRevisionRow

    key = f"{row.template_id}:{row.revision}"
    if session.get(PromptRevisionRow, key) is None:
        session.add(PromptRevisionRow(
            revision_id=key, template_id=row.template_id, revision=row.revision,
            content=row.content, name=row.name, scenario=row.scenario,
        ))
        session.flush()


@router.post("/prompt-templates/{template_id}/binding", response_model=PromptTemplateView)
def bind_prompt(
    template_id: str, payload: PromptBindingRequest,
    session: Any = Depends(get_session), _role: ViewRole = Depends(require_support),
):
    from app.domain.consumer_service.tickets import record_event
    from app.domain.platform.settings import get_template, set_setting

    if payload.purpose not in {"LOREAL_AUTO_REPLY", "LOREAL_ASSISTANT", "LOREAL_SAFETY"}:
        raise ValidationRejected("未知用途")
    row = get_template(session, template_id)
    if row is None or row.code in {"UNDERSTANDING", "REPLY", "REPLY_SUGGEST"}:
        raise NotFoundError("模板不存在")
    row.status = "enabled"
    set_setting(session, f"prompt.binding.{payload.purpose}", template_id)
    record_event(session, template_id, "prompt", "绑定用途", payload.purpose)
    return _template_view(row, session)


@router.get("/prompt-templates/{template_id}/revisions", response_model=list[PromptRevisionView])
def prompt_revisions(
    template_id: str, session: Any = Depends(get_session), _role: ViewRole = Depends(require_support),
):
    from sqlalchemy import select

    from app.domain.platform.models import PromptRevisionRow
    from app.domain.platform.settings import get_template

    row = get_template(session, template_id)
    if row is None:
        raise NotFoundError("模板不存在")
    _save_prompt_revision(session, row)
    return [PromptRevisionView(
        revision=r.revision, name=r.name, scenario=r.scenario,
        content=r.content, created_at=r.created_at.isoformat(),
    ) for r in session.scalars(select(PromptRevisionRow).where(
        PromptRevisionRow.template_id == template_id,
    ).order_by(PromptRevisionRow.revision.desc()))]


@router.post("/prompt-templates/{template_id}/restore", response_model=PromptTemplateView)
def restore_prompt(
    template_id: str, payload: PromptRestoreRequest,
    session: Any = Depends(get_session), _role: ViewRole = Depends(require_support),
):
    from app.domain.platform.models import PromptRevisionRow
    from app.domain.platform.settings import get_template
    from app.errors import ConflictError

    row = get_template(session, template_id)
    revision = session.get(PromptRevisionRow, f"{template_id}:{payload.revision}")
    if row is None or revision is None:
        raise NotFoundError("版本不存在")
    if row.revision != payload.expected_revision:
        raise ConflictError("模板已更新，请刷新")
    _save_prompt_revision(session, row)
    row.content, row.name, row.scenario = revision.content, revision.name, revision.scenario
    row.revision += 1
    session.flush()
    return _template_view(row, session)


class SaveModelConfigRequest(ApiModel):
    base_url: str | None = None
    #: 留空表示「不改」；传 "-" 表示清空
    api_key: str | None = None
    model: str | None = None
    vision_model: str | None = None
    #: 向量模型：本地 ONNX 或远端 OpenAI 兼容服务
    embedding_backend: str | None = None
    embedding_model: str | None = None
    embedding_path: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_dimension: int | None = None
    #: 重排序（可选精排）
    rerank_backend: str | None = None
    rerank_base_url: str | None = None
    rerank_api_key: str | None = None
    rerank_model: str | None = None


class SaveModelConfigView(ApiModel):
    ok: bool
    message: str
    config: ModelConfigView


@router.put("/models/config", response_model=SaveModelConfigView)
async def save_model_config(
    payload: SaveModelConfigRequest,
    session: Any = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> SaveModelConfigView:
    """保存模型配置（地址 / 密钥 / 文本模型 / 多模态模型）。

    三条约定：
    1. **密钥只进不出**：保存后返回的是掩码，页面永远拿不到原文；
    2. 立即生效并持久化到 `runtime_setting`（重启由启动流程套用）；
    3. 保存后**立刻做一次连通性测试**，把真实结果放在 `message` 里——
       否则用户以为配好了，实际下一句对话就失败。
    """

    from app.domain.platform.settings import (
        API_KEY_KEY,
        BASE_URL_KEY,
        EMBEDDING_API_KEY_KEY,
        EMBEDDING_BACKEND_KEY,
        EMBEDDING_BASE_URL_KEY,
        EMBEDDING_DIMENSION_KEY,
        EMBEDDING_MODEL_KEY,
        EMBEDDING_PATH_KEY,
        MODEL_KEY,
        RERANK_API_KEY_KEY,
        RERANK_BACKEND_KEY,
        RERANK_BASE_URL_KEY,
        RERANK_MODEL_KEY,
        VISION_MODEL_KEY,
        set_setting,
    )

    if payload.base_url is not None and payload.base_url.strip():
        set_setting(session, BASE_URL_KEY, payload.base_url.strip())
    if payload.api_key is not None:
        # 空字符串=不改；"-"=清空
        if payload.api_key == "-":
            set_setting(session, API_KEY_KEY, "")
        elif payload.api_key.strip():
            set_setting(session, API_KEY_KEY, payload.api_key.strip())
    if payload.model is not None and payload.model.strip():
        set_setting(session, MODEL_KEY, payload.model.strip())
        set_setting(session, "llm.active_model", payload.model.strip())
    if payload.vision_model is not None:
        set_setting(session, VISION_MODEL_KEY, payload.vision_model.strip())
    if payload.embedding_backend is not None and payload.embedding_backend.strip():
        backend = payload.embedding_backend.strip()
        if backend not in {"onnx-local", "http"}:
            raise ValidationRejected(f"未知的向量后端：{backend}（可选 onnx-local / http）")
        set_setting(session, EMBEDDING_BACKEND_KEY, backend)
    if payload.embedding_model is not None and payload.embedding_model.strip():
        set_setting(session, EMBEDDING_MODEL_KEY, payload.embedding_model.strip())
    if payload.embedding_path is not None:
        set_setting(session, EMBEDDING_PATH_KEY, payload.embedding_path.strip())
    if payload.embedding_base_url is not None:
        set_setting(session, EMBEDDING_BASE_URL_KEY, payload.embedding_base_url.strip())
    if payload.embedding_api_key is not None:
        if payload.embedding_api_key == "-":
            set_setting(session, EMBEDDING_API_KEY_KEY, "")
        elif payload.embedding_api_key.strip():
            set_setting(session, EMBEDDING_API_KEY_KEY, payload.embedding_api_key.strip())
    if payload.embedding_dimension is not None:
        set_setting(session, EMBEDDING_DIMENSION_KEY, str(payload.embedding_dimension))
    if payload.rerank_backend is not None and payload.rerank_backend.strip():
        rerank_backend = payload.rerank_backend.strip()
        if rerank_backend not in {"none", "http"}:
            raise ValidationRejected(f"未知的重排序后端：{rerank_backend}（可选 none / http）")
        set_setting(session, RERANK_BACKEND_KEY, rerank_backend)
    if payload.rerank_base_url is not None:
        set_setting(session, RERANK_BASE_URL_KEY, payload.rerank_base_url.strip())
    if payload.rerank_api_key is not None:
        if payload.rerank_api_key == "-":
            set_setting(session, RERANK_API_KEY_KEY, "")
        elif payload.rerank_api_key.strip():
            set_setting(session, RERANK_API_KEY_KEY, payload.rerank_api_key.strip())
    if payload.rerank_model is not None:
        set_setting(session, RERANK_MODEL_KEY, payload.rerank_model.strip())

    configure = getattr(context.model_provider, "configure", None)
    if configure is None:
        raise ValidationRejected("当前模型提供者不支持运行时配置")
    configure(
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        vision_model=payload.vision_model,
    )

    # 重排序是纯 HTTP 调用，可以热替换：保存后立刻让运行时用新配置
    from app.integrations.rerank_provider import build_rerank_provider
    from app.runtime import _apply_saved_rerank_settings

    _apply_saved_rerank_settings(context.settings, context.session_factory)
    try:
        context.rerank_provider = build_rerank_provider(context.settings)
    except Exception as exc:
        context.rerank_provider = None
        raise ValidationRejected(f"重排序配置无法生效：{type(exc).__name__}: {exc}") from exc

    # 保存后立即实测：成功与失败都如实回给页面
    restart_hint = ""
    if (
        payload.embedding_model is not None
        or payload.embedding_path is not None
        or payload.embedding_backend is not None
        or payload.embedding_base_url is not None
        or payload.embedding_api_key is not None
        or payload.embedding_dimension is not None
    ):
        restart_hint = "；向量模型改动需重启后端生效（编码后端在启动时构建，且索引与维度绑定）"
    message = "已保存（未做测试）" + restart_hint
    ok = True
    try:
        result = context.model_provider.test_model(context.model_provider.model_id)
        message = (
            f"已保存并测试通过：{context.model_provider.model_id} "
            f"返回 {(result.text or '').strip()[:40]}{restart_hint}"
        )
    except Exception as exc:
        ok = False
        message = f"已保存，但测试失败：{type(exc).__name__}: {str(exc)[:160]}{restart_hint}"

    if context.rerank_provider is not None:
        message = f"{message}；重排序已启用：{context.rerank_provider.model_id}"
    elif payload.rerank_backend == "none":
        message = f"{message}；重排序未启用"

    refreshed = await model_config(session=session, context=context, _role=ViewRole.SUPPORT)
    return SaveModelConfigView(ok=ok, message=message, config=refreshed)


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseItem])
async def knowledge_bases(
    session: Any = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[KnowledgeBaseItem]:
    """知识库列表：每个库的文档数与片段数（真实聚合，供左侧列表）。"""

    from sqlalchemy import func, select

    from app.knowledge.models import KnowledgeBaseRow, KnowledgeDocumentRow

    counts = dict(
        session.execute(
            select(
                KnowledgeDocumentRow.knowledge_base_id,
                func.count(),
            ).group_by(KnowledgeDocumentRow.knowledge_base_id)
        ).all()
    )
    chunks = dict(
        session.execute(
            select(
                KnowledgeDocumentRow.knowledge_base_id,
                func.sum(KnowledgeDocumentRow.chunk_count),
            ).group_by(KnowledgeDocumentRow.knowledge_base_id)
        ).all()
    )
    rows = session.execute(select(KnowledgeBaseRow)).scalars().all()
    return [
        KnowledgeBaseItem(
            knowledge_base_id=row.knowledge_base_id,
            name=row.name,
            source_type=row.source_type,
            enabled=bool(row.enabled),
            document_count=int(counts.get(row.knowledge_base_id, 0)),
            chunk_count=int(chunks.get(row.knowledge_base_id, 0) or 0),
        )
        for row in rows
    ]
