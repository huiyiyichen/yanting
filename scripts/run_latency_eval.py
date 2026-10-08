"""响应时延评测（PRD AC-16）。

口径严格按 PRD 第 7 节说明：
- 计时区间为「后端接受有效输入」到「本轮完整、校验后的回复或明确失败状态」；
- 文本样本量 >= 20，逐个记录，**不剔除失败**，失败单列；
- 报告硬件、模型、冷/热启动、失败率与样本量；
- 不用首 token 代替完整响应；人工等待不计入（本探针无人工环节）。

用法（在 services/api 下，需要后端已在运行）：
    .\.venv\Scripts\python.exe ..\..\scripts\run_latency_eval.py --base-url http://127.0.0.1:8000 --samples 20

输出：`code/evals/results/latency-text-<UTC>.json`，同时打印摘要。
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "evals" / "results"

CUSTOMER_HEADERS = {"X-Demo-View-Role": "customer", "content-type": "application/json"}

# 覆盖不同路径：知识检索、事实补问、排障、低风险兜底。
# 每条都会真实走一遍 F1 理解 → 路由 → 工具/检索 → 回复生成。
SAMPLE_MESSAGES = [
    "无线吸尘器吸力明显减弱，应该按什么顺序排查？",
    "滤芯清洗后可以直接装回使用吗？",
    "我的吸尘器在保修期内坏了，怎么申请换货？",
    "扫地机器人拖地之后地面上一直有水，怎么处理？",
    "电池续航比刚买时短了一半，正常吗？",
    "尘盒满了会影响吸力吗？",
    "刷头缠了头发要多久清理一次？",
    "充电时指示灯一直闪红灯是什么意思？",
    "机器充不上电了，插上充电座没有反应",
    "噪音突然变得很大，是不是电机坏了？",
    "在第三方店铺买的，还能享受质保吗？",
    "我想退款，需要准备什么材料？",
    "收到货发现有划痕，可以换新吗？",
    "滤网多久需要更换一次？",
    "边刷不转了，自己能修吗？",
    "机器总是卡在地毯边缘，怎么调整？",
    "集尘袋可以用水洗吗？",
    "APP 连不上机器，一直提示配对失败",
    "滚刷被卡住之后就不转了",
    "保修期是多久？",
]


def _post_json(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object] | None, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=CUSTOMER_HEADERS, method="POST")
    try:
        with request.urlopen(req, timeout=120) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw), ""
    except error.HTTPError as exc:
        return exc.code, None, exc.read().decode("utf-8", "replace")[:400]
    except Exception as exc:  # noqa: BLE001
        return 0, None, str(exc)[:400]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--run-mode", default="live")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    samples = SAMPLE_MESSAGES[: args.samples]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results: list[dict[str, object]] = []

    print(f"[latency] 目标 {base}，样本 {len(samples)} 条，模式 {args.run_mode}")
    for index, message in enumerate(samples, start=1):
        created_at = datetime.now(UTC).isoformat()
        status, created, err = _post_json(
            f"{base}/api/customer/conversations", {"customerId": "CUST-DEMO-01"}
        )
        if status != 200 or not created:
            results.append(
                {
                    "index": index,
                    "message": message,
                    "ok": False,
                    "status": status,
                    "error": err or "创建会话失败",
                    "elapsed_seconds": None,
                }
            )
            print(f"  [{index:02d}] 创建会话失败 status={status} {err[:80]}")
            continue

        conversation_id = str(created["conversationId"])
        # 计时只覆盖消息处理本身：从发出请求到收到完整回复
        started = time.perf_counter()
        status, payload, err = _post_json(
            f"{base}/api/customer/conversations/{conversation_id}/messages",
            {"body": message, "clientMessageKey": f"lat-{stamp}-{index}"},
        )
        elapsed = time.perf_counter() - started

        reply_text = ""
        if payload:
            reply = payload.get("reply") or payload.get("assistantMessage") or {}
            if isinstance(reply, dict):
                reply_text = str(reply.get("body") or "")
        ok = status == 200 and bool(reply_text.strip())
        results.append(
            {
                "index": index,
                "message": message,
                "conversation_id": conversation_id,
                "ok": ok,
                "status": status,
                "elapsed_seconds": round(elapsed, 3),
                "reply_chars": len(reply_text),
                "error": None if ok else (err or "无回复内容"),
                "started_at": created_at,
            }
        )
        mark = "OK " if ok else "FAIL"
        print(f"  [{index:02d}] {mark} {elapsed:6.3f}s chars={len(reply_text):4d} {message[:22]}")

    successes = [item for item in results if item["ok"]]
    failures = [item for item in results if not item["ok"]]
    elapsed_values = sorted(float(item["elapsed_seconds"]) for item in successes)

    def percentile(values: list[float], ratio: float) -> float | None:
        if not values:
            return None
        # 最近秩法：P95 = 第 ceil(0.95 * n) 个（1 基）
        rank = max(1, min(len(values), int(-(-len(values) * ratio // 1))))
        return round(values[rank - 1], 3)

    text_p95 = percentile(elapsed_values, 0.95)
    summary = {
        "samples": len(samples),
        "successes": len(successes),
        "failures": len(failures),
        "failure_rate": round(len(failures) / len(samples), 4) if samples else None,
        "text_p50_seconds": round(statistics.median(elapsed_values), 3) if elapsed_values else None,
        "text_p95_seconds": text_p95,
        "text_max_seconds": round(max(elapsed_values), 3) if elapsed_values else None,
        "text_min_seconds": round(min(elapsed_values), 3) if elapsed_values else None,
        "target_text_p95_seconds": 10.0,
        "meets_text_target": (text_p95 is not None and text_p95 <= 10.0),
        "cold_start_seconds": results[0]["elapsed_seconds"] if results else None,
    }

    report = {
        "note": "本报告基于虚构夹具与本机 Demo 后端；不得作为线上业务指标。",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": __import__("os").cpu_count(),
        },
        "config": {
            "run_mode": args.run_mode,
            "base_url": base,
            "model_id": args.model,
            "sample_count": len(samples),
            "measurement": "后端接受有效输入到完整回复返回（不含人工等待）",
        },
        "summary": summary,
        "results": results,
        "failures": failures,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"latency-text-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[latency] 摘要")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[latency] 报告：{out.relative_to(REPO_ROOT)}")
    if failures:
        print(f"[latency] 失败 {len(failures)} 条（未剔除，已单列）")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
