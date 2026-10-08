import pytest

from app.domain.consumer_service.emotion import ANGRY, has_complaint_signal, score_message
from app.evaluation.loreal import binary_metrics, set_metrics


def test_binary_metrics_preserve_denominators_and_case_membership():
    result = binary_metrics([
        {"id": "tp", "expected": True, "predicted": True},
        {"id": "fn", "expected": True, "predicted": False},
        {"id": "fp", "expected": False, "predicted": True},
        {"id": "tn", "expected": False, "predicted": False},
    ])
    assert result["sampleCount"] == 4
    assert result["recall"] == result["precision"] == result["accuracy"] == 0.5
    assert result["falsePositiveCaseIds"] == ["fp"]
    assert result["missedCaseIds"] == ["fn"]


def test_no_positive_or_empty_is_unknown_not_perfect_recall():
    assert binary_metrics([])["accuracy"] is None
    result = binary_metrics([{"id": "negative", "expected": False, "predicted": False}])
    assert result["recall"] is None
    assert result["precision"] is None
    assert result["accuracy"] == 1


def test_multilabel_counts_are_per_label_not_sum_of_overlapping_signals():
    result = set_metrics([
        {"id": "both", "expected": ["a", "b"], "predicted": ["a", "b"]},
        {"id": "missed", "expected": ["a"], "predicted": []},
    ], ["a", "b"])
    assert result["sampleCount"] == 2
    assert result["exactMatches"] == 1
    assert result["byLabel"]["a"]["recall"] == 0.5
    assert result["byLabel"]["b"]["recall"] == 1


@pytest.mark.parametrize("body", [
    "我去平台申请退款", "我不是要投诉，是问退款流程",
    "如果我以后不满意，可以投诉吗？", "你们说可以投诉，我只想知道到货时间",
    "客服说让我去平台申请退款",
])
def test_normal_process_negation_and_reported_advice_are_not_complaints(body):
    assert score_message(body) < ANGRY
    assert not has_complaint_signal(body)


@pytest.mark.parametrize("body", [
    "刚才不想投诉，现在还是要投诉", "如果不给处理，我就要投诉",
    "客服说不处理，所以我现在要正式投诉",
])
def test_explicit_current_complaint_is_not_hidden_by_an_earlier_context(body):
    assert score_message(body) == ANGRY
    assert has_complaint_signal(body)
