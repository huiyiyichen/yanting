"""Export current-source OpenAPI without starting a runtime or listening service."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.domain.enums import enum_values  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    destination = REPO / "data/runtime/contracts-export/openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    for path, payload in (
        (destination, create_app().openapi()),
        (destination.with_suffix(".enums.json"), enum_values()),
    ):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Exported current-source contracts to data/runtime/contracts-export; runtime not started.")


if __name__ == "__main__":
    main()
