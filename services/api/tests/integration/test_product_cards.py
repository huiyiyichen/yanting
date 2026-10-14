"""商品卡与客户发送商品卡（P1-4），经 HTTP 验收。先列失败方式：
F1 客户端自带的商品名、图片被原样采信（应只收 SKU 或订单号，名称与图片由服务端取）。
F2 目录外 SKU、或不属于本会话的订单号也能发出（跨客户泄露订单）。
F3 只发商品卡就触发模型回复（空输入），或被当成图片转人工。
F4 客户侧可选项或消息带出内部信息（实付、状态、物流、风险等）。
F5 客服顶部商品卡来源优先级错误：最新商品卡消息应优先于关联订单，都没有时不显示。
F6 同一幂等键重复提交生成第二张卡。
F7 Agent 上下文看不到消费者正在咨询的商品。
F8 正文、附件、商品都为空的消息仍被接受。
F9 旧库缺少新列时无法启动（需自动补列）。
"""

from sqlalchemy import create_engine, text
from tests.integration import test_reception_workspace as fixtures

from app.knowledge.reference_products import seed_reference_products

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER
SKU = "LRLWX26013"
ORDER = "6920947277927059788"  # 官方订单，属于 S00038


def seeded(workspace):
    client, factory, provider = workspace
    with factory() as session:
        seed_reference_products(session)
        session.commit()
    return client, factory, provider


def send(client, cid, key, **payload):
    return client.post(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER,
                       json={"clientMessageKey": key, **payload})


def test_customer_sends_catalog_card_server_derived(workspace):
    client, factory, provider = seeded(workspace)
    cid = fixtures._create(client)
    options = client.get(f"/api/customer/conversations/{cid}/product-options", headers=CUSTOMER)
    assert options.status_code == 200, options.text
    item = next(o for o in options.json() if o["sku"] == SKU)
    assert set(item) <= {"source", "sku", "name", "imageUrl", "orderId"}  # F4
    forged = send(client, cid, "card-0", product={"sku": SKU, "name": "伪造名", "imageUrl": "https://evil/x.png"})
    assert forged.status_code == 422  # F1：只收 SKU 或订单号
    sent = send(client, cid, "card-1", product={"sku": SKU})
    assert sent.status_code == 200, sent.text
    card = sent.json()["message"]["productCard"]
    assert card["name"] == item["name"]
    assert card["imageUrl"] == item["imageUrl"]
    again = send(client, cid, "card-1", product={"sku": SKU})
    assert again.json()["created"] is False  # F6
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert sum(1 for m in messages if m.get("productCard")) == 1
    assert provider.calls == []  # F3：只发卡片不调模型
    with factory() as session:
        from sqlalchemy import select

        from app.domain.consumer_service.models import AutoReplyJobRow
        assert session.scalars(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid)).first() is None


def test_rejects_unknown_sku_foreign_order_and_empty(workspace):
    client, _, _ = seeded(workspace)
    cid = fixtures._create(client)
    assert send(client, cid, "k1", product={"sku": "NOT-A-SKU"}).status_code == 422  # F2
    assert send(client, cid, "k2", product={"orderId": ORDER}).status_code == 422  # F2
    assert send(client, cid, "k3", body="  ").status_code == 422  # F8
    assert send(client, cid, "k4", product={}).status_code == 422


def test_linked_order_option_and_desk_header_priority(workspace):
    client, factory, _ = seeded(workspace)
    cid = fixtures._create(client)
    assert client.get(f"/api/support/reception/{cid}/product-card", headers=SUPPORT).json() is None  # F5
    fixtures._send(client, cid, f"订单{ORDER}什么时候到", key="m1")
    options = client.get(f"/api/customer/conversations/{cid}/product-options", headers=CUSTOMER).json()
    order_option = next(o for o in options if o.get("orderId") == ORDER)
    assert order_option["source"] == "order" and "paidAmountMinor" not in order_option  # F4
    header = client.get(f"/api/support/reception/{cid}/product-card", headers=SUPPORT).json()
    assert header["source"] == "order" and header["orderId"] == ORDER
    assert header["paidAmountMinor"] == 25900 and header["carrier"] == "圆通快递" and header["city"] == "苏州市"
    sent = send(client, cid, "card-2", product={"sku": SKU})
    assert sent.status_code == 200, sent.text
    header = client.get(f"/api/support/reception/{cid}/product-card", headers=SUPPORT).json()
    assert header["source"] == "message" and header["sku"] == SKU and header["imageUrl"]
    order_card = send(client, cid, "card-3", product={"orderId": ORDER})
    assert order_card.status_code == 200, order_card.text
    header = client.get(f"/api/support/reception/{cid}/product-card", headers=SUPPORT).json()
    assert header["source"] == "message" and header["orderId"] == ORDER and header["status"] == "交易成功"
    assert client.get(f"/api/support/reception/{cid}/product-card", headers=CUSTOMER).status_code in {401, 403}
    desk_messages = client.get(f"/api/support/reception/{cid}/messages", headers=SUPPORT).json()
    assert desk_messages[-1]["productCard"]["orderId"] == ORDER
    with factory() as session:  # F7
        from app.repositories.consumer_service import ConsumerServiceRepository
        context = ConsumerServiceRepository(session).context(cid)
        cards = [e.message for e in context.timeline if e.message and e.message.content_type == "product_card"]
        assert len(cards) == 2 and "欧莱雅金致小蜜罐" in (cards[0].body or "")


def test_old_database_gets_column(tmp_path):
    from app.domain.case_state.models import migrate_message_table

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'old.sqlite3'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE message (message_id VARCHAR(64) PRIMARY KEY, body TEXT)")
    migrate_message_table(engine)
    migrate_message_table(engine)  # 幂等
    with engine.connect() as connection:
        columns = [row[1] for row in connection.execute(text("PRAGMA table_info(message)"))]
    assert "product_card_json" in columns
