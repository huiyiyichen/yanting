from app.domain.consumer_service.reply_policy import (
    normalize_customer_terms,
    validate_customer_reply,
)
from app.schemas.grounding import GroundingSource


def test_internal_ticket_presentation_is_not_customer_facing():
    source = GroundingSource(
        source_id="w1", kind="work_order", subject_id="123456",
        label="补发记录", text="已完结",
        fields={"workOrderId": "BH450849382497"},
    )
    for body in (
        "该工单已完结，本地跟进也已完结。",
        "补发编号BH450849382497，快递为韵达。",
        "以上仅为已有订单记录核对，未查询实时物流，也未执行任何售后操作。",
    ):
        assert validate_customer_reply(body, {"w1": source})


def test_short_honest_answers_do_not_need_capability_disclaimers():
    for body in (
        "亲，这单实付1598元，每支799元。",
        "目前还没有查到补发包裹的签收信息，韵达单号是463458174220690。",
        "不客气亲~",
        "亲，物流这边还没更新，您可以点快递单号查最新进度哦。",
    ):
        assert validate_customer_reply(body, {}) == []


def test_customer_terms_are_translated_before_delivery():
    assert normalize_customer_terms("留意 oil-free 或 non-comedogenic 标签") == "留意 无油配方 或 不易堵塞毛孔 标签"
    assert normalize_customer_terms("是否标注oil-free或noncomedogenic这几个方向") == "是否标注无油配方或不易堵塞毛孔这几个方向"


def test_product_follow_up_asks_for_the_next_useful_detail():
    assert validate_customer_reply("孕期能不能用我这边没法确认，所以不好直接给您推荐具体哪款。", {})
    assert validate_customer_reply("商品资料里没有成分和适用性信息。", {})
    assert validate_customer_reply("亲，麻烦您拍下包装上的成分表，我帮您一起看看哦。", {}) == []
    assert validate_customer_reply("亲，您平时洗完脸会紧绷，还是容易出油呀？", {}) == []
