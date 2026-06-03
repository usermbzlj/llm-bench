"""Tests for llm_bench.config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from llm_bench.config import (
    CONFIG_DIR_ENV,
    BenchConfig,
    config_dir,
    env_api_key,
    load_bench_config,
)


def test_config_dir_defaults_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "llm-bench-test"))
    assert config_dir() == tmp_path / "llm-bench-test"
    # Created if missing.
    assert (tmp_path / "llm-bench-test").exists()


def test_config_dir_respects_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "custom"
    monkeypatch.setenv(CONFIG_DIR_ENV, str(target))
    assert config_dir() == target
    assert target.is_dir()


def test_load_bench_config_minimal(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text("base_url: https://demo.test/v1\nmodel: demo\n", encoding="utf-8")
    cfg = load_bench_config(path)
    assert cfg.base_url == "https://demo.test/v1"
    assert cfg.model == "demo"
    # Defaults applied for missing fields.
    assert cfg.concurrency == 5
    assert cfg.timeout_s == 120.0


def test_load_bench_config_empty_file_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    cfg = load_bench_config(path)
    assert cfg.model == "gpt-4o-mini"


def test_load_bench_config_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_bench_config(path)


def test_load_bench_config_raises_on_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("foo: : :\n  - bar\n", encoding="utf-8")  # malformed
    with pytest.raises(yaml.YAMLError):
        load_bench_config(path)


def test_load_bench_config_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "extra.yaml"
    path.write_text("model: demo\ntotally_made_up_field: 42\n", encoding="utf-8")
    cfg = load_bench_config(path)
    assert cfg.model == "demo"
    # No error — extra fields are silently dropped (per extra="ignore" config).


def test_env_api_key_prefers_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "llm-value")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-value")
    assert env_api_key() == "llm-value"


def test_env_api_key_falls_back_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-value")
    assert env_api_key() == "openai-value"


def test_env_api_key_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert env_api_key() is None


def test_bench_config_validates_field_ranges() -> None:
    # Pydantic enforces ge=1 / gt=0 — bad values raise ValidationError.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BenchConfig(concurrency=0)
    with pytest.raises(ValidationError):
        BenchConfig(timeout_s=0)


def test_bench_config_retry_defaults_match_gui_and_docs() -> None:
    # GUI widgets and README document the defaults as 3/1/1. Keep BenchConfig
    # in sync so the headless CLI path doesn't silently differ from the GUI.
    cfg = BenchConfig()
    assert cfg.retry_on_429 == 3
    assert cfg.retry_on_network == 1
    assert cfg.retry_on_5xx == 1
