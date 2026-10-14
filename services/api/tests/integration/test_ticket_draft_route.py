"""剧情 D：官方 S00015 不良反应会话在工作台内预填工单（P1-4）。
失败方式：预填不带来源；就医状态与原话不符；多订单时擅自选订单；预填即创建工单；调用模型。
"""

from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def test_story_d_prefill_from_official_conversation(workspace):
    client, _, provider = workspace
    before_calls = len(provider.calls)
    before_tickets = len(client.get("/api/support/desk/tickets", headers=SUPPORT).json())
    response = client.post("/api/support/desk/tickets/draft", json={"conversationId": "S00015"}, headers=SUPPORT)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["workOrderType"] == "adverse_reaction"
    assert draft["orderId"]
    fields = {item["field"]: item for item in draft["fields"]}
    assert fields["soughtMedicalCare"]["value"] == "yes"
    assert "医院" in fields["soughtMedicalCare"]["quote"]
    assert all(item["sourceRef"].startswith("message:S00015:") for item in draft["fields"])
    assert len(client.get("/api/support/desk/tickets", headers=SUPPORT).json()) == before_tickets
    assert len(provider.calls) == before_calls
