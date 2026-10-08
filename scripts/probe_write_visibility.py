"""写后立即读的可见性探针（诊断脚本，不是评测）。

背景：缺陷第 26 项（创建的会话立刻读 404）与第 33 项（并发重放幂等键）都属于
「写入已返回 200，但另一次请求读不到」这一族问题。第 49 项把它的根因定位清楚了：
FastAPI 把带 `yield` 依赖的收尾（`get_session` 的 `commit()`）放在**响应发送之后**，
于是客户端拿到 200 的瞬间数据可能还没落库。修复方式是让路由在响应发出前提交
（`app/routes/commit.py`）。

**这个探针的结论要说清楚**：修复前后各跑 20 轮，都是 20/20 读到新值——它**没有**
复现出竞态。原因是窗口很窄（提交通常紧跟响应之后完成），而 httpx 同步客户端
「读响应 → 再发下一请求」的间隔恰好常常落在窗口之外。真实浏览器那次踩中了：
`GET /api/support/queue` 在接管 POST 完成后 27 ms 发出，返回的仍是旧响应体。

因此：**不要用本脚本证明时序正确**，它只能作为黑盒冒烟。
可靠的回归在 `services/api/tests/integration/test_commit_timing.py`——
它在 ASGI 的 `http.response.start` 时刻用另一条连接读库，直接断言顺序不变量，
且已验证「去掉路由类就会失败」。

用法（后端需已启动）：
    .\.venv\Scripts\python.exe ..\..\scripts\probe_write_visibility.py --rounds 20
"""

from __future__ import annotations

import argparse
import sys

import httpx

CUSTOMER = {"X-Demo-View-Role": "customer"}
SUPPORT = {"X-Demo-View-Role": "support"}


def probe_takeover(client: httpx.Client, index: int) -> bool:
    """接管后立刻读队列：返回 True 表示读到了新值（无竞态）。"""

    created = client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
    created.raise_for_status()
    conversation_id = created.json()["conversationId"]

    response = client.post(
        f"/api/support/conversations/{conversation_id}/service-mode",
        json={"mode": "operator_assisted"},
        headers=SUPPORT,
    )
    response.raise_for_status()
    body = response.json()

    queue = client.get("/api/support/queue", headers=SUPPORT)
    queue.raise_for_status()
    row = next(
        (item for item in queue.json() if item["conversationId"] == conversation_id),
        None,
    )
    observed = row["serviceMode"] if row else "<缺失>"
    ok = observed == body["serviceMode"]
    if not ok:
        print(
            f"  第 {index} 轮：接管响应 {body['serviceMode']}，紧随其后的队列读到 {observed}"
        )
    return ok


def probe_rating(client: httpx.Client, index: int) -> bool:
    """评价后立刻读案件：评价状态必须立刻可见。"""

    created = client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
    created.raise_for_status()
    conversation_id = created.json()["conversationId"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/rating",
        json={"score": 5, "comment": "探针"},
        headers=CUSTOMER,
    )
    if response.status_code != 200:
        # 服务未结束时按设计 422，本探针只关心「写成功后能否立刻读到」
        return True

    detail = client.get(f"/api/customer/conversations/{conversation_id}/rating", headers=CUSTOMER)
    if detail.status_code != 200:
        print(f"  第 {index} 轮：评价写入成功但紧接着读返回 {detail.status_code}")
        return False
    observed = detail.json()
    ok = observed.get("score") == 5
    if not ok:
        print(f"  第 {index} 轮：评价写入 5 分，紧随其后的读取到 {observed}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--rounds", type=int, default=30)
    args = parser.parse_args()

    failures = 0
    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        for index in range(1, args.rounds + 1):
            if not probe_takeover(client, index):
                failures += 1

    print(f"接管写后读：{args.rounds - failures}/{args.rounds} 轮读到新值，失败 {failures} 轮")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
