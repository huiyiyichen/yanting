"""测试统一按 single 编排运行。

产品默认是 multi（多 Agent），但大量旧测试按 single 的模型调用顺序编排了假响应；
multi 相关测试会在用例里显式切到 multi。
"""

import os

os.environ.setdefault("YANTING_ORCHESTRATION", "single")
