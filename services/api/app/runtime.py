"""应用运行时上下文：把配置、存储和外部适配器组装成可注入的对象。

生命周期由 FastAPI lifespan 管理：
- 启动时创建运行目录、数据库引擎并校验外部能力；
- 关闭时显式释放 Qdrant 本地客户端。

为什么必须显式 close：QdrantClient(local) 若依赖 `__del__` 收尾，CPython 解释器关闭
阶段 portalocker 会尝试 `import msvcrt` 而失败，打印堆栈并让进程以非 0 退出。
在 Windows + Python 3.11 上已实测确认（见 code/scripts/_probe_qdrant_close.py）。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.integrations.embedding_provider import (
    EmbeddingProvider,
    build_embedding_provider,
)
from app.integrations.model_provider import (
    ModelProvider,
    OpenAICompatibleModelProvider,
)
from app.logging_setup import get_logger, log_event
from app.schemas.health import CapabilityStatus, HealthResponse

logger = get_logger(__name__)

APP_VERSION = "0.1.0"


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


@dataclass
class RuntimeContext:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    model_provider: ModelProvider
    embedding_provider: EmbeddingProvider
    tool_registry: Any = None
    #: 可选精排：未配置时为 None，检索链路按"没有重排序"处理
    rerank_provider: Any = None
    startup_notes: list[str] = field(default_factory=list)

    def new_session(self) -> Session:
        return self.session_factory()

    def build_gateway(self, session: Session) -> Any:
        """为一次请求构建 ToolGateway。

        Gateway 持有幂等缓存与调用轨迹，因此**按请求创建**，
        不跨请求复用（否则幂等键会在无关请求之间串用）。
        """

        from app.tool_gateway.gateway import ToolGateway

        return ToolGateway(
            self.tool_registry,
            session=session,
            settings=self.settings,
            embedding_provider=self.embedding_provider,
            rerank_provider=self.rerank_provider,
        )

    def build_orchestrator(self, session: Session) -> Any:
        from app.domain.agent.orchestrator import CaseOrchestrator, OrchestratorDeps
        from app.domain.agent.understanding import UnderstandingAnalyzer

        def resolve_understanding_prompt() -> str | None:
            """取当前启用中的「售后理解」提示词模板（没有则返回 None，回退代码常量）。

            取模板失败（如表缺失、库不可用）时记警告并回退：提示词是**可选项**，
            不该因为它读不到就把整条对话链路打断。
            """

            from app.domain.platform.settings import UNDERSTANDING_CODE, get_enabled_template

            try:
                row = get_enabled_template(session, UNDERSTANDING_CODE)
            except Exception as exc:
                log_event(
                    logger,
                    "understanding_prompt_fallback",
                    reason=type(exc).__name__,
                )
                return None
            return row.content if row is not None else None

        def resolve_reply_prompt() -> str | None:
            """取启用中的 REPLY 提示词模板（Prompt 管理可编辑）；没有则用代码常量。"""

            from app.domain.platform.settings import REPLY_CODE, get_enabled_template

            try:
                row = get_enabled_template(session, REPLY_CODE)
            except Exception as exc:
                log_event(logger, "reply_prompt_fallback", reason=type(exc).__name__)
                return None
            return row.content if row is not None else None

        return CaseOrchestrator(
            OrchestratorDeps(
                session=session,
                settings=self.settings,
                embedding_provider=self.embedding_provider,
                gateway=self.build_gateway(session),
                analyzer=UnderstandingAnalyzer(self.model_provider, resolve_understanding_prompt),
                # 回复生成用同一个模型提供者；Prompt 管理里的 REPLY 模板可覆盖提示词
                reply_model=self.model_provider,
                reply_prompt_resolver=resolve_reply_prompt,
            )
        )

    def apply_runtime_settings(self) -> None:
        """启动时套用页面保存的模型配置（地址 / 密钥 / 文本模型 / 多模态模型）。

        为什么放在启动而不是每次请求：这是低频运维动作，启动读一次即可；
        每次请求都查库会给所有模型调用加一次数据库往返。
        页面写过的键覆盖 `.env`，没写过的保持 `.env` 的值。
        """

        from app.domain.platform.settings import (
            ACTIVE_MODEL_KEY,
            API_KEY_KEY,
            BASE_URL_KEY,
            MODEL_KEY,
            VISION_MODEL_KEY,
            get_setting,
        )

        session = self.new_session()
        try:
            saved = {
                key: get_setting(session, key)
                for key in (
                    BASE_URL_KEY,
                    API_KEY_KEY,
                    MODEL_KEY,
                    VISION_MODEL_KEY,
                    ACTIVE_MODEL_KEY,
                )
            }
        finally:
            session.close()

        model = saved[ACTIVE_MODEL_KEY] or saved[MODEL_KEY]
        configure = getattr(self.model_provider, "configure", None)
        if configure is not None:
            configure(
                base_url=saved[BASE_URL_KEY],
                api_key=saved[API_KEY_KEY],
                model=model,
                vision_model=saved[VISION_MODEL_KEY],
            )
            applied = [key for key, value in saved.items() if value]
            if applied:
                self.startup_notes.append(f"已套用页面保存的模型配置：{', '.join(applied)}")
            return

        # 兜底：只支持切换模型名的提供者（测试桩等）
        if not model:
            return
        setter = getattr(self.model_provider, "set_active_model", None)
        if setter is None:
            self.startup_notes.append(f"已保存的生效模型 {model} 无法套用：提供者不支持配置")
            return
        setter(model)
        self.startup_notes.append(f"已套用保存的生效模型：{model}")

    def ensure_schema(self) -> None:
        """建表。会话/案件表与知识表分属两个 Base，都要创建。"""

        from app.domain.case_state.models import Base as CaseBase
        from app.domain.consumer_service import models as _consumer_service_models  # noqa: F401
        from app.domain.consumer_service.models import migrate_risk_alert_table
        from app.knowledge.models import Base as KnowledgeBase

        migrate_risk_alert_table(self.engine)
        CaseBase.metadata.create_all(self.engine)
        KnowledgeBase.metadata.create_all(self.engine)

        # 平台表（运行设置 / 提示词模板）挂在 CaseBase 上，随上面一起建；
        # 建完表再播种内置提示词，最后套用保存的运行设置。
        from app.domain.platform.settings import ensure_builtin_templates
        from app.knowledge.reference_products import seed_reference_products

        session = self.new_session()
        try:
            ensure_builtin_templates(session)
            seed_reference_products(session)
            session.commit()
        finally:
            session.close()
        self.apply_runtime_settings()

    def capabilities(self) -> HealthResponse:
        return HealthResponse(
            status="ok" if self._all_ready() else "degraded",
            run_mode=self.settings.run_mode,
            contract_version=self.settings.contract_version,
            app_version=APP_VERSION,
            database=self._database_status(),
            llm=self._llm_status(),
            vision=self._vision_status(),
            embedding=self._embedding_status(),
            knowledge_index=self._knowledge_index_status(),
            rerank=self._rerank_status(),
        )

    def _rerank_status(self) -> CapabilityStatus:
        """精排状态：未配置就如实说未启用，绝不写成"已重排序"。"""

        provider = self.rerank_provider
        if provider is None or not provider.available():
            return CapabilityStatus(
                name="rerank",
                state="unavailable",
                detail="未配置重排序服务（检索按召回顺序返回，不做精排）",
            )
        return CapabilityStatus(
            name="rerank",
            state="ready",
            detail=f"后端={provider.describe().get('backend')} 模型={provider.model_id}",
            model_id=provider.model_id,
        )

    def _all_ready(self) -> bool:
        required = [
            self._database_status(),
            self._llm_status(),
            self._embedding_status(),
        ]
        return all(item.state == "ready" for item in required)

    def _database_status(self) -> CapabilityStatus:
        try:
            from sqlalchemy import text

            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return CapabilityStatus(
                name="database",
                state="ready",
                detail=f"SQLite 可读写：{self.settings.sqlalchemy_url().rsplit('/', 1)[-1]}",
            )
        except Exception as exc:
            return CapabilityStatus(
                name="database",
                state="unavailable",
                detail=f"{type(exc).__name__}: {str(exc)[:160]}",
            )

    def _llm_status(self) -> CapabilityStatus:
        provider = self.model_provider
        if not provider.available():
            return CapabilityStatus(
                name="llm",
                state="unavailable",
                detail="未配置文本模型（base_url / api_key / model 之一缺失）",
            )
        return CapabilityStatus(
            name="llm",
            state="ready",
            detail="已配置 OpenAI 兼容文本模型；连通性由 /api/health/probe 实测",
            model_id=provider.model_id,
            revision="unavailable",
        )

    def _vision_status(self) -> CapabilityStatus:
        provider = self.model_provider
        if not provider.available():
            return CapabilityStatus(
                name="vision",
                state="unavailable",
                detail="文本模型未配置，多模态链路不可用",
            )
        if not provider.supports_vision:
            return CapabilityStatus(
                name="vision",
                state="unavailable",
                detail="未配置多模态模型；图片线索提取将如实报告无法确认，不猜测",
            )
        return CapabilityStatus(
            name="vision",
            state="ready",
            detail="已配置多模态模型",
            model_id=self.settings.llm_vision_model,
            revision="unavailable",
        )

    def _embedding_status(self) -> CapabilityStatus:
        provider = self.embedding_provider
        try:
            available = provider.available()
        except Exception as exc:
            return CapabilityStatus(
                name="embedding",
                state="unavailable",
                detail=f"{type(exc).__name__}: {str(exc)[:160]}",
            )
        described = provider.describe()
        if not available:
            return CapabilityStatus(
                name="embedding",
                state="unavailable",
                detail=f"本地编码模型未就绪：{described.get('model_path', '')}",
                model_id=provider.model_id,
                revision="unavailable",
            )
        return CapabilityStatus(
            name="embedding",
            state="ready",
            detail=f"后端={described.get('backend')} 维度={described.get('dimension', '待加载')}",
            model_id=provider.model_id,
            revision=described.get("model_revision", "unavailable"),
        )

    def _knowledge_index_status(self) -> CapabilityStatus:
        path = self.settings.qdrant_path_resolved
        if path.exists():
            return CapabilityStatus(
                name="knowledge_index",
                state="ready",
                detail=f"本地索引目录存在：{path}",
                model_id=self.settings.embedding_model_id,
            )
        return CapabilityStatus(
            name="knowledge_index",
            state="unavailable",
            detail="尚未建立知识索引（S1 导入后生成）",
            model_id=self.settings.embedding_model_id,
        )

    def close(self) -> None:
        self.engine.dispose()


def _apply_saved_embedding_settings(settings: Settings, factory: sessionmaker[Session]) -> None:
    """把页面保存的向量模型配置合并进 Settings（缺失或读不到就保持 .env 的值）。

    支持两种后端：本地 ONNX（自带稀疏通道）与远端 OpenAI 兼容服务
    （**只有稠密向量**，切换后混合检索会退化为单路稠密，必须如实记录）。
    """

    from app.domain.platform.settings import (
        EMBEDDING_API_KEY_KEY,
        EMBEDDING_BACKEND_KEY,
        EMBEDDING_BASE_URL_KEY,
        EMBEDDING_DIMENSION_KEY,
        EMBEDDING_MODEL_KEY,
        EMBEDDING_PATH_KEY,
        get_setting,
    )

    session = factory()
    try:
        saved = {
            "backend": get_setting(session, EMBEDDING_BACKEND_KEY),
            "model_id": get_setting(session, EMBEDDING_MODEL_KEY),
            "model_path": get_setting(session, EMBEDDING_PATH_KEY),
            "base_url": get_setting(session, EMBEDDING_BASE_URL_KEY),
            "api_key": get_setting(session, EMBEDDING_API_KEY_KEY),
            "dimension": get_setting(session, EMBEDDING_DIMENSION_KEY),
        }
    except Exception:
        return
    finally:
        session.close()

    if saved["backend"] in {"onnx-local", "http", "mock"}:
        settings.embedding_backend = saved["backend"]  # type: ignore[assignment]
    if saved["model_id"]:
        settings.embedding_model_id = saved["model_id"]
    if saved["model_path"] is not None:
        settings.embedding_model_path = saved["model_path"]
    if saved["base_url"] is not None:
        settings.embedding_http_base_url = saved["base_url"]
    if saved["api_key"]:
        settings.embedding_http_api_key = saved["api_key"]
    if saved["dimension"]:
        with contextlib.suppress(ValueError):
            settings.embedding_dimension = int(saved["dimension"])


def _apply_saved_rerank_settings(settings: Settings, factory: sessionmaker[Session]) -> None:
    """把页面保存的重排序配置合并进 Settings（未保存过就保持 .env 的值）。"""

    from app.domain.platform.settings import (
        RERANK_API_KEY_KEY,
        RERANK_BACKEND_KEY,
        RERANK_BASE_URL_KEY,
        RERANK_MODEL_KEY,
        get_setting,
    )

    session = factory()
    try:
        saved = {
            "backend": get_setting(session, RERANK_BACKEND_KEY),
            "base_url": get_setting(session, RERANK_BASE_URL_KEY),
            "api_key": get_setting(session, RERANK_API_KEY_KEY),
            "model": get_setting(session, RERANK_MODEL_KEY),
        }
    except Exception:
        return
    finally:
        session.close()

    if saved["backend"] in {"none", "http", "mock"}:
        settings.rerank_backend = saved["backend"]  # type: ignore[assignment]
    if saved["base_url"] is not None:
        settings.rerank_base_url = saved["base_url"]
    if saved["api_key"]:
        settings.rerank_api_key = saved["api_key"]
    if saved["model"]:
        settings.rerank_model = saved["model"]


def build_runtime(settings: Settings | None = None) -> RuntimeContext:
    resolved = settings or get_settings()
    resolved.runtime_path.mkdir(parents=True, exist_ok=True)
    engine = build_engine(resolved)
    factory = build_session_factory(engine)

    # 页面保存的「向量模型」覆盖：必须在构建 embedding provider **之前**套用，
    # 否则改了下一次启动还是旧模型（本地 ONNX 会话无法在请求中热替换）。
    _apply_saved_embedding_settings(resolved, factory)
    # 重排序是纯 HTTP 调用，改完立即生效；这里套用页面保存的值
    _apply_saved_rerank_settings(resolved, factory)

    model_provider: Any = OpenAICompatibleModelProvider.from_settings(resolved)
    from app.tools.registry import build_default_registry

    notes: list[str] = []
    try:
        embedding_provider = build_embedding_provider(resolved)
    except Exception as exc:
        # 编码后端配置错误不应让进程无法启动：健康检查如实报告，S1 相关验收保留未通过。
        from app.integrations.embedding_provider import MockEmbeddingProvider

        notes.append(f"编码后端构建失败：{type(exc).__name__}: {exc}")
        embedding_provider = MockEmbeddingProvider(
            reason="编码后端构建失败时的占位，健康检查会报告 unavailable"
        )

    from app.integrations.rerank_provider import build_rerank_provider

    try:
        rerank_provider = build_rerank_provider(resolved)
    except Exception as exc:
        notes.append(f"重排序后端构建失败：{type(exc).__name__}: {exc}")
        rerank_provider = None
    if rerank_provider is not None:
        notes.append(f"已启用重排序：{rerank_provider.model_id}")

    context = RuntimeContext(
        settings=resolved,
        engine=engine,
        session_factory=factory,
        model_provider=model_provider,
        embedding_provider=embedding_provider,
        tool_registry=build_default_registry(),
        rerank_provider=rerank_provider,
        startup_notes=notes,
    )
    try:
        context.ensure_schema()
    except Exception as exc:
        # 建表失败不应让进程无法启动：健康检查会如实报告数据库状态
        notes.append(f"建表失败：{type(exc).__name__}: {exc}")
    log_event(logger, "runtime_ready", run_mode=resolved.run_mode, version=APP_VERSION)
    return context
