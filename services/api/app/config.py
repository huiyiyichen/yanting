"""运行配置。

约束（来自工程规范）：
- 运行配置集中在后端，前端不保存模型凭证；
- `mock` 仅用于测试和早期联调，`live` 用于真实模型与索引链路；
- 默认只绑定本机回环地址。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RunMode = Literal["live", "mock"]
EmbeddingBackend = Literal["onnx-local", "http", "mock"]
RerankBackend = Literal["none", "http", "mock"]

# 仓库根目录：本文件位于 <code>/services/api/app/config.py
REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv_into_environ() -> None:
    """把 services/api/.env 读入环境变量，真实环境变量优先。"""

    env_path = REPO_ROOT / "services" / "api" / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv_into_environ()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANKER_AGENT_",
        env_file=None,
        extra="ignore",
    )

    run_mode: RunMode = "live"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # 文本/多模态模型（OpenAI 兼容）
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_vision_model: str = ""
    llm_timeout_seconds: float = 60.0
    auto_reply_timeout_seconds: float = Field(default=45.0, ge=5, le=120)
    risk_repeat_contact_hours: int = Field(default=72, ge=1, le=720)
    risk_source_ticket_hours: int = Field(default=48, ge=1, le=720)
    risk_monitor_interval_seconds: int = Field(default=15, ge=5, le=300)
    risk_response_wait_seconds: int = Field(default=120, ge=0, le=3600)
    risk_followup_warning_minutes: int = Field(default=30, ge=0, le=1440)

    # 编码模型
    embedding_backend: EmbeddingBackend = "onnx-local"
    embedding_model_id: str = "BAAI/bge-m3"
    embedding_model_path: str = ""
    embedding_http_base_url: str = ""
    embedding_http_api_key: str = ""
    embedding_dimension: int | None = None

    # 重排序（可选增强；未配置时检索链路不做精排）
    rerank_backend: RerankBackend = "none"
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    rerank_timeout_seconds: float = 30.0
    #: 送去重排序的候选条数（要大于最终证据数，否则精排没有选择空间）
    rerank_candidates: int = Field(default=16, ge=2, le=64)

    # 存储
    database_url: str = "sqlite+pysqlite:///data/runtime/anker_agent.sqlite3"
    qdrant_path: str = "data/runtime/qdrant"
    runtime_dir: str = "data/runtime"

    # 知识切片与检索
    chunk_size: int = Field(default=600, ge=50)
    chunk_overlap: int = Field(default=80, ge=0)
    chunk_config_version: str = "chunk-600-80-v1"
    retrieval_top_k: int = Field(default=8, ge=1, le=64)
    retrieval_max_evidence: int = Field(default=5, ge=1, le=32)

    # 附件
    image_max_bytes: int = 5 * 1024 * 1024
    image_allowed_mime: str = "image/jpeg,image/png,image/webp"

    contract_version: str = "0.1.0"
    prompt_version: str = "s0-bootstrap"

    @field_validator("llm_base_url", "embedding_http_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_image_mimes(self) -> list[str]:
        return [item.strip() for item in self.image_allowed_mime.split(",") if item.strip()]

    @property
    def runtime_path(self) -> Path:
        return (REPO_ROOT / self.runtime_dir).resolve()

    @property
    def qdrant_path_resolved(self) -> Path:
        return (REPO_ROOT / self.qdrant_path).resolve()

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def vision_configured(self) -> bool:
        return bool(self.llm_configured and self.llm_vision_model)

    def sqlalchemy_url(self) -> str:
        """把相对 sqlite 路径解析成绝对路径，避免受启动目录影响。"""

        prefix = "sqlite+pysqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix) :]
            if raw and not Path(raw).is_absolute():
                return prefix + str((REPO_ROOT / raw).resolve()).replace("\\", "/")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
