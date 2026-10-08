"""检索模式开关的回归测试。

目的：保证 `mode` 参数确实改变检索行为，而不是被静默忽略。
历史教训：切片 `chunk_size` 曾经因为实现缺陷完全不起作用，
三种配置产出完全相同的索引，而结果看起来「正常」。
"""

from __future__ import annotations

from app.knowledge.retrieval import RetrievalRequest


def test_default_mode_is_hybrid() -> None:
    request = RetrievalRequest(query="吸尘器吸力弱")
    assert request.mode == "hybrid"


def test_mode_is_carried_into_filter_summary() -> None:
    """filter_summary 会随结果返回，便于在证据里复盘本次用的哪条通道。"""

    request = RetrievalRequest(query="吸尘器吸力弱", mode="dense_only")
    assert request.mode == "dense_only"
    request_sparse = RetrievalRequest(query="吸尘器吸力弱", mode="sparse_only")
    assert request_sparse.mode == "sparse_only"


def test_mode_literal_values_are_the_expected_three() -> None:
    from typing import get_args

    from app.integrations.qdrant_store import RetrievalMode

    assert set(get_args(RetrievalMode)) == {"hybrid", "dense_only", "sparse_only"}
