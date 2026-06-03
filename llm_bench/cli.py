"""Headless 命令行压测入口。

复用 :mod:`llm_bench.config`（YAML）+ :func:`llm_bench.runner.run_benchmark`
+ :func:`llm_bench.models.build_stats_dict`，让压测引擎可以在 CI / 脚本 /
无显示器服务器上运行，无需启动桌面 GUI。本模块刻意不导入 ``nicegui`` /
``gui_*``，保持 headless 轻量。

示例::

    # 用 YAML 配置跑，把完整统计写到 JSON
    llm-bench bench --config bench.yaml --json result.json

    # 直接用命令行参数（本地 vLLM，100 请求，并发 8）
    llm-bench bench --base-url http://localhost:8000/v1 --model qwen --total 100 -c 8

    # 固定 RPS 压测 60 秒
    llm-bench bench --config bench.yaml --rps 10 --rps-duration 60

不带子命令（或 ``llm-bench gui``）时启动桌面 GUI。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from llm_bench import __version__
from llm_bench.config import (
    BenchConfig,
    env_api_key,
    load_bench_config,
    resolve_prompts,
)
from llm_bench.models import RequestResult, build_stats_dict
from llm_bench.runner import run_benchmark

# base_url 已带这些后缀时直接使用，否则拼 /chat/completions。
_CHAT_SUFFIXES = ("/chat/completions", "/completions", "/responses")


def _resolve_endpoint(cfg: BenchConfig) -> str:
    """从配置推导最终请求 URL：``url`` 优先，否则在 ``base_url`` 上补后缀。"""
    if cfg.url:
        return cfg.url.strip()
    base = cfg.base_url.strip().rstrip("/")
    if any(base.endswith(s) for s in _CHAT_SUFFIXES):
        return base
    return base + "/chat/completions"


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _build_body(cfg: BenchConfig) -> dict[str, Any]:
    """构造请求体：优先 body_json / body_file，否则按标准 OpenAI body 拼装。"""
    if cfg.body_json:
        data = json.loads(cfg.body_json)
    elif cfg.body_file:
        data = json.loads(Path(cfg.body_file).read_text(encoding="utf-8"))
    else:
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
        }
        if cfg.stream:
            body["stream"] = True
        return body
    if not isinstance(data, dict):
        raise ValueError("自定义请求体必须是 JSON 对象")
    return data


def _csv_bytes(rows: list[RequestResult]) -> bytes:
    """逐请求 CSV；字段与 GUI 导出保持一致（见 README）。"""
    buf = io.StringIO()
    fields = [
        "ok",
        "status_code",
        "latency_ms",
        "final_attempt_latency_ms",
        "ttft_ms",
        "ttfb_ms",
        "tpot_ms",
        "tokens_per_sec",
        "attempt_count",
        "retry_sleep_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "output_chars",
        "stream_chunks",
        "itl_count",
        "itl_mean_ms",
        "response_text",
        "error_kind",
        "error",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        itl_mean = (sum(row.itl_ms) / len(row.itl_ms)) if row.itl_ms else None
        writer.writerow(
            {
                "ok": row.ok,
                "status_code": row.status_code,
                "latency_ms": round(row.latency_ms, 4),
                "final_attempt_latency_ms": ""
                if row.final_attempt_latency_ms is None
                else round(row.final_attempt_latency_ms, 4),
                "ttft_ms": "" if row.ttft_ms is None else round(row.ttft_ms, 4),
                "ttfb_ms": "" if row.ttfb_ms is None else round(row.ttfb_ms, 4),
                "tpot_ms": "" if row.tpot_ms is None else round(row.tpot_ms, 4),
                "tokens_per_sec": ""
                if row.tokens_per_sec is None
                else round(row.tokens_per_sec, 4),
                "attempt_count": row.attempt_count,
                "retry_sleep_ms": round(row.retry_sleep_ms, 4),
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "total_tokens": row.total_tokens,
                "output_chars": row.output_chars,
                "stream_chunks": row.stream_chunks,
                "itl_count": len(row.itl_ms),
                "itl_mean_ms": "" if itl_mean is None else round(itl_mean, 4),
                "response_text": (row.response_text or "")[:500],
                "error_kind": row.error_kind.value
                if hasattr(row.error_kind, "value")
                else str(row.error_kind),
                "error": (row.error or "")[:500],
            }
        )
    return buf.getvalue().encode("utf-8-sig")


def _merge_config(args: argparse.Namespace) -> BenchConfig:
    """加载 YAML（或内置默认）后，用显式传入的命令行参数覆盖对应字段。"""
    cfg = load_bench_config(args.config) if args.config else BenchConfig()
    overrides = {
        "base_url": args.base_url,
        "url": args.url,
        "model": args.model,
        "concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "timeout_s": args.timeout_s,
        "stream": args.stream,
        "http2": args.http2,
        "warmup": args.warmup,
        "timeline_bucket_s": args.timeline_bucket,
    }
    data = cfg.model_dump()
    for key, value in overrides.items():
        if value is not None:
            data[key] = value
    return BenchConfig.model_validate(data)


def _fmt(value: Any, *, suffix: str = "", nd: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{nd}f}{suffix}"
    return f"{value}{suffix}"


def _print_summary(stats: dict[str, Any]) -> None:
    """把核心指标以人类可读的形式打印到 stdout。"""
    total = stats.get("requests_total") or 0
    lines = [
        "─" * 52,
        f"请求    : 总 {total} | 成功 {stats.get('requests_success')} | "
        f"失败 {stats.get('requests_failed')} "
        f"(成功率 {_fmt(stats.get('success_rate_pct'), suffix='%', nd=1)})",
        f"吞吐    : {_fmt(stats.get('throughput_rps'))} req/s | "
        f"{_fmt(stats.get('requests_per_sec'))} req/s(含失败)",
        f"延迟 ms : p50 {_fmt(stats.get('latency_ms_p50'), nd=1)} | "
        f"p95 {_fmt(stats.get('latency_ms_p95'), nd=1)} | "
        f"p99 {_fmt(stats.get('latency_ms_p99'), nd=1)} | "
        f"max {_fmt(stats.get('latency_ms_max'), nd=1)}",
    ]
    if stats.get("ttft_ms_p50") is not None:
        lines.append(
            f"流式 ms : TTFT p50 {_fmt(stats.get('ttft_ms_p50'), nd=1)} | "
            f"TPOT p50 {_fmt(stats.get('tpot_ms_p50'), nd=1)}"
        )
    lines.append(
        f"Token   : prompt {stats.get('prompt_tokens_total')} | "
        f"completion {stats.get('completion_tokens_total')} | "
        f"{_fmt(stats.get('throughput_completion_tok_s'))} tok/s"
    )
    if stats.get("error_kind_counts"):
        kinds = ", ".join(f"{k}x{v}" for k, v in sorted(stats["error_kind_counts"].items()))
        lines.append(f"错误    : {kinds}")
    lines.append("─" * 52)
    print("\n".join(lines))


async def _run_bench(args: argparse.Namespace) -> int:
    cfg = _merge_config(args)
    api_key = args.api_key or env_api_key()
    if not api_key:
        print(
            "提示: 未提供 API Key（--api-key 或环境变量 LLM_API_KEY / OPENAI_API_KEY）；"
            "本地服务可忽略。",
            file=sys.stderr,
        )

    prompts = resolve_prompts(cfg, args.prompts_file)
    endpoint = _resolve_endpoint(cfg)
    body = _build_body(cfg)

    target_rps = args.target_rps
    if target_rps is not None:
        total_requests: int | None = None
        duration_s: float | None = None
        rps_duration_s: float | None = args.rps_duration if args.rps_duration is not None else 30.0
        mode = "rps"
    else:
        rps_duration_s = None
        total_requests = args.total
        duration_s = args.duration
        if total_requests is None and duration_s is None:
            total_requests = 20
        mode = "duration" if duration_s else "total"

    raw_results: list[RequestResult] | None = [] if args.csv_out else None

    def on_progress(summary: Any) -> None:
        if args.quiet:
            return
        inflight = summary.in_flight_samples[-1] if summary.in_flight_samples else 0
        print(
            f"\r进行中: 完成={summary.total} 成功={summary.success} "
            f"失败={summary.failed} 在飞={inflight}   ",
            end="",
            file=sys.stderr,
            flush=True,
        )

    print(
        f"开始压测: {endpoint} | model={cfg.model} | 并发={cfg.concurrency} | mode={mode}",
        file=sys.stderr,
    )
    summary = await run_benchmark(
        url=endpoint,
        headers=_headers(api_key),
        body_template=body,
        concurrency=cfg.concurrency,
        total_requests=total_requests,
        duration_s=duration_s,
        stream=cfg.stream,
        timeout_s=cfg.timeout_s,
        http2=cfg.http2,
        warmup_requests=cfg.warmup,
        timeline_bucket_s=cfg.timeline_bucket_s,
        prompts=prompts,
        prompt_strategy=args.prompt_strategy or "sequential",
        retry_on_429=cfg.retry_on_429,
        retry_on_network=cfg.retry_on_network,
        retry_on_5xx=cfg.retry_on_5xx,
        target_rps=target_rps,
        rps_duration_s=rps_duration_s,
        raw_results=raw_results,
        proxy_mode=cfg.proxy_mode,
        proxy_url=cfg.proxy_url,
        progress_callback=on_progress,
        progress_every_n=1,
    )
    if not args.quiet:
        print("", file=sys.stderr)

    stats = build_stats_dict(
        summary,
        metadata={
            "model": cfg.model,
            "endpoint": endpoint,
            "mode": mode,
            "concurrency": cfg.concurrency,
            "llm_bench_version": __version__,
        },
    )
    _print_summary(stats)

    if args.json_out:
        args.json_out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 JSON: {args.json_out}", file=sys.stderr)
    if args.csv_out and raw_results is not None:
        args.csv_out.write_bytes(_csv_bytes(raw_results))
        print(f"已写入 CSV: {args.csv_out}", file=sys.stderr)

    if summary.total == 0:
        print("错误: 没有产生任何已完成请求（请检查连通性 / 配置）", file=sys.stderr)
        return 1
    if args.fail_on_error and summary.failed > 0:
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-bench",
        description="大模型 OpenAI 兼容 API 压测工具。不带子命令时启动桌面 GUI。",
    )
    parser.add_argument("--version", action="version", version=f"llm-bench {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="启动桌面 GUI（默认行为）")

    b = sub.add_parser("bench", help="无界面运行一次压测（headless，适合 CI / 脚本）")
    b.add_argument("--config", type=Path, help="YAML 配置路径（缺省用内置默认值）")
    b.add_argument("--base-url", help="API 根路径，覆盖配置，例如 http://localhost:8000/v1")
    b.add_argument("--url", help="完整 endpoint URL，设置后忽略 base-url")
    b.add_argument("--model", help="模型标识")
    b.add_argument("--api-key", help="API Key；缺省读 LLM_API_KEY / OPENAI_API_KEY")
    b.add_argument("-c", "--concurrency", type=int, help="并发数")
    b.add_argument("--max-tokens", type=int, help="单次最大输出 token")
    b.add_argument("--temperature", type=float)
    b.add_argument("--timeout", type=float, dest="timeout_s", help="单请求超时（秒）")
    b.add_argument(
        "--stream", action=argparse.BooleanOptionalAction, default=None, help="启用 SSE 流式"
    )
    b.add_argument("--http2", action=argparse.BooleanOptionalAction, default=None)
    b.add_argument("--warmup", type=int, help="预热请求数（不计入统计）")
    b.add_argument("--total", type=int, help="总请求数（默认 20）")
    b.add_argument("--duration", type=float, help="按时长压测（秒），与 --total 二选一")
    b.add_argument("--rps", type=float, dest="target_rps", help="固定 RPS 目标速率")
    b.add_argument("--rps-duration", type=float, help="固定 RPS 持续秒数（默认 30）")
    b.add_argument("--prompts-file", type=Path, help="每行一条 prompt 的文件")
    b.add_argument(
        "--prompt-strategy",
        choices=("sequential", "random", "weighted"),
        help="多 prompt 选取策略（默认 sequential）",
    )
    b.add_argument("--timeline-bucket", type=float, help="时间线分桶秒数（用于 timeline 输出）")
    b.add_argument("--json", type=Path, dest="json_out", help="把完整统计写入 JSON 文件")
    b.add_argument("--csv", type=Path, dest="csv_out", help="把逐请求结果写入 CSV 文件")
    b.add_argument("-q", "--quiet", action="store_true", help="不打印实时进度")
    b.add_argument(
        "--fail-on-error",
        action="store_true",
        help="存在失败请求时以非 0 退出（CI 友好）",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "bench":
        try:
            code = asyncio.run(_run_bench(args))
        except KeyboardInterrupt:
            print("\n已中断", file=sys.stderr)
            code = 130
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"错误: {exc}", file=sys.stderr)
            code = 2
        sys.exit(code)
    # 无子命令或 `gui` → 桌面 GUI（延迟导入，避免 headless 路径拉起 nicegui）。
    from llm_bench.gui_dual import launch

    launch()


if __name__ == "__main__":
    main()
