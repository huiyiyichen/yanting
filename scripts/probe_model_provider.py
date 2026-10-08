"""验证 DeepSeek OpenAI 兼容接口的可用性与能力边界。

用途（S0 / DEP-02 证据）：
1. 确认 base_url + key 能完成一次真实 chat.completions 往返；
2. 确认返回值里实际使用的 model 标识，写入台账时不猜测；
3. 确认该服务是否接受图片输入（决定 AC-01「看图」live 链路是否具备条件）。

本脚本只打印模型标识、耗时和结构化布尔结论，不打印任何密钥。
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

BASE_URL = os.environ.get("ANKER_AGENT_LLM_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("ANKER_AGENT_LLM_API_KEY", "")
MODEL = os.environ.get("ANKER_AGENT_LLM_MODEL", "")
VISION_MODEL = os.environ.get("ANKER_AGENT_LLM_VISION_MODEL", "")


def load_dotenv(path: Path) -> None:
    """把 .env 读入 os.environ；真实环境变量优先，便于临时覆盖。"""

    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def post(base_url: str, api_key: str, path: str, payload: dict, timeout: float = 90.0) -> tuple[int, dict | str, float]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            elapsed = time.perf_counter() - started
            return response.status, json.loads(body), elapsed
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - started
        detail = exc.read().decode("utf-8", "replace")[:400]
        return exc.code, detail, elapsed
    except Exception as exc:
        return -1, f"{type(exc).__name__}: {exc}", time.perf_counter() - started


def png_1x1() -> str:
    """构造一张最小合法 PNG（纯色 1x1），用于探测多模态支持。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / "services" / "api" / ".env")
    base = os.environ.get("ANKER_AGENT_LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("ANKER_AGENT_LLM_API_KEY", "")
    model = os.environ.get("ANKER_AGENT_LLM_MODEL", "")
    vision = os.environ.get("ANKER_AGENT_LLM_VISION_MODEL", "")

    report: dict[str, object] = {
        "base_url_set": bool(base),
        "api_key_set": bool(key),
        "text_model_configured": model or None,
    }
    if not (base and key):
        report["result"] = "SKIPPED_NO_CREDENTIALS"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    status, body, elapsed = post(
        base,
        key,
        "/v1/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "只回复两个字：可用"}],
            "max_tokens": 16,
            "temperature": 0,
        },
    )

    report["text_status"] = status
    report["text_latency_s"] = round(elapsed, 2)
    if status == 200 and isinstance(body, dict):
        report["text_ok"] = True
        report["returned_model"] = body.get("model")
        choices = body.get("choices") or []
        report["text_reply"] = (
            (choices[0].get("message") or {}).get("content", "")[:40] if choices else None
        )
        report["usage"] = body.get("usage")
    else:
        report["text_ok"] = False
        report["text_error"] = body if isinstance(body, str) else json.dumps(body)[:300]

    probe_model = vision or model
    status_v, body_v, elapsed_v = post(
        base,
        key,
        "/v1/chat/completions",
        {
            "model": probe_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这张图是什么颜色？只回一个词。"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{png_1x1()}"},
                        },
                    ],
                }
            ],
            "max_tokens": 16,
            "temperature": 0,
        },
    )
    report["vision_probe_model"] = probe_model
    report["vision_status"] = status_v
    report["vision_latency_s"] = round(elapsed_v, 2)
    if status_v == 200 and isinstance(body_v, dict):
        report["vision_ok"] = True
        choices_v = body_v.get("choices") or []
        report["vision_reply"] = (
            (choices_v[0].get("message") or {}).get("content", "")[:40] if choices_v else None
        )
    else:
        report["vision_ok"] = False
        report["vision_error"] = body_v if isinstance(body_v, str) else json.dumps(body_v)[:300]

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
