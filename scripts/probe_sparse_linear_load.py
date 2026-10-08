"""验证能否不依赖 torch，直接读取 bge-m3 的 sparse_linear 权重。

背景：bge-m3 的 ONNX 导出只包含 token_embeddings 与 sentence_embedding，
稀疏（词项权重）通道需要额外的 sparse_linear 线性层权重，官方以 .pt 提供。
安装 torch 只为了读一个 1x1024 的线性层会引入约 2GB 依赖，因此这里验证
用标准库 zipfile + pickle 读取 storage 字节、再用 numpy 还原张量的可行性。

只读取张量结构与数值统计，不写出权重内容。
"""

from __future__ import annotations

import io
import json
import pickle
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.integrations.embedding_provider import default_model_dir  # noqa: E402


class _StorageReader:
    """兼容旧引用；实际解析由 _UnpicklerWithTorch 完成。"""

    def __init__(self, archive: zipfile.ZipFile, prefix: str) -> None:
        self._archive = archive
        self._prefix = prefix

    def __call__(self, storage: Any) -> Any:
        import numpy as np

        name = f"{self._prefix}/data/{storage.key}"
        raw = self._archive.read(name)
        dtype = _TORCH_DTYPE_TO_NUMPY.get(str(storage.dtype))
        if dtype is None:
            raise ValueError(f"未映射的 dtype：{storage.dtype}")
        count = storage.numel()
        return np.frombuffer(raw, dtype=dtype, count=count)


_TORCH_DTYPE_TO_NUMPY = {
    "torch.float32": "float32",
    "torch.float16": "float16",
    "torch.float64": "float64",
    "torch.int64": "int64",
    "torch.int32": "int32",
    "torch.bool": "bool",
}

# 归档内 storage 的类名与 dtype 对应关系（legacy .pt 用这些类名标记元素类型）。
_STORAGE_CLASS_TO_DTYPE = {
    "FloatStorage": "float32",
    "HalfStorage": "float16",
    "DoubleStorage": "float64",
    "LongStorage": "int64",
    "IntStorage": "int32",
    "BoolStorage": "bool",
    "ByteStorage": "uint8",
}


class _FakeTensor:
    """仅承载元数据，真正的数值在 unpickle 后由 _rebuild_tensor_v2 组装。"""

    __slots__ = ()


class _TorchModule:
    """让 pickle 能解析 `torch.X` 名字，返回一个可调用的占位类。"""

    def __init__(self) -> None:
        self._cache: dict[str, type] = {}

    def __getattr__(self, name: str) -> type:
        if name not in self._cache:
            self._cache[name] = type(name, (_FakeTensor,), {})
        return self._cache[name]


def _rebuild_tensor(storage: Any, storage_offset: int, size: Any, stride: Any, *_: Any) -> Any:
    """复现 torch._utils._rebuild_tensor_v2 的核心语义。"""


    array = storage.array
    if storage_offset:
        array = array[storage_offset:]
    count = 1
    for dim in size:
        count *= int(dim)
    flat = array[:count]
    if len(size) == 1:
        return flat.copy()
    return flat.reshape([int(dim) for dim in size], order="C").copy()


class _TorchRebuild:
    """替代 `torch._utils`，提供 _rebuild_tensor_v2。"""

    _rebuild_tensor_v2 = staticmethod(_rebuild_tensor)
    _rebuild_tensor = staticmethod(_rebuild_tensor)
    _rebuild_parameter = staticmethod(lambda data, *_: data)


class _TorchClasses:
    """替代 `torch` 顶层模块：解析各 Storage 类名。"""

    _utils = _TorchRebuild()

    def __init__(self) -> None:
        self._cache: dict[str, type] = {}

    def __getattr__(self, name: str) -> type:
        if name not in self._cache:
            self._cache[name] = type(name, (_FakeTensor,), {})
        return self._cache[name]


class _Storage:
    """storage 引用：记录 key 与元素类型，数值延迟到归档读取时填充。"""

    __slots__ = ("array", "dtype_name", "key", "location", "numel")

    def __init__(self, key: str, dtype_name: str, location: str, numel: int) -> None:
        self.key = key
        self.dtype_name = dtype_name
        self.location = location
        self.numel = numel
        self.array: Any = None


