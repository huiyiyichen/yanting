"""FastAPI 入口。

路由分组：
- `/api/health`：无鉴权的运行状态，如实报告外部能力；
- `/api/customer/*`：客户侧，只有会话与普通消息，不返回内部判断与依据；
- `/api/support/*`：客服侧，案件/AI 辅助/知识依据/审批。

两组在**接口层**分别校验角色与会话范围，不能只靠前端隐藏按钮
（工程规范第 13.3 节，对应 AC-24 与 AC-30）。
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AnkerAgentError
from app.logging_setup import configure_logging, get_logger
from app.routes import (
    contracts,
    customer,
    health,
    knowledge_management,
    platform,
    reception,
    service_desk,
    support,
)
from app.runtime import APP_VERSION, RuntimeContext, build_runtime

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    context = build_runtime()
    app.state.runtime = context
    for note in context.startup_notes:
        logger.warning(note)
    from app.domain.consumer_service.auto_reception import run_reply_worker
    from app.domain.consumer_service.risk_rules import run_risk_monitor

    reply_worker = asyncio.create_task(run_reply_worker(context))
    risk_monitor = asyncio.create_task(run_risk_monitor(context))
    try:
        yield
    finally:
        reply_worker.cancel()
        risk_monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reply_worker
        with contextlib.suppress(asyncio.CancelledError):
            await risk_monitor
        # Cancelled to_thread tasks can still be using the database or provider.
        await asyncio.get_running_loop().shutdown_default_executor()
        context.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="颜听消费者服务 Agent API",
        version=APP_VERSION,
        description=(
            "颜听：面向美妆电商客服的智能接待辅助与风险预警平台。"
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AnkerAgentError)
    async def _handle_domain_error(_request: Request, exc: AnkerAgentError) -> JSONResponse:
        status_by_code = {
            "provider_not_configured": 503,
            "provider_timeout": 504,
            "provider_request_failed": 502,
            "tool_access_denied": 403,
            "risk_boundary_violation": 403,
            "conflict": 409,
            "not_found": 404,
            "validation_rejected": 422,
        }
        return JSONResponse(
            status_code=status_by_code.get(exc.code, 400),
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.detail,
                }
            },
        )

    app.include_router(health.router)
    app.include_router(contracts.router)
    app.include_router(customer.router)
    app.include_router(support.router)
    app.include_router(platform.router)
    app.include_router(reception.router)
    app.include_router(service_desk.router)
    app.include_router(knowledge_management.router)

    @app.get("/", include_in_schema=False)
    async def _root() -> dict[str, Any]:
        context: RuntimeContext = app.state.runtime
        return {
            "name": "loreal-consumer-service-api",
            "version": APP_VERSION,
            "runMode": context.settings.run_mode,
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
