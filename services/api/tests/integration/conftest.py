"""集成测试公共设置。

既有集成用例按“每次都调用模型核验”编写调用次数与核验输入断言；按需核验
（P0-2）默认开启后，这些用例仍应验证核验链路本身，因此默认关闭按需核验。
专门验证按需核验的用例用 `@pytest.mark.on_demand_verification` 打开。
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _verify_every_draft_unless_marked(request, monkeypatch):
    enabled = request.node.get_closest_marker("on_demand_verification") is not None
    monkeypatch.setenv("YANTING_VERIFY_ON_DEMAND", "true" if enabled else "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
