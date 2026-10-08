"""检查 sparse_linear.pt / colbert_linear.pt 的实际结构，确认能否手工复现稀疏通道。

bge-m3 的 ONNX 导出只到 token_embeddings / sentence_embedding；
官方 FlagEmbedding 的稀疏权重由独立的 sparse_linear 线性层（作用于 token 嵌入）得到。
本脚本用 zipfile 读取 pt 内的张量名与形状，不依赖 torch。
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.integrations.embedding_provider import default_model_dir  # noqa: E402


def inspect(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith(".data"):
                # PyTorch 归档里张量元数据存放在 <name>/data.pkl，这里只取条目与大小。
                entries.append({"entry": name, "size": archive.getinfo(name).file_size})
    return {"exists": True, "path": str(path), "entries": entries}


def main() -> int:
    settings = Settings()
    snapshot = default_model_dir(settings.embedding_model_id)
    report = {
        "snapshot": str(snapshot),
        "files": sorted(p.name for p in snapshot.iterdir()),
        "sparse_linear": inspect(snapshot / "sparse_linear.pt"),
        "colbert_linear": inspect(snapshot / "colbert_linear.pt"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
