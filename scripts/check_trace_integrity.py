"""追踪完整性检查：读当前配置的数据库，输出分子/分母报告到 evals/results/。

用法（仓库根）：services/api/.venv/bin/python scripts/check_trace_integrity.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.audit.trace_integrity import check  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402


def main() -> int:
    engine = build_engine(get_settings())
    with build_session_factory(engine)() as session:
        report = check(session)
    out = ROOT / "evals" / "results" / f"trace-integrity-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in report["checks"]:
        print(f"{row['check']}: {row['passed']}/{row['total']}")
    print(out)
    return 0 if report["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
