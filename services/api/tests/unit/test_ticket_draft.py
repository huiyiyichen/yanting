"""工作台内建工单预填（P1-4），规则抽取，不调模型。先列失败方式：
K1 预填字段没有原话来源，或来源不是消费者本人发言。
K2 没有依据的字段被填上默认值（如“是否就医=否”）。应留空/unknown。
K3 否定表达被抽成肯定：“没去医院”不是已就医，“还在用”不是已停用。
K4 工单类型判断：脸肿/起疹 -> 不良反应；空包/漏发 -> 补发换货；退款没到账 -> 线下打款；物流不动 -> 物流；退货 -> 售后退货。
K5 多个诉求同时出现时安全优先：不良反应优先于其他类型。
K6 客服/AI 发言里的症状描述被当成消费者自述。
"""

import pytest

from app.domain.consumer_service.ticket_draft import draft_ticket


def msgs(*bodies, role="customer"):
    return [(role, f"message:c:{i}", body) for i, body in enumerate(bodies)]


def test_k1_k6_adverse_fields_cite_customer_words_only():
    draft = draft_ticket([*msgs("前天用了B5面膜，两颊又红又痒", "现在脸肿了，已经去医院了，也停用了"), ("assistant", "message:c:9", "亲，额头起疹的话建议停用")])
    assert draft.work_order_type == "adverse_reaction"
    fields = {item.field: item for item in draft.fields}
    assert fields["symptomDescription"].source_ref in {"message:c:0", "message:c:1"}
    assert fields["affectedArea"].value == "两颊" and fields["affectedArea"].source_ref == "message:c:0"
    assert fields["soughtMedicalCare"].value == "yes" and fields["stoppedUse"].value == "yes"
    assert all(item.source_ref != "message:c:9" for item in draft.fields)


def test_k2_no_basis_means_empty():
    draft = draft_ticket(msgs("用了以后脸有点红"))
    fields = {item.field: item.value for item in draft.fields}
    assert "soughtMedicalCare" not in fields and "stoppedUse" not in fields and "productBatchNo" not in fields


@pytest.mark.parametrize("body,field,value", [
    ("脸红了但还没去医院", "soughtMedicalCare", "no"),
    ("脸红，不过我还在用", "stoppedUse", "no"),
])
def test_k3_negations(body, field, value):
    fields = {item.field: item.value for item in draft_ticket(msgs(body)).fields}
    assert fields[field] == value


@pytest.mark.parametrize("body,kind", [
    ("箱子打开是空的，空包裹", "reship_exchange"),
    ("说好的退款一个礼拜了还没到账", "offline_payment"),
    ("物流三天没动了", "logistics"),
    ("我要退货", "return_refund"),
])
def test_k4_type_inference(body, kind):
    assert draft_ticket(msgs(body)).work_order_type == kind


def test_k5_safety_first():
    assert draft_ticket(msgs("物流好慢", "收到用了起疹子")).work_order_type == "adverse_reaction"


def test_no_signal_returns_no_type():
    assert draft_ticket(msgs("你好在吗")).work_order_type is None
