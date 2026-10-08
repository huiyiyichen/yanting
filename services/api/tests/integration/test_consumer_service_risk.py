from __future__ import annotations

from pathlib import Path

from tests.integration.test_consumer_service_assistant import (
    SUPPORT,
    _AssistantProvider,
    _client,
)


def _provider() -> _AssistantProvider:
    return _AssistantProvider(
        {
            "current_question": "消费者反馈使用后皮肤不适",
            "service_summary": "存在不良反应工单。",
            "emotion_level": "dissatisfied",
            "missing_information": [],
            "next_steps": ["核对工单"],
            "reply_suggestions": [
                {
                    "style": "recommended",
                    "body": "抱歉给您带来不适，我先核对服务记录，再请客服继续跟进。",
                }
            ],
        }
    )


def test_risk_alert_list_detail_and_status_flow(tmp_path: Path) -> None:
    client = _client(tmp_path, _provider())
    with client:
        generated = client.post(
            "/api/support/reception/S00082/assistant",
            headers=SUPPORT,
        )
        assert generated.status_code == 200, generated.text

        listed = client.get("/api/support/risk-alerts", headers=SUPPORT)
        assert listed.status_code == 200
        alerts = [
            item
            for item in listed.json()
            if item["conversationId"] == "S00082" and item["riskType"] == "adverse_reaction"
        ]
        assert alerts
        alert = alerts[0]
        assert alert["riskType"] == "adverse_reaction"
        assert alert["riskLevel"] == "high"
        assert alert["riskStatus"] == "pending"

        detail = client.get(
            f"/api/support/risk-alerts/{alert['alertId']}",
            headers=SUPPORT,
        )
        assert detail.status_code == 200
        assert detail.json()["serviceContext"]["conversationId"] == "S00082"

        customer = client.get("/api/support/risk-alerts", headers={"X-Demo-View-Role": "customer"})
        assert customer.status_code == 403

        processing = client.post(
            f"/api/support/risk-alerts/{alert['alertId']}/status",
            json={"status": "in_progress"},
            headers=SUPPORT,
        )
        assert processing.status_code == 200
        assert processing.json()["riskStatus"] == "in_progress"

        missing_note = client.post(
            f"/api/support/risk-alerts/{alert['alertId']}/status",
            json={"status": "resolved"},
            headers=SUPPORT,
        )
        assert missing_note.status_code == 422

        resolved = client.post(
            f"/api/support/risk-alerts/{alert['alertId']}/status",
            json={"status": "resolved", "note": "客服已完成人工复核"},
            headers=SUPPORT,
        )
        assert resolved.status_code == 200
        assert resolved.json()["riskStatus"] == "resolved"

        reopened = client.post(
            f"/api/support/risk-alerts/{alert['alertId']}/status",
            json={"status": "ignored", "note": "重复预警"},
            headers=SUPPORT,
        )
        assert reopened.status_code == 422

        audit = client.get("/api/support/audit/S00082", headers=SUPPORT)
        assert any(item["eventType"] == "risk_status_changed" for item in audit.json())
