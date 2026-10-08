"""编码适配层：稠密向量 + 稀疏词项权重两通道。

约束（工程规范第 12.4 节）：
- 不允许"只返回 dense 的接口"冒充混合检索；
- 不同编码模型不能混用同一向量空间，因此维度与版本必须随快照记录；
- 服务不暴露 revision 时记录 `unavailable` 及请求模型 ID，不能编造。

后端选择：
- `OnnxLocalEmbeddingProvider`：本地 bge-m3 ONNX，同时产出 dense 与 sparse；
- `HttpEmbeddingProvider`：比赛/第三方提供的 OpenAI 兼容 /embeddings；
- `MockEmbeddingProvider`：确定性伪向量，仅测试用，构造函数强制传入明确理由。
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.errors import (
    ProviderNotConfigured,
    ProviderRequestFailed,
    ProviderTimeout,
)
from app.integrations.checkpoint_loader import load_legacy_pt
from app.logging_setup import get_logger

logger = get_logger(__name__)

UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class SparseVector:
    indices: list[int]
    values: list[float]


@dataclass(slots=True)
class EmbeddingBatch:
    dense: list[list[float]]
    sparse: list[SparseVector]
    dimension: int
    model_id: str
    model_revision: str
    sparse_model_id: str
    sparse_model_revision: str
    tokenizer_revision: str
    latency_seconds: float
    is_mock: bool = False


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def available(self) -> bool: ...

    def encode(self, texts: list[str], *, is_query: bool = False) -> EmbeddingBatch: ...

    def describe(self) -> dict[str, str]: ...


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return UNAVAILABLE


class OnnxLocalEmbeddingProvider:
    """本地 bge-m3 ONNX：稠密 + 稀疏（sparse_linear）两通道。

    说明：稀疏通道输出的是模型学到的词项权重（lexical weights），
    不是 BM25，也不是精确字符串匹配 —— 这一点在证据与报告中必须如实描述。
    """

    def __init__(
        self,
        *,
        model_id: str,
        model_path: str,
        max_length: int = 8192,
        sparse_top_k: int = 250,
    ) -> None:
        self._model_id = model_id
        self._model_path = Path(model_path)
        self._max_length = max_length
        self._sparse_top_k = sparse_top_k
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._dimension: int | None = None
        self._sparse_weight: Any | None = None
        self._sparse_bias: Any | None = None
        self._sparse_source: str = "unknown"

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise ProviderNotConfigured("编码模型尚未加载，维度未知")
        return self._dimension

    def available(self) -> bool:
        return self._model_path.exists() and (self._model_path / "model.onnx").exists()

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer

        onnx_file = self._model_path / "model.onnx"
        if not onnx_file.exists():
            raise ProviderNotConfigured(
                "本地编码模型未就绪",
                detail=f"未找到 {onnx_file}；请先运行 scripts/fetch_embedding_model.py",
            )
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = 0
        started = time.perf_counter()
        self._session = ort.InferenceSession(
            str(onnx_file), sess_options=options, providers=["CPUExecutionProvider"]
        )
        tokenizer_file = self._model_path / "tokenizer.json"
        if not tokenizer_file.exists():
            raise ProviderNotConfigured(
                "本地编码模型缺少 tokenizer.json", detail=str(tokenizer_file)
            )
        self._tokenizer = Tokenizer.from_file(str(tokenizer_file))
        self._tokenizer.enable_truncation(max_length=self._max_length)
        self._tokenizer.enable_padding()
        self._load_sparse_weights(tokenizer_file.parent)
        # 维度从会话输出形状推断，不写死猜测值。
        for output in self._session.get_outputs():
            if output.name == "sentence_embedding":
                shape = output.shape
                self._dimension = int(shape[-1])
        logger.info(
            json.dumps(
                {
                    "event": "embedding_model_loaded",
                    "model_id": self._model_id,
                    "dimension": self._dimension,
                    "sparse_source": self._sparse_source,
                    "load_seconds": round(time.perf_counter() - started, 2),
                },
                ensure_ascii=False,
            )
        )

    def _load_sparse_weights(self, model_root: Path) -> None:
        """准备稀疏通道权重。

        两条路径：
        1. ONNX 图内自带 `sparse_embedding` 输出 —— 直接使用，最省事；
        2. 图内只有 `token_embeddings` —— 用官方 `sparse_linear` 线性层
           （权重以 legacy .pt 提供）对 token 嵌入做投影，复现 FlagEmbedding 的
           sparse 通道。第 2 条路径由 `checkpoint_loader` 读取，不需要 torch。
        """

        import numpy as np

        self._sparse_source = "onnx_graph" if self._has_graph_sparse() else "external_linear"
        if self._sparse_source == "onnx_graph":
            return

        checkpoint = self._find_sparse_checkpoint(model_root)
        if checkpoint is None:
            # 找不到权重时不伪造：保留为 missing，encode 时显式报错。
            self._sparse_source = "missing"
            return
        state = load_legacy_pt(checkpoint)
        weight = None
        bias = None
        for name, tensor in state.items():
            if name.endswith("weight"):
                weight = tensor
            elif name.endswith("bias"):
                bias = tensor
        if weight is None:
            raise ProviderRequestFailed("sparse_linear.pt 中未找到 weight", detail=str(list(state)))
        self._sparse_weight = np.asarray(weight, dtype=np.float32).reshape(-1)
        self._sparse_bias = (
            float(np.asarray(bias, dtype=np.float32).reshape(-1)[0]) if bias is not None else 0.0
        )
        if self._sparse_weight.shape[0] != self._hidden_size():
            raise ProviderRequestFailed(
                "sparse_linear 权重维度与模型隐藏层不一致",
                detail=f"weight={self._sparse_weight.shape[0]} hidden={self._hidden_size()}",
            )

    @staticmethod
    def _find_sparse_checkpoint(model_root: Path) -> Path | None:
        """定位 sparse_linear.pt。

        官方仓库把 ONNX 图放在 `onnx/`，而 sparse_linear.pt 在仓库根，
        因此需要向上一层查找。
        """

        candidates = [
            model_root / "sparse_linear.pt",
            model_root.parent / "sparse_linear.pt",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _has_graph_sparse(self) -> bool:
        assert self._session is not None
        return any(item.name == "sparse_embedding" for item in self._session.get_outputs())

    def _is_causal_lm(self) -> bool:
        """bge-m3 的 ONNX 导出输出 causal LM 风格的 `logits`，需要取 [:, 0] 作为句向量。"""

        assert self._session is not None
        return any(item.name == "logits" for item in self._session.get_outputs())

    def _hidden_size(self) -> int:
        assert self._session is not None
        for output in self._session.get_outputs():
            if output.name == "token_embeddings":
                return int(output.shape[-1])
            if output.name == "last_hidden_state":
                return int(output.shape[-1])
            if output.name == "logits":
                return int(output.shape[-1])
        return self._dimension or 0

    def encode(self, texts: list[str], *, is_query: bool = False) -> EmbeddingBatch:
        del is_query  # bge-m3 的查询/文档编码约定一致，无需加前缀
        if not texts:
            raise ProviderRequestFailed("编码输入为空")
        self._ensure_loaded()
        assert self._session is not None and self._tokenizer is not None

        started = time.perf_counter()
        encodings = self._tokenizer.encode_batch(texts)
        input_ids = [enc.ids for enc in encodings]
        attention_mask = [enc.attention_mask for enc in encodings]

        import numpy as np

        inputs = {
            "input_ids": np.array(input_ids, dtype=np.int64),
            "attention_mask": np.array(attention_mask, dtype=np.int64),
        }
        input_names = {item.name for item in self._session.get_inputs()}
        if "token_type_ids" in input_names:
            inputs["token_type_ids"] = np.zeros_like(inputs["input_ids"])

        outputs = self._session.run(None, inputs)
        output_names = [item.name for item in self._session.get_outputs()]
        named = dict(zip(output_names, outputs, strict=True))

        dense = self._dense_from_outputs(named, output_names)
        sparse_list = self._sparse_from_outputs(named, inputs, output_names)

        self._dimension = int(dense.shape[-1])
        return EmbeddingBatch(
            dense=dense.tolist(),
            sparse=sparse_list,
            dimension=self._dimension,
            model_id=self._model_id,
            model_revision=self._read_revision(),
            sparse_model_id=f"{self._model_id}#sparse_linear",
            sparse_model_revision=self._read_revision(),
            tokenizer_revision=f"tokenizers=={_package_version('tokenizers')}",
            latency_seconds=time.perf_counter() - started,
        )

    def _dense_from_outputs(self, named: dict[str, Any], output_names: list[str]) -> Any:
        """提取句向量并做 L2 归一化。

        导出格式随 transformers 版本不同，按优先级依次尝试：
        `sentence_embedding`（sentence-transformers）→ `logits[:, 0]`（causal LM 风格）
        → `last_hidden_state` 的首 token。
        """

        import numpy as np

        raw = named.get("sentence_embedding")
        if raw is None and "logits" in named:
            raw = np.asarray(named["logits"], dtype=np.float32)[:, 0]
        if raw is None and "last_hidden_state" in named:
            raw = np.asarray(named["last_hidden_state"], dtype=np.float32)[:, 0]
        if raw is None:
            raise ProviderRequestFailed(
                "ONNX 模型未输出可用的句向量", detail=f"可用输出：{output_names}"
            )
        dense = np.asarray(raw, dtype=np.float32)
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (dense / norms).astype(np.float32)

    def _sparse_from_outputs(
        self, named: dict[str, Any], inputs: dict[str, Any], output_names: list[str]
    ) -> list[SparseVector]:
        """提取稀疏词项权重。

        复现 FlagEmbedding 的 sparse 通道：
        1. 对每个 token 位置的隐藏向量过 sparse_linear，得到该位置的词项权重；
        2. ReLU 去掉负值；
        3. 按 token id 做 max 归约（同一词出现多次取最大），得到词表维度稀疏向量。

        注意：不能先做句级 mean-pooling 再投影 —— 那样每个文本只会得到一个标量，
        无法形成词项级稀疏向量（已实测确认，见 scripts/probe_sparse_diag.py）。
        """

        import numpy as np

        graph_sparse = named.get("sparse_embedding")
        if graph_sparse is not None:
            return [self._to_sparse(row) for row in np.asarray(graph_sparse, dtype=np.float32)]

        if self._sparse_weight is None:
            raise ProviderRequestFailed(
                "稀疏通道不可用：ONNX 图未导出 sparse_embedding，且未找到 sparse_linear 权重",
                detail=(
                    f"sparse_source={self._sparse_source}；可用输出：{output_names}；"
                    "请运行 scripts/fetch_embedding_model.py 补齐 sparse_linear.pt"
                ),
            )

        tokens = named.get("token_embeddings")
        if tokens is None:
            tokens = named.get("last_hidden_state")
        if tokens is None:
            raise ProviderRequestFailed(
                "稀疏通道需要 token 级嵌入，但图中未输出 token_embeddings",
                detail=f"可用输出：{output_names}",
            )

        token_array = np.asarray(tokens, dtype=np.float32)
        # (batch, seq, hidden) @ (hidden,) -> (batch, seq)
        token_weights = np.maximum(token_array @ self._sparse_weight + self._sparse_bias, 0.0)

        input_ids = np.asarray(inputs["input_ids"])
        attention = np.asarray(inputs["attention_mask"]).astype(bool)
        vectors: list[SparseVector] = []
        for row_weights, row_ids, row_mask in zip(token_weights, input_ids, attention, strict=True):
            keep = row_mask & (row_weights > 0)
            if not keep.any():
                vectors.append(SparseVector(indices=[], values=[]))
                continue
            vocab_ids = row_ids[keep]
            values = row_weights[keep]
            # 同一 token id 可能出现在多个位置，按 max 归约（与 FlagEmbedding 一致）。
            order = np.argsort(vocab_ids, kind="stable")
            sorted_ids = vocab_ids[order]
            sorted_values = values[order]
            unique_ids, first_index = np.unique(sorted_ids, return_index=True)
            reduced = np.maximum.reduceat(sorted_values, first_index)
            vectors.append(self._to_sparse_pairs(unique_ids, reduced))
        return vectors

    def _to_sparse_pairs(self, indices: Any, values: Any) -> SparseVector:
        """按权重从大到小保留前 sparse_top_k 个词项，再按 id 升序输出。"""

        import numpy as np

        if indices.size > self._sparse_top_k:
            top = np.argpartition(values, -self._sparse_top_k)[-self._sparse_top_k :]
            indices = indices[top]
            values = values[top]
        order = np.argsort(indices)
        return SparseVector(
            indices=[int(i) for i in indices[order]],
            values=[float(v) for v in values[order]],
        )

    def _to_sparse(self, row: Any) -> SparseVector:
        import numpy as np

        positive = np.flatnonzero(row > 0)
        if positive.size == 0:
            return SparseVector(indices=[], values=[])
        values = row[positive]
        if positive.size > self._sparse_top_k:
            top = np.argpartition(values, -self._sparse_top_k)[-self._sparse_top_k :]
            positive = positive[top]
            values = values[top]
        order = np.argsort(positive)
        positive = positive[order]
        values = values[order]
        return SparseVector(indices=[int(i) for i in positive], values=[float(v) for v in values])

    def _read_revision(self) -> str:
        """确定模型 revision。

        HuggingFace snapshot 目录名就是 commit hash：`<cache>/models--<org>--<name>/snapshots/<hash>/`。
        模型路径既可能是该目录本身，也可能是其下的 `onnx/` 子目录，两种都要识别。
        """

        candidate = self._model_path
        if (candidate / "sparse_linear.pt").exists() or (candidate / "onnx").exists():
            # 已经指向 snapshot 根目录
            pass
        elif (candidate.parent / "sparse_linear.pt").exists():
            candidate = candidate.parent
        if candidate.parent.name == "snapshots" and candidate.name:
            return candidate.name
        if candidate.name == "snapshots" and self._model_path.name:
            return self._model_path.name
        for name in ("revision.txt", ".revision"):
            path = self._model_path / name
            if path.exists():
                return path.read_text(encoding="utf-8").strip() or UNAVAILABLE
        # 无法确认时如实返回 unavailable，不编造 revision。
        return UNAVAILABLE

    def describe(self) -> dict[str, str]:
        return {
            "backend": "onnx-local",
            "model_id": self._model_id,
            "model_revision": self._read_revision(),
            "model_path": str(self._model_path),
            "dimension": str(self._dimension) if self._dimension else UNAVAILABLE,
            "sparse_source": self._sparse_source,
            "sparse_top_k": str(self._sparse_top_k),
            "onnxruntime": _package_version("onnxruntime"),
            "tokenizers": _package_version("tokenizers"),
        }


#: 页面下拉的候选编码模型（不写死唯一解；VL 系列为多模态，本期索引是文本切片）
EMBEDDING_MODEL_OPTIONS: tuple[str, ...] = (
    "BAAI/bge-m3",
    "Qwen/Qwen3-Embedding-8B",
    "Qwen/Qwen3-Embedding-4B",
    "Qwen/Qwen3-Embedding-0.6B",
    "Qwen/Qwen3-VL-Embedding-8B",
)


class HttpEmbeddingProvider:
    """OpenAI 兼容 /embeddings 服务。

    诚实边界：标准的 `/embeddings` 只返回稠密向量。因此在配置为 `http` 后端时，
    稀疏通道必须另行提供；仅当 `sparse_backend` 也被显式配置时才算混合检索，
    否则调用方会得到 `sparse` 为空的批次，必须在报告中标注为单路检索。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        dimension: int | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._dimension = dimension
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> HttpEmbeddingProvider:
        return cls(
            base_url=settings.embedding_http_base_url,
            api_key=settings.embedding_http_api_key,
            model_id=settings.embedding_model_id,
            dimension=settings.embedding_dimension,
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise ProviderNotConfigured("HTTP 编码服务未声明向量维度")
        return self._dimension

    def available(self) -> bool:
        return bool(self._base_url and self._model_id)

    def _endpoint(self, path: str) -> str:
        """拼出 `/v1/...` 端点：用户填 `https://host` 或 `https://host/v1` 都要能用。"""

        base = self._base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}/v1/{path}"

    def encode(self, texts: list[str], *, is_query: bool = False) -> EmbeddingBatch:
        del is_query
        if not self.available():
            raise ProviderNotConfigured(
                "HTTP 编码服务未配置",
                detail="缺少 ANKER_AGENT_EMBEDDING_HTTP_BASE_URL / ANKER_AGENT_EMBEDDING_MODEL_ID",
            )
        payload = {"model": self._model_id, "input": texts}
        request = urllib.request.Request(
            self._endpoint("embeddings"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}),
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderRequestFailed(
                f"编码服务返回 HTTP {exc.code}",
                detail=exc.read().decode("utf-8", "replace")[:300],
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout("编码服务超时") from exc
        except Exception as exc:
            raise ProviderRequestFailed(
                f"编码服务请求失败：{type(exc).__name__}", detail=str(exc)[:300]
            ) from exc

        data = sorted(body.get("data") or [], key=lambda item: item.get("index", 0))
        dense = [item["embedding"] for item in data]
        if not dense:
            raise ProviderRequestFailed("编码服务返回空向量列表")
        self._dimension = len(dense[0])
        return EmbeddingBatch(
            dense=dense,
            sparse=[SparseVector(indices=[], values=[]) for _ in dense],
            dimension=self._dimension,
            model_id=body.get("model") or self._model_id,
            model_revision=UNAVAILABLE,
            sparse_model_id=UNAVAILABLE,
            sparse_model_revision=UNAVAILABLE,
            tokenizer_revision=UNAVAILABLE,
            latency_seconds=time.perf_counter() - started,
        )

    def describe(self) -> dict[str, str]:
        return {
            "backend": "http",
            "model_id": self._model_id,
            "base_url_set": str(bool(self._base_url)),
            "dimension": str(self._dimension) if self._dimension else UNAVAILABLE,
        }


class MockEmbeddingProvider:
    """确定性伪向量，仅用于自动化测试。

    构造函数要求显式 `reason`，避免在生产路径上被无意启用。
    """

    def __init__(
        self, *, dimension: int = 64, model_id: str = "mock-embedding", reason: str = ""
    ) -> None:
        if not reason:
            raise ValueError("MockEmbeddingProvider 必须说明使用理由（reason）")
        self._dimension = dimension
        self._model_id = model_id
        self.reason = reason

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def available(self) -> bool:
        return True

    def encode(self, texts: list[str], *, is_query: bool = False) -> EmbeddingBatch:
        del is_query
        if not texts:
            raise ProviderRequestFailed("编码输入为空")
        dense: list[list[float]] = []
        sparse: list[SparseVector] = []
        for text in texts:
            raw = [0.0] * self._dimension
            counts: dict[int, float] = {}
            for token in text:
                bucket = (ord(token) * 31) % self._dimension
                raw[bucket] += 1.0
                counts[bucket] = counts.get(bucket, 0.0) + 1.0
            norm = math.sqrt(sum(value * value for value in raw)) or 1.0
            dense.append([value / norm for value in raw])
            indices = sorted(counts)
            sparse.append(
                SparseVector(indices=indices, values=[counts[index] for index in indices])
            )
        return EmbeddingBatch(
            dense=dense,
            sparse=sparse,
            dimension=self._dimension,
            model_id=self._model_id,
            model_revision="mock",
            sparse_model_id=f"{self._model_id}#sparse",
            sparse_model_revision="mock",
            tokenizer_revision="mock",
            latency_seconds=0.0,
            is_mock=True,
        )

    def describe(self) -> dict[str, str]:
        return {
            "backend": "mock",
            "model_id": self._model_id,
            "reason": self.reason,
            "dimension": str(self._dimension),
        }


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """按配置构建编码适配器。

    注意：`run_mode=mock` 时才允许 mock 后端；live 模式下若配置为 mock，
    直接报错而不是悄悄降级。
    """

    if settings.embedding_backend == "mock":
        if settings.run_mode != "mock":
            raise ProviderNotConfigured(
                "live 模式不允许 mock 编码后端",
                detail="如需联调请显式设置 ANKER_AGENT_RUN_MODE=mock，并在报告中标注",
            )
        return MockEmbeddingProvider(reason="run_mode=mock 的显式测试配置")
    if settings.embedding_backend == "http":
        return HttpEmbeddingProvider.from_settings(settings)

    model_path = settings.embedding_model_path
    if not model_path:
        model_path = str(default_model_dir(settings.embedding_model_id) / "onnx")
    return OnnxLocalEmbeddingProvider(model_id=settings.embedding_model_id, model_path=model_path)


def default_model_dir(repo_id: str, cache_root: Path | None = None) -> Path:
    """定位 snapshot_download 落盘后的模型目录。

    优先使用 `ANKER_AGENT_MODEL_CACHE`，否则使用 `%LOCALAPPDATA%\\anker-agent\\models`，
    与 `scripts/fetch_embedding_model.py` 保持一致。
    """

    import os

    root = cache_root
    if root is None:
        override = os.environ.get("ANKER_AGENT_MODEL_CACHE")
        if override:
            root = Path(override)
        else:
            local = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
            root = Path(local) / "anker-agent" / "models"
    folder = "models--" + repo_id.replace("/", "--")
    snapshots = root / folder / "snapshots"
    if not snapshots.exists():
        return root / folder
    revisions = sorted(
        (path for path in snapshots.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return revisions[0] if revisions else root / folder
