"""检查 bge-m3 ONNX 计算图的实际输入输出名称与稀疏权重可用性。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.integrations.embedding_provider import default_model_dir  # noqa: E402


def main() -> int:
    import onnxruntime as ort

    settings = Settings()
    snapshot = default_model_dir(settings.embedding_model_id)
    onnx_dir = snapshot / "onnx"
    session = ort.InferenceSession(
        str(onnx_dir / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    report = {
        "snapshot_dir": str(snapshot),
        "snapshot_files": sorted(p.name for p in snapshot.iterdir()),
        "inputs": [
            {"name": i.name, "shape": i.shape, "type": i.type} for i in session.get_inputs()
        ],
        "outputs": [
            {"name": o.name, "shape": o.shape, "type": o.type} for o in session.get_outputs()
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
