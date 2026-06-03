"""Tests for llm_bench.models: stats aggregation, percentile key naming,
and BenchSummary semantics."""

from __future__ import annotations

import pytest

from llm_bench.models import (
    BenchSummary,
    ErrorKind,
    RequestResult,
    _percentile_block,
    build_stats_dict,
    mean_std,
    percentile,
    percentile_key,
)


def _ok_result(latency_ms: float = 100.0, *, completion_tokens: int = 10) -> RequestResult:
    return RequestResult(
        ok=True,
        status_code=200,
        latency_ms=latency_ms,
        prompt_tokens=5,
        completion_tokens=completion_tokens,
        total_tokens=15,
        response_bytes=256,
    )


# ── percentile_key ───────────────────────────────────────────────────────────


def test_percentile_key_uses_underscore_for_99_9() -> None:
    # 99.9 is the awkward one — int(99.9) would be 99, so we special-case it.
    assert percentile_key("latency_ms", 99.9) == "latency_ms_p99_9"
    assert percentile_key("latency_ms", 99) == "latency_ms_p99"
    assert percentile_key("latency_ms", 50) == "latency_ms_p50"
    assert percentile_key("ttft_ms", 99.9) == "ttft_ms_p99_9"


def test_percentile_key_is_stable_for_int_inputs() -> None:
    # The standard percentiles (50, 75, 90, 95, 99) all map to int keys.
    for p in (50, 75, 90, 95, 99):
        assert percentile_key("x", float(p)) == f"x_p{int(p)}"


# ── percentile (numeric) ────────────────────────────────────────────────────


def test_percentile_empty_returns_none() -> None:
    assert percentile([], 50) is None


def test_percentile_single_value_returns_it_for_any_p() -> None:
    assert percentile([42.0], 0) == 42.0
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 100) == 42.0
    assert percentile([42.0], 99.9) == 42.0


def test_percentile_clamps_p_above_100() -> None:
    assert percentile([1.0, 2.0, 3.0], 150) == 3.0


def test_percentile_50_is_median() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == pytest.approx(3.0)


# ── mean_std (n=1 docstring) ─────────────────────────────────────────────────


def test_mean_std_n1_returns_zero_std() -> None:
    # Documented behavior: n=1 → (mean, 0.0) — not None. Callers that want
    # to distinguish "no samples" from "single sample" should check len.
    mean, std = mean_std([7.5])
    assert mean == 7.5
    assert std == 0.0


def test_mean_std_empty_returns_none() -> None:
    assert mean_std([]) == (None, None)


def test_mean_std_uses_bessel_correction() -> None:
    # n=2: divisor is (2-1) = 1, not 2. With [0, 2]: variance = ((-1)^2 + 1^2)/1 = 2.
    mean, std = mean_std([0.0, 2.0])
    assert mean == 1.0
    assert std == pytest.approx(2.0**0.5)


# ── _percentile_block (helper writing to dict) ──────────────────────────────


def test_percentile_block_writes_all_requested_keys() -> None:
    out: dict[str, float | None] = {}
    _percentile_block(out, "x", [1.0, 2.0, 3.0, 4.0, 5.0], (50, 99, 99.9))
    # All three keys must be present, regardless of data shape.
    assert set(out) == {"x_p50", "x_p99", "x_p99_9"}
    assert out["x_p50"] == pytest.approx(3.0)
    # For [1,2,3,4,5] (n=5), p=99 → k = 4 * 0.99 = 3.96, f=3, c=4,
    # linear interp = 4*0.04 + 5*0.96 = 4.96.
    assert out["x_p99"] == pytest.approx(4.96, abs=1e-9)
    assert out["x_p99_9"] == pytest.approx(4.996, abs=1e-9)


def test_percentile_block_with_empty_data_writes_nulls() -> None:
    out: dict[str, float | None] = {}
    _percentile_block(out, "x", [], (50, 99, 99.9))
    assert out == {"x_p50": None, "x_p99": None, "x_p99_9": None}


# ── BenchSummary.add / gap semantics ────────────────────────────────────────


def test_inter_completion_gap_uses_all_completions() -> None:
    """L16: gap baseline is updated unconditionally (failed requests count too)."""
    summary = BenchSummary()
    summary.add(_ok_result(100.0))
    summary.add(RequestResult(ok=False, status_code=500, latency_ms=200.0))
    summary.add(_ok_result(50.0))
    # 3 requests → 2 gaps.
    assert len(summary.inter_completion_gap_ms) == 2


def test_error_kind_counts_only_nonzero_kind() -> None:
    summary = BenchSummary()
    summary.add(_ok_result(100.0))  # success: not counted
    summary.add(
        RequestResult(ok=False, status_code=429, latency_ms=10.0, error_kind=ErrorKind.RATE_LIMIT)
    )
    assert summary.error_kind_counts == {"rate_limit": 1}


def test_status_histogram_includes_success() -> None:
    summary = BenchSummary()
    summary.add(_ok_result(100.0))
    summary.add(
        RequestResult(ok=False, status_code=500, latency_ms=10.0, error_kind=ErrorKind.SERVER_ERROR)
    )
    assert summary.status_histogram == {200: 1, 500: 1}


# ── build_stats_dict ────────────────────────────────────────────────────────


def test_build_stats_dict_renames_attempted_rps_to_requests_per_sec() -> None:
    """L17: attempted_rps was misleading (it was requests/s, not HTTP attempts/s)."""
    summary = BenchSummary()
    summary.add(_ok_result(100.0))
    summary.add_attempt(_ok_result(100.0))  # 1 attempt total
    stats = build_stats_dict(summary)
    assert "requests_per_sec" in stats
    assert "http_attempts_per_sec" in stats
    # Old name must be GONE so downstream consumers don't accidentally use it.
    assert "attempted_rps" not in stats


def test_build_stats_dict_keys_are_stable() -> None:
    """Schema stability: even with zero data, every percentile key is present."""
    stats = build_stats_dict(BenchSummary())
    # Latency percentiles (p50..p99 + p99_9)
    for p in (50, 75, 90, 95, 99, 99.9):
        assert f"latency_ms_p{int(p) if p != 99.9 else '99_9'}" in stats
    # Final attempt latency (subset)
    for p in (50, 90, 95, 99):
        assert f"final_attempt_latency_ms_p{p}" in stats
    # TTFT / TTFB / TPOT / TPS / ITL percentiles
    for prefix in ("ttft_ms", "ttfb_ms", "tpot_ms", "tokens_per_sec_per_request", "itl_ms"):
        for p in (50, 90, 95, 99):
            assert f"{prefix}_p{p}" in stats


def test_build_stats_dict_no_timeline_emits_empty_list() -> None:
    """Without timeline_bucket_s the timeline key is an empty list, not None,
    so downstream code can iterate it unconditionally."""
    summary = BenchSummary()
    stats = build_stats_dict(summary)
    assert stats["timeline"] == []
    assert stats["timeline_bucket_s"] is None
