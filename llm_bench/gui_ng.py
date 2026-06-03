from __future__ import annotations

import asyncio
import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from nicegui import ui

from llm_bench import __version__
from llm_bench.config import env_api_key
from llm_bench.models import RequestResult, build_stats_dict
from llm_bench.runner import limits_for_concurrency, probe_connectivity, run_benchmark

# ─── constants ────────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_PROMPT = "仅输出15个字符，告诉我你是谁"
_LAYOUT_SIDEBAR_WIDTH_PX = 420
_STATS_LOG_PREVIEW_LIMIT = 4000
_DEFAULT_CUSTOM_BODY = json.dumps(
    {
        "model": _DEFAULT_MODEL,
        "messages": [{"role": "user", "content": _DEFAULT_PROMPT}],
        "max_tokens": 128,
        "temperature": 0.2,
    },
    ensure_ascii=False,
    indent=2,
)

_PROXY_OPTIONS = ["直连", "系统代理", "自定义代理"]
_PROXY_LABEL_TO_VALUE = {"直连": "direct", "系统代理": "system", "自定义代理": "custom"}
_KNOWN_ENDPOINT_SUFFIXES = ("/chat/completions", "/responses", "/completions")

# ─── helpers ──────────────────────────────────────────────────────────────────


def _safe_int(v: Any, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(v))
    except (TypeError, ValueError):
        return max(minimum, default)


def _safe_float(v: Any, default: float, minimum: float | None = None) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        out = default
    if minimum is not None:
        out = max(minimum, out)
    return out


def _normalize_base_url(raw: str) -> tuple[str | None, str | None]:
    raw = (raw or "").strip()
    if not raw:
        return _DEFAULT_BASE_URL, None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, "Base URL 必须是完整地址，例如 https://api.openai.com/v1"
    return raw.rstrip("/"), None


def _resolve_endpoint(base_url: str, endpoint_or_url: str | None = None) -> str:
    raw = (endpoint_or_url or "").strip()
    normalized, _ = _normalize_base_url(base_url)
    base = normalized or _DEFAULT_BASE_URL
    parsed = urlparse(base)
    base_path = parsed.path.rstrip("/")
    base_root = base.rstrip("/")
    matched_suffix = ""
    for suffix in _KNOWN_ENDPOINT_SUFFIXES:
        if base_path.endswith(suffix):
            root_path = base_path[: -len(suffix)].rstrip("/") or "/"
            base_root = urlunparse(
                parsed._replace(path=root_path, params="", query="", fragment="")
            ).rstrip("/")
            matched_suffix = suffix
            break
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if not raw:
        return base if matched_suffix else base.rstrip("/") + "/chat/completions"
    normalized_raw = "/" + raw.lstrip("/")
    if matched_suffix and normalized_raw == matched_suffix:
        return base
    return base_root + normalized_raw


def _resolve_proxy_inputs(proxy_mode: str, proxy_url: str) -> tuple[str, str | None, str | None]:
    mode = (proxy_mode or "direct").strip().lower()
    if mode not in {"direct", "system", "custom"}:
        return "direct", None, "代理模式不合法"
    if mode == "custom":
        raw = (proxy_url or "").strip()
        if not raw:
            return mode, None, "请填写代理地址，例如 http://127.0.0.1:7890"
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.netloc:
            return mode, None, "代理地址格式不正确，需包含协议和端口"
        return mode, raw, None
    return mode, None, None


