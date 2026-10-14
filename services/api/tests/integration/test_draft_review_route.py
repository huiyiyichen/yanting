"""发送前质检接口（P1-5）。失败方式：
D1 金额与官方记录不符（S00005 退款 8.8 元，草稿写 9.8 元）未提示；写对时误报。
D2 当前会话情绪激烈时冷漠模板未提示（S00059 最新消费者原话为激烈）。
D3 客户视角能调用质检接口。
D4 质检未写审计，事后无法追溯客服看到过哪些提示。
D5 质检调用模型。
"""

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def review(client, cid, body, headers=SUPPORT):
    return client.post(f"/api/support/reception/{cid}/draft-review", json={"body": body}, headers=headers)


def test_draft_review_against_official_records(workspace):
    from app.domain.case_state.models import AuditEventRow

    client, factory, provider = workspace
    before = len(provider.calls)
    wrong = review(client, "S00005", "亲，退款9.80元已原路退回")
    assert wrong.status_code == 200, wrong.text
    assert [item["kind"] for item in wrong.json()["findings"]] == ["fact_mismatch"]
    assert review(client, "S00005", "亲，退款8.8元已原路退回").json()["findings"] == []
    cold = review(client, "S00059", "按流程需要您先拍照").json()["findings"]
    assert {item["kind"] for item in cold} == {"cold_tone"}
    assert review(client, "S00059", "x", headers=CUSTOMER).status_code in {401, 403}
    with factory() as session:
        events = list(session.scalars(select(AuditEventRow).where(AuditEventRow.event_type == "draft_review")))
    assert len(events) == 3
    assert len(provider.calls) == before
