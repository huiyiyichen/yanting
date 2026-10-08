"""无 torch 依赖地读取 legacy PyTorch `.pt` 检查点。

为什么需要本模块：bge-m3 的 ONNX 导出只到 `token_embeddings` / `sentence_embedding`，
稀疏（词项权重）通道所需的 `sparse_linear` 权重只以 legacy `.pt` 形式提供。
官方 FlagEmbedding 依赖 torch 读取它；本项目只需读取一个 1x1024 的线性层，
为它引入约 2GB 的 torch 依赖不划算，因此这里用标准库 zipfile + pickle 复现
`torch.load` 的最小语义。

安全说明：只在本地加载官方模型仓库的权重文件，不加载任何用户上传的 `.pt`。
本模块按需读取 storage 字节后再还原张量，避免把任意 pickle 交给 `torch.load`。
"""

from __future__ import annotations

import io
import pickle
import zipfile
from pathlib import Path
from typing import Any

__all__ = ["TorchFreeCheckpointError", "load_legacy_pt"]


class TorchFreeCheckpointError(RuntimeError):
    """检查点结构不符合预期。"""


# 归档内 storage 类名 -> numpy dtype
_STORAGE_CLASS_TO_DTYPE: dict[str, str] = {
    "FloatStorage": "float32",
    "HalfStorage": "float16",
    "DoubleStorage": "float64",
    "LongStorage": "int64",
    "IntStorage": "int32",
    "BoolStorage": "bool",
    "ByteStorage": "uint8",
    "CharStorage": "int8",
    "ShortStorage": "int16",
    "BFloat16Storage": "bfloat16",
}

_TORCH_DTYPE_TO_NUMPY: dict[str, str] = {
    "torch.float32": "float32",
    "torch.float16": "float16",
    "torch.float64": "float64",
    "torch.int64": "int64",
    "torch.int32": "int32",
    "torch.bool": "bool",
}

_TENSOR_STORAGE_OFFSET_INDEX = 1
_TENSOR_SIZE_INDEX = 2


class _StorageRef:
    """storage 引用：记录 key 与元素类型，数值延迟到读取归档时填充。"""

    __slots__ = ("array", "dtype_name", "key", "location", "numel")

    def __init__(self, key: str, dtype_name: str, location: str, numel: int) -> None:
        self.key = key
        self.dtype_name = dtype_name
        self.location = location
        self.numel = numel
        self.array: Any = None


def _make_storage_factory(class_name: str) -> type:
    """生成与 torch Storage 类同名的占位类，供 pickle.find_class 解析。"""

    dtype_name = _STORAGE_CLASS_TO_DTYPE[class_name]

    def _factory(key: str, location: str = "cpu", numel: int = 0) -> _StorageRef:
        return _StorageRef(str(key), dtype_name, str(location), int(numel))

    _factory.__name__ = class_name
    return _factory  # type: ignore[return-value]


def _rebuild_tensor(
    storage: _StorageRef,
    storage_offset: int = 0,
    size: Any = None,
    stride: Any = None,
    *_: Any,
) -> Any:
    """复现 torch._utils._rebuild_tensor_v2 的核心语义（连续张量）。"""

    array = storage.array
    if array is None:
        raise TorchFreeCheckpointError(f"storage {storage.key} 尚未加载字节")
    if storage_offset:
        array = array[storage_offset:]
    shape = [int(dim) for dim in (size or ())]
    count = 1
    for dim in shape:
        count *= dim
    flat = array[:count]
    if not shape:
        return flat.copy()
    if len(shape) == 1:
        return flat.copy()
    return flat.reshape(shape, order="C").copy()


class _TorchUtilsShim:
    """替代 `torch._utils`。"""

    _rebuild_tensor_v2 = staticmethod(_rebuild_tensor)
    _rebuild_tensor = staticmethod(_rebuild_tensor)
    _rebuild_parameter = staticmethod(lambda data, *_: data)


class _TorchShim:
    """替代 `torch` 顶层模块。"""

    _utils = _TorchUtilsShim()

    def __getattr__(self, name: str) -> Any:
        if name in _STORAGE_CLASS_TO_DTYPE:
            return _make_storage_factory(name)
        return type(name, (), {})


class _TorchFreeUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if module == "torch._utils":
            return getattr(_TorchUtilsShim, name)
        if module == "torch":
            return getattr(_TorchShim(), name)
        return super().find_class(module, name)


def load_legacy_pt(path: Path) -> dict[str, Any]:
    """读取 legacy `.pt`（zip + pickle）中的张量。

    返回 `{张量名: numpy.ndarray}`；只保留 ndarray，忽略无关的嵌套字典层级。
    """

    import numpy as np

    if not path.exists():
        raise TorchFreeCheckpointError(f"检查点不存在：{path}")

    tensors: dict[str, Any] = {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        pkl_names = [name for name in names if name.endswith("data.pkl")]
        if not pkl_names:
            raise TorchFreeCheckpointError(f"{path.name} 内未找到 data.pkl")
        pkl_name = pkl_names[0]
        prefix = pkl_name.rsplit("/", 1)[0]

        def persistent_load(payload: Any) -> _StorageRef:
            # legacy .pt 的形状：('storage', <StorageClass>, key, location, numel)
            if isinstance(payload, tuple) and len(payload) >= 5 and payload[0] == "storage":
                _, storage_type, key, location, numel = payload[:5]
            elif isinstance(payload, tuple) and len(payload) >= 4:
                storage_type, key, location, numel = payload[:4]
            else:
                raise TorchFreeCheckpointError(f"无法解析的 storage 载荷：{payload!r}")
            class_name = getattr(storage_type, "__name__", "")
            dtype_name = _STORAGE_CLASS_TO_DTYPE.get(class_name)
            if dtype_name is None:
                raise TorchFreeCheckpointError(f"未识别的 storage 类型：{class_name!r}")
            entry = f"{prefix}/data/{key}"
            if entry not in names:
                raise TorchFreeCheckpointError(f"归档内缺少 storage 字节：{entry}")
            dtype = _TORCH_DTYPE_TO_NUMPY.get(f"torch.{dtype_name}", dtype_name)
            if dtype == "bfloat16":
                raise TorchFreeCheckpointError("暂不支持 bfloat16 storage")
            array = np.frombuffer(archive.read(entry), dtype=dtype)
            if numel and array.size != int(numel):
                raise TorchFreeCheckpointError(f"storage {key} 元素数不符：{array.size} != {numel}")
            # 关键：必须在归档仍打开时读取字节。_rebuild_tensor_v2 在 unpickle
            # 过程中就被调用，而 `with zipfile.ZipFile(...)` 退出后归档即关闭。
            ref = _StorageRef(str(key), dtype_name, str(location), int(numel))
            ref.array = array
            return ref

        unpickler = _TorchFreeUnpickler(io.BytesIO(archive.read(pkl_name)))
        unpickler.persistent_load = persistent_load  # type: ignore[method-assign]
        root = unpickler.load()

    def walk(node: Any, trail: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{trail}.{key}" if trail else str(key))
        elif isinstance(node, np.ndarray):
            tensors[trail] = node

    walk(root)
    if not tensors:
        raise TorchFreeCheckpointError(f"{path.name} 内未解析出任何张量")
    return tensors
