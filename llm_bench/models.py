"""压测数据模型与统计聚合。

公共 API（``__all__``）：
    - :class:`ErrorKind`           — 错误分类枚举
    - :class:`RequestResult`       — 单次请求结果（per-attempt 或 final 包裹）
    - :class:`TimelineBucket`      — 时间线分桶
    - :class:`BenchSummary`        — 聚合统计
    - :func:`build_stats_dict`     — 序列化为可导出 dict
    - :func:`percentile` / :func:`percentile_key` / :func:`mean_std` — 统计 helpers
    - :func:`finalize_timeline`    — 时间线分桶 → 行 dict
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorKind(StrEnum):
    NONE = ""
    TIMEOUT = "timeout"
    NETWORK = "network"
    CONNECT = "connect"
    PROXY = "proxy"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    PARSE = "parse"
    OTHER = "other"


@dataclass
class RequestResult:
    """单次（逻辑）请求的结果。

    ``raw_results`` 列表里既有 per-attempt 结果（来自 :func:`llm_bench.runner.one_chat_request`）
    也有被重试包裹后的 final 结果（来自 :func:`llm_bench.runner._one_with_retry`）。
    下游代码若聚合分位数，请用 ``attempt_count == 1`` 或经由 :class:`BenchSummary`
    过滤——下面这些 timing 字段在两种来源下语义不同：

    - ``latency_ms``：per-attempt 时为单次 HTTP 耗时；final 包裹时为端到端耗时
      （含所有 retry 的 backoff 等待）。
    - ``ttft_ms`` / ``ttfb_ms``：per-attempt 时相对于该 attempt 的 t0；final 包裹时
      会加上 ``prefinal_ms``（"前序所有 attempt + backoff"），等于"用户感知的首 token
      / 首字节时间"。
    - ``tpot_ms`` / ``tokens_per_sec``：per-attempt 时 per-attempt 视角；final 包裹时
      基于端到端 ``latency_ms``。
    - ``final_attempt_latency_ms``：仅 final 包裹时有值（per-attempt 为 None）。
    """

    ok: bool
    status_code: int | None
    latency_ms: float
    error: str | None = None
    response_text: str | None = None
    raw_response_text: str | None = None
    error_kind: ErrorKind = ErrorKind.NONE
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    response_bytes: int = 0
    ttft_ms: float | None = None
    ttfb_ms: float | None = None
    json_parse_ok: bool = False
    output_chars: int = 0
    stream_chunks: int = 0
    itl_ms: list[float] = field(default_factory=list)
    tpot_ms: float | None = None
    tokens_per_sec: float | None = None
    final_attempt_latency_ms: float | None = None
    attempt_count: int = 1
    retry_sleep_ms: float = 0.0
    # Persistent snapshot of the exact JSON body sent on the wire. Used by
    # the GUI's 'replay' feature to faithfully re-fire the same request.
    # None for results that predate this field.
    raw_request_body: str | None = None


@dataclass
class TimelineBucket:
    requests: int = 0
    success: int = 0
    failed: int = 0
    latency_sum_ms: float = 0.0
    latency_max_ms: float = 0.0
    bytes_in: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, r: RequestResult) -> None:
        self.requests += 1
        if r.ok:
            self.success += 1
            self.latency_sum_ms += r.latency_ms
            self.latency_max_ms = max(self.latency_max_ms, r.latency_ms)
        else:
            self.failed += 1
        self.bytes_in += r.response_bytes
        if r.prompt_tokens is not None:
            self.prompt_tokens += int(r.prompt_tokens)
        if r.completion_tokens is not None:
            self.completion_tokens += int(r.completion_tokens)


@dataclass
class BenchSummary:
    total: int = 0
    success: int = 0
    failed: int = 0
    attempt_total: int = 0
    attempt_success: int = 0
    attempt_failed: int = 0
    wall_seconds: float = 0.0
    wall_t0: float | None = None
    latencies_ms: list[float] = field(default_factory=list)
    final_attempt_latencies_ms: list[float] = field(default_factory=list)
    ttft_ms: list[float] = field(default_factory=list)
    ttfb_ms: list[float] = field(default_factory=list)
    inter_completion_gap_ms: list[float] = field(default_factory=list)
    _last_completion_mono: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    bytes_in: int = 0
    output_chars_total: int = 0
    stream_chunks_total: int = 0
    status_histogram: dict[int, int] = field(default_factory=dict)
    attempt_status_histogram: dict[int, int] = field(default_factory=dict)
    errors_sample: list[str] = field(default_factory=list)
    error_kind_counts: dict[str, int] = field(default_factory=dict)
    attempt_error_kind_counts: dict[str, int] = field(default_factory=dict)
    warmup_total: int = 0
    rps_schedule_skipped: int = 0
    timeline_bucket_s: float | None = None
    timeline_buckets: list[TimelineBucket] = field(default_factory=list)
    tpot_ms: list[float] = field(default_factory=list)
    tokens_per_sec_per_req: list[float] = field(default_factory=list)
    itl_ms_all: list[float] = field(default_factory=list)
    in_flight_samples: list[int] = field(default_factory=list)

    def add_attempt(self, r: RequestResult) -> None:
        self.attempt_total += 1
        if r.ok:
            self.attempt_success += 1
        else:
            self.attempt_failed += 1

        if r.status_code is not None:
            self.attempt_status_histogram[r.status_code] = (
                self.attempt_status_histogram.get(r.status_code, 0) + 1
            )

        ek = r.error_kind.value if isinstance(r.error_kind, ErrorKind) else str(r.error_kind)
        if ek and ek != ErrorKind.NONE.value:
            self.attempt_error_kind_counts[ek] = self.attempt_error_kind_counts.get(ek, 0) + 1

    def add(self, r: RequestResult, *, now_mono: float | None = None) -> None:
        t = time.perf_counter() if now_mono is None else now_mono

        self.total += 1
        self.bytes_in += r.response_bytes
        if r.status_code is not None:
            self.status_histogram[r.status_code] = self.status_histogram.get(r.status_code, 0) + 1

        ek = r.error_kind.value if isinstance(r.error_kind, ErrorKind) else str(r.error_kind)
        if ek and ek != ErrorKind.NONE.value:
            self.error_kind_counts[ek] = self.error_kind_counts.get(ek, 0) + 1

        if self._last_completion_mono is not None:
            self.inter_completion_gap_ms.append((t - self._last_completion_mono) * 1000.0)
        # Note: the gap baseline is updated unconditionally — failed requests also
        # advance _last_completion_mono. So the gap is "time between any two result
        # recordings", not strictly "time between successes". The list has n-1
        # entries for n requests (first request contributes no gap).
        self._last_completion_mono = t

        if self.timeline_bucket_s is not None and self.wall_t0 is not None:
            idx = int((t - self.wall_t0) / self.timeline_bucket_s)
            while len(self.timeline_buckets) <= idx:
                self.timeline_buckets.append(TimelineBucket())
            self.timeline_buckets[idx].add(r)

        if r.ok:
            self.success += 1
            self.latencies_ms.append(r.latency_ms)
            if r.final_attempt_latency_ms is not None:
                self.final_attempt_latencies_ms.append(r.final_attempt_latency_ms)
            if r.ttft_ms is not None:
                self.ttft_ms.append(r.ttft_ms)
            if r.ttfb_ms is not None:
                self.ttfb_ms.append(r.ttfb_ms)
            if r.prompt_tokens is not None:
                self.prompt_tokens += r.prompt_tokens
            if r.completion_tokens is not None:
                self.completion_tokens += r.completion_tokens
            if r.total_tokens is not None:
                self.total_tokens += r.total_tokens
            self.output_chars_total += r.output_chars
            self.stream_chunks_total += r.stream_chunks
            if r.tpot_ms is not None:
                self.tpot_ms.append(r.tpot_ms)
            if r.tokens_per_sec is not None:
                self.tokens_per_sec_per_req.append(r.tokens_per_sec)
            if r.itl_ms:
                self.itl_ms_all.extend(r.itl_ms)
        else:
            self.failed += 1
            if r.error and len(self.errors_sample) < 20:
                self.errors_sample.append(r.error[:500])


def percentile_key(prefix: str, p: float) -> str:
    """统一百分位键名：``p99`` vs ``p99_9`` 区分。

    OpenAI 风格中 99.9 写为 ``p99_9``，避免与 ``int(99.9) == 99`` 撞键。
    """
    return f"{prefix}_p99_9" if p == 99.9 else f"{prefix}_p{int(p)}"


def percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # Clamp p to [0, 100] — values outside the standard range previously caused
    # an IndexError (k > n-1).
    p = max(0.0, min(100.0, p))
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def mean_std(xs: list[float]) -> tuple[float | None, float | None]:
    """返回 ``(mean, std)``。

    n=0 → ``(None, None)``；n=1 → ``(mean, 0.0)``。注意 n=1 的 std 是 0 而非 None：
    下游若用 ``if std is not None`` 做"有方差"判断会得到"是"。如果你想严格区分
    "未定义方差"和"方差为 0"，调用方需要额外检查 len(xs) > 1。
    """
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return m, var**0.5


def finalize_timeline(buckets: list[TimelineBucket], bucket_s: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, b in enumerate(buckets):
        if b.requests == 0:
            continue
        t0 = i * bucket_s
        row: dict[str, Any] = {
            "t_start_s": round(t0, 3),
            "t_end_s": round(t0 + bucket_s, 3),
            "requests": b.requests,
            "success": b.success,
            "failed": b.failed,
            "success_rate_pct": 100.0 * b.success / b.requests,
            "rps_attempted": b.requests / bucket_s,
            "rps_success": b.success / bucket_s,
            "download_mbps_bucket": (b.bytes_in * 8) / bucket_s / 1_000_000,
            "prompt_tokens_bucket": b.prompt_tokens,
            "completion_tokens_bucket": b.completion_tokens,
            "throughput_prompt_tok_s_bucket": b.prompt_tokens / bucket_s,
            "throughput_completion_tok_s_bucket": b.completion_tokens / bucket_s,
        }
        if b.success:
            row["latency_ms_mean_bucket"] = b.latency_sum_ms / b.success
            # Note: max is success-only — a 100s failure won't be reported.
            # The bucket-level max reflects "the longest successful request" only.
            row["latency_ms_max_bucket"] = b.latency_max_ms
        else:
            row["latency_ms_mean_bucket"] = None
            row["latency_ms_max_bucket"] = None
        out.append(row)
    return out


def _percentile_block(
    out: dict[str, Any], prefix: str, sorted_vals: list[float], ps: tuple[float, ...]
) -> None:
    if not sorted_vals:
        for p in ps:
            out[percentile_key(prefix, p)] = None
        return
    for p in ps:
        out[percentile_key(prefix, float(p))] = percentile(sorted_vals, float(p))


def build_stats_dict(
    summary: BenchSummary,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lat = sorted(summary.latencies_ms)
    final_attempt_lat = (
        sorted(summary.final_attempt_latencies_ms) if summary.final_attempt_latencies_ms else []
    )
    ttft_sorted = sorted(summary.ttft_ms) if summary.ttft_ms else []
    ttfb_sorted = sorted(summary.ttfb_ms) if summary.ttfb_ms else []
    gaps = sorted(summary.inter_completion_gap_ms) if summary.inter_completion_gap_ms else []
    tpot_sorted = sorted(summary.tpot_ms) if summary.tpot_ms else []
    tps_req_sorted = (
        sorted(summary.tokens_per_sec_per_req) if summary.tokens_per_sec_per_req else []
    )
    itl_sorted = sorted(summary.itl_ms_all) if summary.itl_ms_all else []
    inflight = sorted(summary.in_flight_samples) if summary.in_flight_samples else []

    w = max(summary.wall_seconds, 1e-9)
    out: dict[str, Any] = {
        "requests_total": summary.total,
        "requests_success": summary.success,
        "requests_failed": summary.failed,
        "success_rate_pct": (100.0 * summary.success / summary.total) if summary.total else 0.0,
        "wall_seconds": summary.wall_seconds,
        "throughput_rps": summary.success / w,
        "throughput_failed_rps": summary.failed / w,
        "requests_per_sec": summary.total / w,
        "http_attempts_per_sec": summary.attempt_total / w,
        "goodput_fraction": (summary.success / summary.total) if summary.total else 0.0,
        "response_bytes_total": summary.bytes_in,
        "download_mbps": (summary.bytes_in * 8) / w / 1_000_000,
        "status_histogram": dict(summary.status_histogram),
        "error_kind_counts": dict(summary.error_kind_counts),
        "http_attempts_total": summary.attempt_total,
        "http_attempts_success": summary.attempt_success,
        "http_attempts_failed": summary.attempt_failed,
        "http_attempt_success_rate_pct": (100.0 * summary.attempt_success / summary.attempt_total)
        if summary.attempt_total
        else 0.0,
        "attempt_status_histogram": dict(summary.attempt_status_histogram),
        "attempt_error_kind_counts": dict(summary.attempt_error_kind_counts),
        "warmup_requests": summary.warmup_total,
        "rps_schedule_skipped": summary.rps_schedule_skipped,
        "output_chars_total": summary.output_chars_total,
        "stream_chunks_total": summary.stream_chunks_total,
    }
    if metadata:
        out["metadata"] = dict(metadata)

    if lat:
        out["latency_ms_min"] = lat[0]
        out["latency_ms_max"] = lat[-1]
        mu, sd = mean_std(lat)
        out["latency_ms_mean"] = mu
        out["latency_ms_std"] = sd
        if mu is not None and mu > 0 and sd is not None:
            out["latency_cv"] = sd / mu
        else:
            out["latency_cv"] = None
        for p in (50, 75, 90, 95, 99, 99.9):
            out[percentile_key("latency_ms", float(p))] = percentile(lat, float(p))
        p50 = percentile(lat, 50.0)
        p99 = percentile(lat, 99.0)
        out["latency_ms_p99_minus_p50"] = (
            (p99 - p50) if (p50 is not None and p99 is not None) else None
        )
    else:
        out["latency_ms_min"] = out["latency_ms_max"] = None
        out["latency_ms_mean"] = out["latency_ms_std"] = None
        out["latency_cv"] = None
        for p in (50, 75, 90, 95, 99, 99.9):
            out[percentile_key("latency_ms", float(p))] = None
        out["latency_ms_p99_minus_p50"] = None

    _percentile_block(out, "final_attempt_latency_ms", final_attempt_lat, (50, 90, 95, 99))

    if summary.completion_tokens and summary.success:
        out["completion_tokens_total"] = summary.completion_tokens
        out["throughput_completion_tok_s"] = summary.completion_tokens / w
        out["avg_completion_tokens_per_success"] = summary.completion_tokens / summary.success
    else:
        out["completion_tokens_total"] = summary.completion_tokens
        out["throughput_completion_tok_s"] = None
        out["avg_completion_tokens_per_success"] = None

    out["prompt_tokens_total"] = summary.prompt_tokens
    out["throughput_prompt_tok_s"] = (summary.prompt_tokens / w) if summary.prompt_tokens else None

    _percentile_block(out, "ttft_ms", ttft_sorted, (50, 90, 95, 99))
    _percentile_block(out, "ttfb_ms", ttfb_sorted, (50, 90, 95, 99))

    _percentile_block(out, "tpot_ms", tpot_sorted, (50, 90, 95, 99))
    _percentile_block(out, "tokens_per_sec_per_request", tps_req_sorted, (50, 90, 95, 99))
    _percentile_block(out, "itl_ms", itl_sorted, (50, 90, 95, 99))

    if inflight:
        out["in_flight_mean"] = sum(inflight) / len(inflight)
        out["in_flight_max"] = inflight[-1]
        out["in_flight_p50"] = percentile(inflight, 50.0)
        out["in_flight_p95"] = percentile(inflight, 95.0)
    else:
        out["in_flight_mean"] = out["in_flight_max"] = None
        out["in_flight_p50"] = out["in_flight_p95"] = None

    if gaps:
        out["inter_completion_gap_ms_p50"] = percentile(gaps, 50)
        out["inter_completion_gap_ms_p95"] = percentile(gaps, 95)
        out["inter_completion_gap_ms_mean"], out["inter_completion_gap_ms_std"] = mean_std(gaps)
    else:
        out["inter_completion_gap_ms_p50"] = None
        out["inter_completion_gap_ms_p95"] = None
        out["inter_completion_gap_ms_mean"] = None
        out["inter_completion_gap_ms_std"] = None

    if summary.output_chars_total and summary.success:
        out["avg_output_chars_per_success"] = summary.output_chars_total / summary.success
        out["output_chars_per_sec_wall"] = summary.output_chars_total / w
    else:
        out["avg_output_chars_per_success"] = None
        out["output_chars_per_sec_wall"] = None

    if summary.stream_chunks_total:
        out["stream_chunks_per_sec_wall"] = summary.stream_chunks_total / w
    else:
        out["stream_chunks_per_sec_wall"] = None

    if summary.timeline_bucket_s is not None and summary.timeline_buckets:
        out["timeline_bucket_s"] = summary.timeline_bucket_s
        out["timeline"] = finalize_timeline(summary.timeline_buckets, summary.timeline_bucket_s)
    else:
        out["timeline_bucket_s"] = None
        out["timeline"] = []

    out["errors_sample"] = list(summary.errors_sample)
    return out


__all__ = [
    "ErrorKind",
    "RequestResult",
    "TimelineBucket",
    "BenchSummary",
    "build_stats_dict",
    "percentile",
    "percentile_key",
    "mean_std",
    "finalize_timeline",
]
