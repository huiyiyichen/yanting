"""意图与情绪评测（可量化指标）。

评测集：evals/cases/loreal_intent_emotion.json（团队标注，六类难度标签）。
对比对象：
- rules：规则基线（分诊同一套词表，等价于拆分前的规则提示）；
- agent：意图与情绪 Agent（规则优先，拿不准时调用快速档模型）。

指标：
- 意图 accuracy、macro-F1；
- 情绪 accuracy、macro-F1、负面情绪召回（dissatisfied+angry 被识别为非 calm）、愤怒召回；
- 按难度标签的准确率（基础 / 否定 / 反讽 / 隐含 / 混合 / 上文）；
- 成本：调用模型的比例、Token 合计与每条均值。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from app.domain.consumer_service.understanding import EMOTIONS, INTENTS, understand


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def classification(rows: Iterable[tuple[str, str]], labels: Iterable[str]) -> dict[str, Any]:
    rows = list(rows)
    labels = list(labels)
    per: dict[str, dict] = {}
    for label in labels:
        tp = sum(e == label and p == label for e, p in rows)
        fp = sum(e != label and p == label for e, p in rows)
        fn = sum(e == label and p != label for e, p in rows)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (0.0 if tp + fn else None)
        per[label] = {"support": tp + fn, "precision": precision, "recall": recall, "f1": f1}
    scored = [v["f1"] for v in per.values() if v["support"]]
    return {
        "sampleCount": len(rows),
        "accuracy": sum(e == p for e, p in rows) / len(rows) if rows else None,
        "macroF1": sum(scored) / len(scored) if scored else None,
        "byLabel": per,
    }


def run(cases: list[dict], ask_model: Callable[[str, dict], str] | None, usage: list[dict] | None = None) -> dict:
    predictions = []
    for case in cases:
        before = len(usage) if usage is not None else 0
        found = understand(case["latest"], case.get("recent") or [], ask_model=ask_model)
        calls = usage[before:] if usage is not None else []
        predictions.append({
            "id": case["id"], "tags": case.get("tags", []),
            "expectedIntent": case["intent"], "predictedIntent": found.intent,
            "expectedEmotion": case["emotion"], "predictedEmotion": found.emotion_level,
            "source": found.source, "reasons": found.reasons,
            "promptTokens": sum(c.get("promptTokens") or 0 for c in calls),
            "completionTokens": sum(c.get("completionTokens") or 0 for c in calls),
        })
    return {"metrics": metrics(predictions), "cases": predictions}


def metrics(predictions: list[dict]) -> dict[str, Any]:
    intent = classification(((p["expectedIntent"], p["predictedIntent"]) for p in predictions), INTENTS)
    emotion = classification(((p["expectedEmotion"], p["predictedEmotion"]) for p in predictions), EMOTIONS)
    negative = [p for p in predictions if p["expectedEmotion"] != "calm"]
    angry = [p for p in predictions if p["expectedEmotion"] == "angry"]
    calm = [p for p in predictions if p["expectedEmotion"] == "calm"]
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for p in predictions:
        for tag in p["tags"] or ["untagged"]:
            by_tag[tag].append(p)
    model_calls = [p for p in predictions if p["source"] in {"model", "rule_fallback"}]
    uncertain = [p for p in predictions if any(r.startswith("U1") for r in p["reasons"])]
    wrong = [p for p in predictions
             if p["expectedIntent"] != p["predictedIntent"] or p["expectedEmotion"] != p["predictedEmotion"]]
    rule_wrong = [p for p in predictions if p["source"] == "rule"
                  and (p["expectedIntent"] != p["predictedIntent"] or p["expectedEmotion"] != p["predictedEmotion"])]
    prompt = sum(p["promptTokens"] for p in predictions)
    completion = sum(p["completionTokens"] for p in predictions)
    return {
        "sampleCount": len(predictions),
        "intent": intent,
        "emotion": {
            **emotion,
            "negativeRecall": sum(p["predictedEmotion"] != "calm" for p in negative) / len(negative) if negative else None,
            "angryRecall": sum(p["predictedEmotion"] == "angry" for p in angry) / len(angry) if angry else None,
            "calmFalseAlarmRate": sum(p["predictedEmotion"] != "calm" for p in calm) / len(calm) if calm else None,
        },
        "byTag": {tag: {
            "sampleCount": len(rows),
            "intentAccuracy": sum(p["expectedIntent"] == p["predictedIntent"] for p in rows) / len(rows),
            "emotionAccuracy": sum(p["expectedEmotion"] == p["predictedEmotion"] for p in rows) / len(rows),
        } for tag, rows in sorted(by_tag.items())},
        "cost": {
            "modelCallRate": len(model_calls) / len(predictions) if predictions else None,
            "modelCalls": len(model_calls),
            # 规则拿不准、会交给模型的比例（规则基线下也能算，代表上线后的调用比例）
            "uncertainRate": len(uncertain) / len(predictions) if predictions else None,
            # 规则判错的样本中，有多少被识别为“拿不准”而交给模型：越高说明 U1 的分流越准
            "errorRoutingRecall": (sum(any(r.startswith("U1") for r in p["reasons"]) for p in wrong) / len(wrong))
            if wrong else None,
            # 规则自信却判错（模型也救不回来）的样本
            "confidentRuleErrors": [p["id"] for p in rule_wrong if not any(r.startswith("U1") for r in p["reasons"])],
            "fallbacks": sum(p["source"] == "rule_fallback" for p in predictions),
            "promptTokens": prompt, "completionTokens": completion,
            "tokensPerMessage": (prompt + completion) / len(predictions) if predictions else None,
        },
        "errors": [p["id"] for p in wrong],
    }
