"""诊断稀疏通道：为什么每个文本只得到 1 个非零词项权重。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

import numpy as np  # noqa: E402

from app.config import Settings  # noqa: E402
from app.integrations.embedding_provider import (  # noqa: E402
    OnnxLocalEmbeddingProvider,
    default_model_dir,
)


def main() -> int:
    settings = Settings()
    model_dir = default_model_dir(settings.embedding_model_id) / "onnx"
    provider = OnnxLocalEmbeddingProvider(
        model_id=settings.embedding_model_id, model_path=str(model_dir)
    )
    provider._ensure_loaded()
    assert provider._session is not None and provider._tokenizer is not None

    texts = [
        "S1 Pro 吸尘器吸力变弱，请先检查集尘盒滤网是否堵塞并清洗滤网。",
        "保修期自购买之日起 24 个月，需提供有效购买凭证。",
    ]
    encodings = provider._tokenizer.encode_batch(texts)
    inputs = {
        "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
    }
    names = [i.name for i in provider._session.get_inputs()]
    if "token_type_ids" in names:
        inputs["token_type_ids"] = np.zeros_like(inputs["input_ids"])
    outputs = provider._session.run(None, inputs)
    named = dict(zip([o.name for o in provider._session.get_outputs()], outputs, strict=True))

    tokens = np.asarray(named["token_embeddings"], dtype=np.float32)
    mask = np.asarray(inputs["attention_mask"], dtype=np.float32)[..., None]
    pooled = (tokens * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1.0, None)

    weight = provider._sparse_weight
    bias = provider._sparse_bias
    assert weight is not None
    print(f"token_embeddings: shape={tokens.shape} min={tokens.min():.4f} max={tokens.max():.4f}")
    print(f"pooled: shape={pooled.shape} min={pooled.min():.4f} max={pooled.max():.4f}")
    print(f"sparse_weight: shape={weight.shape} min={weight.min():.6f} max={weight.max():.6f}")
    print(f"sparse_bias: {bias!r}")
    print(f"seq lens: {[len(e.ids) for e in encodings]}")
    print(f"mask sums: {mask.sum(axis=1).ravel().tolist()}")

    raw = pooled @ weight
    print(f"raw proj (no bias): {np.round(raw, 4).tolist()}")
    raw_b = raw + bias
    print(f"raw proj (+bias):   {np.round(raw_b, 4).tolist()}")
    for index, value in enumerate(raw_b):
        print(f"  text{index}: positive_count={(value > 0).sum()}")
    print("=> 单个标量投影无法产生词项级稀疏向量；需要 token 级权重。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
