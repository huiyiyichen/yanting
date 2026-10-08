"""请求级依赖：数据库会话、运行时上下文与角色校验。

权限模型（工程规范第 13.3 节）：
- 演示角色切换**不是**生产认证；服务端维护 Demo 会话角色与会话访问范围；
- 客户接口与客服接口**分开校验**，不能只靠前端隐藏按钮；
- 客户上下文不能批准申请，也不能读取内部依据。

做法：路由通过 `Depends(require_view_role(...))` 声明所需角色，
角色由请求头 `X-Demo-View-Role` 提供（缺省 `customer`），服务端再次校验。
这样绕过 UI 直接请求内部接口会得到 403，而不是成功。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.db import commit_with_retry
from app.domain.enums import ViewRole
from app.errors import AnkerAgentError
from app.routes.commit import SESSION_STATE_KEY
from app.runtime import RuntimeContext

DEMO_ROLE_HEADER = "X-Demo-View-Role"


class PermissionDenied(AnkerAgentError):
    """接口层权限拒绝。与会话不存在区分开（不泄露资源是否存在）。"""

    code = "tool_access_denied"


def get_context(request: Request) -> RuntimeContext:
    return request.app.state.runtime  # type: ignore[no-any-return]


def get_session(
    request: Request,
    context: RuntimeContext = Depends(get_context),
) -> Iterator[Session]:
    """每请求一个数据库会话。

    提交时机（缺陷第 49 项）：正常结束时的提交由
    `app.routes.commit.CommitBeforeResponseRoute` 在**响应发出之前**执行，
    这里只登记会话；此处的收尾提交是兜底（例如未使用该路由类的接口）。
    为什么不能让收尾承担全部提交：FastAPI 把带 `yield` 依赖的收尾放在响应
    发送**之后**，客户端可能已经拿到 200 并立刻发起下一次读取，而那次读取
    看不到尚未提交的数据（实测：接管会话后立刻刷新队列读到旧值）。

    异常路径仍然回滚：处理函数抛错时不会走到路由类的提交，收尾负责回滚。
    """

    session = context.session_factory()
    # 登记给路由类使用（见上）；`state` 是每请求独立的。
    setattr(request.state, SESSION_STATE_KEY, session)
    try:
        yield session
        commit_with_retry(session)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_view_role(
    x_demo_view_role: str | None = Header(default=None, alias=DEMO_ROLE_HEADER),
) -> ViewRole:
    """解析演示角色。非法值一律按 customer 处理（最小权限）。"""

    if not x_demo_view_role:
        return ViewRole.CUSTOMER
    try:
        return ViewRole(x_demo_view_role.strip().lower())
    except ValueError:
        return ViewRole.CUSTOMER


def require_view_role(required: ViewRole):
    """生成一个角色校验依赖。"""

    def _dependency(role: ViewRole = Depends(current_view_role)) -> ViewRole:
        if role is not required:
            raise PermissionDenied(
                f"当前演示角色（{role.value}）无权访问该接口",
                detail=f"该接口仅限 {required.value}；演示角色不是生产认证",
            )
        return role

    return _dependency


require_support = require_view_role(ViewRole.SUPPORT)
require_customer = require_view_role(ViewRole.CUSTOMER)
