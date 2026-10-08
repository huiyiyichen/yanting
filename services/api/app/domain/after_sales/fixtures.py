"""结构化夹具的加载与查询。

设计约束：
- 订单和经销商事实由**结构化查询**确定，不向量化后凭相似性判断质保/授权；
- 用户选择或相似度**不能**改变源订单，也不能证明授权；
- 全部数据来自标注为虚构的夹具（DEP-01：官方数据未提供）。

阈值说明：`FUZZY_ACCEPT` / `FUZZY_AMBIGUOUS_MARGIN` 是**待校准的工程起点**，
不是业务结论。它们只影响候选排序与「是否需要补问」的判断，
最终授权结论仍必须来自名录中的明确记录。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from app.config import REPO_ROOT
from app.domain.enums import DealerAuthorizationStatus, PurchaseChannel, WarrantyStatus

FIXTURES_ROOT = REPO_ROOT / "data" / "fixtures"

# 待校准起点，不是业务结论：
# - 召回最小分：低于此值不返回候选，避免把噪音当候选。
#   不要用 `partial_ratio`：它会把「完全无关的内容 xyzzy」也判成 100 分，
#   因为短型号名 `A1 Pro` 是其子串（已实测），因此这里先剥离品类词与完整型号，
#   再用 `token_set_ratio` 比较剩余描述。
# - 授权接受分：达到此分才视为强候选。低于它返回「无法判断」并要求补凭证。
# - 歧义间距：前两名分差小于此值时视为难以区分，返回 multiple_matches 而不是任选。
#   实测依据（虚构名录，CN，token_set_ratio）：
#     `星海数码`     → 100 / 80（差距 20）→ 判为歧义：该名称同时被两家授权店包含，
#                       任意选定就等于替用户猜店铺，正是 AC-18 要禁止的；
#     `星海数码华东` → 100 / 80（差距 20）→ 同样歧义；
#     `星海数码专营店` → 100 / 72.7（差距 27.3）→ 唯一，可用于日常场景。
#   因此间距取 25：低于它才补问，避免把清晰输入也变成追问。
FUZZY_RECALL_MIN = 60.0
FUZZY_ACCEPT = 85.0
FUZZY_AMBIGUOUS_MARGIN = 25.0
# 竞争候选下限：分数达到它且与最佳候选的差距小于间距时，视为存在竞争候选。
# 必须与 FUZZY_ACCEPT 分开，并且阈值由实测分布确定（CN 虚构名录，token_set_ratio）：
#   查询             最佳(差距)      次佳(差距)        期望
#   星海数码          100             80（20）          歧义：两家店都叫「星海数码…」
#   星海数码华东      100             80（20）          歧义：同上
#   星海数码专营店    100             77.8（22.2）      唯一：次佳 77.8 明显是另一家
#   星海数码旗舰店    100             61.5（38.5）      唯一
# 因此下限取 78：77.8 被排除（唯一），80 被保留（歧义）。
FUZZY_AMBIGUOUS_FLOOR = 78.0

PRODUCT_NOISE_PATTERN = re.compile(
    r"\bA1\s*Pro\b|无线吸尘器|扫地机器人|洗地机器人|智能看护器|看护器|摄像头|户外电源",
    re.IGNORECASE,
)

# 只剥离型号写法（含空格变体）。用于把**查询**里的型号词去掉，保留品类词。
#
# 为什么不能沿用 PRODUCT_NOISE_PATTERN 处理查询：那个模式连品类词一起去掉，
# 会让「A1 Pro 无线吸尘器」和「A1 Pro 扫地机器人」都退化成「A1 Pro」而打平，
# 排序只能靠产品表顺序决定——实测导致 3/12 题把吸尘器问题判成扫地机器人
# （AC-02 消歧准确率因此只有 0.85）。保留品类词后，品类本身就成为区分信号。
PRODUCT_MODEL_ONLY_PATTERN = re.compile(r"\bA1\s*Pro\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Product:
    product_id: str
    product_model: str
    product_category: str
    display_name: str
    aliases: tuple[str, ...]
    sku: str
    regions: tuple[str, ...]
    released_at: date
    spec_highlights: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    order_no_masked: str
    customer_id: str
    product_id: str
    product_model: str
    product_name_snapshot: str
    sku: str
    purchased_at: date
    country_code: str
    purchase_channel: PurchaseChannel
    seller_name_raw: str
    seller_name_standard: str | None
    warranty_months: int
    status: str


@dataclass(frozen=True, slots=True)
class Dealer:
    dealer_id: str
    name_standard: str
    aliases: tuple[str, ...]
    country_code: str
    channels: tuple[str, ...]
    authorization_status: str
    authorized_since: date | None


@dataclass(frozen=True, slots=True)
class DealerMatch:
    """授权核验结果。

    `status` 严格区分「明确非授权」「多个匹配」「查询失败」「无法判断」——
    这四种状态不得互相替代（工程规范第 5.4 节）。
    """

    status: DealerAuthorizationStatus
    candidates: tuple[Dealer, ...] = ()
    best_score: float | None = None
    seller_name_raw: str = ""
    seller_name_standard: str | None = None
    note: str = ""


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"夹具缺失：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache
def load_products() -> tuple[Product, ...]:
    raw = _read_json(FIXTURES_ROOT / "products" / "products.json")
    return tuple(
        Product(
            product_id=item["product_id"],
            product_model=item["product_model"],
            product_category=item["product_category"],
            display_name=item["display_name"],
            aliases=tuple(item.get("aliases") or []),
            sku=item["sku"],
            regions=tuple(item["regions"]),
            released_at=date.fromisoformat(item["released_at"]),
            spec_highlights=tuple(item.get("spec_highlights") or []),
        )
        for item in raw["products"]
    )


@lru_cache
def load_orders() -> tuple[Order, ...]:
    raw = _read_json(FIXTURES_ROOT / "orders" / "orders.json")
    return tuple(
        Order(
            order_id=item["order_id"],
            order_no_masked=item["order_no_masked"],
            customer_id=item["customer_id"],
            product_id=item["product_id"],
            product_model=item["product_model"],
            product_name_snapshot=item["product_name_snapshot"],
            sku=item["sku"],
            purchased_at=date.fromisoformat(item["purchased_at"]),
            country_code=item["country_code"],
            purchase_channel=PurchaseChannel(item["purchase_channel"]),
            seller_name_raw=item["seller_name_raw"],
            seller_name_standard=item.get("seller_name_standard"),
            warranty_months=int(item["warranty_months"]),
            status=item["status"],
        )
        for item in raw["orders"]
    )


@lru_cache
def load_dealers() -> tuple[Dealer, ...]:
    raw = _read_json(FIXTURES_ROOT / "dealers" / "dealers.json")
    return tuple(
        Dealer(
            dealer_id=item["dealer_id"],
            name_standard=item["name_standard"],
            aliases=tuple(item.get("aliases") or []),
            country_code=item["country_code"],
            channels=tuple(item["channels"]),
            authorization_status=item["authorization_status"],
            authorized_since=(
                date.fromisoformat(item["authorized_since"])
                if item.get("authorized_since")
                else None
            ),
        )
        for item in raw["authorized_dealers"]
    )


# --------------------------------------------------------------------- 订单


def find_orders_by_customer(customer_id: str) -> list[Order]:
    return [item for item in load_orders() if item.customer_id == customer_id]


def find_order(order_id: str) -> Order | None:
    for item in load_orders():
        if item.order_id == order_id:
            return item
    return None


def find_orders_by_masked_no(masked: str) -> list[Order]:
    normalized = masked.strip().upper()
    return [item for item in load_orders() if item.order_no_masked.upper() == normalized]


def find_orders_by_product(product_id: str) -> list[Order]:
    return [item for item in load_orders() if item.product_id == product_id]


# --------------------------------------------------------------------- 产品


def match_products_by_name(text: str, *, limit: int = 5) -> list[tuple[Product, float]]:
    """按名称/别名做候选召回。返回 (产品, 分数) 降序。

    这里只做候选**召回**：分数仅用于排序，不代表确认结果，也不改变源订单。
    低于 `FUZZY_RECALL_MIN` 的候选不返回，避免把噪音当候选（AC-10）。
    """

    if not text.strip():
        return []
    haystack = text.strip()
    # 查询去掉型号写法、**保留品类词**：只描述故障时会话里通常没有型号，
    # 但「吸尘器 / 扫地机器人」这类品类词正是区分同型号不同产品的关键。
    residual = PRODUCT_MODEL_ONLY_PATTERN.sub(" ", haystack).strip()

    scored: list[tuple[Product, float]] = []
    for product in load_products():
        # 不把裸 `product_model` 当比较对象：`token_set_ratio` 对「子集」给满分，
        # 查询里出现「A1 Pro」时它与三个同型号产品都得 100 分，直接把排序打平
        # （实测就是 3/12 题判错的原因）。display_name 与 aliases 已包含型号，
        # 且额外带品类词，才是可区分的信息。
        candidates = (product.display_name, *product.aliases)
        best = 0.0
        for item in candidates:
            # 原文比较：用户完整说出产品名的情况
            best = max(best, float(fuzz.token_set_ratio(haystack, item)))
            # 去型号比较：用户只描述故障的情况
            if residual:
                best = max(best, float(fuzz.token_set_ratio(residual, item)))
        scored.append((product, best))
    scored = [item for item in scored if item[1] >= FUZZY_RECALL_MIN]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def products_by_model(product_model: str) -> list[Product]:
    """同名产品的全部候选。`A1 Pro` 会命中扫地机器人与无线吸尘器。"""

    target = product_model.strip().lower()
    return [item for item in load_products() if item.product_model.lower() == target]


# ------------------------------------------------------------------ 经销商


def _normalize_seller(value: str) -> str:
    return " ".join(value.lower().replace("（", "(").replace("）", ")").split())


def _score_seller(query: str, dealer: Dealer) -> float:
    """卖家名相似度。

    用 `token_set_ratio` 而不是 `ratio`：中文店铺名经常是另一个店铺名的子串
    （如「星海数码」是「星海数码专营店」与「星海数码旗舰店」的公共前缀）。
    按字符比例计算时子串只能得到 70—80 分，无法识别「这一名称同时指向多家店铺」；
    `token_set_ratio` 会把「查询词完全被候选包含」判为 100，从而正确暴露歧义。
    """

    normalized = _normalize_seller(query)
    candidates = (dealer.name_standard, *dealer.aliases)
    return max(
        float(fuzz.token_set_ratio(normalized, _normalize_seller(item))) for item in candidates
    )


def verify_dealer_authorization(
    *,
    seller_name_raw: str,
    country_code: str | None,
    channel: PurchaseChannel | None = None,
) -> DealerMatch:
    """按「国家/地区精确匹配 + 卖家名称模糊匹配」核验授权。

    规则（工程规范第 5.4 节）：
    - 国家缺失时**不能**跨国家匹配，返回无法判断并说明需要补问；
    - 唯一强匹配 → authorized（并给出标准名）；
    - 名录中有明确 `not_authorized` 记录且强匹配 → not_authorized；
    - 多个候选难以区分 → multiple_matches；
    - 无候选达到阈值 → unknown（提示补充凭证），**不是** not_authorized。
    """

    raw = seller_name_raw.strip()
    if not raw:
        return DealerMatch(
            status=DealerAuthorizationStatus.UNKNOWN,
            seller_name_raw="",
            note="缺少实际卖家名称，需要补问购买店铺或补充凭证。",
        )
    if not country_code:
        return DealerMatch(
            status=DealerAuthorizationStatus.UNKNOWN,
            seller_name_raw=raw,
            note="缺少购买国家/地区，不能跨国家匹配授权名录；需要先补问地区。",
        )

    pool = [item for item in load_dealers() if item.country_code == country_code]
    if not pool:
        return DealerMatch(
            status=DealerAuthorizationStatus.UNKNOWN,
            seller_name_raw=raw,
            note=f"该国家/地区（{country_code}）在名录中没有记录，需要人工复核。",
        )

    scored = sorted(
        ((dealer, _score_seller(raw, dealer)) for dealer in pool),
        key=lambda item: item[1],
        reverse=True,
    )
    best_dealer, best_score = scored[0]

    if best_score < FUZZY_ACCEPT:
        return DealerMatch(
            status=DealerAuthorizationStatus.UNKNOWN,
            seller_name_raw=raw,
            best_score=best_score,
            note="名录中没有达到匹配阈值的记录；需要补充购买凭证后复核，不能判定为非授权。",
        )

    # 竞争候选：分数达到竞争下限且与最佳候选足够接近。
    # 最佳候选自身也计入，因此 len(near) > 1 表示「存在第二个合理读法」。
    near = [
        dealer
        for dealer, score in scored
        if score >= FUZZY_AMBIGUOUS_FLOOR and best_score - score < FUZZY_AMBIGUOUS_MARGIN
    ]
    if len(near) > 1:
        return DealerMatch(
            status=DealerAuthorizationStatus.MULTIPLE_MATCHES,
            candidates=tuple(near),
            best_score=best_score,
            seller_name_raw=raw,
            note=(
                "该卖家名同时指向多家名录记录（得分接近），不能任选其一；"
                "需要补问实际店铺或补充购买凭证。"
            ),
        )

    if best_dealer.authorization_status != "authorized":
        return DealerMatch(
            status=DealerAuthorizationStatus.NOT_AUTHORIZED,
            candidates=(best_dealer,),
            best_score=best_score,
            seller_name_raw=raw,
            note="名录中明确记录该卖家未获授权。",
        )

    if channel is not None and best_dealer.channels and channel.value not in best_dealer.channels:
        # 名称命中但渠道类型不符时仍需复核，不直接判为授权
        return DealerMatch(
            status=DealerAuthorizationStatus.UNKNOWN,
            candidates=(best_dealer,),
            best_score=best_score,
            seller_name_raw=raw,
            note=(
                f"卖家名称命中，但订单渠道（{channel.value}）不在该经销商记录的渠道范围内，"
                "需要人工复核。"
            ),
        )

    return DealerMatch(
        status=DealerAuthorizationStatus.AUTHORIZED,
        candidates=(best_dealer,),
        best_score=best_score,
        seller_name_raw=raw,
        # 只有唯一核验成功才写标准名，且不覆盖原始名
        seller_name_standard=best_dealer.name_standard,
        note="国家/地区精确匹配 + 卖家名称唯一强匹配。",
    )


# -------------------------------------------------------------------- 质保


@dataclass(frozen=True, slots=True)
class WarrantyEvaluation:
    status: WarrantyStatus
    reason: str
    warranty_months: int | None = None
    expires_on: date | None = None
    days_remaining: int | None = None


def evaluate_warranty(order: Order, *, on_date: date | None = None) -> WarrantyEvaluation:
    """按订单购买日期与质保月数计算质保状态。

    这里只做**算术**：起算日与期限来自订单事实与政策文件。
    政策规则本身由检索到的适用文档提供，不在代码里硬编码业务承诺。
    """

    today = on_date or date.today()
    if order.status != "active":
        return WarrantyEvaluation(
            status=WarrantyStatus.UNKNOWN,
            reason=f"订单状态为 {order.status}，无法据其判定质保。",
        )
    months = order.warranty_months
    if months <= 0:
        return WarrantyEvaluation(
            status=WarrantyStatus.UNKNOWN,
            reason="订单未载明质保月数，需要核对购买凭证。",
        )
    purchased = order.purchased_at
    year = purchased.year + (purchased.month - 1 + months) // 12
    month = (purchased.month - 1 + months) % 12 + 1
    day = min(purchased.day, 28)
    expires = date(year, month, day)
    remaining = (expires - today).days
    if remaining < 0:
        return WarrantyEvaluation(
            status=WarrantyStatus.OUT_OF_WARRANTY,
            reason=f"按订单购买日期 {purchased} 与 {months} 个月质保，已于 {expires} 到期。",
            warranty_months=months,
            expires_on=expires,
            days_remaining=remaining,
        )
    return WarrantyEvaluation(
        status=WarrantyStatus.IN_WARRANTY,
        reason=f"按订单购买日期 {purchased} 与 {months} 个月质保，有效期至 {expires}。",
        warranty_months=months,
        expires_on=expires,
        days_remaining=remaining,
    )


def clear_fixture_cache() -> None:
    """测试用：夹具文件变化后清空缓存。"""

    load_products.cache_clear()
    load_orders.cache_clear()
    load_dealers.cache_clear()
