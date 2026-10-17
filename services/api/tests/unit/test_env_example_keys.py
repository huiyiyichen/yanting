"""P0-5 提交包密钥处理。失败方式：
K1 .env.example 漏列 Settings 新增字段，评委照示例填写后功能缺配置；或列出已删除的键。
K2 .env.example 里出现像真实密钥的值（key/token/secret/password 类键有非空值）。
K3 打包脚本把 .env / .env.local 收进提交包（add_tree 与 git 文件两条路径都要排除，.env.example 保留）。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.config import ENV_PREFIX, Settings

ROOT = Path(__file__).resolve().parents[4]
EXAMPLE = ROOT / ".env.example"
SECRET_KEY = re.compile(r"(?i)(key|token|secret|password)")


def _example() -> dict[str, str]:
    pairs = {}
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs


def test_k1_example_keys_match_settings_fields():
    expected = {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}
    actual = set(_example())
    assert actual - expected == set(), f"示例里多余的键：{sorted(actual - expected)}"
    assert expected - actual == set(), f"示例里缺少的键：{sorted(expected - actual)}"


def test_k2_example_has_no_secret_values():
    leaked = {key for key, value in _example().items() if SECRET_KEY.search(key) and value.strip("\"'")}
    assert leaked == set()


def test_k3_packaging_skips_env_files(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_submission", ROOT / "scripts/build_submission.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in (".env", ".env.local", ".env.example", "main.py"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(module, "FILES", {})
    module.add_tree(tmp_path, "code/services/api")
    assert set(module.FILES) == {"code/services/api/main.py"}
    source = (ROOT / "scripts/build_submission.py").read_text(encoding="utf-8")
    assert "path.name.startswith('.env') and path.name != '.env.example'" in source
