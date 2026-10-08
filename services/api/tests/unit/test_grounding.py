import pytest

from app.domain.consumer_service.grounded_workflow import GroundedDraft
from app.domain.consumer_service.grounding import (
    _flatten,
    validate_claims,
    validate_dialogue_fields,
    validate_memory,
)
from app.schemas.grounding import GroundingClaim, GroundingSource, MemoryItem


def order(identifier="111111", amount="10", status="已发货"):
    return GroundingSource(
        source_id=f"order:{identifier}", kind="order", subject_id=identifier, label="订单",
        text=f"订单号：{identifier}\n实付：{amount}元\n状态：{status}\n下单时间：2026-05-01",
        fields={"orderId": identifier, "paidAmount": amount, "sourceStatus": status},
    )


def test_amount_and_identifier_must_match_the_referenced_order():
    a, b = order(), order("222222", "20")
    sources = {s.source_id: s for s in [a, b]}
    correct = "订单111111实付10元。"
    assert not validate_claims(correct, [GroundingClaim(text=correct, source_refs=[a.source_id])], sources)
    wrong = "订单111111实付20元。"
    assert validate_claims(wrong, [GroundingClaim(text=wrong, source_refs=[a.source_id])], sources)
    assert validate_claims(wrong, [GroundingClaim(text=wrong, source_refs=[b.source_id])], sources)


def test_customer_statement_cannot_supply_another_orders_amount():
    a, b = order(), order("222222", "20")
    customer = GroundingSource(source_id="m1", kind="customer_message", subject_id="c1",
                               label="客户自述", text="我说的是订单111111")
    sources = {s.source_id: s for s in [a, b, customer]}
    body = "订单111111实付20元。"
    assert validate_claims(body, [GroundingClaim(text=body, source_refs=[b.source_id, "m1"])], sources)


@pytest.mark.parametrize("body", [
    "订单111111实付10元。", "订单111111已经发货。", "发货时间是2026-05-01。",
])
def test_factual_text_cannot_be_left_out_of_the_claim_list(body):
    source = order()
    assert validate_claims(body, [], {source.source_id: source})


@pytest.mark.parametrize("body", ["订单111111已签收。", "订单111111于2027-05-01发货。"])
def test_invented_status_or_date_is_rejected_even_with_a_real_reference(body):
    source = order()
    assert validate_claims(body, [GroundingClaim(text=body, source_refs=[source.source_id])],
                           {source.source_id: source})


def test_empathy_and_clarifying_questions_do_not_need_invented_citations():
    assert not validate_claims("让您着急了，我先帮您核对记录。", [], {})
    assert not validate_claims("请确认是否已经发货？", [], {})
    assert not validate_claims("目前不能确认适合敏感肌，成分资料未提供。", [], {})
    assert not validate_claims("建议您先和医生确认可用成分方向，再挑选适合自己的洁面乳。", [], {})
    assert not validate_claims("孕期对洁面成分多留个心很正常。", [], {})
    assert not validate_claims("您方便的话把在用的洁面包装成分表拍给我，我帮您一起看看。", [], {})
    assert not validate_claims("孕期选洁面建议先看成分表，麻烦拍张包装照片发我哦。", [], {})
    assert not validate_claims("先看看成分表，您再把洗后的感受告诉我哦。", [], {})
    assert validate_claims("成分表标明不含酒精。", [], {})
    assert validate_claims("建议您先查看订单111111实付999元的记录。", [], {})
    assert validate_claims("不能确认适合敏感肌，但它不含酒精。", [], {})


def test_staff_submission_statement_is_not_proof_of_a_current_business_action():
    source = GroundingSource(
        source_id="staff:1", kind="staff_message", subject_id="c1",
        label="历史客服", text="已提交打款申请，请留意到账通知。",
    )
    for body in ("打款申请已提交。", "已提交打款申请，请留意到账。"):
        claim = GroundingClaim(text=body, source_refs=[source.source_id])
        assert validate_claims(body, [claim], {source.source_id: source})
        assert validate_claims(body, [], {source.source_id: source})
    body = "此前客服曾告知打款申请已提交。"
    claim = GroundingClaim(text=body, source_refs=[source.source_id])
    assert validate_claims(body, [claim], {source.source_id: source}) == []


@pytest.mark.parametrize("body, accepted", [
    ("没有成分资料，我不会替您猜测成分。", True),
    ("不会猜测功效，请提供要查询的商品名称。", True),
    ("也不推荐品牌或猜具体商品功效。", True),
    ("我会猜具体商品功效。", False),
    ("不推荐品牌或猜具体商品功效，但它具有保湿功效。", False),
    ("我不会猜测成分，但它不含酒精。", False),
    ("我不会猜成分，它具有保湿功效。", False),
])
def test_refusing_to_guess_is_not_a_product_claim_but_nearby_assertions_still_require_sources(body, accepted):
    assert (not validate_claims(body, [], {})) is accepted


