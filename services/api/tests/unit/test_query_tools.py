"""结构化查询工具测试。

重点覆盖「四种状态不得互相替代」（工程规范第 5.4 节）与 AC-18/AC-19/AC-20：
- 订单未命中 ≠ 非授权；
- 查询失败 ≠ 非授权；
- 多个候选不得任选其一；
- 国家缺失不得跨国家匹配；
- 卖家原始名与标准名分开保存，无唯一匹配时标准名为空。
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.after_sales import fixtures
from app.domain.enums import DealerAuthorizationStatus, WarrantyStatus
from app.tools import query_tools


class TestOrderLookup:
    def test_find_by_customer(self) -> None:
        result = query_tools.order_lookup(customer_id="CUST-DEMO-01")
        assert result.ok
        orders = result.data["orders"]
        assert len(orders) == 2
        assert {item["orderId"] for item in orders} == {"ORD-DEMO-1001", "ORD-DEMO-1002"}

    def test_order_not_found_is_not_a_negative_authorization(self) -> None:
        """AC-18：订单未命中必须如实报告，且提示这不等于非授权。"""

        result = query_tools.order_lookup(order_id="ORD-DOES-NOT-EXIST")
        assert result.status == "not_found"
        assert "不等于非授权" in result.message

    def test_requires_at_least_one_selector(self) -> None:
        result = query_tools.order_lookup()
        assert result.status == "invalid_argument"

    def test_masked_order_number_lookup(self) -> None:
        result = query_tools.order_lookup(order_no_masked="SO-2026-****-1001")
        assert result.ok
        assert result.data["orders"][0]["orderId"] == "ORD-DEMO-1001"

    def test_order_exposes_both_seller_names(self) -> None:
        """AC-19：原始值与标准值必须都能读到。"""

        result = query_tools.order_lookup(order_id="ORD-DEMO-1002")
        order = result.data["orders"][0]
        assert order["sellerNameRaw"] == "星海数码专营店"
        assert order["sellerNameStandard"] == "星海数码专营店"


class TestProductLookup:
    def test_same_model_name_returns_multiple_candidates(self) -> None:
        """AC-03：同名型号必须作为多候选返回，不得擅自选定。"""

        result = query_tools.product_lookup(product_model="A1 Pro")
        assert result.ok
        assert result.data["requiresDisambiguation"] is True
        assert result.data["candidateCount"] >= 2
        categories = {item["productCategory"] for item in result.data["candidates"]}
        assert {"robot_vacuum", "stick_vacuum"} <= categories

    def test_unknown_model_reports_not_found(self) -> None:
        result = query_tools.product_lookup(product_model="Z9 Ultra")
        assert result.status == "not_found"

    def test_name_recall_returns_scored_candidates(self) -> None:
        result = query_tools.product_lookup(query="我的 A1 Pro 不吸了")
        assert result.ok
        assert result.data["requiresDisambiguation"] is True
        for item in result.data["candidates"]:
            assert "matchScore" in item

    def test_no_recall_returns_empty_not_error(self) -> None:
        result = query_tools.product_lookup(query="完全无关的内容 xyzzy")
        assert result.status == "empty"


class TestDealerLookup:
    def test_unique_match_is_authorized(self) -> None:
        result = query_tools.dealer_lookup(seller_name_raw="星海数码专营店", country_code="CN")
        assert result.ok
        assert result.data["authorizationStatus"] == DealerAuthorizationStatus.AUTHORIZED.value
        assert result.data["sellerNameStandard"] == "星海数码专营店"

    def test_multiple_close_candidates_are_not_resolved_arbitrarily(self) -> None:
        """卖家名同时指向多家店铺时必须返回 multiple_matches，不得任选其一。

        `星海数码` 同时是 DLR-CN-001 的别名与 DLR-CN-003/DLR-CN-004 品牌前缀，
        实测最佳 100、次佳 80（差距 20 < 间距 25），属于真实歧义。
        """

        result = query_tools.dealer_lookup(seller_name_raw="星海数码", country_code="CN")
        assert (
            result.data["authorizationStatus"] == DealerAuthorizationStatus.MULTIPLE_MATCHES.value
        )
        assert result.data["candidateCount"] > 1
        # 多候选时不得给出标准名
        assert result.data["sellerNameStandard"] is None
        assert result.status == "conflict"

    def test_specific_name_resolves_to_single_match(self) -> None:
        """足够具体的名称应唯一命中，避免把清晰输入也变成追问。"""

        result = query_tools.dealer_lookup(seller_name_raw="星海数码旗舰店", country_code="CN")
        assert result.data["authorizationStatus"] == DealerAuthorizationStatus.AUTHORIZED.value
        assert result.data["sellerNameStandard"] == "星海数码旗舰店"

    def test_explicit_non_authorized_record(self) -> None:
        result = query_tools.dealer_lookup(seller_name_raw="QuickBuy Deals", country_code="US")
        assert result.data["authorizationStatus"] == DealerAuthorizationStatus.NOT_AUTHORIZED.value

    def test_unknown_seller_is_unknown_not_non_authorized(self) -> None:
        result = query_tools.dealer_lookup(
            seller_name_raw="完全没听过的店铺名称", country_code="CN"
        )
        assert result.data["authorizationStatus"] == DealerAuthorizationStatus.UNKNOWN.value
        assert "不能判定为非授权" in result.data["note"] or "复核" in result.data["note"]
        assert result.data["sellerNameStandard"] is None

    def test_missing_country_does_not_cross_match(self) -> None:
        """国家缺失时不得跨国匹配，即使卖家名与某国记录高度相似。"""

        result = query_tools.dealer_lookup(seller_name_raw="Nordwind Technik GmbH")
        assert result.data["authorizationStatus"] == DealerAuthorizationStatus.UNKNOWN.value
        assert "国家" in result.data["note"]

    def test_country_isolation_prevents_cross_border_match(self) -> None:
        """德国授权经销商在美国国家下不得命中。"""

        result = query_tools.dealer_lookup(
            seller_name_raw="Nordwind Technik GmbH", country_code="US"
        )
        assert result.data["authorizationStatus"] != DealerAuthorizationStatus.AUTHORIZED.value

    def test_raw_name_is_preserved(self) -> None:
        result = query_tools.dealer_lookup(seller_name_raw="  星海数码专营店  ", country_code="CN")
        assert result.data["sellerNameRaw"] == "星海数码专营店"

    def test_invalid_channel_is_rejected(self) -> None:
        result = query_tools.dealer_lookup(
            seller_name_raw="星海数码专营店", country_code="CN", purchase_channel="not_a_channel"
        )
        assert result.status == "invalid_argument"


class TestWarrantyEvaluate:
    def test_in_warranty(self) -> None:
        result = query_tools.warranty_evaluate(order_id="ORD-DEMO-1004", on_date="2026-06-01")
        assert result.ok
        assert result.data["warrantyStatus"] == WarrantyStatus.IN_WARRANTY.value
        assert result.data["expiresOn"] == "2028-04-08"

    def test_out_of_warranty(self) -> None:
        result = query_tools.warranty_evaluate(order_id="ORD-DEMO-1005", on_date="2026-06-01")
        assert result.data["warrantyStatus"] == WarrantyStatus.OUT_OF_WARRANTY.value

    def test_order_not_found_yields_unknown_not_expired(self) -> None:
        """订单查不到时不得判定过保。"""

        result = query_tools.warranty_evaluate(order_id="ORD-DOES-NOT-EXIST")
        assert result.status == "not_found"
        assert result.data["warrantyStatus"] == WarrantyStatus.UNKNOWN.value
        assert "不得据此判定过保" in result.message

    def test_invalid_date_is_rejected(self) -> None:
        result = query_tools.warranty_evaluate(order_id="ORD-DEMO-1001", on_date="not-a-date")
        assert result.status == "invalid_argument"


class TestFixtureIntegrity:
    def test_candidates_do_not_mutate_source_orders(self) -> None:
        """AC-20：候选选择不得改变源订单。工具只能读，不能写。"""

        before = [
            (
                item.order_id,
                item.product_id,
                item.purchased_at,
                item.seller_name_raw,
            )
            for item in fixtures.load_orders()
        ]
        query_tools.product_lookup(product_model="A1 Pro")
        query_tools.dealer_lookup(seller_name_raw="星海数码专营店", country_code="CN")
        after = [
            (
                item.order_id,
                item.product_id,
                item.purchased_at,
                item.seller_name_raw,
            )
            for item in fixtures.load_orders()
        ]
        assert before == after

    def test_orders_contain_no_real_pii(self) -> None:
        """AC-17 子集：夹具不得包含完整订单号、手机号或地址。"""

        import json
        import re
        from pathlib import Path

        from app.config import REPO_ROOT

        raw = (REPO_ROOT / "data" / "fixtures" / "orders" / "orders.json").read_text(
            encoding="utf-8"
        )
        payload = json.loads(raw)
        for order in payload["orders"]:
            assert "****" in order["order_no_masked"], "订单号必须掩码"
            joined = json.dumps(order, ensure_ascii=False)
            assert not re.search(r"1[3-9]\d{9}", joined), "不得出现手机号"
            assert "地址" not in joined
            assert "phone" not in joined.lower()
        del Path

    def test_warranty_month_boundary(self) -> None:
        order = fixtures.find_order("ORD-DEMO-1001")
        assert order is not None
        assert order.warranty_months == 24
        # 购买日 2026-03-12，24 个月后为 2028-03-12
        evaluation = fixtures.evaluate_warranty(order, on_date=date(2028, 3, 12))
        assert evaluation.status is WarrantyStatus.IN_WARRANTY
        assert evaluation.days_remaining == 0
        assert (
            fixtures.evaluate_warranty(order, on_date=date(2028, 3, 13)).status
            is WarrantyStatus.OUT_OF_WARRANTY
        )


@pytest.mark.parametrize(
    ("seller", "country", "expected"),
    [
        ("星海数码专营店", "CN", DealerAuthorizationStatus.AUTHORIZED),
        ("QuickBuy Deals", "US", DealerAuthorizationStatus.NOT_AUTHORIZED),
        ("星海数码", "CN", DealerAuthorizationStatus.MULTIPLE_MATCHES),
        ("无记录卖家", "CN", DealerAuthorizationStatus.UNKNOWN),
        ("星海数码专营店", "US", DealerAuthorizationStatus.UNKNOWN),
    ],
)
def test_dealer_status_matrix(
    seller: str, country: str, expected: DealerAuthorizationStatus
) -> None:
    result = query_tools.dealer_lookup(seller_name_raw=seller, country_code=country)
    assert result.data["authorizationStatus"] == expected.value
