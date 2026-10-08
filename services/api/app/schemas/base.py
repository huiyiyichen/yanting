"""API 契约基类与序列化约定。

约定（工程规范第 4.1 节）：
- Python 内部与存储使用 `snake_case`，API JSON 使用 `camelCase`；
- 通过 Pydantic 序列化别名统一转换，前端类型由同一份 OpenAPI 生成；
- 出参统一用 `by_alias=True` 序列化。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """所有 API 出入参的基类：camelCase 别名 + 禁止未声明字段。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


class CamelModel(BaseModel):
    """需要额外字段的模型基类（如可扩展载荷）。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
        str_strip_whitespace=True,
    )

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")