def _resolve_api_key(api_key: str) -> str | None:
    raw = (api_key or "").strip()
    if raw:
        return raw
    fallback = (env_api_key() or "").strip()
    return fallback or None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _body(model: str, max_tokens: int, temperature: float, stream: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": _DEFAULT_PROMPT}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if stream:
        body["stream"] = True
    return body


def _parse_prompts(raw: str) -> list[str] | None:
    prompts = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return prompts if prompts else None


def _parse_custom_body(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, "请求体不能为空"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败: {exc}"
    if not isinstance(data, dict):
        return None, "请求体必须是 JSON 对象"
    return data, None


def _v(v: Any, d: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{d}f}"
    return str(v)


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _download_bytes(data: bytes, filename: str, media_type: str) -> None:
    ui.download(data, filename=filename, media_type=media_type)


def _stats_log_preview(stats: dict[str, Any], max_chars: int = _STATS_LOG_PREVIEW_LIMIT) -> str:
    preview = json.dumps(stats, ensure_ascii=False, indent=2)
    if len(preview) <= max_chars:
        return preview
    suffix = "\n... (统计 JSON 已截断，完整内容请使用导出按钮保存)"
    return preview[: max_chars - len(suffix)].rstrip() + suffix


def _csv_bytes(rows: list[RequestResult]) -> bytes:
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


def _stat_rows(stats: dict[str, Any]) -> list[dict[str, str]]:
    items = [
        ("总请求数", stats.get("requests_total")),
        ("HTTP attempts", stats.get("http_attempts_total")),
        ("成功", stats.get("requests_success")),
        ("失败", stats.get("requests_failed")),
        ("成功率 %", _v(stats.get("success_rate_pct"))),
        ("墙钟时间 s", _v(stats.get("wall_seconds"))),
        ("吞吐 req/s", _v(stats.get("throughput_rps"))),
        ("延迟 p50 ms", _v(stats.get("latency_ms_p50"))),
        ("延迟 p95 ms", _v(stats.get("latency_ms_p95"))),
        ("延迟 p99 ms", _v(stats.get("latency_ms_p99"))),
        ("最终尝试延迟 p50 ms", _v(stats.get("final_attempt_latency_ms_p50"))),
        ("TTFT p50 ms", _v(stats.get("ttft_ms_p50"))),
        ("TPOT p50 ms", _v(stats.get("tpot_ms_p50"))),
        ("ITL p50 ms", _v(stats.get("itl_ms_p50"))),
        ("在飞请求 mean", _v(stats.get("in_flight_mean"))),
        ("在飞请求 max", _v(stats.get("in_flight_max"))),
        ("RPS 跳过调度数", stats.get("rps_schedule_skipped")),
        ("tok/s", _v(stats.get("throughput_completion_tok_s"))),
    ]
    return [{"指标": k, "值": str(v) if v is not None else "-"} for k, v in items]


# ─── state ────────────────────────────────────────────────────────────────────


@dataclass
class _RunState:
    """每次压测任务的运行时状态，绑定到 NiceGUI 的响应式更新。"""

    busy: bool = False
    status: str = "就绪"
    log_lines: list[str] = None  # type: ignore[assignment]
    stats: dict[str, Any] = None  # type: ignore[assignment]
    raw_results: list[RequestResult] = None  # type: ignore[assignment]
    inflight_samples: list[int] = None  # type: ignore[assignment]
    stop_event: asyncio.Event = None  # type: ignore[assignment]
    started_at_mono: float | None = None
    target_total: int | None = None
    target_duration_s: float | None = None
    consumed_prompt_tokens: int = 0
    consumed_completion_tokens: int = 0
    chart_refresh_mode: str = "interval"
    chart_refresh_interval_s: float = 0.3
    chart_refresh_every_n: int = 5

    def __post_init__(self) -> None:
        self.log_lines = []
        self.stats = {}
        self.raw_results = []
        self.inflight_samples = []
        self.stop_event = asyncio.Event()

    def reset(self) -> None:
        """Reset metrics for a new run. Does NOT clear the stop_event —
        callers that need a fresh event must call :meth:`fresh_stop_event`
        explicitly. This separation fixes the Test#2 race where a phase-N
        reset in _execute_loadcurve would silently clear the user's
        stop signal between phases."""
        self.busy = True
        self.status = "运行中..."
        self.log_lines = []
        self.stats = {}
        self.raw_results = []
        self.inflight_samples = []
        self.started_at_mono = None
        self.target_total = None
        self.target_duration_s = None

    def fresh_stop_event(self) -> None:
        """Allocate a brand-new stop_event. Call this ONLY when starting
        a brand-new run (i.e. the start button was just clicked), never
        between internal phase transitions of a multi-phase run."""
        self.stop_event = asyncio.Event()


# ─── page builder ─────────────────────────────────────────────────────────────


def _build_page(history: list[dict[str, Any]], set_status: Any) -> None:
    """构建页面主体（header 已在调用方创建）。"""

    run_state = _RunState()
    sweep_state: dict[str, Any] = {"busy": False, "rows": [], "all_stats": [], "log": ""}

    # 固定宽度侧栏，彻底放弃拖拽分割，优先保证桌面 WebView 下的稳定显示与滚动。
    with (
        ui.left_drawer(value=True, top_corner=True, bottom_corner=True, bordered=True)
        .classes("bg-white")
        .style(f"width:{_LAYOUT_SIDEBAR_WIDTH_PX}px"),
        ui.column().classes("w-full p-4 gap-3"),
    ):
        ui.label("压测工作台").classes("text-lg font-bold text-indigo-700")
        ui.label("常用配置在前，高级配置折叠。").classes("text-xs text-gray-500")

        # ── 端点预览 ──────────────────────────────────────────
        endpoint_preview = ui.label("").classes("text-xs text-gray-400 break-all")

        # ── 基础连接 ──────────────────────────────────────────
        with ui.expansion("基础连接", icon="link", value=True).classes("w-full border rounded"):
            base_url = ui.input("Base URL", value=_DEFAULT_BASE_URL).classes("w-full")
            api_key = ui.input(
                "API Key", password=True, password_toggle_button=True, value=env_api_key() or ""
            ).classes("w-full")
            model = ui.input("Model", value=_DEFAULT_MODEL).classes("w-full")
            concurrency = ui.number("并发上限", value=5, min=1, step=1).classes("w-full")

        # ── 请求输入 ──────────────────────────────────────────
        with ui.expansion("请求输入", icon="edit", value=True).classes("w-full border rounded"):
            max_tokens = ui.number("max_tokens", value=128, min=1, step=1).classes("w-full")
            temperature = ui.number(
                "temperature", value=0.2, min=0.0, step=0.1, format="%.1f"
            ).classes("w-full")
            with ui.row().classes("items-center gap-4"):
                stream_sw = ui.switch("流式输出", value=False)
            ui.label("Prompt 列表（每行一条）").classes("text-xs text-gray-500 mt-2")
            prompts_area = ui.textarea(placeholder="留空则使用默认 Prompt").classes(
                "w-full font-mono text-sm"
            )
            prompts_area.props("rows=5")

            with ui.expansion("全自定义请求体", icon="code").classes("w-full mt-2"):
                custom_enabled = ui.switch("启用全自定义请求体", value=False)
                custom_endpoint = ui.input(
                    "请求路径 / 完整 URL", value="/chat/completions"
                ).classes("w-full")
                custom_stream_sw = ui.switch("按流式响应解析", value=False)
                ui.label("自定义请求体 JSON").classes("text-xs text-gray-500 mt-2")
                custom_body = ui.textarea(value=_DEFAULT_CUSTOM_BODY).classes(
                    "w-full font-mono text-sm"
                )
                custom_body.props("rows=9")

        # ── 网络与诊断 ─────────────────────────────────────────
        with ui.expansion("网络与诊断", icon="wifi").classes("w-full border rounded"):
            proxy_mode = ui.select(
                options=_PROXY_OPTIONS,
                value="直连",
                label="代理模式",
            ).classes("w-full")
            proxy_url_input = ui.input("代理地址", value="http://127.0.0.1:7890").classes("w-full")
            proxy_url_input.set_visibility(False)
            proxy_mode.on_value_change(
                lambda e: proxy_url_input.set_visibility(e.value == "自定义代理")
            )
            conn_timeout = ui.number("连通性超时（秒）", value=10, min=1, step=1).classes("w-full")
            conn_status = ui.label("尚未测试连通性").classes("text-xs text-gray-500")

            async def _test_connectivity() -> None:
                conn_status.set_text("连通性测试中...")
                norm_url, err = _normalize_base_url(base_url.value)
                if err:
                    conn_status.set_text(f"❌ {err}")
                    return
                ep = _resolve_endpoint(
                    norm_url or _DEFAULT_BASE_URL,
                    custom_endpoint.value if custom_enabled.value else None,
                )
                try:
                    result = await probe_connectivity(
                        url=ep,
                        timeout_s=_safe_float(conn_timeout.value, 10.0, 1.0),
                        http2=http2_sw.value,
                        proxy_mode=_PROXY_LABEL_TO_VALUE.get(proxy_mode.value, "direct"),
                        proxy_url=(proxy_url_input.value or "").strip() or None,
                    )
                except Exception as exc:
                    conn_status.set_text(f"❌ 连通性测试失败：{exc}")
                    return
                if result.get("ok"):
                    conn_status.set_text(
                        f"✅ 连通性正常｜status={result.get('status_code')}｜耗时={_v(result.get('elapsed_ms'))}ms"
                    )
                else:
                    conn_status.set_text(
                        f"❌ 连通性失败｜{result.get('error_kind', '')}｜{str(result.get('detail') or '')[:80]}"
                    )

            ui.button("测试连接", icon="network_check", on_click=_test_connectivity).classes("mt-2")

        # ── 高级控制 ──────────────────────────────────────────
        with ui.expansion("高级控制", icon="tune").classes("w-full border rounded"):
            timeout_s = ui.number("超时（秒）", value=120, min=1, step=1).classes("w-full")
            warmup = ui.number("预热请求数", value=0, min=0, step=1).classes("w-full")
            retry_429 = ui.number("429 重试次数", value=3, min=0, step=1).classes("w-full")
            retry_net = ui.number("网络错误重试", value=1, min=0, step=1).classes("w-full")
            retry_5xx = ui.number("5xx 重试次数", value=1, min=0, step=1).classes("w-full")
            backoff = ui.number(
                "退避基数（秒）", value=1.0, min=0.1, step=0.1, format="%.1f"
            ).classes("w-full")
            with ui.row().classes("items-center gap-4"):
                http2_sw = ui.switch("HTTP/2", value=False)

        def _update_preview(*_: Any) -> None:
            ep = _resolve_endpoint(
                base_url.value,
                custom_endpoint.value if custom_enabled.value else None,
            )
            endpoint_preview.set_text(f"请求地址：{ep}")

        base_url.on_value_change(_update_preview)
        custom_endpoint.on_value_change(_update_preview)
        custom_enabled.on_value_change(_update_preview)
        _update_preview()

    with ui.column().classes("w-full flex-1 min-h-0 overflow-hidden bg-white"):
        with ui.tabs().classes("w-full bg-gray-50 border-b") as right_tabs:
            tab_run = ui.tab("单次压测", icon="play_arrow")
            tab_rps = ui.tab("固定 RPS", icon="speed")
            tab_sweep = ui.tab("并发扫描", icon="bar_chart")
            tab_history = ui.tab("历史记录", icon="history")

        with ui.tab_panels(right_tabs, value=tab_run).classes(
            "w-full flex-1 min-h-0 overflow-hidden"
        ):
            with ui.tab_panel(tab_run).classes("p-4 h-full overflow-auto"):
                _build_run_tab(
                    run_state=run_state,
                    history=history,
                    get_settings=lambda: dict(
                        base_url=base_url.value,
                        api_key=api_key.value,
                        model=model.value,
                        concurrency=int(concurrency.value or 5),
                        max_tokens=int(max_tokens.value or 128),
                        temperature=float(temperature.value or 0.2),
                        timeout_s=float(timeout_s.value or 120),
                        warmup=int(warmup.value or 0),
                        retry_on_429=int(retry_429.value or 3),
                        retry_on_network=int(retry_net.value or 1),
                        retry_on_5xx=int(retry_5xx.value or 1),
                        base_backoff_s=float(backoff.value or 1.0),
                        stream=stream_sw.value,
                        http2=http2_sw.value,
                        proxy_mode=_PROXY_LABEL_TO_VALUE.get(proxy_mode.value, "direct"),
                        proxy_url=(proxy_url_input.value or "").strip() or None,
                        custom_enabled=custom_enabled.value,
                        custom_endpoint=custom_endpoint.value,
                        custom_stream=custom_stream_sw.value,
                        custom_body_json=custom_body.value,
                        prompts_raw=prompts_area.value,
                    ),
                    set_status=set_status,
                    mode="run",
                )

            with ui.tab_panel(tab_rps).classes("p-4 h-full overflow-auto"):
                _build_run_tab(
                    run_state=_RunState(),
                    history=history,
                    get_settings=lambda: dict(
                        base_url=base_url.value,
                        api_key=api_key.value,
                        model=model.value,
                        concurrency=int(concurrency.value or 5),
                        max_tokens=int(max_tokens.value or 128),
                        temperature=float(temperature.value or 0.2),
                        timeout_s=float(timeout_s.value or 120),
                        warmup=int(warmup.value or 0),
                        retry_on_429=int(retry_429.value or 3),
                        retry_on_network=int(retry_net.value or 1),
                        retry_on_5xx=int(retry_5xx.value or 1),
                        base_backoff_s=float(backoff.value or 1.0),
                        stream=stream_sw.value,
                        http2=http2_sw.value,
                        proxy_mode=_PROXY_LABEL_TO_VALUE.get(proxy_mode.value, "direct"),
                        proxy_url=(proxy_url_input.value or "").strip() or None,
                        custom_enabled=custom_enabled.value,
                        custom_endpoint=custom_endpoint.value,
                        custom_stream=custom_stream_sw.value,
                        custom_body_json=custom_body.value,
                        prompts_raw=prompts_area.value,
                    ),
                    set_status=set_status,
                    mode="rps",
                )

            with ui.tab_panel(tab_sweep).classes("p-4 h-full overflow-auto"):
                _build_sweep_tab(
                    sweep_state=sweep_state,
                    history=history,
                    get_settings=lambda: dict(
                        base_url=base_url.value,
                        api_key=api_key.value,
                        model=model.value,
                        concurrency=int(concurrency.value or 5),
                        max_tokens=int(max_tokens.value or 128),
                        temperature=float(temperature.value or 0.2),
                        timeout_s=float(timeout_s.value or 120),
                        warmup=int(warmup.value or 0),
                        retry_on_429=int(retry_429.value or 3),
                        retry_on_network=int(retry_net.value or 1),
                        retry_on_5xx=int(retry_5xx.value or 1),
                        base_backoff_s=float(backoff.value or 1.0),
                        stream=stream_sw.value,
                        http2=http2_sw.value,
                        proxy_mode=_PROXY_LABEL_TO_VALUE.get(proxy_mode.value, "direct"),
                        proxy_url=(proxy_url_input.value or "").strip() or None,
                        custom_enabled=custom_enabled.value,
                        custom_endpoint=custom_endpoint.value,
                        custom_stream=custom_stream_sw.value,
                        custom_body_json=custom_body.value,
                        prompts_raw=prompts_area.value,
                    ),
                    set_status=set_status,
                )

            with ui.tab_panel(tab_history).classes("p-4 h-full overflow-auto"):
                _build_history_tab(history)


# ─── run tab ──────────────────────────────────────────────────────────────────


def _build_run_tab(
    *,
    run_state: _RunState,
    history: list[dict[str, Any]],
    get_settings: Any,
    set_status: Any,
    mode: str,
) -> None:
    is_rps = mode == "rps"
    label_prefix = "固定 RPS" if is_rps else "单次压测"

    # ── 控制栏 ────────────────────────────────────────────────────────────
    with ui.card().classes("w-full mb-4"), ui.row().classes("items-end gap-4 flex-wrap"):
        if is_rps:
            rps_target = ui.number("目标 RPS", value=5.0, min=0.1, step=0.5, format="%.1f").classes(
                "w-32"
            )
            rps_duration = ui.number("持续时长（秒）", value=30, min=1, step=1).classes("w-32")
        else:
            run_total = ui.number("总请求数", value=20, min=1, step=1).classes("w-32")
            run_duration = ui.number("时长（秒，0=按总数）", value=0, min=0, step=1).classes("w-40")

        start_btn = ui.button(f"开始{label_prefix}", icon="play_arrow").props("color=indigo")
        stop_btn = ui.button("停止", icon="stop").props("color=red outline").classes("ml-2")
        stop_btn.disable()

    # ── KPI 卡片 ─────────────────────────────────────────────────────────
    kpi_keys = [
        ("吞吐 req/s", "throughput_rps"),
        ("延迟 p50 ms", "latency_ms_p50"),
        ("延迟 p99 ms", "latency_ms_p99"),
        ("成功率 %", "success_rate_pct"),
        ("tok/s", "throughput_completion_tok_s"),
    ]
    kpi_labels: dict[str, ui.label] = {}
    with ui.row().classes("w-full gap-3 mb-4"):
        for title, key in kpi_keys:
            with ui.card().classes("flex-1 min-w-24 text-center py-3"):
                ui.label(title).classes("text-xs text-gray-500")
                lbl = ui.label("-").classes("text-2xl font-bold text-indigo-700 mt-1")
                kpi_labels[key] = lbl

    # ── 结果标签页 ────────────────────────────────────────────────────────
    with ui.tabs().classes("w-full") as result_tabs:
        rtab_overview = ui.tab("概览", icon="table_chart")
        rtab_charts = ui.tab("图表", icon="bar_chart")
        rtab_log = ui.tab("日志", icon="terminal")

    with ui.tab_panels(result_tabs, value=rtab_overview).classes("w-full border rounded"):
        # 概览：指标表
        with ui.tab_panel(rtab_overview).classes("p-3"):
            stat_cols = [
                {
                    "name": "metric",
                    "label": "指标",
                    "field": "指标",
                    "align": "left",
                    "sortable": False,
                },
                {"name": "value", "label": "值", "field": "值", "align": "left", "sortable": False},
            ]
            stat_table = ui.table(columns=stat_cols, rows=[], row_key="指标").classes("w-full")
            stat_table.props("dense flat")

        # 图表：延迟分位 + 在飞请求
        with ui.tab_panel(rtab_charts).classes("p-3"):
            with ui.row().classes("w-full gap-4"):
                latency_chart = ui.echart(
                    {
                        "title": {"text": "延迟分位 (ms)", "textStyle": {"fontSize": 13}},
                        "tooltip": {},
                        "xAxis": {
                            "type": "category",
                            "data": ["p50", "p75", "p90", "p95", "p99", "p99.9"],
                        },
                        "yAxis": {"type": "value", "name": "ms"},
                        "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#4f46e5"}}],
                    }
                ).classes("flex-1 h-64")
                stream_chart = ui.echart(
                    {
                        "title": {"text": "流式指标 (ms)", "textStyle": {"fontSize": 13}},
                        "tooltip": {},
                        "xAxis": {
                            "type": "category",
                            "data": [
                                "TTFT p50",
                                "TTFT p95",
                                "TPOT p50",
                                "TPOT p95",
                                "ITL p50",
                                "ITL p95",
                            ],
                        },
                        "yAxis": {"type": "value", "name": "ms"},
                        "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#059669"}}],
                    }
                ).classes("flex-1 h-64")
            inflight_chart = ui.echart(
                {
                    "title": {"text": "在飞请求时序", "textStyle": {"fontSize": 13}},
                    "tooltip": {"trigger": "axis"},
                    "xAxis": {"type": "category", "data": [], "boundaryGap": False},
                    "yAxis": {"type": "value", "name": "in-flight"},
                    "series": [
                        {
                            "type": "line",
                            "data": [],
                            "smooth": True,
                            "areaStyle": {"opacity": 0.3},
                            "lineStyle": {"color": "#7c3aed"},
                            "itemStyle": {"color": "#7c3aed"},
                        }
                    ],
                }
            ).classes("w-full h-52 mt-2")

        # 日志
        with ui.tab_panel(rtab_log).classes("p-3"), ui.row().classes("w-full gap-4"):
            with ui.column().classes("flex-1"):
                ui.label("实时日志").classes("text-xs font-bold text-gray-500 mb-1")
                live_log = ui.log(max_lines=200).classes(
                    "w-full h-72 font-mono text-xs border rounded"
                )
            with ui.column().classes("flex-1"):
                ui.label("运行日志 / 统计 JSON").classes("text-xs font-bold text-gray-500 mb-1")
                full_log = ui.log(max_lines=500).classes(
                    "w-full h-72 font-mono text-xs border rounded"
                )

    # ── 导出按钮 ──────────────────────────────────────────────────────────
    with ui.row().classes("mt-3 gap-3"):
        export_json_btn = ui.button("导出 JSON", icon="download").props("outline")
        export_json_btn.disable()
        export_csv_btn = ui.button("导出 CSV", icon="download").props("outline")
        export_csv_btn.disable()

    # ── 内部辅助 ──────────────────────────────────────────────────────────

    def _update_kpis(stats: dict[str, Any]) -> None:
        for key, lbl in kpi_labels.items():
            suffix = " %" if key == "success_rate_pct" else ""
            lbl.set_text(f"{_v(stats.get(key))}{suffix}")

    def _update_charts(stats: dict[str, Any], inflight: list[int]) -> None:
        lat_keys = [
            "latency_ms_p50",
            "latency_ms_p75",
            "latency_ms_p90",
            "latency_ms_p95",
            "latency_ms_p99",
            "latency_ms_p99_9",
        ]
        latency_chart.options["series"][0]["data"] = [
            round(float(stats.get(k) or 0), 2) for k in lat_keys
        ]
        latency_chart.update()

        stream_keys = [
            "ttft_ms_p50",
            "ttft_ms_p95",
            "tpot_ms_p50",
            "tpot_ms_p95",
            "itl_ms_p50",
            "itl_ms_p95",
        ]
        stream_chart.options["series"][0]["data"] = [
            round(float(stats.get(k) or 0), 2) for k in stream_keys
        ]
        stream_chart.update()

        xs = [str(i) for i in range(len(inflight))]
        inflight_chart.options["xAxis"]["data"] = xs
        inflight_chart.options["series"][0]["data"] = inflight
        inflight_chart.update()

    def _build_runtime_payload(s: dict[str, Any]) -> dict[str, Any]:
        norm_url, err = _normalize_base_url(s["base_url"])
        if err:
            raise ValueError(err)
        _, _, proxy_err = _resolve_proxy_inputs(s["proxy_mode"], s.get("proxy_url") or "")
        if proxy_err:
            raise ValueError(proxy_err)
        if s["custom_enabled"]:
            body_template, body_err = _parse_custom_body(s["custom_body_json"])
            if body_err:
                raise ValueError(body_err)
            stream_flag = bool(s["custom_stream"])
            endpoint = _resolve_endpoint(norm_url or _DEFAULT_BASE_URL, s["custom_endpoint"])
            prompts = None
        else:
            body_template = _body(
                (s["model"] or _DEFAULT_MODEL).strip(),
                _safe_int(s["max_tokens"], 128, 1),
                _safe_float(s["temperature"], 0.2, 0.0),
                bool(s["stream"]),
            )
            stream_flag = bool(s["stream"])
            endpoint = _resolve_endpoint(norm_url or _DEFAULT_BASE_URL)
            prompts = _parse_prompts(s["prompts_raw"] or "")
        return {
            "endpoint": endpoint,
            "stream_flag": stream_flag,
            "body_template": body_template,
            "prompts": prompts,
            "proxy_mode": s["proxy_mode"],
            "proxy_url": s.get("proxy_url"),
        }

    async def _do_run() -> None:
        s = get_settings()
        resolved_key = _resolve_api_key(s["api_key"])
        if not resolved_key:
            ui.notify("输入框和环境变量都没有 API Key", type="negative")
            return
        if run_state.busy:
            ui.notify("已有任务运行中", type="warning")
            return

        try:
            runtime = _build_runtime_payload(s)
        except ValueError as exc:
            ui.notify(f"配置不合法：{exc}", type="negative")
            return

        run_state.reset()
        start_btn.disable()
        stop_btn.enable()
        set_status("运行中", "orange")
        live_log.clear()
        full_log.clear()
        stat_table.rows.clear()
        stat_table.update()
        export_json_btn.disable()
        export_csv_btn.disable()
        for lbl in kpi_labels.values():
            lbl.set_text("-")

        if is_rps:
            mode_payload: dict[str, Any] = {
                "target_rps": _safe_float(rps_target.value, 5.0, 0.1),
                "rps_duration_s": _safe_float(rps_duration.value, 30.0, 1.0),
                "total_requests": None,
                "duration_s": None,
            }
        else:
            dur = _safe_float(run_duration.value, 0.0, 0.0)
            mode_payload = {
                "total_requests": None if dur > 0 else _safe_int(run_total.value, 20, 1),
                "duration_s": dur if dur > 0 else None,
                "target_rps": None,
                "rps_duration_s": None,
            }

        progress_stride = max(1, s["concurrency"] // 2 + 1)

        def on_progress(summary: Any) -> None:
            if summary.total % progress_stride != 0:
                return
            line = (
                f"[{datetime.now():%H:%M:%S}] OK={summary.success} FAIL={summary.failed} "
                f"TOTAL={summary.total} "
                f"INFLIGHT={summary.in_flight_samples[-1] if summary.in_flight_samples else 0}"
            )
            run_state.log_lines.append(line)
            live_log.push(line)

        try:
            summary = await run_benchmark(
                url=runtime["endpoint"],
                headers=_headers(resolved_key),
                body_template=runtime["body_template"],
                concurrency=s["concurrency"],
                total_requests=mode_payload.get("total_requests"),
                duration_s=mode_payload.get("duration_s"),
                stream=runtime["stream_flag"],
                timeout_s=s["timeout_s"],
                http2=s["http2"],
                warmup_requests=s["warmup"],
                retry_on_429=s["retry_on_429"],
                retry_on_network=s["retry_on_network"],
                retry_on_5xx=s["retry_on_5xx"],
                base_backoff_s=s["base_backoff_s"],
                prompts=runtime["prompts"],
                target_rps=mode_payload.get("target_rps"),
                rps_duration_s=mode_payload.get("rps_duration_s"),
                raw_results=run_state.raw_results,
                proxy_mode=runtime["proxy_mode"],
                proxy_url=runtime["proxy_url"],
                progress_callback=on_progress,
                progress_every_n=1,
                should_stop=run_state.stop_event.is_set,
            )
            stats = build_stats_dict(
                summary,
                metadata={
                    "bench_start_utc": datetime.now(UTC).isoformat(),
                    "llm_bench_version": __version__,
                    "endpoint": runtime["endpoint"],
                    "model": s["model"],
                    "concurrency": s["concurrency"],
                    "mode": mode,
                    "target_rps": mode_payload.get("target_rps"),
                    "rps_duration_s": mode_payload.get("rps_duration_s"),
                    "proxy_mode": runtime["proxy_mode"],
                },
            )
            run_state.stats = stats
            run_state.inflight_samples = list(summary.in_flight_samples)
            history.append(stats)

            stat_table.rows[:] = _stat_rows(stats)
            stat_table.update()
            _update_kpis(stats)
            _update_charts(stats, run_state.inflight_samples)
            full_log.push(_stats_log_preview(stats))

            run_state.status = "✅ 完成"
            set_status("已完成", "green")
            ui.notify("压测完成", type="positive")
            export_json_btn.enable()
            export_csv_btn.enable()
        except asyncio.CancelledError:
            run_state.status = "已停止"
            set_status("已停止", "gray")
            ui.notify("任务已停止", type="warning")
            return
        except Exception as exc:
            run_state.status = "失败"
            set_status("失败", "red")
            ui.notify(f"压测失败：{exc}", type="negative")
            return
        finally:
            run_state.busy = False
            start_btn.enable()
            stop_btn.disable()

    def _do_stop() -> None:
        run_state.stop_event.set()
        set_status("停止中...", "orange")

    def _export_json() -> None:
        if not run_state.stats:
            return
        data = json.dumps(run_state.stats, ensure_ascii=False, indent=2).encode("utf-8")
        fname = f"bench_{mode}_{_timestamp_slug()}.json"
        _download_bytes(data, fname, "application/json; charset=utf-8")

    def _export_csv() -> None:
        if not run_state.raw_results:
            return
        fname = f"bench_{mode}_{_timestamp_slug()}.csv"
        _download_bytes(_csv_bytes(run_state.raw_results), fname, "text/csv; charset=utf-8")

    start_btn.on_click(lambda: asyncio.create_task(_do_run()))
    stop_btn.on_click(_do_stop)
    export_json_btn.on_click(_export_json)
    export_csv_btn.on_click(_export_csv)


# ─── sweep tab ────────────────────────────────────────────────────────────────


def _build_sweep_tab(
    *,
    sweep_state: dict[str, Any],
    history: list[dict[str, Any]],
    get_settings: Any,
    set_status: Any,
) -> None:

    with ui.card().classes("w-full mb-4"), ui.row().classes("items-end gap-4 flex-wrap"):
        sweep_levels = ui.input("并发级别（逗号分隔）", value="1,2,4,8,16").classes("w-56")
        sweep_per = ui.number("每档请求数", value=40, min=1, step=1).classes("w-32")
        sweep_start_btn = ui.button("开始扫描", icon="play_arrow").props("color=indigo")
        sweep_stop_btn = ui.button("停止", icon="stop").props("color=red outline")
        sweep_stop_btn.disable()

    # KPI 摘要
    with ui.row().classes("w-full gap-3 mb-4"):
        for title, key in [
            ("档位数", "levels"),
            ("最佳 req/s", "best_rps"),
            ("最低 p95 ms", "best_p95"),
        ]:
            with ui.card().classes("flex-1 text-center py-3"):
                ui.label(title).classes("text-xs text-gray-500")
                lbl = ui.label("-").classes("text-2xl font-bold text-indigo-700 mt-1")
                sweep_state[f"kpi_{key}"] = lbl

    with ui.tabs().classes("w-full") as sweep_tabs:
        stab_overview = ui.tab("概览", icon="table_chart")
        stab_charts = ui.tab("图表", icon="bar_chart")
        stab_log = ui.tab("日志", icon="terminal")

    with ui.tab_panels(sweep_tabs, value=stab_overview).classes("w-full border rounded"):
        with ui.tab_panel(stab_overview).classes("p-3"):
            sweep_cols = [
                {"name": "concurrency", "label": "并发", "field": "并发", "align": "center"},
                {"name": "success", "label": "成功率%", "field": "成功率%", "align": "center"},
                {"name": "p50", "label": "p50 ms", "field": "p50 ms", "align": "center"},
                {"name": "p95", "label": "p95 ms", "field": "p95 ms", "align": "center"},
                {"name": "p99", "label": "p99 ms", "field": "p99 ms", "align": "center"},
                {"name": "rps", "label": "req/s", "field": "req/s", "align": "center"},
                {"name": "toks", "label": "tok/s", "field": "tok/s", "align": "center"},
            ]
            sweep_table = ui.table(columns=sweep_cols, rows=[], row_key="并发").classes("w-full")
            sweep_table.props("dense flat")

        with ui.tab_panel(stab_charts).classes("p-3"), ui.row().classes("w-full gap-4"):
            sweep_lat_chart = ui.echart(
                {
                    "title": {"text": "延迟随并发变化", "textStyle": {"fontSize": 13}},
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": ["p50", "p95", "p99"]},
                    "xAxis": {"type": "category", "data": [], "name": "并发"},
                    "yAxis": {"type": "value", "name": "ms"},
                    "series": [
                        {
                            "name": "p50",
                            "type": "line",
                            "data": [],
                            "smooth": True,
                            "itemStyle": {"color": "#4f46e5"},
                        },
                        {
                            "name": "p95",
                            "type": "line",
                            "data": [],
                            "smooth": True,
                            "itemStyle": {"color": "#d97706"},
                        },
                        {
                            "name": "p99",
                            "type": "line",
                            "data": [],
                            "smooth": True,
                            "itemStyle": {"color": "#dc2626"},
                        },
                    ],
                }
            ).classes("flex-1 h-72")
            sweep_rps_chart = ui.echart(
                {
                    "title": {"text": "吞吐随并发变化", "textStyle": {"fontSize": 13}},
                    "tooltip": {},
                    "xAxis": {"type": "category", "data": [], "name": "并发"},
                    "yAxis": {"type": "value", "name": "req/s"},
                    "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#0891b2"}}],
                }
            ).classes("flex-1 h-72")

        with ui.tab_panel(stab_log).classes("p-3"):
            sweep_log = ui.log(max_lines=300).classes(
                "w-full h-72 font-mono text-xs border rounded"
            )

    with ui.row().classes("mt-3"):
        sweep_export_btn = ui.button("导出扫描 JSON", icon="download").props("outline")
        sweep_export_btn.disable()

    def _update_sweep_charts(all_stats: list[dict[str, Any]]) -> None:
        xs = [str(s.get("concurrency_level", i + 1)) for i, s in enumerate(all_stats)]
        sweep_lat_chart.options["xAxis"]["data"] = xs
        sweep_rps_chart.options["xAxis"]["data"] = xs
        for i, key in enumerate(["latency_ms_p50", "latency_ms_p95", "latency_ms_p99"]):
            sweep_lat_chart.options["series"][i]["data"] = [
                round(float(s.get(key) or 0), 2) for s in all_stats
            ]
        sweep_rps_chart.options["series"][0]["data"] = [
            round(float(s.get("throughput_rps") or 0), 2) for s in all_stats
        ]
        sweep_lat_chart.update()
        sweep_rps_chart.update()

        best_rps = max((float(s.get("throughput_rps") or 0) for s in all_stats), default=0.0)
        p95_vals = [
            float(s.get("latency_ms_p95") or 0) for s in all_stats if s.get("latency_ms_p95")
        ]
        best_p95 = min(p95_vals) if p95_vals else 0.0
        sweep_state["kpi_levels"].set_text(str(len(all_stats)))
        sweep_state["kpi_best_rps"].set_text(_v(best_rps))
        sweep_state["kpi_best_p95"].set_text(_v(best_p95))

    async def _do_sweep() -> None:
        s = get_settings()
        resolved_key = _resolve_api_key(s["api_key"])
        if not resolved_key:
            ui.notify("输入框和环境变量都没有 API Key", type="negative")
            return
        if sweep_state.get("busy"):
            ui.notify("已有扫描任务运行中", type="warning")
            return

        try:
            raw_levels_str = sweep_levels.value.replace(";", ",")
            levels = [int(x.strip()) for x in raw_levels_str.split(",") if x.strip()]
        except ValueError:
            ui.notify("并发级别只能填整数，多个用逗号分隔，例如：1,2,4,8,16", type="negative")
            return
        if not levels:
            ui.notify("并发级别不能为空", type="negative")
            return
        levels = [max(1, lv) for lv in levels]

        try:
            norm_url, err = _normalize_base_url(s["base_url"])
            if err:
                raise ValueError(err)
            _, _, proxy_err = _resolve_proxy_inputs(s["proxy_mode"], s.get("proxy_url") or "")
            if proxy_err:
                raise ValueError(proxy_err)
            if s["custom_enabled"]:
                body_template, body_err = _parse_custom_body(s["custom_body_json"])
                if body_err:
                    raise ValueError(body_err)
                stream_flag = bool(s["custom_stream"])
                endpoint = _resolve_endpoint(norm_url or _DEFAULT_BASE_URL, s["custom_endpoint"])
                prompts = None
            else:
                body_template = _body(
                    (s["model"] or _DEFAULT_MODEL).strip(),
                    _safe_int(s["max_tokens"], 128, 1),
                    _safe_float(s["temperature"], 0.2, 0.0),
                    bool(s["stream"]),
                )
                stream_flag = bool(s["stream"])
                endpoint = _resolve_endpoint(norm_url or _DEFAULT_BASE_URL)
                prompts = _parse_prompts(s["prompts_raw"] or "")
        except ValueError as exc:
            ui.notify(f"配置不合法：{exc}", type="negative")
            return

        sweep_state["busy"] = True
        sweep_state["all_stats"] = []
        sweep_state["stop_event"] = asyncio.Event()
        sweep_start_btn.disable()
        sweep_stop_btn.enable()
        sweep_export_btn.disable()
        sweep_table.rows.clear()
        sweep_table.update()
        sweep_log.clear()
        set_status("扫描中", "orange")

        per_n = _safe_int(sweep_per.value, 40, 1)
        proxy_url_val = s.get("proxy_url")
        shared_proxy = proxy_url_val if s["proxy_mode"] == "custom" else None
        shared_trust_env = s["proxy_mode"] == "system"

        try:
            async with httpx.AsyncClient(
                http2=s["http2"],
                limits=limits_for_concurrency(max(levels)),
                proxy=shared_proxy,
                trust_env=shared_trust_env,
            ) as shared_client:
                for concurrency in levels:
                    if sweep_state["stop_event"].is_set():
                        break
                    summary = await run_benchmark(
                        url=endpoint,
                        headers=_headers(resolved_key),
                        body_template=body_template,
                        concurrency=concurrency,
                        total_requests=per_n,
                        duration_s=None,
                        stream=stream_flag,
                        timeout_s=s["timeout_s"],
                        http2=s["http2"],
                        warmup_requests=s["warmup"],
                        retry_on_429=s["retry_on_429"],
                        retry_on_network=s["retry_on_network"],
                        retry_on_5xx=s["retry_on_5xx"],
                        base_backoff_s=s["base_backoff_s"],
                        prompts=prompts,
                        proxy_mode=s["proxy_mode"],
                        proxy_url=proxy_url_val,
                        shared_client=shared_client,
                        should_stop=sweep_state["stop_event"].is_set,
                    )
                    stat = build_stats_dict(
                        summary,
                        metadata={
                            "bench_start_utc": datetime.now(UTC).isoformat(),
                            "llm_bench_version": __version__,
                            "endpoint": endpoint,
                            "model": s["model"],
                            "concurrency": concurrency,
                            "mode": "sweep",
                        },
                    )
                    stat["concurrency_level"] = concurrency
                    sweep_state["all_stats"].append(stat)
                    history.append(stat)

                    sweep_table.rows.append(
                        {
                            "并发": str(concurrency),
                            "成功率%": _v(stat.get("success_rate_pct")),
                            "p50 ms": _v(stat.get("latency_ms_p50")),
                            "p95 ms": _v(stat.get("latency_ms_p95")),
                            "p99 ms": _v(stat.get("latency_ms_p99")),
                            "req/s": _v(stat.get("throughput_rps")),
                            "tok/s": _v(stat.get("throughput_completion_tok_s")),
                        }
                    )
                    sweep_table.update()
                    _update_sweep_charts(sweep_state["all_stats"])
                    sweep_log.push(
                        f"[{datetime.now():%H:%M:%S}] concurrency={concurrency} "
                        f"req/s={_v(stat.get('throughput_rps'))} p95={_v(stat.get('latency_ms_p95'))}"
                    )
            set_status("已完成", "green")
            ui.notify("并发扫描完成", type="positive")
            if sweep_state["all_stats"]:
                sweep_export_btn.enable()
        except asyncio.CancelledError:
            set_status("已停止", "gray")
            ui.notify("扫描已停止", type="warning")
            return
        except Exception as exc:
            set_status("失败", "red")
            ui.notify(f"扫描失败：{exc}", type="negative")
            return
        finally:
            sweep_state["busy"] = False
            sweep_start_btn.enable()
            sweep_stop_btn.disable()

    def _do_sweep_stop() -> None:
        if "stop_event" in sweep_state:
            sweep_state["stop_event"].set()
        set_status("停止中...", "orange")

    def _export_sweep_json() -> None:
        if not sweep_state.get("all_stats"):
            return
        data = json.dumps(sweep_state["all_stats"], ensure_ascii=False, indent=2).encode("utf-8")
        _download_bytes(
            data, f"bench_sweep_{_timestamp_slug()}.json", "application/json; charset=utf-8"
        )

    sweep_start_btn.on_click(lambda: asyncio.create_task(_do_sweep()))
    sweep_stop_btn.on_click(_do_sweep_stop)
    sweep_export_btn.on_click(_export_sweep_json)