class _UnpicklerWithTorch(pickle.Unpickler):
    """把 torch 相关全局名解析成轻量替身，避免安装 torch。"""

    def find_class(self, module: str, name: str) -> Any:
        if module == "torch._utils":
            return getattr(_TorchRebuild, name)
        if module == "torch":
            if name in _STORAGE_CLASS_TO_DTYPE:
                return _make_storage_factory(name)
            return getattr(_TorchClasses(), name)
        return super().find_class(module, name)


def _make_storage_factory(class_name: str) -> type:
    dtype_name = _STORAGE_CLASS_TO_DTYPE[class_name]

    class _StorageFactory(_FakeTensor):
        def __new__(cls, key: str, location: str = "cpu", numel: int = 0) -> _Storage:  # type: ignore[misc]
            return _Storage(key, dtype_name, location, int(numel))

    _StorageFactory.__name__ = class_name
    return _StorageFactory


def load_pt(path: Path) -> dict[str, Any]:
    """读取 legacy .pt（zip + pickle）中的张量，返回 name -> numpy 数组。"""

    import numpy as np

    result: dict[str, Any] = {}
    with zipfile.ZipFile(path) as archive:
        pkl_name = next(n for n in archive.namelist() if n.endswith("data.pkl"))
        prefix = pkl_name.rsplit("/", 1)[0]

        def persistent_load(storage: Any) -> _Storage:
            # persistent_load 的入参形式取决于 pickle 里 storage 的构造方式：
            # 既可能是我们替身类返回的 _Storage，也可能是原始的
            # (storage_type, key, location, numel) 元组。两种都要支持。
            if isinstance(storage, tuple):
                # legacy .pt 的 persistent id 形状为
                # ('storage', <StorageClass>, key, location, numel)
                if len(storage) >= 5 and storage[0] == "storage":
                    _, storage_type, key, location, numel = storage[:5]
                elif len(storage) >= 4:
                    storage_type, key, location, numel = storage[:4]
                else:
                    raise ValueError(f"无法解析的 storage 元组：{storage!r}")
                class_name = getattr(storage_type, "__name__", "")
                dtype_name = _STORAGE_CLASS_TO_DTYPE.get(class_name)
                if dtype_name is None:
                    raise ValueError(f"未识别的 storage 类型：{class_name!r}")
                resolved = _Storage(str(key), dtype_name, str(location), int(numel))
            else:
                resolved = storage

            dtype = _TORCH_DTYPE_TO_NUMPY.get(f"torch.{resolved.dtype_name}")
            if dtype is None:
                raise ValueError(f"未映射的存储类型：{resolved.dtype_name}")
            raw = archive.read(f"{prefix}/data/{resolved.key}")
            array = np.frombuffer(raw, dtype=dtype)
            if resolved.numel and array.size != resolved.numel:
                raise ValueError(
                    f"storage {resolved.key} 元素数不符：{array.size} != {resolved.numel}"
                )
            resolved.array = array
            return resolved

        unpickler = _UnpicklerWithTorch(io.BytesIO(archive.read(pkl_name)))
        unpickler.persistent_load = persistent_load  # type: ignore[method-assign]
        obj = unpickler.load()

    def walk(node: Any, trail: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{trail}.{key}" if trail else str(key))
        elif isinstance(node, np.ndarray):
            result[trail] = node

    walk(obj)
    return result


def main() -> int:
    settings = Settings()
    snapshot = default_model_dir(settings.embedding_model_id)
    report: dict[str, Any] = {"snapshot": str(snapshot)}

    for filename in ("sparse_linear.pt", "colbert_linear.pt"):
        path = snapshot / filename
        try:
            tensors = load_pt(path)
            report[filename] = {
                "ok": True,
                "tensor_count": len(tensors),
                "tensors": {
                    name: {
                        "shape": list(array.shape),
                        "dtype": str(array.dtype),
                        "min": float(array.min()),
                        "max": float(array.max()),
                    }
                    for name, array in tensors.items()
                },
            }
        except Exception as exc:
            report[filename] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    ok = all(report.get(f, {}).get("ok") for f in ("sparse_linear.pt", "colbert_linear.pt"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
