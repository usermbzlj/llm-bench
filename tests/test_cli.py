from __future__ import annotations

import json
from typing import Any

import pytest

from llm_bench import cli
from llm_bench.models import BenchSummary, RequestResult


def _args(*argv: str) -> Any:
    return cli._build_parser().parse_args(["bench", *argv])


# ── endpoint / body / config helpers ───────────────────────────────────────


def test_resolve_endpoint_appends_chat_completions() -> None:
    cfg = cli.BenchConfig(base_url="http://localhost:8000/v1")
    assert cli._resolve_endpoint(cfg) == "http://localhost:8000/v1/chat/completions"


def test_resolve_endpoint_respects_explicit_url() -> None:
    cfg = cli.BenchConfig(base_url="http://x/v1", url="http://y/custom")
    assert cli._resolve_endpoint(cfg) == "http://y/custom"


def test_resolve_endpoint_keeps_existing_suffix() -> None:
    cfg = cli.BenchConfig(base_url="http://x/v1/chat/completions")
    assert cli._resolve_endpoint(cfg) == "http://x/v1/chat/completions"


def test_build_body_standard() -> None:
    cfg = cli.BenchConfig(model="m", max_tokens=7, temperature=0.0, stream=True)
    body = cli._build_body(cfg)
    assert body["model"] == "m"
    assert body["max_tokens"] == 7
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "user"


def test_build_body_custom_json() -> None:
    cfg = cli.BenchConfig(body_json='{"model":"x","messages":[]}')
    body = cli._build_body(cfg)
    assert body == {"model": "x", "messages": []}


def test_merge_config_cli_overrides_yaml(tmp_path: Any) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("model: from-yaml\nconcurrency: 3\n", encoding="utf-8")
    args = _args("--config", str(p), "--concurrency", "9")
    cfg = cli._merge_config(args)
    assert cfg.model == "from-yaml"  # untouched by CLI
    assert cfg.concurrency == 9  # overridden by --concurrency


def test_csv_bytes_has_header_and_row() -> None:
    rows = [
        RequestResult(
            ok=True,
            status_code=200,
            latency_ms=12.3,
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
        )
    ]
    text = cli._csv_bytes(rows).decode("utf-8-sig")
    assert "latency_ms" in text.splitlines()[0]
    assert "12.3" in text


# ── _run_bench: mode selection, output, exit codes ──────────────────────────


@pytest.mark.asyncio
async def test_run_bench_total_mode_writes_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_benchmark(**kwargs: Any) -> BenchSummary:
        captured.update(kwargs)
        return BenchSummary(
            total=5,
            success=5,
            attempt_total=5,
            attempt_success=5,
            wall_seconds=1.0,
            latencies_ms=[10.0] * 5,
        )

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    out = tmp_path / "r.json"
    args = _args(
        "--base-url",
        "http://x/v1",
        "--model",
        "m",
        "--total",
        "5",
        "--api-key",
        "sk-x",
        "--json",
        str(out),
        "-q",
    )
    code = await cli._run_bench(args)
    assert code == 0
    assert captured["total_requests"] == 5
    assert captured["target_rps"] is None
    assert captured["url"] == "http://x/v1/chat/completions"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["requests_total"] == 5
    assert data["metadata"]["mode"] == "total"


@pytest.mark.asyncio
async def test_run_bench_rps_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_benchmark(**kwargs: Any) -> BenchSummary:
        captured.update(kwargs)
        return BenchSummary(
            total=3,
            success=3,
            attempt_total=3,
            attempt_success=3,
            wall_seconds=1.0,
            latencies_ms=[1.0, 2.0, 3.0],
        )

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    args = _args(
        "--base-url",
        "http://x/v1",
        "--rps",
        "10",
        "--rps-duration",
        "5",
        "--api-key",
        "sk-x",
        "-q",
    )
    code = await cli._run_bench(args)
    assert code == 0
    assert captured["target_rps"] == 10
    assert captured["rps_duration_s"] == 5
    assert captured["total_requests"] is None


@pytest.mark.asyncio
async def test_run_bench_fail_on_error_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_benchmark(**kwargs: Any) -> BenchSummary:
        return BenchSummary(
            total=4,
            success=2,
            failed=2,
            attempt_total=4,
            attempt_success=2,
            wall_seconds=1.0,
            latencies_ms=[1.0, 2.0],
        )

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    args = _args("--base-url", "http://x/v1", "--api-key", "sk-x", "--fail-on-error", "-q")
    assert await cli._run_bench(args) == 1


@pytest.mark.asyncio
async def test_run_bench_zero_total_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_benchmark(**kwargs: Any) -> BenchSummary:
        return BenchSummary()

    monkeypatch.setattr(cli, "run_benchmark", fake_run_benchmark)
    args = _args("--base-url", "http://x/v1", "--api-key", "sk-x", "-q")
    assert await cli._run_bench(args) == 1
