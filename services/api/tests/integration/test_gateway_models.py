"""用户反馈 10-18 #5/#6：模型配置页。

G1 抽屉里的“网关可用模型”只是本地配置，不是网关真实列表。
G2 页面上还留着不能配置的“知识索引（Qdrant 本地）”行。
"""
from fastapi.testclient import TestClient

from app.main import app

SUPPORT = {"X-Demo-View-Role": "support"}


def test_gateway_list_and_no_index_row():
    with TestClient(app) as client:
        body = client.get("/api/platform/models/gateway", headers=SUPPORT)
        assert body.status_code == 200, body.text
        data = body.json()
        assert set(data) == {"models", "configured", "reachable"} and data["reachable"] == bool(data["models"])
        page = client.get("/api/platform/models", headers=SUPPORT).json()
        assert "knowledge_index" not in [p["key"] for p in page["providers"]]
