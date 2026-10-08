"""输出后端直接依赖的精确版本，用于运行手册与台账登记。"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, distributions, version

DIRECT = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "python-multipart",
    "sqlalchemy",
    "langgraph",
    "langgraph-checkpoint-sqlite",
    "qdrant-client",
    "onnxruntime",
    "huggingface-hub",
    "tokenizers",
    "numpy",
    "jieba",
    "rapidfuzz",
    "pillow",
    "httpx",
    "python-dotenv",
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "ruff",
    "mypy",
]

TRANSITIVE_OF_INTEREST = [
    "starlette",
    "langchain-core",
    "langgraph-checkpoint",
    "protobuf",
    "pyyaml",
    "tenacity",
]


def main() -> int:
    installed = {d.metadata["Name"].lower(): d.version for d in distributions() if d.metadata["Name"]}
    report: dict[str, object] = {
        "python": sys.version.split()[0],
        "direct": {},
        "transitive": {},
    }
    missing: list[str] = []
    for name in DIRECT:
        resolved = installed.get(name)
        if resolved is None:
            try:
                resolved = version(name)
            except PackageNotFoundError:
                missing.append(name)
                continue
        report["direct"][name] = resolved  # type: ignore[index]
    for name in TRANSITIVE_OF_INTEREST:
        if name in installed:
            report["transitive"][name] = installed[name]  # type: ignore[index]
    report["missing"] = missing
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
