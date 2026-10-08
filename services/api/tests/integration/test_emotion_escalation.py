"""情绪升级预警：导入时按规则生成，客户发新消息时实时生成，均不调用模型。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import select
from tests.integration.test_consumer_service_assistant import OFFICIAL_SOURCE, SUPPORT, _client

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.case_state.models import Base as CaseBase
from app.domain.consumer_service.importer import import_business_workbook
from app.domain.consumer_service.models import ServiceRiskAlertRow, migrate_risk_alert_table
from app.integrations.model_provider import MockModelProvider

CUSTOMER = {"X-Demo-View-Role": "customer"}


def _escalations(client) -> dict[str, dict]:
    alerts = client.get(
        "/api/support/risk-alerts", params={"risk_type": "emotion_escalation"}, headers=SUPPORT
    )
    assert alerts.status_code == 200
    return {item["conversationId"]: item for item in alerts.json()}


def test_import_creates_rule_escalation_alerts(tmp_path: Path) -> None:
    provider = MockModelProvider(responses=[])
    with _client(tmp_path, provider) as client:
        alerts = _escalations(client)
        assert "S00059" in alerts
        # 一开始就愤怒、随后平复，或始终平静的会话不预警
        assert "S00015" not in alerts
        assert "S00016" not in alerts

        alert = alerts["S00059"]
        assert alert["riskStatus"] == "pending"
        # Normal platform refund is not a complaint; confrontation still raises emotion risk.
        assert alert["riskLevel"] == "medium"
        assert "愤怒" in alert["triggerSummary"]
        assert len(alert["evidenceRefs"]) >= 2
        assert alert["orderId"] == "6920621990731110707"
        assert alert["workOrderId"] == "KOC7263722"
        complaints = client.get("/api/support/risk-alerts", params={"risk_type": "complaint_risk"},
                                headers=SUPPORT).json()
        assert not any(row["conversationId"] == "S00059" for row in complaints)
        assert provider.calls == []


def test_customer_message_creates_escalation_for_new_conversation(tmp_path: Path) -> None:
    provider = MockModelProvider(responses=[])
    with _client(tmp_path, provider) as client:
        created = client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
        conversation_id = created.json()["conversationId"]

        def send(body: str, key: str) -> dict:
            response = client.post(
                f"/api/customer/conversations/{conversation_id}/messages",
                json={"body": body, "clientMessageKey": key},
                headers=CUSTOMER,
            )
            assert response.status_code == 200, response.text
            return response.json()

        send("帮我看下订单到哪了", "c1")
        assert conversation_id not in _escalations(client)

        reply = send("三天了还没动静，再不处理我就去平台投诉", "c2")
        assert "risk" not in str(reply).lower()
        alert = _escalations(client)[conversation_id]
        assert alert["riskLevel"] == "high"
        assert alert["riskStatus"] == "pending"
        assert alert["orderId"] is None
        queue = client.get("/api/support/reception/queue", headers=SUPPORT)
        assert queue.status_code == 200, queue.text
        item = next(row for row in queue.json()["items"] if row["conversationId"] == conversation_id)
        assert item["currentEmotion"] == "angry"
        assert "emotion_escalation" in item["activeRiskTypes"]
        refused = client.post(
            f"/api/support/risk-alerts/{alert['alertId']}/status",
            json={"status": "resolved", "note": "不能直接关闭仍在触发的信号"},
            headers=SUPPORT,
        )
        assert refused.status_code == 422

        # 重复发同一幂等键不重复建预警；客服可正常处理本地会话的预警
        send("三天了还没动静，再不处理我就去平台投诉", "c2")
        assert len([key for key in _escalations(client) if key == conversation_id]) == 1
        detail = client.get(f"/api/support/risk-alerts/{alert['alertId']}", headers=SUPPORT)
        assert detail.status_code == 200
        moved = client.post(
            f"/api/support/risk-alerts/{alert['alertId']}/status",
            json={"status": "in_progress"},
            headers=SUPPORT,
        )
        assert moved.status_code == 200

        send("嗯，这还差不多", "c3")
        queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()["items"]
        item = next(row for row in queue if row["conversationId"] == conversation_id)
        assert item["currentEmotion"] == "calm"
        assert item["riskLevel"] is None and item["activeRiskTypes"] == []
        assert "emotion_escalation" in item["reviewRiskTypes"]
        incidents = client.get("/api/support/desk/risks", headers=SUPPORT).json()
        record = next(row for row in incidents if conversation_id in row["conversationIds"])
        assert record["attentionState"] == "review" and record["needsReview"] is True
        path = f"/api/support/desk/risks/{record['incidentId']}/status"
        closed = client.post(path, headers=SUPPORT, json={
            "status": "resolved", "note": "人工核对后关闭", "expectedVersion": record["version"],
        })
        assert closed.status_code == 200, closed.text
        record = closed.json()["incident"]
        assert record["attentionState"] == "closed" and record["needsReview"] is False
        assert record["triageScore"] == 0
        queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()["items"]
        item = next(row for row in queue if row["conversationId"] == conversation_id)
        assert item["activeRiskTypes"] == [] and item["reviewRiskTypes"] == []
        assert provider.calls == []


def test_legacy_risk_table_is_migrated_without_losing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    engine = build_engine(Settings(database_url=f"sqlite+pysqlite:///{db_path}"))
    CaseBase.metadata.create_all(engine)
    with build_session_factory(engine)() as session:
        import_business_workbook(session, OFFICIAL_SOURCE, repo_root=tmp_path)
        session.commit()
        before = {row.alert_id for row in session.scalars(select(ServiceRiskAlertRow))}
    engine.dispose()

    # 把表改回旧结构（会话记录 ID 非空、按会话记录 ID 唯一）
    connection = sqlite3.connect(db_path)
    original = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='service_risk_alert'"
    ).fetchone()[0]
    legacy = original.replace(
        "conversation_record_id VARCHAR(80),", "conversation_record_id VARCHAR(80) NOT NULL,"
    ).replace(
        "UNIQUE (batch_id, conversation_id, risk_type)",
        "UNIQUE (batch_id, conversation_record_id, risk_type)",
    )
    assert legacy != original
    connection.executescript(
        "ALTER TABLE service_risk_alert RENAME TO _tmp;"
        + legacy
        + ";INSERT INTO service_risk_alert SELECT * FROM _tmp; DROP TABLE _tmp;"
    )
    connection.close()

    engine = build_engine(Settings(database_url=f"sqlite+pysqlite:///{db_path}"))
    migrate_risk_alert_table(engine)
    with build_session_factory(engine)() as session:
        after = {row.alert_id for row in session.scalars(select(ServiceRiskAlertRow))}
    engine.dispose()
    connection = sqlite3.connect(db_path)
    migrated = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='service_risk_alert'"
    ).fetchone()[0]
    connection.close()
    assert after == before
    assert "conversation_record_id VARCHAR(80) NOT NULL" not in migrated
