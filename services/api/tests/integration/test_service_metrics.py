"""服务指标顶栏（P1-9）。先列失败方式：
M1 自动回复率分母漏掉转人工任务（应为 sent /(sent + handoff)）。
M2 转人工不区分客户要求、安全、模型失败三类。
M3 平均首响把开场白/系统消息当成服务回复，或在没有回复时给出 0 秒。
M4 建议采纳率在没有任何采用/忽略记录时给出 0%（应为空，表示无数据）。
M5 指标读取调用模型。
"""

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.models import AutoReplyJobRow

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def test_reception_metrics(workspace):
    client, factory, provider = workspace
    empty = client.get("/api/support/desk/stats", headers=SUPPORT).json()
    assert empty["autoReplyRate"] is None and empty["suggestionAdoptionRate"] is None
    assert empty["averageFirstResponseSeconds"] is None

    sent_cid = fixtures._create(client)
    fixtures._send(client, sent_cid, "包裹到哪了")
    with factory() as session:
        job_id = session.scalar(select(AutoReplyJobRow.job_id).where(AutoReplyJobRow.conversation_id == sent_cid))
    process_job(client.app.state.runtime, job_id)

    human_cid = fixtures._create(client)
    fixtures._send(client, human_cid, "面膜什么时候发货")
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == human_cid))
        job.status, job.error_code = "handoff", "customer_requested"
        session.commit()

    calls = len(provider.calls)
    stats = client.get("/api/support/desk/stats", headers=SUPPORT).json()
    assert stats["aiConversations"] == 2
    assert stats["autoReplyRate"] == 0.5
    assert stats["handoffs"] == {"total": 1, "customer": 1, "safety": 0, "modelFailure": 0}
    assert stats["averageFirstResponseSeconds"] is not None and stats["averageFirstResponseSeconds"] >= 0
    assert len(provider.calls) == calls
