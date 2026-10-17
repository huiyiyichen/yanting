"""用户反馈第 8 点：草稿模式的回复建议不因核验问题整体失败。

失败方式：
F1 核验只指出交接摘要（无 replyIndex）有误时，整次生成失败，回复建议一并丢失。
F2 被指出的摘要仍然显示给客服。
F3 草稿模式回复含核验问题时接口报错，客服拿不到任何建议（应返回建议并标注待确认原因）。
F4 待确认的建议不能采用或改写。
F5 自动接待模式下，同样的问题仍被发给消费者（必须继续转人工）。
"""

import json

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_grounded_workflow import make_provider

from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.models import AutoReplyJobRow

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER
REPLY = "亲，理解您着急，我先帮您登记一下订单状态哦。"


def _draft(_payload):
    return {**json.loads(fixtures.OUTPUT), "intent": "order_status",
            "service_summary": "退款已到账，消费者确认。",
            "reply_suggestions": [{"style": "recommended", "body": REPLY}]}


def test_summary_issue_only_withdraws_the_summary(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "帮我看看订单")
    make_provider(provider, _draft, lambda _: {"supported": False, "issues": [
        {"category": "fact", "detail": "service_summary称退款已到账与工单不符"},
    ]})
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["replySuggestions"][0]["body"] == REPLY
    assert body["replySuggestions"][0]["reviewNotes"] == []
    assert body["serviceSummary"] == ""
    assert body["verificationStatus"] == "verified"
    assert body["modelUsage"]["auxiliaryDropped"]


def test_reply_issue_in_draft_mode_is_flagged_not_failed(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "帮我看看订单")
    make_provider(provider, _draft, lambda _: {"supported": False, "issues": [
        {"category": "fact", "replyIndex": 0, "segmentIndex": 0, "detail": "订单状态缺少依据"},
    ]})
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verificationStatus"] == "needs_review"
    assert body["deliveryMode"] == "draft"
    assert body["replySuggestions"][0]["body"] == REPLY
    assert body["replySuggestions"][0]["reviewNotes"] == ["订单状态缺少依据"]
    action = client.post(f"/api/support/reception/{cid}/suggestion-action", headers=SUPPORT,
                         json={"inputHash": body["inputHash"], "style": "recommended", "action": "adopt"})
    assert action.status_code < 400, action.text


def test_reply_issue_in_automatic_mode_is_never_sent(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "帮我看看订单")
    make_provider(provider, _draft, lambda _: {"supported": False, "issues": [
        {"category": "fact", "replyIndex": 0, "segmentIndex": 0, "detail": "订单状态缺少依据"},
    ]})
    with factory() as session:
        job_id = session.scalar(select(AutoReplyJobRow.job_id).where(AutoReplyJobRow.conversation_id == cid))
    process_job(client.app.state.runtime, job_id)
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert not any(REPLY in (m.get("body") or "") for m in messages)
