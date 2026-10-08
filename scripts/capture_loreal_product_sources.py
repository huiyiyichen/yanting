"""Capture bounded public-brand evidence without prices or business-data writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
ORIGIN = "https://www.lorealparis.com.cn"
IMAGE_HOST = "res-wxec-unipt.lorealchina.com"


def capture(goods_id: str, directory: Path, *, images: int, start: int = 0) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9]{12,40}", goods_id):
        raise ValueError("Invalid public product identifier")
    url = f"{ORIGIN}/api/ec-portal/store/pl/goods/{goods_id}"
    with httpx.Client(trust_env=False, timeout=25) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("id") != goods_id or data.get("type") != "GOODS":
            raise ValueError("Public source identity mismatch")
        receipt = {
            "sourceUrl": url, "capturedAt": datetime.now(UTC).isoformat(),
            "responseSha256": hashlib.sha256(response.content).hexdigest(),
            "scope": "public_cn_brand_record_not_personal_suitability",
            "goods": {key: data.get(key) for key in (
                "id", "code", "name", "shortName", "description", "arguments", "usageMode",
            )},
            "specs": [{key: item.get(key) for key in (
                "id", "code", "name", "description", "specifications", "mainImage",
            )} for item in data.get("specs", [])],
            "detailImages": [],
        }
        directory.mkdir(parents=True, exist_ok=True)
        for index, image_url in enumerate(data.get("detailImages", [])[start:start + images], start):
            parsed = httpx.URL(image_url)
            if parsed.scheme != "https" or parsed.host != IMAGE_HOST:
                raise ValueError("Detail image must come from the brand's public host")
            image = client.get(image_url)
            image.raise_for_status()
            if len(image.content) > 12 * 1024 * 1024:
                raise ValueError("Public image exceeded capture budget")
            if "image/" not in image.headers.get("content-type", ""):
                raise ValueError("Public detail asset is not an image")
            suffix = Path(parsed.path).suffix.lower()
            if suffix not in {".jpg", ".png", ".webp"}:
                raise ValueError("Unsupported public detail image")
            destination = directory / f"detail-{index}{suffix}"
            destination.write_bytes(image.content)
            receipt["detailImages"].append({
                "sourceUrl": image_url, "file": destination.name,
                "sha256": hashlib.sha256(image.content).hexdigest(),
            })
        (directory / "receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("goods_id")
    parser.add_argument("--images", type=int, choices=range(0, 7), default=0)
    parser.add_argument("--start", type=int, choices=range(0, 31), default=0)
    args = parser.parse_args()
    root = REPO / "data/runtime/public-product-sources"
    directory = root / f"{args.goods_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    receipt = capture(args.goods_id, directory, images=args.images, start=args.start)
    print(json.dumps({
        "directory": str(directory), "name": receipt["goods"]["name"],
        "responseSha256": receipt["responseSha256"],
        "specs": receipt["specs"], "images": len(receipt["detailImages"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