@pytest.mark.parametrize("body, accepted", [
    ("本地跟进状态为pending。", False),
    ("目前跟进状态为待核对。", True),
    ("核对订单号后，我再帮您查询派送进度。", False),
    ("我会查询实时物流。", False),
    ("我不能查询实时物流。", True),
    ("暂时无法帮您查询实时物流。", True),
    ("确认订单号后，我再帮您查询已有订单记录。", True),
    ("您可以凭单号在快递官方渠道查询最新派送进度。", True),
])
def test_customer_reply_keeps_internal_codes_and_unsupported_live_queries_out(body, accepted):
    assert (not validate_claims(body, [], {})) is accepted


@pytest.mark.parametrize("body", [
    "目前资料没有提供成分表，不能确认适合敏感肌。",
    "未查到成分资料，暂时无法判断适用性。",
    "这款商品的成分未知，不能确认适合敏感肌。",
    "目前不能确认适合敏感肌，但它不含酒精。",
    "未查到成分资料，不过这款适合敏感肌。",
])
def test_missing_product_information_is_not_a_positive_product_claim(body):
    assert bool(validate_claims(body, [], {})) == ("但" in body or "不过" in body)


def test_published_knowledge_can_support_a_product_price():
    source = GroundingSource(source_id="k1", kind="knowledge", subject_id="product1",
                             label="商品资料", text="测试商品的单价为129元。")
    body = "这款测试商品单价为129元。"
    assert not validate_claims(body, [GroundingClaim(text=body, source_refs=["k1"])], {"k1": source})


@pytest.mark.parametrize("fields, text", [
    ({"scope": "general_consumer"}, "敏感肌宣称需要评价依据。"),
    ({}, "非具体商品依据：敏感肌宣称需要评价依据。"),
])
@pytest.mark.parametrize("body", [
    "这款适合敏感肌。",
    "这款不含酒精。",
    "这款具有修护功效。",
    "不能确认适合敏感肌，但它不含酒精。",
    "这款成分未知，不过它具有保湿功效。",
])
def test_general_knowledge_cannot_prove_specific_product_assertions(fields, text, body):
    source = GroundingSource(source_id="k1", kind="knowledge", subject_id="general",
                             label="通用消费资料", text=text, fields=fields)
    issues = validate_claims(body, [GroundingClaim(text=body, source_refs=["k1"])], {"k1": source})
    assert "商品成分、功效或适用性未有明确知识依据" in issues


@pytest.mark.parametrize("body", [
    "敏感肌适用性宣称需要评价依据。",
    "功效宣称需要相应的科学依据。",
    "目前不能确认这款适合敏感肌。",
    "这款商品的功效未知。",
])
def test_general_explanations_and_unknown_product_information_remain_allowed(body):
    source = GroundingSource(source_id="k1", kind="knowledge", subject_id="general",
                             label="通用消费资料", text="非具体商品依据：" + body,
                             fields={"scope": "general_consumer"})
    assert not validate_claims(body, [GroundingClaim(text=body, source_refs=["k1"])], {"k1": source})


def test_specific_product_evidence_is_not_treated_as_general_knowledge():
    source = GroundingSource(source_id="k1", kind="knowledge", subject_id="product1",
                             label="测试专属商品资料", text="该产品保湿功效已提供评价依据。",
                             fields={"scope": "document_context"})
    body = "这款具有保湿功效。"
    assert not validate_claims(body, [GroundingClaim(text=body, source_refs=["k1"])], {"k1": source})


def test_claim_repair_points_to_the_reply_not_a_paraphrase_or_knowledge_quote():
    source = order()
    body = "订单111111已发货。"
    claims = [GroundingClaim(text="订单111111已经发货", source_refs=[source.source_id])]
    issues = validate_claims(body, claims, {source.source_id: source})
    assert any("第1条claims.text" in issue and "从body复制连续原文" in issue for issue in issues)
    exact = [GroundingClaim(text=body, source_refs=[source.source_id])]
    assert not validate_claims(body, exact, {source.source_id: source})


def test_missing_reference_feedback_identifies_the_claim_and_exact_invalid_id():
    body = "我先核对记录。"
    issues = validate_claims(body, [GroundingClaim(text=body, source_refs=["message:wrong-id"])], {})
    assert any("第1条claims.source_refs" in issue and "message:wrong-id" in issue for issue in issues)


