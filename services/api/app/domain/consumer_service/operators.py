"""Explicit local demo identities, not production authentication."""

from typing import Annotated

from fastapi import Depends, Header

from app.deps import require_support
from app.domain.enums import ViewRole
from app.errors import ValidationRejected
from app.schemas.service_desk import DemoOperatorRosterView, DemoOperatorView

DEFAULT_OPERATOR = "G001"
OPERATORS = (
    DemoOperatorView(operator_id="G001", name="模拟客服 G001"),
    DemoOperatorView(operator_id="G002", name="模拟客服 G002"),
    DemoOperatorView(operator_id="G003", name="模拟客服 G003"),
)


def current_operator(
    _role: Annotated[ViewRole, Depends(require_support)],
    operator_id: str = Header(default=DEFAULT_OPERATOR, alias="X-Demo-Operator"),
) -> str:
    if operator_id not in {item.operator_id for item in OPERATORS}:
        raise ValidationRejected("模拟客服不存在")
    return operator_id


def roster() -> DemoOperatorRosterView:
    return DemoOperatorRosterView(default_operator_id=DEFAULT_OPERATOR, operators=list(OPERATORS))
