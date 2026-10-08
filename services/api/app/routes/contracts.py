"""契约导出路由。

提供机器可读的枚举与契约版本，供前端类型生成和跨语言一致性校验使用。
只暴露枚举与版本，不暴露任何业务数据或内部依据。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.domain.enums import enum_values

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("/enums")
async def enums() -> dict[str, dict[str, str]]:
    """全部固定枚举及其中文展示文案。"""

    return enum_values()


@router.get("/manifest")
async def manifest() -> dict[str, Any]:
    settings = get_settings()
    values = enum_values()
    return {
        "contractVersion": settings.contract_version,
        "promptVersion": settings.prompt_version,
        "chunkConfigVersion": settings.chunk_config_version,
        "enumCount": len(values),
        "enumValueCount": sum(len(item) for item in values.values()),
        "namingConvention": {
            "apiJson": "camelCase",
            "pythonInternal": "snake_case",
            "enumMachineValue": "snake_case",
        },
        "sourceOfTruth": "services/api/app/domain/enums.py",
    }
