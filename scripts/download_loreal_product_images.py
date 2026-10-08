"""Download three public brand images with their product-source receipts."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path

import httpx
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
SKUS = {"LRLWX26013", "LRLWX26008", "LRLWX26040"}


def main() -> None:
    catalog = json.loads(
        (REPO / "data/knowledge/loreal/reference-products.json").read_text(encoding="utf-8")
    )
    target = REPO / "data/demo-images/loreal"
    target.mkdir(parents=True, exist_ok=True)
    receipts = []
    with httpx.Client(timeout=45, trust_env=False) as client:
        for product in catalog["products"]:
            if product["sku"] not in SKUS:
                continue
            source = client.get(product["source_url"])
            source.raise_for_status()
            if product["image_url"] not in source.text:
                raise ValueError(f"商品图待核对：{product['sku']}")
            response = client.get(product["image_url"])
            response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as image:
                image.verify()
            path = target / f"{product['sku']}.png"
            path.write_bytes(response.content)
            receipts.append({
                "file": path.name, "product_name": product["name"],
                "reference_sku": product["sku"], "source_url": product["source_url"],
                "image_url": product["image_url"],
                "sha256": hashlib.sha256(response.content).hexdigest(),
            })
    (target / "sources.json").write_text(json.dumps({
        "checked_on": date.today().isoformat(), "publisher": "巴黎欧莱雅中国官网",
        "images": receipts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Downloaded {len(receipts)} product images to {target}")


if __name__ == "__main__":
    main()