def test_completion_of_work_order_never_proves_delivery_or_reship_action():
    source = GroundingSource(
        source_id="w1", kind="work_order", subject_id="order-1", label="补发工单",
        text="工单状态：已完结", fields={"sourceStatus": "已完结"},
    )
    body = "补发包裹已签收。"
    issues = validate_claims(body, [GroundingClaim(text=body, source_refs=["w1"])], {"w1": source})
    assert any("已签收" in issue and "工单完结不等于" in issue for issue in issues)
    body = "补发工单记录已完结，签收情况需另行核对。"
    assert not validate_claims(body, [GroundingClaim(text=body, source_refs=["w1"])], {"w1": source})


@pytest.mark.parametrize("body", [
    "不代表包裹已签收或问题已解决。",
    "不能确认补发包裹已签收，也无法证明问题已经解决。",
    "工单记录完结不等于补发包裹已签收或消费者的问题已经解决。",
    "所以我不能直接说已经签收。",
    "所以不能据此说补发已经签收。",
    "不能因此直接认定包裹已经签收。",
    "无法确定是否已经签收。",
    "不能肯定问题已经解决。",
])
def test_bounded_negative_status_explanations_are_not_misread_as_positive_facts(body):
    source = GroundingSource(source_id="w1", kind="work_order", subject_id="c1",
                             label="补发工单", text="工单状态：已完结",
                             fields={"sourceStatus": "已完结"})
    assert not validate_claims(body, [], {"w1": source})
    assert not validate_claims(body, [GroundingClaim(text=body, source_refs=["w1"])], {"w1": source})


@pytest.mark.parametrize("body", [
    "工单完结不代表问题已解决，但包裹已签收。",
    "不能确认是否已退款，不过问题已解决。",
    "不代表包裹已签收，问题已经解决。",
])
def test_negative_status_does_not_exempt_a_new_positive_clause(body):
    source = GroundingSource(source_id="w1", kind="work_order", subject_id="c1",
                             label="工单", text="工单状态：已完结",
                             fields={"sourceStatus": "已完结"})
    assert validate_claims(body, [], {"w1": source})
    assert validate_claims(body, [GroundingClaim(text=body, source_refs=["w1"])], {"w1": source})


def test_status_claim_fragment_keeps_the_qualification_from_the_actual_reply():
    source = GroundingSource(source_id="w1", kind="work_order", subject_id="c1",
                             label="工单", text="工单状态：已完结",
                             fields={"sourceStatus": "已完结"})
    body = "目前不能确认补发包裹已签收。"
    claim = GroundingClaim(text="补发包裹已签收", source_refs=["w1"])
    assert not validate_claims(body, [claim], {"w1": source})
    body += "不过补发包裹已签收。"
    assert validate_claims(body, [claim], {"w1": source})


def test_source_display_uses_human_local_status_without_rewriting_the_raw_fields():
    fields = {"ticketId": "ticket-1", "localStatus": "resolved"}
    assert "本地跟进完结" in _flatten(fields)
    assert "resolved" not in _flatten(fields)
    assert fields["localStatus"] == "resolved"
    assert any("waiting_internal" in issue for issue in validate_claims("状态为waiting_internal。", [], {}))


@pytest.mark.parametrize("body", [
    "我查了已有记录：补发工单记录为已完结。",
    "我按已有记录说明：补发单号需与原单区分。",
    "我核对了已有的补发记录，签收情况仍未知。",
    "我说明已完结工单：补发包裹签收情况需核对。",
])
def test_reading_existing_reship_records_is_not_execution_of_a_reship(body):
    assert not validate_claims(body, [], {})


@pytest.mark.parametrize("body", [
    "我已经为您补发。",
    "我已给您退款。",
    "我们会立即给您打款。",
    "我现在替您换货。",
    "我这就给您赔付。",
    "我查了已有记录：我会给您退款。",
])
def test_actual_after_sales_execution_claims_remain_blocked(body):
    assert validate_claims(body, [], {})


def test_dialogue_fields_do_not_repeat_declined_customer_actions():
    draft = GroundedDraft(
        reply_suggestions=[{"style": "recommended", "body": "我先核对资料。"}],
        missing_information=["是否已尝试清洁泵头出口", "按压时是否有回弹或异响"],
        next_steps=["请再按几次确认", "提供订单号"],
    )
    issues = validate_dialogue_fields(
        draft,
        ["我已经解锁并按压十次，还是没有出来。不要再让我解锁或再按几次，只梳理还缺什么资料。"],
    )
    assert len(issues) == 2
    assert all("不要求消费者再次操作" in issue for issue in issues)


