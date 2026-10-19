"""意图与情绪评测（可量化指标）。

失败方式：
E1 评测集缺六类难度标签之一，或标签越界。
E2 指标口径错误（macro-F1、负面情绪召回、按标签准确率）。
E3 规则判错的样本大多没被识别为“拿不准”，模型分流形同虚设（召回 < 80%）。
E4 模拟一个总是答对的模型时，Agent 指标没有高于规则基线，或调用比例与拿不准比例不一致。
"""

import json
from pathlib import Path

from app.domain.consumer_service.understanding import EMOTIONS, INTENTS
from app.evaluation.understanding_eval import classification, load_cases, run

CASES = Path(__file__).resolve().parents[4] / "evals" / "cases" / "loreal_intent_emotion.json"


def test_case_file_is_well_formed():
    cases = load_cases(CASES)
    assert len(cases) >= 60 and len({c["id"] for c in cases}) == len(cases)
    assert all(c["intent"] in INTENTS and c["emotion"] in EMOTIONS for c in cases)
    tags = {t for c in cases for t in c["tags"]}
    assert {"basic", "negation", "sarcasm", "implicit", "mixed", "context"} <= tags  # E1


def test_classification_metrics():
    m = classification([("a", "a"), ("a", "b"), ("b", "b"), ("b", "b")], ["a", "b"])
    assert m["accuracy"] == 0.75
    assert m["byLabel"]["a"]["recall"] == 0.5 and m["byLabel"]["b"]["precision"] == 2 / 3
    assert abs(m["macroF1"] - (2 / 3 + 0.8) / 2) < 1e-9  # E2


def test_rule_baseline_routes_its_errors_to_the_model():
    report = run(load_cases(CASES), None)["metrics"]
    assert report["cost"]["modelCallRate"] == 0 and report["cost"]["tokensPerMessage"] == 0
    assert report["cost"]["errorRoutingRecall"] >= 0.8  # E3
    assert report["byTag"]["negation"]["emotionAccuracy"] == 1.0


def test_oracle_model_beats_rules_only_where_routed():
    cases = load_cases(CASES)
    truth = {c["latest"]: c for c in cases}
    usage: list[dict] = []

    def oracle(system, payload):
        case = truth[payload["latestCustomerMessage"]]
        usage.append({"promptTokens": 100, "completionTokens": 20})
        quote = case["latest"][:4] if case["emotion"] != "calm" else ""
        return json.dumps({"intent": case["intent"], "emotion_level": case["emotion"], "evidence": quote},
                          ensure_ascii=False)

    rules = run(cases, None)["metrics"]
    agent = run(cases, oracle, usage)["metrics"]
    assert agent["intent"]["accuracy"] > rules["intent"]["accuracy"]
    assert agent["emotion"]["accuracy"] > rules["emotion"]["accuracy"]  # E4
    assert agent["cost"]["modelCallRate"] == rules["cost"]["uncertainRate"]
    assert agent["cost"]["tokensPerMessage"] == 120 * agent["cost"]["modelCalls"] / len(cases)
