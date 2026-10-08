from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.models import (
    AutoReplyJobRow,
    ServiceImageObservationRow,
    SourceRecordRow,
)
from app.domain.platform.settings import set_setting
from app.integrations.model_provider import ChatResult

base_workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


@pytest.fixture
def workspace(base_workspace, tmp_path):
    client, factory, provider = base_workspace
    client.app.state.runtime.settings.runtime_dir = str(tmp_path / "runtime")
    return client, factory, provider


def attach(client, cid, body="瓶底写的批次号是什么呀？"):
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(buffer, format="PNG")
    response = client.post(f"/api/customer/conversations/{cid}/attachments", headers=CUSTOMER,
                           files={"file": ("label.png", buffer.getvalue(), "image/png")})
    assert response.status_code == 200, response.text
    identifier = response.json()["attachmentId"]
    sent = client.post(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER,
                       json={"body": body, "clientMessageKey": "image", "attachmentIds": [identifier]})
    assert sent.status_code == 200, sent.text
    assert sent.json()["reply"] is None and sent.json()["decision"] is None
    return identifier


def current_job(factory, cid):
    with factory() as session:
        return session.scalar(select(AutoReplyJobRow).where(
            AutoReplyJobRow.conversation_id == cid,
        ).order_by(AutoReplyJobRow.created_at.desc())).job_id


def vision_provider(provider, *, category="label", readable=True, before_verify=None, final_support=True):
    stages = []

    def complete(messages, **kwargs):
        provider._calls.append(list(messages))
        prompt = messages[0].content
        payload = json.loads(messages[1].content)
        if prompt.startswith("IMAGE_OBSERVATION_V1"):
            stages.append("image")
            assert len(messages[1].image_data_urls) == len(payload["images"])
            assert all(url.startswith("data:image/png;base64,") for url in messages[1].image_data_urls)
            value = {"images": [{
                "attachment_id": image["attachment_id"], "category": category, "readable": readable,
                "visible_text": ["2604B"] if readable else [],
                "visible_clues": ["瓶底有一行字符"] if readable else [],
                "uncertainties": [] if readable else ["文字看不清"],
                "requires_human_review": category == "skin" or not readable,
            } for image in payload["images"]]}
        elif prompt.startswith("GROUNDING_REVIEW_V1"):
            stages.append("verify")
            assert messages[1].image_data_urls
            assert payload["imageAttachments"]
            if before_verify:
                before_verify()
            value = {"supported": final_support, "issues": [] if final_support else ["图片文字未被原图支持"]}
        else:
            stages.append("draft")
            assert not messages[1].image_data_urls
            source = next(source for source in payload["sourceCatalog"] if source["kind"] == "image_observation")
            assert source["fields"]["analyzed"]
            assert all(source["kind"] != "image_observation" for source in payload["memorySourceCatalog"])
            value = json.loads(fixtures.OUTPUT)
            value.update(current_question="客户咨询图片上的批次字符。", intent="product_question",
                         service_summary="客户上传了瓶底照片。待核对可见字符。", missing_information=[])
            value["reply_suggestions"] = [{
                "style": "recommended",
                "segments": [{"text": "亲，照片上的字符是2604B。", "source_refs": [source["sourceId"]]}]
                if readable and category != "skin" else [{"text": "亲，这张图片需要人工进一步核实。", "source_refs": []}],
            }]
        return ChatResult(text=json.dumps(value, ensure_ascii=False), model="explicit-vision-fixture",
                          is_mock=True, latency_seconds=0.01, prompt_tokens=40, completion_tokens=20)

    provider.complete = complete
    return stages


def test_automatic_image_reception_is_cited_visible_and_reused_for_followup(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    identifier = attach(client, cid)
    stages = vision_provider(provider)
    process_job(client.app.state.runtime, current_job(factory, cid))
    assert stages == ["image", "draft", "verify"]
    result = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()
    assert result["stale"] is False and result["modelUsage"]["calls"] == 3
    assert result["isMock"] is True
    source = next(source for source in result["groundingSources"] if source["kind"] == "image_observation")
    assert source["sourceId"] == f"image:{identifier}" and source["fields"]["visibleText"] == ["2604B"]
    customer = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert customer[-1]["body"] == "亲，照片上的字符是2604B。"
    assert customer[1]["attachments"][0]["attachmentId"] == identifier
    assert "image_observation" not in json.dumps(customer)
    with factory() as session:
        assert session.get(ServiceImageObservationRow, identifier).model_id == "explicit-vision-fixture"
        assert len(list(session.scalars(select(SourceRecordRow)))) == 1191
    fixtures._send(client, cid, "那就按这个批次继续核对吧", key="followup")
    process_job(client.app.state.runtime, current_job(factory, cid))
    assert stages == ["image", "draft", "verify", "draft", "verify"]
    result = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()
    assert result["stale"] is False and result["modelUsage"]["calls"] == 2


def test_picture_without_customer_text_can_generate_a_manual_draft(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    attach(client, cid, body="")
    vision_provider(provider)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["replySuggestions"][0]["body"] == "亲，照片上的字符是2604B。"
    assert len(client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()) == 3


@pytest.mark.parametrize("category,readable", [("skin", True), ("label", False)])
def test_unclear_or_skin_images_require_human_without_diagnosis(workspace, category, readable):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    attach(client, cid, body="帮我看看这张照片")
    vision_provider(provider, category=category, readable=readable)
    process_job(client.app.state.runtime, current_job(factory, cid))
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()["items"]
    item = next(item for item in queue if item["conversationId"] == cid)
    assert item["serviceMode"] == "operator_assisted"
    assert item["autoReplyStatus"] == "handoff"
    assert "过敏" not in client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).text


def test_takeover_during_image_verification_prevents_late_delivery(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    attach(client, cid)
    invoked = False

    def takeover():
        nonlocal invoked
        if not invoked:
            invoked = True
            response = client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
            assert response.status_code == 200

    stages = vision_provider(provider, before_verify=takeover)
    process_job(client.app.state.runtime, current_job(factory, cid))
    assert stages == ["image", "draft", "verify"]
    rows = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert not any("2604B" in item["body"] and item["senderRole"] == "assistant" for item in rows)
    with factory() as session:
        assert session.scalar(select(ServiceImageObservationRow).where(
            ServiceImageObservationRow.conversation_id == cid,
        )) is None


def test_invalid_image_file_is_never_read_and_failure_does_not_save_observations(workspace):
    from app.domain.case_state.models import AttachmentRow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    identifier = attach(client, cid)
    with factory() as session:
        attachment = session.get(AttachmentRow, identifier)
        # An invalid persisted path must be rejected before any model request.
        attachment.stored_path = str(Path(attachment.stored_path).parents[3] / "outside.png")
        session.commit()
    stages = vision_provider(provider)
    process_job(client.app.state.runtime, current_job(factory, cid))
    assert stages == []
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()["items"]
    assert next(row for row in queue if row["conversationId"] == cid)["serviceMode"] == "operator_assisted"
    with factory() as session:
        assert session.get(ServiceImageObservationRow, identifier) is None


def test_new_visual_model_invalidates_and_reanalyzes_saved_picture(workspace):
    client, factory, provider = workspace
    provider.vision_model_id = "vision-a"
    cid = fixtures._create(client)
    attach(client, cid)
    stages = vision_provider(provider)
    process_job(client.app.state.runtime, current_job(factory, cid))
    with factory() as session:
        set_setting(session, "llm.vision_model", "vision-b")
        session.commit()
    assert client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()["stale"]
    provider.vision_model_id = "vision-b"
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert stages == ["image", "draft", "verify", "image", "draft", "verify"]
