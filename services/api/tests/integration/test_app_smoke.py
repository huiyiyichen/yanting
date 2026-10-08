"""应用冒烟测试：健康检查、契约路由与错误信封。

S0 退出条件之一：能启动后端并完成至少一条契约与冒烟测试。
这些用例不访问外部模型服务，因此可在无凭证环境运行。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_run_mode_and_version() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["runMode"] in {"live", "mock"}
    assert payload["contractVersion"]
    assert payload["status"] in {"ok", "degraded"}
    # 能力状态必须是三者之一，不允许静默成功
    for key in ("database", "llm", "vision", "embedding", "knowledgeIndex"):
        assert payload[key]["state"] in {"ready", "unavailable", "unknown"}, key


def test_health_uses_camel_case_field_names() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/health").json()
    assert "runMode" in payload
    assert "run_mode" not in payload
    assert "contractVersion" in payload


def test_database_capability_is_ready() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/health").json()
    assert payload["database"]["state"] == "ready", payload["database"]["detail"]


def test_enums_endpoint_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/contracts/enums")
    assert response.status_code == 200
    payload = response.json()
    assert "caseStatus" in payload
    assert payload["requestStatus"]["pending_confirmation"] == "待人工确认"


def test_contract_manifest() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/contracts/manifest").json()
    assert payload["namingConvention"]["apiJson"] == "camelCase"
    assert payload["enumCount"] > 0
    assert payload["sourceOfTruth"].endswith("domain/enums.py")


def test_openapi_is_generated() -> None:
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    assert schema["openapi"].startswith("3.")
    assert "/api/health" in schema["paths"]
    assert "HealthResponse" in schema["components"]["schemas"]


def test_unknown_route_returns_404() -> None:
    with TestClient(app) as client:
        assert client.get("/api/does-not-exist").status_code == 404


def test_domain_error_envelope() -> None:
    """领域异常必须返回带 code 的结构化信封，而不是裸 500。"""

    from app.errors import ProviderNotConfigured

    @app.get("/api/_test/domain-error", include_in_schema=False)
    async def _raise() -> None:
        raise ProviderNotConfigured("未配置模型", detail="缺少 API key")

    with TestClient(app) as client:
        response = client.get("/api/_test/domain-error")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_not_configured"
    assert body["error"]["detail"] == "缺少 API key"

    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", "") != "/api/_test/domain-error"
    ]