def test_dialogue_fields_can_request_descriptive_facts_after_declined_actions():
    draft = GroundedDraft(
        reply_suggestions=[{"style": "recommended", "body": "我先核对资料。"}],
        missing_information=["按压时是否有回弹或异响", "订单号"],
        next_steps=["核对已有售后记录"],
    )
    assert not validate_dialogue_fields(
        draft,
        ["解锁和按压都试过了，不要再让我重复操作，只帮我梳理还缺什么资料。"],
    )


def test_explicit_customer_concern_cannot_be_saved_only_as_known():
    source = GroundingSource(
        source_id="m1", kind="customer_message", subject_id="c1",
        label="消费者自述", text="我更在意粉底服帖。",
    )
    item = MemoryItem(category="known", source_ref="m1", quote="我更在意粉底服帖")
    issues = validate_memory([item], {"m1": source})
    assert any("归入concern" in issue for issue in issues)


@pytest.mark.parametrize("body", [
    "目前目录里没有测试化妆海绵的记录。",
    "商品库没有这款商品记录。",
])
def test_non_exhaustive_search_cannot_claim_whole_catalog_absence(body):
    issues = validate_claims(body, [], {})
    assert any("不是全目录盘点" in issue for issue in issues)


def test_bounded_search_absence_is_allowed_when_scope_is_explicit():
    body = "本次检索未找到测试化妆海绵的资料，不能确认目录中是否存在对应记录。"
    assert not validate_claims(body, [], {})


@pytest.mark.parametrize("body", [
    "您想问目录里有没有测试化妆海绵的记录，本次检索未找到对应资料。",
    "目录中是否没有相关记录，我目前无法确认。",
    "无法确认目录中不存在相关记录。",
    "不能据此确认商品库没有这个商品记录。",
])
def test_catalog_question_or_uncertainty_is_not_a_whole_catalog_absence_assertion(body):
    assert not validate_claims(body, [], {})


@pytest.mark.parametrize("body", [
    "无法确认其他信息，但目录里没有测试化妆海绵的记录。",
    "目录里有没有记录需要核对。不过商品库没有这款商品记录。",
    "不能确认目录是否存在其他记录，目录里没有这款商品记录。",
])
def test_catalog_uncertainty_does_not_exempt_a_later_absence_assertion(body):
    assert any("不是全目录盘点" in issue for issue in validate_claims(body, [], {}))


@pytest.mark.parametrize("body, cited", [
    ("谢谢您确认之前的问题已解决。", "之前的问题已解决"),
    ("您已经确认该咨询已解决，我不再追问旧咨询。", "该咨询已解决"),
])
def test_customer_confirmed_resolution_is_attributed_using_the_actual_reply_context(body, cited):
    source = GroundingSource(source_id="m1", kind="customer_message", subject_id="c1",
                             label="消费者自述", text="之前的问题已经解决，不用再跟进。")
    assert not validate_claims(
        body, [GroundingClaim(text=cited, source_refs=["m1"])], {"m1": source},
    )


@pytest.mark.parametrize("body, source_text", [
    ("您确认咨询已解决。现在所有售后问题已解决。", "之前的问题已解决。"),
    ("您确认咨询已解决。", "不能确认咨询已解决。"),
    ("您确认咨询已解决。", "咨询不是已解决，还需要跟进。"),
])
def test_attributed_resolution_cannot_prove_another_clause_or_negated_customer_statement(body, source_text):
    source = GroundingSource(source_id="m1", kind="customer_message", subject_id="c1",
                             label="消费者自述", text=source_text)
    assert validate_claims(
        body, [GroundingClaim(text=body, source_refs=["m1"])], {"m1": source},
    )


@pytest.mark.parametrize("latest, rejected", [
    ("我愿意继续排查操作，请重新指导。", False),
    ("我同意继续尝试操作。", False),
    ("我不愿意继续排查，请只核对资料。", True),
    ("我愿意继续排查，但不要让我重复操作。", True),
])
def test_dialogue_fields_follow_the_latest_explicit_choice(latest, rejected):
    draft = GroundedDraft(
        reply_suggestions=[{"style": "recommended", "body": "我先核对。"}],
        next_steps=["请再按几次确认"],
    )
    assert bool(validate_dialogue_fields(draft, ["不要让我重复操作。", latest])) is rejected


def test_a_negative_next_step_does_not_ask_the_consumer_to_repeat_an_action():
    draft = GroundedDraft(
        reply_suggestions=[{"style": "recommended", "body": "我先核对。"}],
        next_steps=["不要再按几次，也不用清洁泵头出口，只核对订单号"],
    )
    assert not validate_dialogue_fields(draft, ["不要让我再折腾，只梳理资料。"])


