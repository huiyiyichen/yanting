"""Resolve packaged attachment and knowledge paths on the submission computer."""

import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path, PureWindowsPath

root = Path(__file__).resolve().parent
metadata = json.loads((root / "文件清单.json").read_text(encoding="utf-8"))
original = PureWindowsPath(metadata["original_code_root"])
current = root / "code"
columns = (
    ("attachment", "stored_path"),
    ("knowledge_document", "source_abs_path"),
    ("knowledge_import_run", "manifest_path"),
    ("service_import_batch", "snapshot_path"),
)
count = 0
with closing(sqlite3.connect(current / "data/runtime/anker_agent.sqlite3")) as database:
    with database:
        for table, column in columns:
            for rowid, value in database.execute(f'SELECT rowid, "{column}" FROM "{table}"').fetchall():
                source = PureWindowsPath(value or "")
                if source.is_relative_to(original):
                    target = current / Path(*source.relative_to(original).parts)
                    if target.exists():
                        database.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',
                                         (str(target), rowid))
                        count += 1
print(f"Submission data ready: {count} file paths resolved.")

cache = Path(os.environ.get("YANTING_MODEL_CACHE") or
             str(Path(os.environ["LOCALAPPDATA"]) / "anker-agent/models"))
snapshots = cache / "models--BAAI--bge-m3/snapshots"
if not any(snapshots.glob("*/onnx/model.onnx_data")):
    print("Downloading the BGE-M3 embedding model for first startup...")
    subprocess.run(
        ["uv", "run", "--project", str(current / "services/api"), "--extra", "dev",
         "--no-editable", str(current / "scripts/fetch_embedding_model.py"),
         "--repo", "BAAI/bge-m3", "--allow-pattern", "onnx/*"],
        check=True,
    )
