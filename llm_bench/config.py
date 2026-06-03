"""压测参数模型与 YAML 配置加载。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# User-level config directory. Overridable via env so tests / portable installs
# can redirect without monkey-patching.
CONFIG_DIR_ENV = "LLM_BENCH_CONFIG_DIR"


def config_dir() -> Path:
    """Return the user-level config directory (created if missing).

    Default: ``~/.llm_bench/`` (XDG-ish: home, not cwd). Override with the
    ``LLM_BENCH_CONFIG_DIR`` environment variable.
    """
    override = os.environ.get(CONFIG_DIR_ENV)
    base = Path(override) if override else Path.home() / ".llm_bench"
    base.mkdir(parents=True, exist_ok=True)
    return base


class BenchConfig(BaseModel):
    """与 CLI 对齐的默认配置；YAML 可只写部分字段。"""

    model_config = ConfigDict(extra="ignore")

    base_url: str = Field(default="https://api.openai.com/v1", description="API 根路径")
    url: str | None = Field(default=None, description="完整 URL，若设置则忽略 base_url")
    model: str = Field(default="gpt-4o-mini")
    concurrency: int = Field(default=5, ge=1)
    max_tokens: int = Field(default=128, ge=1)
    temperature: float = Field(default=0.2)
    stream: bool = Field(default=False)
    timeout_s: float = Field(default=120.0, gt=0)
    http2: bool = Field(default=False)
    warmup: int = Field(default=0, ge=0)
    retry_on_429: int = Field(default=3, ge=0, description="429 时额外重试次数（与 GUI/文档默认一致）")
    retry_on_network: int = Field(default=1, ge=0, description="网络错误时额外重试次数")
    retry_on_5xx: int = Field(default=1, ge=0, description="服务端 5xx 时额外重试次数")
    proxy_mode: str = Field(default="direct", description="代理模式：direct/system/custom")
    proxy_url: str | None = Field(
        default=None, description="自定义代理地址，例如 http://127.0.0.1:7890"
    )
    timeline_bucket_s: float | None = Field(default=None, description="时间线分桶秒数，>=0.1")
    prompts: list[str] | None = Field(
        default=None,
        description="多 prompt 轮换；非空时覆盖默认 user 首条 content",
    )
    prompts_file: str | None = Field(
        default=None,
        description="每行一条 prompt 的文件路径（相对 cwd）",
    )
    body_file: str | None = Field(default=None)
    body_json: str | None = Field(default=None)


def load_bench_config(path: Path) -> BenchConfig:
    """Load a :class:`BenchConfig` from a YAML file.

    Raises:
        FileNotFoundError: if ``path`` doesn't exist.
        yaml.YAMLError: if the file is not valid YAML.
        ValueError: if the YAML root isn't a mapping.
        pydantic.ValidationError: if a field has the wrong type / range.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("YAML 根节点须为 mapping")
    return BenchConfig.model_validate(raw)


class _ApiKeyEnv(BaseSettings):
    """从环境变量读取密钥（pydantic-settings）。"""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    LLM_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None


def env_api_key() -> str | None:
    e = _ApiKeyEnv()
    return e.LLM_API_KEY or e.OPENAI_API_KEY


def load_prompts_from_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [ln.strip() for ln in lines if ln.strip()]
    if not out:
        raise ValueError(f"prompt 文件为空: {path}")
    return out


def resolve_prompts(cfg: BenchConfig, prompts_file_cli: Path | None) -> list[str] | None:
    """合并 YAML 与 CLI 的 prompts_file，返回轮换列表或 None。"""
    pfile = prompts_file_cli
    if pfile is None and cfg.prompts_file:
        pfile = Path(cfg.prompts_file)
    if pfile is not None:
        return load_prompts_from_file(pfile)
    if cfg.prompts:
        return list(cfg.prompts)
    return None


T = TypeVar("T")


def pick(cli: T | None, cfg_value: T) -> T:
    return cfg_value if cli is None else cli


__all__ = [
    "BenchConfig",
    "CONFIG_DIR_ENV",
    "config_dir",
    "load_bench_config",
    "env_api_key",
    "load_prompts_from_file",
    "resolve_prompts",
    "pick",
]
