"""P2-1 旧安克售后编排移除。

失败方式：
L1 旧话术候选、只读提示词一览等无页面调用的旧接口仍挂载，评委可调到与现方案不符的行为；
L2 移除时误删当前页面在用的接口（接待辅助、提示词模板、消费者消息）；
L3 旧编排模块仍可导入，被新代码误用。
L4 旧售后工具网关（app.tools / app.tool_gateway / domain.after_sales）仍在，评价仍绕道工具调用；
   待确认申请接口 /api/support/requests/* 仍挂载（无页面使用）。评价与结束服务必须照常工作（test_api_routes 覆盖）。
"""

import importlib.util

import pytest
from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


@pytest.mark.parametrize("method,path", [
    ("get", "/api/support/conversations/{cid}/suggestions"),
    ("post", "/api/support/conversations/{cid}/suggestions/generate"),
    ("post", "/api/support/conversations/{cid}/suggestions/action"),
    ("get", "/api/platform/prompts"),
])
def test_legacy_routes_are_gone(workspace, method, path):
    client, _, _ = workspace
    response = getattr(client, method)(path.format(cid="S00001"), headers=SUPPORT)
    assert response.status_code in (404, 405)


def test_current_routes_remain(workspace):
    client, _, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "帮我看看订单")
    assert client.get(f"/api/support/conversations/{cid}/service-context", headers=SUPPORT).status_code == 200
    assert client.get("/api/platform/prompt-templates", headers=SUPPORT).status_code == 200
    assert client.get(f"/api/support/conversations/{cid}/messages", headers=SUPPORT).status_code == 200


@pytest.mark.parametrize("module", ["orchestrator", "routing", "reply", "understanding", "suggestions", "contracts"])
def test_legacy_modules_removed(module):
    assert importlib.util.find_spec(f"app.domain.agent.{module}") is None


@pytest.mark.parametrize("module", ["app.tools", "app.tool_gateway", "app.domain.after_sales"])
def test_after_sales_tool_modules_removed(module):
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize("method,path", [
    ("get", "/api/support/requests/pending"),
    ("post", "/api/support/requests/R1/review"),
])
def test_after_sales_request_routes_gone(workspace, method, path):
    client, _, _ = workspace
    response = getattr(client, method)(path, headers=SUPPORT)
    assert response.status_code in (404, 405)
