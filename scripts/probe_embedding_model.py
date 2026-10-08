"""验证本地 bge-m3 ONNX 是否可用于稠密 + 稀疏两通道，并实测 CPU 时延。

这是 DEP-03（编码模型/中文稀疏通道与硬件未跑通）的验证脚本。
只输出结构与时延，不输出模型权重内容。

用法：
    python scripts/probe_embedding_model.py
"""

from __future__ import annotations

import json
import sys
import time
from importlib.metadata import version
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.integrations.embedding_provider import (  # noqa: E402
    OnnxLocalEmbeddingProvider,
    default_model_dir,
)


def main() -> int:
    settings = Settings()
    model_dir = default_model_dir(settings.embedding_model_id) / "onnx"
    report: dict[str, object] = {
        "model_id": settings.embedding_model_id,
        "model_dir": str(model_dir),
        "model_dir_exists": model_dir.exists(),
        "onnxruntime": version("onnxruntime"),
        "tokenizers": version("tokenizers"),
    }
    if not model_dir.exists():
        report["result"] = "FAILED_MODEL_MISSING"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    provider = OnnxLocalEmbeddingProvider(
        model_id=settings.embedding_model_id, model_path=str(model_dir)
    )

    # 中文 + 型号 + 否定条件，覆盖工程规范第 12.4 节查询要求
    corpus = [
        "S1 Pro 吸尘器吸力变弱，请先检查集尘盒滤网是否堵塞并清洗滤网。",
        "若滤网堵塞会导致吸力下降，清洗后静置 24 小时再测试吸力。",
        "保修期自购买之日起 24 个月，需提供有效购买凭证。",
        "设备漏水时立即停止使用，检查水箱密封圈是否安装到位。",
        "经销商授权核验按国家/地区精确匹配、卖家名称模糊匹配进行。",
        "这不是关于滤网的问题，设备是充电口无法充电。",
    ]

    load_started = time.perf_counter()
    batch = provider.encode(corpus)
    first_batch_seconds = time.perf_counter() - load_started

    single_started = time.perf_counter()
    query = provider.encode(["吸尘器没有吸力了怎么排查"])
    single_seconds = time.perf_counter() - single_started

    # 余弦相似度：验证稠密向量确实携带语义，而非随机噪声
    import math

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    scores = [round(cosine(query.dense[0], row), 4) for row in batch.dense]
    best = max(range(len(scores)), key=lambda i: scores[i])

    report.update(
        {
            "dimension": batch.dimension,
            "model_revision": batch.model_revision,
            "sparse_model_id": batch.sparse_model_id,
            "tokenizer_revision": batch.tokenizer_revision,
            "dense_is_normalized": all(
                abs(math.sqrt(sum(x * x for x in row)) - 1.0) < 1e-3 for row in batch.dense[:2]
            ),
            "sparse_nonzero_counts": [len(item.indices) for item in batch.sparse],
            "sparse_indices_in_range": all(
                all(0 <= i < 250002 for i in item.indices) for item in batch.sparse
            ),
            "first_batch_seconds": round(first_batch_seconds, 3),
            "single_query_seconds": round(single_seconds, 3),
            "query_seconds_per_text": round(single_seconds, 3),
            "corpus_seconds_per_text": round(first_batch_seconds / len(corpus), 3),
            "cosine_scores": scores,
            "top_match_index": best,
            "top_match_text": corpus[best][:40],
            "semantic_sanity": "PASS" if best in (0, 1) else "REVIEW",
        }
    )
    report["result"] = "PASS" if report["sparse_nonzero_counts"][0] > 0 else "FAILED_NO_SPARSE"  # type: ignore[index]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
