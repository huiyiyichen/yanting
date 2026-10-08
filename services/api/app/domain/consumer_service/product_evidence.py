"""Resolve explicitly registered product identities, not fuzzy name similarity."""

from __future__ import annotations

import re

from app.schemas.grounding import GroundingSource


def product_names(catalog: dict[str, GroundingSource]) -> dict[str, tuple[str, ...]]:
    owners: dict[str, set[str]] = {}
    names: dict[str, set[str]] = {}
    for source in catalog.values():
        sku = source.fields.get("productSku")
        if source.kind != "knowledge" or not sku:
            continue
        values = [sku, source.fields.get("productName"), *source.fields.get("productAliases", [])]
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            name = value.strip().casefold()
            names.setdefault(sku, set()).add(name)
            owners.setdefault(name, set()).add(sku)
    # An alias shared by two color variants cannot identify either variant.
    return {
        sku: tuple(sorted((name for name in values if owners[name] == {sku}), key=len, reverse=True))
        for sku, values in names.items()
    }


def mentioned_products(text: str, names: dict[str, tuple[str, ...]]) -> set[str]:
    text = text.casefold()
    return {
        sku for sku, aliases in names.items()
        if any(re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text)
               for alias in aliases)
    }
