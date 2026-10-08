"""Validate source-backed L'Oreal knowledge files without starting the API."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

SOURCE_SHA256 = "b5ac027e863c5580dab39c8f459e4698d65e9fbec29832c9915448f2087307b7"
SOURCE_PATH = REPO / f"data/source/loreal-official-mock/source-{SOURCE_SHA256}.xlsx"
KNOWLEDGE_ROOT = REPO / "data/knowledge/loreal"
PRODUCT_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
SKU_LINE = re.compile(r"^货号：(.+)$", re.MULTILINE)
PRICE_LINE = re.compile(r"^订单单价：(.+)$", re.MULTILINE)
BOUNDARY_LINE = re.compile(r"^成分、功效与适用性：(.+)$", re.MULTILINE)


def source_products(path: Path) -> set[tuple[str, str]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook["订单"].values
        header = next(rows)
        products = set()
        for values in rows:
            row = dict(zip(header, values, strict=True))
            products.add((str(row["商品货号"]), str(row["商品名称"])))
        return products
    finally:
        workbook.close()


def validate(cases_path: Path) -> dict:
    errors: list[str] = []
    manifest = json.loads((KNOWLEDGE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest() != SOURCE_SHA256:
        errors.append("官方虚构源文件哈希不匹配")

    documents = manifest.get("documents", [])
    document_reports = []
    for document in documents:
        source_path = KNOWLEDGE_ROOT / document["source_path"]
        if not source_path.exists():
            errors.append(f"知识文件不存在：{document['source_path']}")
            continue
        text = source_path.read_text(encoding="utf-8")
        document_reports.append({
            "documentId": document["document_id"],
            "path": document["source_path"],
            "version": document["document_version"],
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "characters": len(text),
            "headings": len(PRODUCT_HEADING.findall(text)),
        })

    product_path = KNOWLEDGE_ROOT / "products.md"
    product_text = product_path.read_text(encoding="utf-8")
    sections = product_text.split("\n## ")[1:]
    documented_products: set[tuple[str, str]] = set()
    invalid_product_boundaries = []
    for section in sections:
        lines = section.splitlines()
        name = lines[0].strip()
        sku = SKU_LINE.search("\n".join(lines))
        price = PRICE_LINE.search("\n".join(lines))
        boundary = BOUNDARY_LINE.search("\n".join(lines))
        if sku:
            documented_products.add((sku.group(1).strip(), name))
        if (
            not sku
            or not price
            or not boundary
            or boundary.group(1).strip() != "源文件未提供，不作判断。"
        ):
            invalid_product_boundaries.append(name)
    expected_products = source_products(SOURCE_PATH)
    missing_products = sorted(expected_products - documented_products)
    extra_products = sorted(documented_products - expected_products)
    if missing_products:
        errors.append(f"商品目录缺少{len(missing_products)}个源商品")
    if extra_products:
        errors.append(f"商品目录包含{len(extra_products)}个源文件不存在的商品")
    if invalid_product_boundaries:
        errors.append(f"商品专业信息边界不符合当前资料范围：{len(invalid_product_boundaries)}项")

    service_text = (KNOWLEDGE_ROOT / "service.md").read_text(encoding="utf-8")
    required_service_phrases = [
        "不能根据聊天中的客服说法判断",
        "待审核不等于转账成功",
        "不进行医学诊断",
        "客服先回应消费者表达的困扰",
    ]
    missing_service_phrases = [phrase for phrase in required_service_phrases if phrase not in service_text]
    if missing_service_phrases:
        errors.append(f"服务边界资料缺少{len(missing_service_phrases)}条固定约束")

    return {
        "createdAt": datetime.now(UTC).isoformat(),
        "mode": "offline_knowledge_quality",
        "caseVersion": "loreal-knowledge-quality-v1",
        "caseSha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "sourceSha256": SOURCE_SHA256,
        "python": platform.python_version(),
        "documents": document_reports,
        "productCoverage": {
            "sourceProductCount": len(expected_products),
            "documentedProductCount": len(documented_products),
            "missingProducts": missing_products,
            "extraProducts": extra_products,
            "coverage": len(documented_products & expected_products) / len(expected_products),
        },
        "professionalKnowledge": {
            "ingredientClaimsAvailable": False,
            "efficacyClaimsAvailable": False,
            "skinSuitabilityClaimsAvailable": False,
            "medicalAdviceAvailable": False,
            "reason": "官方虚构订单资料未提供成分、功效、肤质适用性或医学证据",
        },
        "serviceBoundaryChecks": {
            "requiredCount": len(required_service_phrases),
            "missing": missing_service_phrases,
        },
        "errors": errors,
        "status": "passed" if not errors else "failed",
        "limitations": [
            "结构和来源检查通过不等于专业美妆建议效果通过。",
            "当前资料只支持订单/工单事实核对和服务边界回复，不支持功效、成分或肤质推荐。",
            "本检查不启动API、不调用模型、不发布知识索引。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=REPO / "evals/cases/loreal_breakpoints.json",
    )
    args = parser.parse_args()
    report = validate(args.cases)
    destination = REPO / "evals/results" / (
        f"loreal-knowledge-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(destination),
        "status": report["status"],
        "productCoverage": report["productCoverage"],
        "professionalKnowledge": report["professionalKnowledge"],
        "errors": report["errors"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
