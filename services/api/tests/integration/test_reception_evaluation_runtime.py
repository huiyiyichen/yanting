import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient
from tests.integration import test_reception_workspace as fixtures

from app import main as main_module
from app.domain.consumer_service import auto_reception
from app.domain.consumer_service.models import AutoReplyJobRow
from app.evaluation.reception_runtime import reception_client

workspace = fixtures.workspace


def test_evaluation_client_runs_real_background_worker_without_manual_job_processing(workspace):
    existing_client, factory, provider = workspace
    context = existing_client.app.state.runtime
    with reception_client(context) as client:
        cid = fixtures._create(client)
        sent = fixtures._send(client, cid, "包裹到哪了")
        assert sent["reply"] is None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            queue = client.get("/api/support/reception/queue", headers=fixtures.SUPPORT).json()
            item = next(row for row in queue["items"] if row["conversationId"] == cid)
            if item["autoReplyStatus"] == "sent":
                break
            time.sleep(0.05)
        assert item["autoReplyStatus"] == "sent"
        messages = client.get(
            f"/api/customer/conversations/{cid}/messages", headers=fixtures.CUSTOMER,
        ).json()
        assert messages[-1]["senderRole"] == "assistant"
        assert messages[-1]["body"] == "我来核对这笔订单，方便提供订单号吗？"
        assert len(provider.calls) == 2
        with factory() as session:
            job = session.query(AutoReplyJobRow).filter_by(conversation_id=cid).one()
            assert job.status == "sent"


def test_worker_limits_parallel_generations_and_eventually_processes_fifth_conversation(workspace):
    existing_client, factory, provider = workspace
    context = existing_client.app.state.runtime
    release, four_started = Event(), Event()
    lock = Lock()
    active = peak = 0
    original_complete = provider.complete

    def gated_complete(messages, **kwargs):
        nonlocal active, peak
        drafting = not messages[0].content.startswith("GROUNDING_REVIEW_V1")
        if drafting:
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 4:
                    four_started.set()
            try:
                assert release.wait(15), "Test generations were not released"
            finally:
                with lock:
                    active -= 1
        return original_complete(messages, **kwargs)

    provider.complete = gated_complete
    with reception_client(context) as client:
        try:
            ids = [fixtures._create(client) for _ in range(5)]
            for cid in ids:
                fixtures._send(client, cid)
            assert four_started.wait(10)
            with factory() as session:
                jobs = session.query(AutoReplyJobRow).filter(AutoReplyJobRow.conversation_id.in_(ids)).all()
                assert sum(job.status == "running" for job in jobs) == 4
                assert sum(job.status == "queued" for job in jobs) == 1
            assert peak == 4
        finally:
            release.set()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with factory() as session:
                jobs = session.query(AutoReplyJobRow).filter(AutoReplyJobRow.conversation_id.in_(ids)).all()
                if all(job.status == "sent" for job in jobs):
                    break
            time.sleep(0.05)
        assert all(job.status == "sent" for job in jobs)
        assert len(provider.calls) == 10
        assert peak == 4


def test_background_worker_supersedes_an_inflight_reply_without_delivering_it(workspace):
    existing_client, factory, provider = workspace
    context = existing_client.app.state.runtime
    entered, release = Event(), Event()
    original_complete = provider.complete

    def gated_complete(messages, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(15), "Test generation was not released"
        return original_complete(messages, **kwargs)

    provider.complete = gated_complete
    with reception_client(context) as client:
        try:
            cid = fixtures._create(client)
            baseline = client.get(f"/api/customer/conversations/{cid}/messages", headers=fixtures.CUSTOMER).json()
            fixtures._send(client, cid, "先查询订单", key="first")
            assert entered.wait(10)
            fixtures._send(client, cid, "补充一下，请核对物流记录", key="second")
        finally:
            release.set()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with factory() as session:
                jobs = session.query(AutoReplyJobRow).filter_by(conversation_id=cid).order_by(
                    AutoReplyJobRow.message_revision,
                ).all()
                if len(jobs) == 2 and jobs[-1].status == "sent":
                    break
            time.sleep(0.05)
        assert [job.status for job in jobs] == ["superseded", "sent"]
        messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=fixtures.CUSTOMER).json()
        initial_ids = {message["messageId"] for message in baseline}
        generated = [message for message in messages
                     if message["senderRole"] == "assistant" and message["messageId"] not in initial_ids]
        assert len(generated) == 1
        assert len(provider.calls) == 3  # Old draft, then current draft and verifier.


@pytest.mark.parametrize("runtime_kind", ["evaluation", "application"])
def test_shutdown_waits_for_inflight_provider_and_database_work_before_disposal(workspace, monkeypatch, runtime_kind):
    existing_client, factory, provider = workspace
    context = existing_client.app.state.runtime
    started, worker_stopped, release, completed = Event(), Event(), Event(), Event()
    original_complete, original_worker, original_close = provider.complete, auto_reception.run_reply_worker, context.close

    def gated_complete(messages, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10), "Test provider was not released"
        result = original_complete(messages, **kwargs)
        completed.set()
        return result

    async def observed_worker(runtime):
        try:
            await original_worker(runtime)
        finally:
            worker_stopped.set()

    def close_after_work():
        assert worker_stopped.is_set() and completed.is_set()
        with factory() as session:
            assert session.query(AutoReplyJobRow).filter_by(conversation_id=cid).one().status == "sent"
        original_close()

    def release_on_shutdown():
        try:
            assert worker_stopped.wait(10), "Worker did not receive shutdown"
        finally:
            release.set()

    monkeypatch.setattr(provider, "complete", gated_complete)
    monkeypatch.setattr(auto_reception, "run_reply_worker", observed_worker)
    monkeypatch.setattr(context, "close", close_after_work)
    monkeypatch.setattr(main_module, "build_runtime", lambda: context)
    client_context = reception_client(context) if runtime_kind == "evaluation" else TestClient(main_module.create_app())
    with ThreadPoolExecutor(max_workers=1) as helper:
        with client_context as client:
            cid = fixtures._create(client)
            fixtures._send(client, cid)
            assert started.wait(10)
            assert not completed.is_set()
            releasing = helper.submit(release_on_shutdown)
        releasing.result(timeout=10)
    assert completed.is_set()