def test_unsafe_guarantee_feedback_offers_a_bounded_explanation_without_relaxing_the_gate():
    for body in ["它绝对安全。", "我不能说它绝对安全。"]:
        issues = validate_claims(body, [], {})
        assert any("不复述确定安全保证" in issue for issue in issues)


def test_repeated_cited_identifier_can_be_used_as_a_locator_without_reciting_the_same_claim():
    source = order()
    body = "订单111111已发货。您可以凭订单111111继续核对已有记录。"
    claims = [GroundingClaim(text="订单111111已发货。", source_refs=[source.source_id])]
    assert not validate_claims(body, claims, {source.source_id: source})
    for suffix in ["另一单222222也可核对。", "订单111111已签收。", "订单111111实付20元。"]:
        assert validate_claims("订单111111已发货。" + suffix, claims, {source.source_id: source})


@pytest.mark.parametrize("body", ["我已经为您退款。", "我保证明天到账。", "这是过敏。"])
def test_unauthorized_actions_and_medical_diagnosis_are_rejected(body):
    assert validate_claims(body, [], {})


def test_memory_requires_exact_source_quotes_and_does_not_diagnose_a_person():
    source = GroundingSource(source_id="m1", kind="customer_message", subject_id="c1",
                             label="消费者自述", text="我是干皮，泵头已经按了两次还是没用。")
    assert not validate_memory([MemoryItem(category="known", source_ref="m1", quote="我是干皮")], {"m1": source})
    assert validate_memory([MemoryItem(category="known", source_ref="m1", quote="我是油皮")], {"m1": source})
    assert validate_memory([MemoryItem(category="known", source_ref="missing", quote="我是干皮")], {"m1": source})


def test_general_knowledge_is_not_personal_memory():
    source = GroundingSource(source_id="k1", kind="knowledge", subject_id="p1",
                             label="一般知识", text="敏感肌需要注意使用感受。")
    item = MemoryItem(category="known", source_ref="k1", quote=source.text)
    assert validate_memory([item], {"k1": source})


@pytest.mark.parametrize("kind", ["staff_message", "order", "work_order", "followup"])
def test_attempted_memory_is_a_consumer_action_not_a_staff_promise_or_record_state(kind):
    source = GroundingSource(source_id="s1", kind=kind, subject_id="c1",
                             label="记录", text="已创建工单，明天会处理")
    item = MemoryItem(category="attempted", source_ref="s1", quote="已创建工单")
    assert any("消费者本人自述" in issue for issue in validate_memory([item], {"s1": source}))
    consumer = source.model_copy(update={"kind": "customer_message", "text": "我已经按了十次"})
    item = MemoryItem(category="attempted", source_ref="s1", quote="我已经按了十次")
    assert not validate_memory([item], {"s1": consumer})


def test_citing_two_orders_does_not_transfer_the_second_orders_status():
    a, b = order(status="已发货"), order("222222", status="已签收")
    body = "订单111111已签收。"
    assert validate_claims(body, [GroundingClaim(text=body, source_refs=[a.source_id, b.source_id])],
                           {s.source_id: s for s in [a, b]})


@pytest.mark.parametrize("body, accepted", [
    ("订单111111实付100元。", True), ("订单111111单价50元。", True),
    ("订单111111单价100元。", False), ("订单111111退款100元。", False),
    ("订单111111退款金额20元，待审核。", True),
])
def test_amounts_match_the_named_field_not_any_number_in_the_source(body, accepted):
    source = order(amount="100")
    source.fields["unitPrice"] = "50"
    refund = GroundingSource(source_id="w1", kind="work_order", subject_id="111111",
                             label="退款工单", text="退款金额20元", fields={"orderId": "111111", "refundAmount": "20"})
    issues = validate_claims(body, [GroundingClaim(text=body, source_refs=[source.source_id, "w1"])],
                             {source.source_id: source, "w1": refund})
    assert (not issues) is accepted


@pytest.mark.parametrize("body, accepted", [
    ("订单111111于2026-05-01下单。", True),
    ("订单111111于2026-05-03发货。", True),
    ("订单111111于2026-05-01发货。", False),
])
def test_dates_match_the_named_event_not_an_unrelated_time(body, accepted):
    source = order()
    source.fields.update({"orderedAt": "2026-05-01", "shippedAt": "2026-05-03"})
    source.text += "\n发货时间：2026-05-03"
    issues = validate_claims(body, [GroundingClaim(text=body, source_refs=[source.source_id])],
                             {source.source_id: source})
    assert (not issues) is accepted
