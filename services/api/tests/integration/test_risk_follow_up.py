"""风险约定跟进（用户反馈 10-18 #7 修订：处置栏必填下次跟进，到期回到待处理）。

先列失败方式：
F1 约定跟进没写进处置记录；风险上看不到下次跟进时间。
F2 到了跟进时间仍不提醒（followUpDue 仍为 false、分诊原因里没有“跟进到期”）。
F3 之后做了别的处置（关闭、处理中）仍显示旧的跟进。
F4 跟进时间在过去或备注为空也能提交；版本冲突不报 409。
F5 约定跟进改了风险状态，或做了任何业务动作（退款/改单等）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from tests.integration.test_risk_lifecycle import action, create_manual, incident, workspace  # noqa: F401
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.models import ServiceDeskEventRow

SUPPORT = fixtures.SUPPORT


def follow(client, record, at, note="约客户明早回电", version=None):
    return client.post(f"/api/support/desk/risks/{record['incidentId']}/follow-up", headers=SUPPORT,
                       json={"at": at, "note": note, "expectedVersion": version or record["version"]})


def risky(client):
    cid = create_manual(client)
    fixtures._send(client, cid, "请查一下订单", key="baseline")
    fixtures._send(client, cid, "再不处理我就投诉", key="first-risk")
    return cid


def test_follow_up_recorded_then_due_then_cleared(workspace):
    client, factory, _ = workspace
    cid = risky(client)
    record = incident(client, cid)
    status_before = record["riskStatus"]
    at = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    response = follow(client, record, at)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["incident"]["followUpAt"] and body["incident"]["followUpDue"] is False  # F1
    assert body["incident"]["riskStatus"] == status_before  # F5
    assert any(e["action"] == "follow_up" and "约客户明早回电" in e["note"] for e in body["handlingHistory"])
    # F2 时间到了
    with factory() as session:
        session.execute(update(ServiceDeskEventRow).where(ServiceDeskEventRow.action == "follow_up").values(
            note=(datetime.now(UTC) - timedelta(minutes=1)).isoformat() + "|约客户明早回电"))
        session.commit()
    row = incident(client, cid)
    assert row["followUpDue"] is True and "跟进到期" in row["triageReasons"]
    # F3 之后做了处置，跟进清除
    response = action(client, row, "in_progress")
    assert response.status_code == 200, response.text
    assert response.json()["incident"]["followUpAt"] is None and response.json()["incident"]["followUpDue"] is False


def test_follow_up_validation(workspace):
    client, factory, _ = workspace
    record = incident(client, risky(client))
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert follow(client, record, past).status_code == 422
    assert follow(client, record, future, note=" ").status_code == 422
    assert follow(client, record, future, version="stale").status_code == 409
    with factory() as session:
        assert not session.scalars(select(ServiceDeskEventRow).where(ServiceDeskEventRow.action == "follow_up")).all()
