"""在响应真正发出**之前**提交事务的路由类。

为什么需要（缺陷第 49 项）：FastAPI 把「带 `yield` 的依赖」的收尾放在响应发送
**之后**执行。`fastapi/routing.py` 的实际顺序是：

    async with AsyncExitStack() as request_stack:   # 依赖收尾在这里
        response = await f(request)                 # 处理函数 + 序列化
        await response(scope, receive, send)        # 响应先发给客户端
    # 退出 with 时才执行 get_session 的 session.commit()

于是一段「写 → 立刻读」的客户端序列存在竞态窗口：写请求的 200 已经到达浏览器，
但另一个请求（另一次会话、另一次连接）此时读到的仍是旧值。实测发生在客服
「接管会话」后立刻刷新队列：接管 POST 返回 200、库里 `service_mode` 已改为
`operator_assisted`（`mode_revision=1`、审计事件同时落库），而紧随其后的
`GET /api/support/queue` 返回的响应体与接管前**逐字节相同**（10186 字节），
前端据此仍显示「AI 托管中」且输入框保持禁用。

同一族缺陷此前已出现两次：第 26 项「刚创建的会话立刻读 404」（对照实验
10/25 = 40% 失败）与第 33 项「并发重放同一幂等键」。当时只在两个创建类接口上
补了显式提交，其余写接口仍然依赖响应之后的收尾提交——窗口只是变窄，没有消失。

做法：把提交提前到处理函数返回响应之后、Starlette 发送响应之前。此时
- 处理函数已经跑完（要写的数据都在会话里）；
- 响应头还没发出去，提交失败可以如实变成 5xx，而不是「客户端收到 200、数据却丢了」。

语义与旧实现保持一致：处理函数**正常返回**就提交；抛异常（含领域错误
`AnkerAgentError`）则交给 `get_session` 收尾回滚，绝不半写。
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from app.db import commit_with_retry

#: `get_session` 把会话登记在 `request.state` 上的属性名。
SESSION_STATE_KEY = "db_session"


class CommitBeforeResponseRoute(APIRoute):
    """处理函数返回后、响应发出前提交事务。"""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def commit_then_return(request: Request) -> Response:
            response = await handler(request)
            session = getattr(request.state, SESSION_STATE_KEY, None)
            if session is not None:
                # 提交失败会在这里抛出：此时响应还没发出，客户端收到的是 5xx，
                # 不会出现「200 已返回但数据未落库」的静默丢失。
                commit_with_retry(session)
            return response

        return commit_then_return
