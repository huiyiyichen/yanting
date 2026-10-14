from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import sys
from contextlib import closing
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo


BASE = Path(__file__).resolve().parents[2]
CODE = BASE / "code"
BUILD = BASE / ".submission-build"
VIDEO = BUILD / "颜听_演示视频.mp4"
NAME = "颜听_作品提交包_20261014"
OUTPUT = BASE / f"{NAME}.zip"
FILES: dict[str, Path] = {}


def add_tree(source: Path, prefix: str) -> None:
    if source.exists():
        for path in sorted(source.rglob("*")):
            if path.is_file():
                relative = path.relative_to(source)
                if any(part in {".locks", "__pycache__", "logs", "model-cache", "validation", "archive"} for part in relative.parts):
                    continue
                if path.name.startswith('.env') or path.suffix in {'.onnx', '.onnx_data', '.safetensors', '.pt'}:
                    continue
                if path.name == ".lock" or path.name.endswith(("-wal", "-shm", "-journal", ".pid", ".log")):
                    continue
                FILES[f"{prefix}/{relative.as_posix()}"] = path


def main() -> None:
    if OUTPUT.exists() and "--replace-generated-archive" not in sys.argv:
        raise FileExistsError(OUTPUT)
    assert VIDEO.is_file()
    secrets = set()
    for env_file in (CODE / "services/api").glob('.env*'):
        if env_file.name.endswith('.example'):
            continue
        for line in env_file.read_text(encoding='utf-8').splitlines():
            key, _, value = line.partition('=')
            value = value.strip().strip('\"\'')
            if re.search(r'(?i)(key|token|secret|password)', key) and len(value) >= 8:
                secrets.add(value.encode())
    with closing(sqlite3.connect((CODE / 'data/runtime/anker_agent.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        for key, value in db.execute('SELECT key, value FROM runtime_setting'):
            if re.search(r'(?i)(key|token|secret|password)', key) and len(value) >= 8:
                secrets.add(value.encode())
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=CODE
    ).decode("utf-8").split("\0")
    for relative in tracked:
        path = CODE / relative
        if relative and path.is_file():
            if path.name.startswith('.env') and path.name != '.env.example':
                continue
            FILES[f"code/{relative}"] = path
    for directory in ("data/source", "data/normalized", "data/index"):
        add_tree(CODE / directory, f"code/{directory}")
    for directory in ('attachments', 'qdrant', 'knowledge-publications', 'public-product-sources', 'real-products'):
        add_tree(CODE / 'data/runtime' / directory, f'code/data/runtime/{directory}')
    FILES['code/data/runtime/anker_agent.sqlite3'] = CODE / 'data/runtime/anker_agent.sqlite3'
    for directory in ("01_PRD", "02_工程规范", "06_前端设计"):
        add_tree(BASE / directory, directory)
    for path in sorted((BASE / "07_路演PPT").glob("*.pptx")):
        FILES[f"07_路演PPT/{path.name}"] = path
    for path in sorted((CODE / 'scripts/submission').iterdir()):
        FILES[path.name] = path
    FILES[f"演示视频/{VIDEO.name}"] = VIDEO
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CODE, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=CODE).decode("utf-8")
    manifest = {"project": "颜听", "packaged_date": "2026-10-14", "source_commit": commit,
                "original_code_root": str(CODE),
                "working_tree_changes": status, "files": []}

    validation = CODE / 'data/runtime/validation/submission'
    validation.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="database-snapshots-", dir=validation) as temporary:
        databases = [(name, path) for name, path in FILES.items() if path.suffix in {".sqlite", ".sqlite3", ".db"}]
        for index, (name, source) in enumerate(databases):
            destination = Path(temporary) / f"{index}.sqlite3"
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
                with closing(sqlite3.connect(destination)) as writer:
                    reader.backup(writer, pages=256)
                    writer.execute("PRAGMA journal_mode=DELETE")
                    writer.execute("PRAGMA secure_delete=ON")
                    tables = {row[0] for row in writer.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if 'runtime_setting' in tables:
                        writer.execute("DELETE FROM runtime_setting WHERE lower(key) LIKE '%key%' OR lower(key) LIKE '%token%' OR lower(key) LIKE '%secret%' OR lower(key) LIKE '%password%' OR key LIKE 'llm.%' OR key LIKE 'embedding.%' OR key LIKE 'rerank.%'")
                        writer.commit()
                        writer.execute('VACUUM')
            FILES[name] = destination
        print(f"Database snapshots: {len(databases)}; package files: {len(FILES)}", flush=True)
        partial = OUTPUT.with_suffix(".zip.partial")
        with ZipFile(partial, "x", allowZip64=True, compression=ZIP_DEFLATED, compresslevel=3) as archive:
            for index, (relative, path) in enumerate(sorted(FILES.items()), 1):
                size = path.stat().st_size
                stored = path.suffix in {".mkv", ".mp4", ".onnx_data", ".pptx", ".png", ".jpg", ".webp"}
                if size >= 100_000_000:
                    print(f"Packing {relative}: {size:,} bytes", flush=True)
                digest = hashlib.sha256()
                info = ZipInfo(f"{NAME}/{relative}", datetime.now().timetuple()[:6])
                info.file_size = size
                info.compress_type = ZIP_STORED if stored else ZIP_DEFLATED
                # The file is hashed as it is written, including the complete original video.
                with path.open("rb") as source, archive.open(info, "w", force_zip64=size >= 2**30) as target:
                    tail = b''
                    while chunk := source.read(4 * 1024 * 1024):
                        if any(secret in tail + chunk for secret in secrets):
                            raise RuntimeError(f'Credential detected in package file: {relative}')
                        tail = chunk[-max((len(secret) for secret in secrets), default=1):]
                        target.write(chunk)
                        digest.update(chunk)
                manifest["files"].append({"path": relative, "bytes": size, "sha256": digest.hexdigest()})
                if index % 250 == 0:
                    print(f"Packed {index}/{len(FILES)}", flush=True)
            archive.writestr(f"{NAME}/文件清单.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        print("Checking archive integrity...", flush=True)
        with ZipFile(partial) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"Archive checksum mismatch: {bad}")
            video = archive.getinfo(f"{NAME}/演示视频/{VIDEO.name}")
            assert video.file_size == VIDEO.stat().st_size
            assert len(archive.namelist()) == len(FILES) + 1
            assert not any("/model-cache/" in name for name in archive.namelist())
        assert partial.stat().st_size < 1_000_000_000
        partial.replace(OUTPUT)
    print(json.dumps({"archive": str(OUTPUT), "bytes": OUTPUT.stat().st_size,
                      "files": len(FILES) + 1, "source_commit": commit,
                      "video_bytes": VIDEO.stat().st_size, "integrity": "passed"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
