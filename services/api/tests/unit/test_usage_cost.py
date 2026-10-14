"""成本估算（P1-7）。先列失败方式：
U1 未配置价格的模型给出 0 元（应为空，表示无法估算），被误读为免费。
U2 缓存命中 Token 仍按普通输入价计费，或从输入 Token 里重复扣减出负数。
U3 Token 缺失（平台未返回用量）时按 0 计入，压低平均成本。
U4 价格表 JSON 写错时静默为空，没有报错。
"""

import pytest

from app.domain.platform.usage import estimate_cost, parse_price_table

PRICES = parse_price_table('{"deepseek-chat": {"input": 2, "cachedInput": 0.5, "output": 8}}')


def test_u1_unknown_model_has_no_cost():
    assert estimate_cost(PRICES, "qwen3-32b", prompt=1000, cached=0, completion=100) is None


def test_u2_cached_tokens_use_cached_price():
    cost = estimate_cost(PRICES, "deepseek-chat", prompt=1_000_000, cached=400_000, completion=0)
    assert cost == pytest.approx(600_000 / 1e6 * 2 + 400_000 / 1e6 * 0.5)
    assert estimate_cost(PRICES, "deepseek-chat", prompt=100, cached=500, completion=0) is None


def test_u3_missing_tokens_have_no_cost():
    assert estimate_cost(PRICES, "deepseek-chat", prompt=None, cached=0, completion=10) is None


def test_u4_invalid_price_table_raises():
    with pytest.raises(ValueError):
        parse_price_table('{"deepseek-chat": {"input": "两元"}}')
    assert parse_price_table("") == {}
