"""风险看板数据能力（改进方案 P1-6），官方数据经 HTTP 验收。

先列失败方式：
O1 事件数与信号数混用：信号逐条规则命中，事件按风险事件合并，必须分开计数。
O2 官方范围混入本地会话产生的风险，或实时范围混入官方历史。
O3 情绪分布小时桶不按 UTC+8 分桶，或把客服/系统消息计入消费者情绪。
O4 情绪分布未标明情绪来源（规则或模型），被误读为模型结果。
O5 商品风险线索把批次“00”当真实批次，或把不同批次写成同批次聚集。
O6 商品线索排序分不是 不良反应×3 + 就医×5 + 其他工单×1；阈值外商品被返回。
O7 商品线索给出质量结论文字（只允许计数与原始记录入口）。
O8 读取看板触发模型调用或写库。
"""

from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def test_overview_counts_and_hourly_distribution(workspace):
    client, _, provider = workspace
    client.post("/api/support/desk/risks/scan", headers=SUPPORT)
    before = len(provider.calls)
    official = client.get("/api/support/desk/risks/overview?scope=official", headers=SUPPORT)
    assert official.status_code == 200, official.text
    view = official.json()
    assert view["scope"] == "official"
    assert view["counts"]["signals"] >= view["counts"]["events"] > 0
    assert sum(view["levels"].values()) == view["counts"]["signals"]
    assert view["types"]["adverse_reaction"] == 10
    assert view["emotionSource"] == "rule"
    hours = view["hourly"]
    assert all(8 <= bucket["hour"] <= 23 for bucket in hours)
    total = sum(b["calm"] + b["dissatisfied"] + b["angry"] for b in hours)
    assert total == view["customerMessages"]
    assert 0 < total <= 487
    assert view["highRiskMarkers"] and all(m["conversationId"].startswith("S") for m in view["highRiskMarkers"])
    live = client.get("/api/support/desk/risks/overview?scope=live", headers=SUPPORT).json()
    assert live["counts"]["signals"] == 0 and live["customerMessages"] == 0
    assert len(provider.calls) == before


def test_product_clues_from_official_work_orders(workspace):
    client, _, _ = workspace
    response = client.get("/api/support/desk/risks/product-clues", headers=SUPPORT)
    assert response.status_code == 200, response.text
    clues = {item["productName"]: item for item in response.json()}
    b5 = clues["测试B5多效修护面膜20片"]
    assert b5["adverseReactions"] == 3 and b5["medicalVisits"] == 1
    assert sorted(b5["batches"]) == ["26A05", "26A18", "未记录"]
    assert b5["score"] == 3 * 3 + 5 * 1 + b5["otherTickets"]
    assert all(item["adverseReactions"] >= 2 or item["relatedTickets"] >= 5 for item in clues.values())
    scores = [item["score"] for item in response.json()]
    assert scores == sorted(scores, reverse=True)
    assert set(b5) == {"productName", "adverseReactions", "medicalVisits", "batches", "relatedTickets",
                       "otherTickets", "abnormalReturns", "score", "workOrderIds"}
