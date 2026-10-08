"""干净环境复现（S5 退出条件）。

**复现什么**：从「只有源码 + 知识源 + 夹具」的状态出发，不借助任何既有运行数据，
按运行手册的命令把系统重新建起来，并确认核心链路真的可用。

**为什么用独立运行目录**：`data/runtime` 里还有开发期的会话数据（截图与联调用的）。
本脚本用 `data/runtime-clean` 做真正的从零重建，全程不碰开发库；脚本结束即清理。

执行步骤（全部真实运行，不跳过）：
1. 删掉并重建运行目录（模拟「新克隆后还没有运行数据」）；
2. 启动后端 → 确认运行目录与库被自动创建（健康检查 `knowledge_index: unavailable`，
   因为此时还没导入知识——这正是干净状态的应有表现）；
3. 对 16 份知识源执行导入（解析→切片→编码→暂存快照→校验→激活）；
4. 对发布后的索引做检索探针，确认命中且能给出证据与来源；
5. 再次健康检查，确认 `knowledge_index: ready`；
6. 结束后清理该运行目录。

用法（在 `code` 根目录）：
    .\services\api\.venv\Scripts\python.exe scripts/run_clean_reproduction.py

输出：`code/evals/results/clean-reproduction-<UTC>.json`
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_API = REPO_ROOT / "services" / "api"
PYTHON = SERVICES_API / ".venv" / "Scripts" / "python.exe"
RESULTS_DIR = REPO_ROOT / "evals" / "results"

RUNTIME_REL = "data/runtime-clean"
RUNTIME = REPO_ROOT / RUNTIME_REL


def http_json(url: str) -> tuple[int, object]:
    try:
        with request.urlopen(url, timeout=20) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)[:200]


def wait_health(url: str, attempts: int = 60) -> object | None:
    for _ in range(attempts):
        time.sleep(0.5)
        status, payload = http_json(url)
        if status == 200 and isinstance(payload, dict):
            return payload
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8014)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    steps: list[dict[str, object]] = []

    def record(step: str, ok: bool, detail: object = None) -> None:
        steps.append({"step": step, "ok": ok, "detail": detail})
        print(f"  [{'OK ' if ok else 'FAIL'}] {step}" + (f" — {detail}" if detail else ""))

    # ── 1) 从零开始：删掉运行目录 ─────────────────────────────────────────
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    record("清空运行目录（模拟新克隆）", not RUNTIME.exists(), RUNTIME_REL)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["ANKER_AGENT_DATABASE_URL"] = f"sqlite+pysqlite:///{RUNTIME_REL}/clean.sqlite3"
    env["ANKER_AGENT_RUNTIME_DIR"] = RUNTIME_REL
    env["ANKER_AGENT_QDRANT_PATH"] = f"{RUNTIME_REL}/qdrant"

    server = subprocess.Popen(  # noqa: S603
        [str(PYTHON), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(SERVICES_API), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # ── 2) 首次启动：自动建运行目录与库 ───────────────────────────────
        health = wait_health(f"{base}/api/health")
        if health is None:
            record("后端首次启动", False, "健康检查未就绪")
            raise SystemExit(1)
        record("后端首次启动（自动创建运行目录与空库）", True, health.get("status"))
        first_index_state = (health.get("knowledgeIndex") or {}).get("state")
        record(
            "干净状态下知识索引为 unavailable（符合预期，尚未导入）",
            first_index_state == "unavailable",
            f"knowledgeIndex={first_index_state}",
        )
        record(
            "数据库能力就绪",
            (health.get("database") or {}).get("state") == "ready",
            f"database={(health.get('database') or {}).get('state')}",
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
    time.sleep(0.8)

    # ── 3) 导入知识（真实编码 16 份文档）────────────────────────────────
    ingest = subprocess.run(  # noqa: S603
        [str(PYTHON), str(REPO_ROOT / "scripts" / "ingest_knowledge.py"), "--json"],
        cwd=str(SERVICES_API), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800,
    )
    ingest_payload: object = None
    if ingest.stdout:
        try:
            ingest_payload = json.loads(ingest.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            ingest_payload = ingest.stdout[-500:]
    record(
        "知识导入（解析→切片→编码→发布快照）",
        ingest.returncode == 0,
        (ingest_payload if not isinstance(ingest_payload, str) else ingest_payload[:300]),
    )
    if ingest.returncode != 0:
        print("导入 stderr 尾部：", (ingest.stderr or "")[-600:])

    # ── 4) 重启后端并做检索探针 ─────────────────────────────────────────
    server = subprocess.Popen(  # noqa: S603
        [str(PYTHON), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=str(SERVICES_API), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        health = wait_health(f"{base}/api/health")
        record("导入后重启后端", health is not None)
        second_index_state = ((health or {}).get("knowledgeIndex") or {}).get("state")
        record(
            "知识索引变为 ready",
            second_index_state == "ready",
            f"knowledgeIndex={second_index_state}",
        )

        probe = subprocess.run(  # noqa: S603
            [str(PYTHON), str(REPO_ROOT / "scripts" / "probe_retrieval.py"),
             "--query", "无线吸尘器吸力明显减弱，应该按什么顺序排查？"],
            cwd=str(SERVICES_API), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
        hit = "sufficient" in (probe.stdout or "")
        evidence_line = next(
            (line.strip() for line in (probe.stdout or "").splitlines()
             if line.strip().startswith("evidence")),
            "",
        )
        record("检索探针命中并给出证据", probe.returncode == 0 and hit, evidence_line)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
    time.sleep(0.8)

    # ── 5) 清理 ────────────────────────────────────────────────────────
    shutil.rmtree(RUNTIME, ignore_errors=True)
    record("清理复现用运行目录", not RUNTIME.exists())
    record("开发运行目录未被触碰", (REPO_ROOT / "data" / "runtime").exists())

    passed = all(bool(item["ok"]) for item in steps)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "note": "在独立运行目录上从零重建；数据源仅 data/knowledge 与 data/fixtures。",
        "scope": (
            "复现范围说明：本次在**同一台机器、同一 Python 环境**下验证了"
            "「无运行数据 → 自动建库 → 导入知识 → 检索可用」这条链路。"
            "「新机器 + 重新安装依赖」部分未执行，不得据此宣称已通过。"
        ),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "steps": steps,
        "result": "passed" if passed else "failed",
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"clean-reproduction-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n结论：{report['result']}")
    print(f"报告：{out.relative_to(REPO_ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