# ─── history tab ──────────────────────────────────────────────────────────────


def _build_history_tab(history: list[dict[str, Any]]) -> None:
    hist_cols = [
        {"name": "idx", "label": "#", "field": "#", "align": "center", "sortable": True},
        {"name": "time", "label": "时间", "field": "时间", "align": "left"},
        {"name": "mode", "label": "模式", "field": "模式", "align": "center"},
        {"name": "model", "label": "模型", "field": "模型", "align": "left"},
        {"name": "concurrency", "label": "并发", "field": "并发", "align": "center"},
        {"name": "success", "label": "成功率%", "field": "成功率%", "align": "center"},
        {"name": "rps", "label": "req/s", "field": "req/s", "align": "center"},
        {"name": "p50", "label": "p50 ms", "field": "p50 ms", "align": "center"},
        {"name": "p99", "label": "p99 ms", "field": "p99 ms", "align": "center"},
    ]

    def _on_select(e: Any) -> None:
        rows = getattr(e, "selection", [])
        if not rows:
            return
        idx = int(rows[0]["id"]) - 1
        if 0 <= idx < len(history):
            detail_json.set_content(json.dumps(history[idx], ensure_ascii=False, indent=2))

    hist_table = ui.table(
        columns=hist_cols,
        rows=[],
        row_key="id",
        selection="single",
        on_select=_on_select,
    ).classes("w-full")
    hist_table.props("dense flat")

    detail_json = ui.code("", language="json").classes("w-full mt-4 text-xs max-h-96 overflow-auto")

    def _refresh() -> None:
        hist_table.rows.clear()
        for idx, stat in enumerate(history, start=1):
            meta = stat.get("metadata") or {}
            hist_table.rows.append(
                {
                    "id": idx,
                    "#": idx,
                    "时间": (meta.get("bench_start_utc") or "")[:19].replace("T", " "),
                    "模式": str(meta.get("mode", "-")),
                    "模型": str(meta.get("model", "-")),
                    "并发": str(meta.get("concurrency", "-")),
                    "成功率%": _v(stat.get("success_rate_pct")),
                    "req/s": _v(stat.get("throughput_rps")),
                    "p50 ms": _v(stat.get("latency_ms_p50")),
                    "p99 ms": _v(stat.get("latency_ms_p99")),
                }
            )
        hist_table.update()

    def _clear() -> None:
        history.clear()
        _refresh()
        detail_json.set_content("")

    def _export_all() -> None:
        if not history:
            ui.notify("暂无历史记录", type="warning")
            return
        data = json.dumps(history, ensure_ascii=False, indent=2).encode("utf-8")
        _download_bytes(
            data, f"bench_history_{_timestamp_slug()}.json", "application/json; charset=utf-8"
        )

    with ui.row().classes("mt-3 gap-3"):
        ui.button("刷新", icon="refresh", on_click=_refresh).props("outline")
        ui.button("导出全部 JSON", icon="download", on_click=_export_all).props("outline")
        ui.button("清空历史", icon="delete", on_click=_clear).props("outline color=red")


# ─── entry ────────────────────────────────────────────────────────────────────


def launch() -> None:
    history: list[dict[str, Any]] = []

    @ui.page("/")
    def index() -> None:
        ui.query("html").style("height:100%; overflow:hidden")
        ui.query("body").style("margin:0; height:100%; overflow:hidden")
        ui.query(".q-page").style("display:flex; flex-direction:column; height:100%")
        ui.query(".nicegui-content").style(
            "display:flex; flex-direction:column; flex:1; overflow:hidden"
        )

        # ui.header 必须是页面顶层元素，不能嵌套在任何容器内
        with ui.header().classes(
            "items-center justify-between px-6 py-3 bg-indigo-700 text-white shadow"
        ):
            ui.label(f"LLM Bench Desktop  v{__version__}").classes(
                "text-xl font-bold tracking-wide"
            )
            status_badge = ui.badge("空闲", color="green").classes("text-sm px-3 py-1")

        def _set_status(text: str, color: str = "green") -> None:
            status_badge.set_text(text)
            status_badge.props(f"color={color}")

        _build_page(history, _set_status)

    ui.run(
        title=f"LLM Bench Desktop v{__version__}",
        native=True,
        window_size=(1500, 930),
        reload=False,
        show=True,
    )
