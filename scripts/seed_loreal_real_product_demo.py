"""Create one natural image-reception demo with a public L'Oreal product image.

The image is downloaded from the product registry into runtime data and then sent
through the same customer upload/message path used by the browser.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

BASE = "http://127.0.0.1:8000"
CUSTOMER = {"X-Demo-View-Role": "customer"}
SUPPORT = {"X-Demo-View-Role": "support"}


def product_catalog() -> list[dict]:
    path = REPO / "data" / "knowledge" / "loreal" / "reference-products.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["products"]


def wait_for_reply(client: httpx.Client, conversation_id: str) -> dict:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        queue = client.get("/api/support/reception/queue", headers=SUPPORT)
        queue.raise_for_status()
        item = next(
            row for row in queue.json()["items"]
            if row["conversationId"] == conversation_id
        )
        if item["autoReplyStatus"] not in {"queued", "running"}:
            messages = client.get(
                f"/api/customer/conversations/{conversation_id}/messages",
                headers=CUSTOMER,
            )
            messages.raise_for_status()
            return {
                "queue": item,
                "messages": messages.json(),
            }
        time.sleep(0.5)
    raise TimeoutError("自动接待未在90秒内完成")


def seed_with_client(client, product: dict, image_path: Path) -> dict:
    created = client.post(
        "/api/customer/conversations",
        headers=CUSTOMER,
        json={
            "customerId": "CUST-DEMO-01",
            "title": f"商品识别 · {product['name']}",
        },
    )
    created.raise_for_status()
    conversation_id = created.json()["conversationId"]

    with image_path.open("rb") as handle:
        uploaded = client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            headers=CUSTOMER,
            files={"file": (image_path.name, handle, "image/png")},
        )
    uploaded.raise_for_status()
    attachment_id = uploaded.json()["attachmentId"]

    sent = client.post(
        f"/api/customer/conversations/{conversation_id}/messages",
        headers=CUSTOMER,
        json={
            "body": "亲，这是什么商品呀？",
            "clientMessageKey": f"real-product-{int(time.time())}",
            "attachmentIds": [attachment_id],
        },
    )
    sent.raise_for_status()
    result = wait_for_reply(client, conversation_id)
    replies = [
        item["body"]
        for item in result["messages"]
        if item["senderRole"] == "assistant"
    ]
    return {
        "conversationId": conversation_id,
        "sku": product["sku"],
        "productName": product["name"],
        "image": str(image_path),
        "customerMessage": "亲，这是什么商品呀？",
        "reply": replies[-1] if replies else None,
        "autoReplyStatus": result["queue"]["autoReplyStatus"],
        "serviceMode": result["queue"]["serviceMode"],
    }


@contextmanager
def demo_client(api_url: str, isolated: bool):
    if not isolated:
        with httpx.Client(base_url=api_url, timeout=120, trust_env=False) as client:
            yield client
        return
    from app.config import get_settings
    from app.evaluation.reception_runtime import (
        configured_prompts,
        configured_settings,
        isolated_settings,
        prepare_runtime,
        reception_client,
    )

    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    settings = get_settings()
    target = isolated_settings(
        configured_settings(settings),
        REPO / "data" / "runtime" / f"real-product-demo-{run_key}",
    )
    runtime, _metadata = prepare_runtime(
        target,
        prompt_snapshot=configured_prompts(settings),
    )
    with reception_client(runtime) as client:
        yield client


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", default="LRLWX26013")
    parser.add_argument("--api", default=BASE)
    parser.add_argument("--isolated", action="store_true")
    args = parser.parse_args()

    products = {item["sku"]: item for item in product_catalog()}
    product = products.get(args.sku)
    if product is None:
        raise SystemExit(f"商品资料不存在：{args.sku}")

    image_path = REPO / "data" / "runtime" / f"loreal-product-{args.sku}.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, trust_env=False) as download_client:
        if not image_path.exists():
            image = download_client.get(product["image_url"])
            image.raise_for_status()
            image_path.write_bytes(image.content)

    with demo_client(args.api, args.isolated) as client:
        result = seed_with_client(client, product, image_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
