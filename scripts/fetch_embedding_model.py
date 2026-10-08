"""下载编码模型到代码仓库之外的缓存目录。

设计原因：编码模型权重（bge-m3 约 4.5GB）属于大数据，不应进入 Git 仓库，
也不应放在 `code/` 内部。默认缓存到 `%LOCALAPPDATA%\\anker-agent\\models`，
可用 ANKER_AGENT_MODEL_CACHE 覆盖。

用法：
    python scripts/fetch_embedding_model.py --repo BAAI/bge-m3 --allow-pattern "onnx/*"
    python scripts/fetch_embedding_model.py --repo BAAI/bge-small-zh-v1.5
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def default_cache() -> Path:
    override = os.environ.get("ANKER_AGENT_MODEL_CACHE")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(local) / "anker-agent" / "models"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="HuggingFace 仓库 ID")
    parser.add_argument(
        "--allow-pattern",
        action="append",
        default=None,
        help="只下载匹配的文件（可重复），缺省下载除 pytorch/colbert 权重外的全部文件",
    )
    parser.add_argument("--cache", default=None)
    args = parser.parse_args()

    # Windows 默认不允许普通用户创建符号链接（WinError 1314），
    # 因此必须先关闭 HF 缓存的 symlink 优化，否则下载在写 pointer 时失败。
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    from huggingface_hub import snapshot_download

    cache = Path(args.cache) if args.cache else default_cache()
    cache.mkdir(parents=True, exist_ok=True)
    patterns = args.allow_pattern
    if patterns is None:
        patterns = [
            "*.json",
            "*.txt",
            "*.model",
            "*.onnx",
            "*.onnx_data",
            "*.safetensors",
            "1_Pooling/*",
        ]
    started = time.perf_counter()
    print(f"downloading {args.repo} -> {cache}")
    print(f"allow_patterns={patterns}")
    path = snapshot_download(
        repo_id=args.repo,
        cache_dir=str(cache),
        allow_patterns=patterns,
        max_workers=4,
    )
    elapsed = time.perf_counter() - started
    total = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    print(f"DONE repo={args.repo} path={path}")
    print(f"elapsed={elapsed:.1f}s size={total / 1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
