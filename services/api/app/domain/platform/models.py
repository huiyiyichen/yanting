"""平台级持久化：运行设置与提示词模板。

**为什么挂在 `case_state` 的 Base 上**：本期有两套 `DeclarativeBase`
（案件状态一套、知识库一套），历史上正因为「只 create_all 了一个 Base」
导致隔离环境缺表（台账缺陷第 39 项）。把平台表声明在**同一套 Base** 上，
就自动被现有的 `ensure_schema()`、测试夹具与隔离播种脚本一起创建，
不再新增第二个需要记住的建表入口。

两张表各自解决一个真实需求：
- `runtime_setting`：模型配置页「切换生效模型」要能持久化，重启后仍然生效；
- `prompt_template`：Prompt 管理要能新增/编辑/启停提示词，而不是只能看代码常量。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.case_state.models import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_template_id() -> str:
    return f"ptpl-{uuid4().hex[:12]}"


class RuntimeSettingRow(Base):
    """运行设置（键值）。当前只用于「切换生效的文本模型」。"""

    __tablename__ = "runtime_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="demo")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class PromptTemplateRow(Base):
    """提示词模板。

    `code` 是**用途标识**（如 `UNDERSTANDING`），Agent 按 code 取「已启用」的那条；
    `revision` 每次改内容自增，方便回答「当时用的是哪一版提示词」。
    内置模板（`is_builtin`）来自代码常量，可被编辑与停用，但不会因停用而被删除。
    """

    __tablename__ = "prompt_template"

    template_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_template_id)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scenario: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="demo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class PromptRevisionRow(Base):
    __tablename__ = "prompt_revision"

    revision_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(128))
    scenario: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


__all__ = ["PromptTemplateRow", "RuntimeSettingRow", "new_template_id"]
