from __future__ import annotations

import asyncio
import copy
import json
import multiprocessing as mp
import os
import re
import socket
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from nicegui import events, ui
from nicegui.client import Client
from nicegui.native import find_open_port
from nicegui.server import Server
from wsproto.utilities import LocalProtocolError

from llm_bench import __version__
from llm_bench.config import config_dir, env_api_key
from llm_bench.gui_ng import (
    _DEFAULT_BASE_URL,
    _DEFAULT_CUSTOM_BODY,
    _DEFAULT_MODEL,
    _DEFAULT_PROMPT,
    _PROXY_LABEL_TO_VALUE,
    _PROXY_OPTIONS,
    _body,
    _csv_bytes,
    _download_bytes,
    _headers,
    _normalize_base_url,
    _parse_custom_body,
    _parse_prompts,
    _resolve_api_key,
    _resolve_endpoint,
    _resolve_proxy_inputs,
    _RunState,
    _safe_float,
    _safe_int,
    _stat_rows,
    _stats_log_preview,
    _timestamp_slug,
    _v,
)
from llm_bench.models import build_stats_dict
from llm_bench.runner import (
    limits_for_concurrency,
    one_chat_request,
    probe_connectivity,
    run_benchmark,
)
from llm_bench.tokens import estimate_tokens_local, estimate_tokens_prerun

_CONTROL_WINDOW_WIDTH = 540
_CONTROL_WINDOW_HEIGHT = 980
_MONITOR_WINDOW_WIDTH = 1180
_MONITOR_WINDOW_HEIGHT = 980
_WINDOW_GAP = 24
_PREFERENCES_FILE = "preferences.json"
_WEBVIEW2_ARGS_ENV = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
_WEBVIEW2_GPU_FIX_ENV = "LLM_BENCH_WEBVIEW2_DISABLE_GPU"
_WEBVIEW2_GPU_FIX_ARGS = ("--disable-gpu",)
_CONTROL_MULTI_COLUMN_BREAKPOINT = 1024
_CONTROL_GRID_CLASSES = "control-grid w-full gap-4 items-start grid-cols-1 lg:grid-cols-2"
_CONTROL_PANEL_CLASSES = (
    "control-panel w-full border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden"
)
_CONTROL_PANEL_WIDE_CLASSES = f"{_CONTROL_PANEL_CLASSES} lg:col-span-2"
_CONTROL_MODE_CLASSES = (
    "control-mode-card w-full border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden"
)
_CONTROL_SINGLE_COLUMN_DEFAULTS = {
    "base_connection": True,
    "request_input": True,
    "network": False,
    "advanced": False,
}

# ── i18n: minimal English / Chinese dictionaries + a lookup function.
# The lookup is a thin shim — when a key is missing in the active
# language, we fall back to zh-CN so existing users see no breakage.
# The set of translated strings is intentionally small (the most
# user-visible labels). Hardcoded Chinese elsewhere is left alone for
# now; this is the seed for an incremental migration.
_I18N_EN: dict[str, str] = {
    "start_run": "Start Run",
    "stop": "Stop",
    "save": "Save",
    "load": "Load",
    "save_as": "Save As",
    "delete": "Delete",
    "saved": "Saved",
    "unsaved_changes": "Unsaved changes",
    "fields_changed": "{n} fields changed",
    "press_to_start": "Click Start to begin benchmarking",
    "press_to_start_monitor": "Configure in Control window, then click Start",
    "ready": "Ready",
    "running": "Running...",
    "stopping": "Stopping...",
    "stopped": "Stopped",
    "failed": "Failed",
    "done": "Done",
    "partial_failure": "Partial failure",
    "test_connection": "Test Connection",
    "language": "Language",
    # UX#1 polish: high-visibility strings the user actually sees.
    "no_history": "No history yet",
    "select_at_least_two": "Select at least 2 history entries to compare",
    "view_pick": "Side-by-side",
    "view_group": "Group by",
    "view_rank": "Rank by",
    "replay": "Replay",
    "replay_tooltip": "Re-fire the original request body and show the new response.",
    "diff_badge_tooltip": "Click to see which fields differ from the saved version.",
    "port_status_tooltip": "🟢 reachable · 🔴 unreachable · 🟡 probing. Click 探测 to retry.",
    "loadcurve_malformed": "No valid phases detected. Each line must be <seconds>:<rps>.",
    "loadcurve_total": "Total {total}s · {n} phases · max {max_rps} req/s",
    "ab_view_tooltip": "Side-by-side: raw 2-6 picks. Group: aggregate by chosen key. Rank: top-20 by chosen metric.",
    "ab_selected_count": "{n} selected",
    "ab_no_group_candidates": "No groups have enough data to rank.",
    "replay_safety_dialog": "Endpoint is not a known read-only chat endpoint. Replay may trigger a side effect on the remote service.",
    # UX#5 polish: strings introduced since the first i18n pass
    "sweep_export_csv_btn": "Export sweep raw_results (CSV)",
    "sweep_no_raw_results": "This sweep has no raw_results to export",
    "sweep_all_levels_empty": "All levels have empty raw_results",
    "sweep_exported_n_followup": "Exported {n} raw results. To replay a single row: open 'History', find the matching (model, mode, concurrency) entry, run that level again, then use the 'Replay' button in the Run monitor.",
    "sweep_exported_n": "Exported {n} raw results",
    "sweep_raw_count_badge": " {n} raw results ",
    "sweep_truncated_n": "Truncated {n} raw_results (per-level cap)",
    # UX#8: high-frequency notify / button / dialog strings
    "notify_import_prompts_failed": "Import prompts failed: {err}",
    "notify_imported_n_prompts": "Imported {n} prompts",
    "notify_file_too_large": "File too large to import",
    "notify_enter_api_key": "Please enter an API key first",
    "notify_prerun_failed": "Pre-run token estimation failed: {err}",
    "notify_prerun_done": "Pre-run token estimation complete",
    "notify_migrated_to_custom": "Migrated standard config to custom body",
    "notify_config_name_empty": "Config name cannot be empty",
    "notify_no_configs": "No saved config files yet",
    "notify_config_saved": "Config saved: {name}",
    "notify_config_not_found": "Config file not found: {path}",
    "notify_config_read_failed": "Failed to read config: {err}",
    "notify_config_yaml_failed": "YAML parse failed: {err}",
    "notify_config_bad_root": "Config root must be a YAML mapping",
    "notify_config_loaded": "Config loaded: {name}",
    "notify_config_deleted": "Config deleted: {name}",
    "notify_api_key_missing": "API key is not set",
    "notify_dryrun_failed": "Dry-run failed: {err}",
    "notify_dryrun_exception": "Dry-run exception: {type}: {err}",
    "notify_dryrun_ok": "Dry-run OK in {ms} ms · tokens: p={p} c={c}",
    "notify_dryrun_failed_status": "Dry-run failed · status={status} · kind={kind}",
    "notify_template_applied": "Applied {label} template — remember to edit placeholders",
    "notify_template_applied_placeholder": "Applied {label} template — edit placeholders before starting",
    "notify_test_connection_ok": "POST OK · status={status} · elapsed={ms} ms",
    "notify_test_connection_failed": "POST failed · status={status} · kind={kind}",
    "notify_test_connection_failed_url": "Invalid URL: {err}",
    "notify_test_connection_exception": "Test request exception: {err}",
    "notify_invalid_url": "Invalid Base URL: {err}",
    "btn_test_connection": "Test Connection",
    "btn_save": "Save",
    "btn_save_as": "Save As",
    "btn_load": "Load",
    "btn_delete": "Delete",
    "btn_start_run": "Start Run",
    "btn_start_rps": "Start RPS Run",
    "btn_start_sweep": "Start Sweep",
    "btn_probe_suggest": "Probe Suggested Concurrency",
    "btn_dryrun": "Dry-run",
    "btn_export_json": "Export JSON",
    "btn_export_csv": "Export CSV",
    "btn_clear_history": "Clear History",
    "btn_replay_selected": "Replay Selected",
    "btn_running_curve": "Run Curve",
    "btn_refresh_port": "Probe",
    "btn_stop": "Stop",
    "btn_cancel": "Cancel",
    "btn_confirm": "Confirm",
    "btn_apply": "Apply",
    "btn_close": "Close",
    "btn_migrate": "Migrate",
    "btn_skip_migration": "Don't migrate",
    "btn_save_then_run": "Save then run",
    "btn_run_without_save": "Run without saving",
    "btn_cancel_run": "Cancel run",
    "btn_replay_anyway": "Replay anyway",
    "btn_probe_anyway": "Probe anyway",
    "btn_clear_anyway": "Clear anyway",
    "dialog_save_before_run_title": "Save current config?",
    "dialog_save_before_run_desc": "You have unsaved changes. Save before running?",
    "dialog_secret_warning_title": "API key looks like a placeholder",
    "dialog_secret_warning_desc": "Detected: '{key}...'. This is usually a copy-paste leftover. Continuing will result in 401.",
    "dialog_replay_safety_title": "Endpoint is not a known read-only chat endpoint",
    "dialog_replay_safety_desc": "Target: {endpoint}",
    "dialog_proxy_url": "Proxy URL",
}
_I18N_ZH: dict[str, str] = {
    "start_run": "开始单次压测",
    "stop": "停止",
    "save": "保存",
    "load": "加载",
    "save_as": "另存为",
    "delete": "删除",
    "saved": "已保存",
    "unsaved_changes": "未保存改动",
    "fields_changed": "{n} 个字段改动",
    "press_to_start": "请配置参数后点击开始",
    "press_to_start_monitor": "请到 Control 窗口配置并点击开始",
    "ready": "空闲",
    "running": "运行中...",
    "stopping": "停止中...",
    "stopped": "已停止",
    "failed": "失败",
    "done": "已完成",
    "partial_failure": "部分失败",
    "test_connection": "测试连接",
    "language": "语言",
    # UX#1 polish
    "no_history": "暂无历史记录",
    "select_at_least_two": "请至少勾选 2 条历史进行对比",
    "view_pick": "原始对比",
    "view_group": "按组聚合",
    "view_rank": "单指标排名",
    "replay": "重放选中",
    "replay_tooltip": "重新发送原始请求体，显示新响应。",
    "diff_badge_tooltip": "点击查看与已保存版本的具体差异字段。",
    "port_status_tooltip": "🟢 可达 · 🔴 不可达 · 🟡 探测中。点击 探测 重新检测。",
    "loadcurve_malformed": "未识别到合法阶段。每行格式：<秒数>:<rps>。",
    "loadcurve_total": "总时长 {total}s · {n} 阶段 · 最高 {max_rps} req/s",
    "ab_view_tooltip": "原始对比：选 2-6 条并列展示。按组聚合：按所选键分组排名。排名：按单指标前 20 名。",
    "ab_selected_count": "已选 {n} 条",
    "ab_no_group_candidates": "没有足够数据的分组可排名。",
    "replay_safety_dialog": "端点不是已知只读 chat endpoint，重放可能触发远程服务的副作用。",
    # UX#5 polish
    "sweep_export_csv_btn": "导出本 sweep 的 raw_results (CSV)",
    "sweep_no_raw_results": "本 sweep 没有可导出的 raw_results",
    "sweep_all_levels_empty": "所有档位均无 raw_results",
    "sweep_exported_n_followup": "已导出 {n} 条 raw 结果。想要重放单条：去 '历史记录' tab 找到同 (model, mode, concurrency) 行，然后点 '开始单次压测' 用同样参数跑一次，再到 '单次压测' monitor 的 '响应' tab 选行重放。",
    "sweep_exported_n": "已导出 {n} 条 raw 结果",
    "sweep_raw_count_badge": " {n} 条原始数据 ",
    "sweep_truncated_n": "截断 {n} 条 raw_results（每档上限）",
    # UX#8: 中文版本
    "notify_import_prompts_failed": "导入 Prompt 失败：{err}",
    "notify_imported_n_prompts": "已导入 {n} 条 Prompt",
    "notify_file_too_large": "文件过大，无法导入",
    "notify_enter_api_key": "请先填写 API Key",
    "notify_prerun_failed": "精确预跑估算失败：{err}",
    "notify_prerun_done": "精确预跑估算完成",
    "notify_migrated_to_custom": "已迁移普通模式配置到自定义请求体",
    "notify_config_name_empty": "配置文件名不能为空",
    "notify_no_configs": "当前还没有配置文件",
    "notify_config_saved": "配置已保存：{name}",
    "notify_config_not_found": "配置文件不存在：{path}",
    "notify_config_read_failed": "读取配置失败：{err}",
    "notify_config_yaml_failed": "YAML 解析失败：{err}",
    "notify_config_bad_root": "配置文件格式错误：根节点必须是对象",
    "notify_config_loaded": "已加载配置：{name}",
    "notify_config_deleted": "已删除配置：{name}",
    "notify_api_key_missing": "API Key 未设置",
    "notify_dryrun_failed": "试跑失败：{err}",
    "notify_dryrun_exception": "试跑异常：{type}: {err}",
    "notify_dryrun_ok": "✅ 试跑成功｜{ms} ms｜tokens: p={p} c={c}",
    "notify_dryrun_failed_status": "❌ 试跑失败｜status={status}｜kind={kind}",
    "notify_template_applied": "已应用 {label} 模板，记得修改占位符",
    "notify_template_applied_placeholder": "已应用 {label} 模板 — 请先把占位符替换成真实值再启动",
    "notify_test_connection_ok": "✅ POST 正常｜status={status}｜耗时={ms} ms",
    "notify_test_connection_failed": "❌ POST 失败｜status={status}｜kind={kind}",
    "notify_test_connection_failed_url": "❌ Base URL 不合法：{err}",
    "notify_test_connection_exception": "测试请求失败：{err}",
    "notify_invalid_url": "❌ Base URL 不合法：{err}",
    "btn_test_connection": "测试连接",
    "btn_save": "保存",
    "btn_save_as": "另存为",
    "btn_load": "加载",
    "btn_delete": "删除",
    "btn_start_run": "开始单次压测",
    "btn_start_rps": "开始固定 RPS",
    "btn_start_sweep": "开始并发扫描",
    "btn_probe_suggest": "探测建议并发",
    "btn_dryrun": "试一次",
    "btn_export_json": "导出 JSON",
    "btn_export_csv": "导出 CSV",
    "btn_clear_history": "清空历史",
    "btn_replay_selected": "🔁 重放选中",
    "btn_running_curve": "按曲线运行",
    "btn_refresh_port": "探测",
    "btn_stop": "停止",
    "btn_cancel": "取消",
    "btn_confirm": "确认",
    "btn_apply": "应用",
    "btn_close": "关闭",
    "btn_migrate": "迁移",
    "btn_skip_migration": "不迁移",
    "btn_save_then_run": "保存后运行",
    "btn_run_without_save": "不保存直接运行",
    "btn_cancel_run": "取消运行",
    "btn_replay_anyway": "仍然重放",
    "btn_probe_anyway": "仍然继续",
    "btn_clear_anyway": "清空",
    "dialog_save_before_run_title": "保存当前配置？",
    "dialog_save_before_run_desc": "你有未保存的改动。是否在运行前保存？",
    "dialog_secret_warning_title": "⚠️ API Key 看起来是占位符",
    "dialog_secret_warning_desc": "检测到：'{key}...'。这通常是复制粘贴时漏改的占位符。继续运行会得到 401。",
    "dialog_replay_safety_title": "⚠️ 端点不是已知只读 chat endpoint",
    "dialog_replay_safety_desc": "目标：{endpoint}",
    "dialog_proxy_url": "代理地址",
}
_CURRENT_LANG: list[str] = ["zh"]  # mutable cell so we can change at runtime


def t(key: str, **fmt: object) -> str:
    """Look up a string in the active language; fall back to zh-CN."""
    table = _I18N_ZH if _CURRENT_LANG[0] == "zh" else _I18N_EN
    text = table.get(key) or _I18N_ZH.get(key, key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text
_CONFIG_DIRNAME = ".llm_bench_configs"
_PROMPT_IMPORT_MAX_BYTES = 1_000_000
_RECOMMENDED_CONCURRENCY_SUCCESS_RATE_PCT = 95.0
_RESPONSE_PREVIEW_LIMIT = 96
_PROMPT_STRATEGY_OPTIONS = {
    "sequential": "顺序循环",
    "random": "随机挑选",
    "weighted": "加权随机",
}
# Tooltips: each entry is a 3-5 line explanation covering what the field does,
# what its default is, when to change it, and what to watch out for. Newlines
# render in NiceGUI's hover popup, so we use them freely.
_TOOLTIPS = {
    "base_url": (
        "API 服务地址，通常以 /v1 结尾。\n"
        "【默认】https://api.openai.com/v1\n"
        "【常见】\n"
        "  • OpenAI: https://api.openai.com/v1\n"
        "  • Azure: https://{resource}.openai.azure.com/openai/deployments/{deploy}\n"
        "  • 智谱 GLM: https://open.bigmodel.cn/api/paas/v4\n"
        "  • vLLM 本地: http://localhost:8000/v1\n"
        "  • Ollama: http://localhost:11434/v1\n"
        "【注意】Ollama 的 chat endpoint 路径是 /v1/chat/completions，"
        "但 base_url 是 /v1；不要带 /chat/completions 进来。"
    ),
    "api_key": (
        "Bearer Token 认证密钥。\n"
        "【优先级】界面输入 > 环境变量 LLM_API_KEY > OPENAI_API_KEY\n"
        "【安全】字段已遮蔽，旁边有眼睛按钮可临时显示。\n"
        "【坑】如果不确定是哪个来源，鼠标悬停此处会显示当前实际值。\n"
        "【本地服务】vLLM/Ollama 填任意非空字符串即可（不会真的校验）。"
    ),
    "model": (
        "模型标识符。\n"
        "【示例】gpt-4o-mini、gpt-4o、claude-3-5-sonnet-20241022、glm-4.5、qwen-plus\n"
        "【坑】大小写敏感、版本号后缀不能省。\n"
        "【坑】某些代理服务需要带 'openai/' 前缀，看你的网关文档。"
    ),
    "concurrency": (
        "同时在飞的最大请求数（Semaphore 上限）。\n"
        "【默认 5】开始是稳妥值。\n"
        "【经验】\n"
        "  • 调 1-10 看延迟基线\n"
        "  • 调 10-50 看吞吐上限\n"
        "  • 调 50+ 看服务抗压\n"
        "【瓶颈】如果服务器延迟是 2s，并发 5 最多 2.5 req/s。"
    ),
    "proxy_mode": (
        "代理模式。\n"
        "  • 直连：不使用任何代理（默认）\n"
        "  • 系统代理：读环境变量 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY\n"
        "  • 自定义代理：填下方'代理地址'\n"
        "【注意】Windows 系统的'代理设置'不会被自动读取——选'系统代理'才能用 env。"
    ),
    "proxy_url": (
        "仅在'自定义代理'模式下生效。\n"
        "【支持】http://、https://、socks5://、socks5h://\n"
        "【示例】http://127.0.0.1:7890（Clash 默认）\n"
        "【坑】socks5h 表示'远程解析域名'，socks5 是'本地解析'。"
        "压测时如果遇到 DNS 错误，改用 socks5h。"
    ),
    "conn_timeout": (
        "连通性测试请求的超时秒数。\n"
        "【默认 10】实际硬上限 60 秒（避免 UI 卡死）。\n"
        "【注意】这是单次测试请求的超时，跟压测的 timeout_s 无关。"
    ),
    "max_tokens": (
        "单次请求的最大输出 token 数。\n"
        "【默认 128】GPT-4o 范围 1-16384。\n"
        "【影响】值越大每次响应越慢、消耗越多 token；"
        "压测时建议固定值避免响应长度波动污染延迟数据。"
    ),
    "temperature": (
        "采样温度，0 = 贪心（稳定），1 = 标准，2 = 发散。\n"
        "【压测建议】设为 0 让响应更稳定可复现。\n"
        "【影响】高温度会让相同 prompt 的响应长度差异变大，"
        "导致延迟方差升高、p99 噪声大。"
    ),
    "stream": (
        "启用 SSE 流式返回。\n"
        "【必须开】才能测量 TTFT/ITL/TPOT 指标。\n"
        "【影响】开启后 TTFB 不再适用，改用 TTFT。\n"
        "【坑】某些 OpenAI 兼容服务对流式支持差，"
        "返回 chunk 不带 usage 字段，会导致 token 计数为 0。"
    ),
    "prompt_strategy": (
        "多 Prompt 的选取策略。\n"
        "  • 顺序循环 (sequential)：第 N 个请求用第 N%L 条 prompt\n"
        "  • 随机 (random)：每次均匀随机\n"
        "  • 加权随机 (weighted)：按右侧权重采样（权重列即使在非加权模式也可编辑）\n"
        "【建议】1 个 prompt 时选 sequential；模拟真实流量用 random 或 weighted。"
    ),
    "append_body_json": (
        "将 JSON 递归合并到基础请求体中。\n"
        "【示例】{\"thinking\": {\"type\": \"enabled\"}} → 在 body 中加上 thinking 字段\n"
        "【适用】想用标准 body 但加额外参数（思维链、tools 等）\n"
        "【替代】复杂定制用'全自定义请求体'模式。\n"
        "【注意】冲突时右侧（append）覆盖左侧（基础）。"
    ),
    "custom_stream": (
        "自定义请求体模式下是否按 SSE 流式解析。\n"
        "【与'stream'区分】这是当'请求模式=全自定义'时，"
        "控制流式协议的字段。\n"
        "【坑】自定义模式里流式响应里需要自己确认是 SSE 还是 NDJSON，"
        "本工具只支持 SSE。"
    ),
    "custom_endpoint": (
        "完整 URL 或相对路径。\n"
        "【示例】\n"
        "  • 相对: /chat/completions（拼到 base_url 后）\n"
        "  • 完整: https://api.deepseek.com/v1/chat/completions（绕过 base_url）\n"
        "【高级】支持 /responses、/completions 等其他 OpenAI 风格 endpoint。"
    ),
    "custom_body_json": (
        "全自定义请求体 JSON，会被直接发送。\n"
        "【行为】\n"
        "  • 切换到本模式后，多 Prompt 编辑器被禁用\n"
        "  • 引擎不会修改 body（不替换 user 消息、不加 stream 字段）\n"
        "【迁移】点 '迁移到自定义' 可把标准配置带过来。\n"
        "【坑】必须含 'messages' 数组（除非调 /completions）。"
    ),
    "timeout_s": (
        "单个请求的最长耗时（秒）。\n"
        "【默认 120】大模型响应慢的话加大。\n"
        "【影响】超时会分类为 timeout 错误，可能触发网络重试。\n"
        "【经验】流式 + 长 prompt 设 300 比较稳。"
    ),
    "warmup": (
        "正式计时前发送的预热请求数。\n"
        "【默认 0】建议 ≥ 10。\n"
        "【作用】触发 JIT、连接池预热、模型 KV cache 预热。\n"
        "【不计入统计】预热请求不会出现在 results 里。\n"
        "【坑】并发扫描时如果每档只有 25 个请求，"
        "预热 10 个会显著污染样本。"
    ),
    "retry_on_429": (
        "HTTP 429（限流）的自动重试次数。\n"
        "【默认 3】对按 token 配额的服务建议 ≥ 3。\n"
        "【影响】每次重试会用指数退避，1+2+4+8 = 15s 最长等待。\n"
        "【警告】重试会污染端到端延迟；如果只看 p99，"
        "建议关掉重试后再测一次对比。"
    ),
    "retry_on_network": (
        "连接/超时/代理错误的重试次数。\n"
        "【默认 1】生产环境建议 2-3。\n"
        "【触发场景】DNS 失败、TCP RST、TLS 握手失败、socket 超时。"
    ),
    "retry_on_5xx": (
        "服务端 5xx 错误的重试次数。\n"
        "【默认 1】5xx 多半是真的过载，重试可能加重问题，"
        "建议保持 1 或 0。\n"
        "【区分】5xx 重试不会覆盖 429 配额。"
    ),
    "base_backoff_s": (
        "重试退避基数（秒）。\n"
        "【默认 1.0】实际退避：base, 2*base, 4*base, ...\n"
        "【示例】base=1 时 4 次重试的等待是 1+2+4+8 = 15s。\n"
        "【建议】对 429 限流 base=2 给上游充分恢复时间。"
    ),
    "http2": (
        "启用 HTTP/2 多路复用。\n"
        "【默认关】OpenAI/Anthropic 都支持。\n"
        "【影响】开启后单连接可以并发多个流，减少 TCP/TLS 握手开销。\n"
        "【坑】要服务端也支持；vLLM 默认开，Ollama 默认关。"
    ),
    "run_total": (
        "单次压测发送的总请求数。\n"
        "【默认 20】统计意义需要 ≥ 100；想看 p99 起码 500。\n"
        "【经验】p50 稳定 ≥ 30；p99 稳定 ≥ 500；p99.9 稳定 ≥ 5000。\n"
        "【时间预估】总耗时 ≈ 并发数 / 服务器吞吐 (req/s)。"
    ),
    "run_duration": (
        "按时长压测（秒）。\n"
        "【默认 0】0 = 按总请求数；>0 = 按时间。\n"
        "【适用】想看 5 分钟持续负载下的稳定性、token 累计成本。\n"
        "【配合】'持续时长'与'总请求数'二选一。"
    ),
    "rps_target": (
        "固定 RPS 模式下的每秒请求目标。\n"
        "【RPS vs 并发】RPS 是速率（每秒几个请求），"
        "并发是同时在飞上限。RPS=5 不等于 5 并发，"
        "可能 5 并发跑 0.5 req/s（如果延迟 10s）。\n"
        "【行为】服务器处理慢时，调度器会跳过超额而不是堆积，"
        "rps_schedule_skipped 计数会涨。"
    ),
    "rps_duration": (
        "固定 RPS 模式持续时间（秒）。\n"
        "【默认 30】最少 1。\n"
        "【建议】生产稳态测试 ≥ 5 分钟；找峰值 ≥ 30 分钟。"
    ),
    "sweep_levels": (
        "并发扫描的并发档位列表，逗号分隔。\n"
        "【示例】1,2,4,8,16,32,64\n"
        "【建议】3-7 个档位；太多耗时长。\n"
        "【推荐】\n"
        "  • 快速摸底：1,5,10,20\n"
        "  • 找拐点：1,2,4,8,16,32,64\n"
        "  • 验证稳定性：1,10,100"
    ),
    "sweep_per": (
        "每个并发档位发送的请求数。\n"
        "【默认 40】太少噪声大。\n"
        "【建议】\n"
        "  • 看 p50：≥ 50\n"
        "  • 看 p99：≥ 200\n"
        "  • 看 p99.9：≥ 2000\n"
        "【注意】每档独立计时，不共享预热。"
    ),
    # UX#6: new-feature tooltips (deep replay, A/B board, port probe, etc.)
    "replay_btn": (
        "重放单条原始请求并对比新旧响应。\n"
        "【前提】该结果带有 raw_request_body（深度重放）。\n"
        "【行为】用当前 Control 配置（URL + Key + Headers）发同样的 body，"
        "在响应框显示原始与新响应的 diff。\n"
        "【注意】非 chat endpoint 会弹确认（防误触发）。"
    ),
    "port_status": (
        "TCP 端口实时可达性徽标。\n"
        "【🟢 可达】TCP connect 成功（2 秒超时内）\n"
        "【🔴 不可达】超时或拒绝（含 SSRF 防护拒绝私有地址）\n"
        "【🟡 探测中】异步 ping 进行中\n"
        "【自动】修改 Base URL 后 600ms 防抖自动探测。"
    ),
    "ab_view_mode": (
        "A/B 看板视图选择。\n"
        "【原始对比】选 2-6 条历史，best/worst 行列展示。\n"
        "【按组聚合】按所选键（model / concurrency / mode）分组，"
        "每组取 p99 最低者作为赢家。\n"
        "【单指标排名】按所选指标（p50/p95/p99/req/s/成功率）排序，前 20 名。"
    ),
    "ab_group_key": (
        "按组聚合视图的分组维度。\n"
        "model：按模型名分组（适合跨模型对比）。\n"
        "concurrency：按并发数分组（适合同模型不同并发）。\n"
        "mode：按压测模式（run/rps/sweep/loadcurve）分组。"
    ),
    "ab_rank_metric": (
        "排名视图的排序指标。\n"
        "latency_*：越小越好（按升序）。\n"
        "throughput / success：越大越好（按降序）。\n"
        "【注意】切换指标会重排行，方向由字段名决定（硬编码判断）。"
    ),
    "config_diff_badge": (
        "配置 diff 徽标 — 显示未保存改动数。\n"
        "【黄色】1-2 个字段\n"
        "【橙色】3+ 个字段\n"
        "【点击】弹窗显示每个字段的 old / new 值。\n"
        "【首次保存前】显示 '未保存'。"
    ),
    "loadcurve_chart": (
        "负载曲线 ECharts 阶梯图预览。\n"
        "【X 轴】累计时间（秒）。\n"
        "【Y 轴】目标 RPS。\n"
        "【阶梯】每个 phase 是一段水平线 + 一次阶跃。\n"
        "【实时】textarea 改完 150ms 后刷新。"
    ),
    "sweep_raw_export_btn": (
        "导出本 sweep 的 raw_results 到 CSV。\n"
        "【包含】每个档位下每条请求的 status / latency / tokens / 等。\n"
        "【用法】在 Run monitor 的响应 tab 选行 → 重放选中。"
    ),
}


@dataclass
class _SweepState:
    busy: bool = False
    rows: list[dict[str, str]] = field(default_factory=list)
    all_stats: list[dict[str, Any]] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    consumed_prompt_tokens: int = 0
    consumed_completion_tokens: int = 0
    chart_refresh_mode: str = "interval"
    chart_refresh_interval_s: float = 0.3
    chart_refresh_every_n: int = 5
    # UX#5: per-level raw_results so the sweep monitor can replay any
    # individual request. Inner list index = level number (0..N-1).
    raw_results_per_level: list[list[Any]] = field(default_factory=list)
    raw_results_levels: list[int] = field(default_factory=list)
    raw_results_stats_indices: list[int] = field(default_factory=list)

    def reset(self) -> None:
        # Test#2: don't touch stop_event here — start-button calls
        # fresh_stop_event() explicitly.
        self.busy = True
        self.rows = []
        self.all_stats = []
        self.log_lines = []
        self.raw_results_per_level = []
        self.raw_results_levels = []
        self.raw_results_stats_indices = []

    def fresh_stop_event(self) -> None:
        """Allocate a brand-new stop_event. Called only at the
        start-button entry point (see Test#2 race fix)."""
        self.stop_event = asyncio.Event()


# Cap on history size to keep memory bounded during long sessions. Once exceeded
# we drop the oldest entries (FIFO). 500 ≈ 100 sweeps × 5 levels — comfortable
# for a normal day; rare to need more.
_HISTORY_CAP = 500

# Perf#1: per-level raw_results cap. A typical request result is ~1 KB
# (status, latency, tokens, raw body). 500 × 1 KB × 5 levels = 2.5 MB per
# sweep — reasonable. Raise this if you regularly need deeper replay; the
# truncations are noted in the log so you can spot it.
_MAX_RAW_PER_LEVEL = 500

# Perf#3: port probe global cache (60s TTL) — avoid re-opening TCP
# sockets when the same host:port is probed multiple times during a
# session. Key: (host, port). Value: (ok, detail, expires_mono).
_PORT_PROBE_TTL_S = 60.0
_PORT_PROBE_CACHE: dict[tuple[str, int], tuple[bool, object, float]] = {}


@dataclass
class _AppState:
    history: list[dict[str, Any]] = field(default_factory=list)
    run_states: dict[str, _RunState] = field(
        default_factory=lambda: {"run": _RunState(), "rps": _RunState()}
    )
    sweep_state: _SweepState = field(default_factory=_SweepState)
    status_text: str = "空闲"
    status_color: str = "green"
    consumed_prompt_tokens: int = 0
    consumed_completion_tokens: int = 0

    def set_status(self, text: str, color: str = "green") -> None:
        self.status_text = text
        self.status_color = color

    def is_busy(self) -> bool:
        return any(state.busy for state in self.run_states.values()) or self.sweep_state.busy

    @property
    def consumed_total_tokens(self) -> int:
        return self.consumed_prompt_tokens + self.consumed_completion_tokens

    def add_history(self, stats: dict[str, Any]) -> None:
        """Append to history, truncating oldest if over cap.

        Perf#2: also invalidate the A/B group/rank cache so the next
        view-mode switch recomputes against the new history. We don't
        keep the old id-based keys — they'll never be hit again since
        the history list object is reused.
        """
        self.history.append(stats)
        if len(self.history) > _HISTORY_CAP:
            del self.history[: len(self.history) - _HISTORY_CAP]
        _AB_CACHE.clear()

    def add_consumed_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.consumed_prompt_tokens += max(0, int(prompt_tokens))
        self.consumed_completion_tokens += max(0, int(completion_tokens))

    def reset_consumed_tokens(self) -> None:
        self.consumed_prompt_tokens = 0
        self.consumed_completion_tokens = 0
        for state in self.run_states.values():
            # L12: these per-state accumulators are kept for backwards compat
            # but are not surfaced anywhere in the UI — they're dead fields.
            state.consumed_prompt_tokens = 0
            state.consumed_completion_tokens = 0
        self.sweep_state.consumed_prompt_tokens = 0
        self.sweep_state.consumed_completion_tokens = 0


@dataclass
class _ConfigState:
    current_name: str | None = None
    last_saved_snapshot: str | None = None


def _apply_control_page_css() -> None:
    ui.add_css(
        """
        .control-panel {
            transition: box-shadow .18s ease, transform .18s ease;
        }
        .control-panel:hover {
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
        }
        .control-panel .q-expansion-item__container {
            border-radius: 0.75rem;
            overflow: hidden;
            background: #ffffff;
        }
        .control-panel .q-item {
            min-height: 58px;
            padding: 10px 16px;
            background: linear-gradient(180deg, #f8fbff 0%, #f8fafc 100%);
        }
        .control-panel .q-expansion-item__content > .q-card {
            border-top: 1px solid #e2e8f0;
            box-shadow: none;
        }
        .control-panel .q-card__section {
            padding: 16px;
        }
        .control-mode-card .q-tabs {
            background: #f8fafc;
            border-bottom: 1px solid #e2e8f0;
        }
        .control-mode-card .q-tab-panels,
        .control-mode-card .q-tab-panel {
            background: #ffffff;
        }
        """
    )


def _apply_control_panel_state(panels: dict[str, Any], *, expand_all: bool) -> None:
    if expand_all:
        for panel in panels.values():
            if not bool(panel.value):
                panel.set_value(True)
        return
    for key, default_value in _CONTROL_SINGLE_COLUMN_DEFAULTS.items():
        panels[key].set_value(default_value)


async def _sync_control_layout(panels: dict[str, Any], state: dict[str, Any]) -> None:
    try:
        width = int(await ui.context.client.run_javascript("window.innerWidth") or 0)
    except Exception:
        # Best-effort JS bridge call: any failure (disconnected client,
        # cancelled task, no script context yet) just means we keep the
        # current layout. Deliberately broad — narrowing to specific
        # exception types here would re-raise on novel edge cases and
        # break the responsive-grid behavior in ways the caller can't
        # handle.
        return

    is_single_column = width < _CONTROL_MULTI_COLUMN_BREAKPOINT
    if is_single_column:
        if state.get("mode") != "single":
            _apply_control_panel_state(panels, expand_all=False)
            state["mode"] = "single"
        return

    if state.get("mode") != "wide":
        state["mode"] = "wide"
        _apply_control_panel_state(panels, expand_all=True)


def _notify_client(
    client_id: str, message: str, level: str, position: str | None = None
) -> None:
    client = Client.instances.get(client_id)
    if client is None:
        return
    with suppress(RuntimeError), client:
        kwargs = {"type": level}
        if position is not None:
            kwargs["position"] = position
        ui.notify(message, **kwargs)


def _attach_tooltip(widget: Any, text: str) -> None:
    if not text:
        return
    with widget:
        ui.tooltip(text)


def _deep_merge_dict(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in extra.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _config_dir() -> Path:
    # Delegate to llm_bench.config.config_dir so the location is overridable
    # via LLM_BENCH_CONFIG_DIR env and stable across cwd changes.
    return config_dir()


def _read_dark_preference() -> bool:
    path = _config_dir() / _PREFERENCES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("dark_mode"))


def _apply_dark_mode(enabled: bool) -> None:
    path = _config_dir() / _PREFERENCES_FILE
    path.write_text(
        json.dumps({"dark_mode": bool(enabled)}, ensure_ascii=False),
        encoding="utf-8",
    )


def _merge_webview2_browser_args(existing: str, required: tuple[str, ...]) -> str:
    args = [arg for arg in existing.split() if arg]
    seen = set(args)
    for arg in required:
        if arg not in seen:
            args.append(arg)
            seen.add(arg)
    return " ".join(args)


def _configure_webview2_browser_args() -> None:
    # WebView2 can render a completely black surface on some GPU/driver stacks.
    # This desktop UI is not graphics-heavy, so software rendering is safer here.
    disable_gpu = os.environ.get(_WEBVIEW2_GPU_FIX_ENV, "1").strip().lower()
    if disable_gpu in {"0", "false", "no", "off"}:
        return
    os.environ[_WEBVIEW2_ARGS_ENV] = _merge_webview2_browser_args(
        os.environ.get(_WEBVIEW2_ARGS_ENV, ""),
        _WEBVIEW2_GPU_FIX_ARGS,
    )


def _normalize_config_name(name: str) -> str | None:
    raw = (name or "").strip().replace("\\", "_").replace("/", "_")
    if not raw:
        return None
    if not raw.lower().endswith((".yml", ".yaml")):
        raw += ".yaml"
    return raw


def _config_path(name: str) -> Path:
    return _config_dir() / name


def _list_config_names() -> list[str]:
    return sorted(path.name for path in _config_dir().glob("*.y*ml"))


def _snapshot_key(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


def _format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(round(seconds)))
    mins, sec = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours:d}:{mins:02d}:{sec:02d}"
    return f"{mins:02d}:{sec:02d}"


def _parse_prompt_upload_text(filename: str, text: str) -> list[str]:
    if filename.lower().endswith(".json"):
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("prompts")
        if not isinstance(payload, list):
            raise ValueError('JSON 必须是字符串数组，或形如 {"prompts": [...]}。')
        prompts = [str(item).strip() for item in payload if str(item).strip()]
    else:
        prompts = [line.strip() for line in text.splitlines() if line.strip()]
    if not prompts:
        raise ValueError("导入后没有可用 Prompt。")
    return prompts


def _resolve_prompt_list(settings: dict[str, Any]) -> list[str]:
    prompts = list(settings.get("prompts_list") or [])
    if prompts:
        return [prompt for prompt in prompts if prompt]
    # _parse_prompts returns None when raw is empty (no non-blank lines).
    # The connectivity probe path can call this before the user has filled
    # in any prompts — coerce to [] so callers can rely on list[str].
    return _parse_prompts(settings.get("prompts_raw") or "") or []


def _resolve_prompt_weights(settings: dict[str, Any], prompts: list[str]) -> list[float]:
    # Defensive: callers sometimes pass None (e.g. custom-body mode where
    # prompts live in the body template). Treat as no prompts.
    if not prompts:
        return []
    raw = settings.get("prompt_weights") or []
    out: list[float] = []
    for idx in range(len(prompts)):
        try:
            value = float(raw[idx]) if idx < len(raw) else 1.0
        except (TypeError, ValueError):
            value = 1.0
        out.append(value if value > 0 else 1.0)
    return out


def _apply_preview_prompt(body_template: dict[str, Any], prompt: str) -> dict[str, Any]:
    body = copy.deepcopy(body_template)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        body["messages"] = [{"role": "user", "content": prompt}]
        return body
    messages = copy.deepcopy(messages)
    for index, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            messages[index] = {**message, "content": prompt}
            body["messages"] = messages
            return body
    messages.append({"role": "user", "content": prompt})
    body["messages"] = messages
    return body


def _build_standard_request_body(settings: dict[str, Any]) -> dict[str, Any]:
    body_template = _body(
        (settings["model"] or _DEFAULT_MODEL).strip(),
        _safe_int(settings["max_tokens"], 128, 1),
        _safe_float(settings["temperature"], 0.2, 0.0),
        bool(settings["stream"]),
    )
    append_body_raw = (settings.get("append_body_json") or "").strip()
    if append_body_raw:
        append_body, append_err = _parse_custom_body(append_body_raw)
        if append_err:
            raise ValueError(f"附加请求体不合法：{append_err}")
        body_template = _deep_merge_dict(body_template, append_body or {})
    return body_template


def _preview_text(text: str | None, limit: int = _RESPONSE_PREVIEW_LIMIT) -> str:
    if not text:
        return "-"
    single_line = " ".join(text.split())
    if len(single_line) <= limit:
        return single_line
    return single_line[: max(0, limit - 3)].rstrip() + "..."


def _dominant_entry(histogram: dict[Any, Any] | None) -> str | None:
    if not histogram:
        return None
    key, _ = max(histogram.items(), key=lambda item: int(item[1] or 0))
    return str(key)


def _run_completion_feedback(stats: dict[str, Any]) -> tuple[str, str, str, str, str]:
    total = _safe_int(stats.get("requests_total"), 0, 0)
    success = _safe_int(stats.get("requests_success"), 0, 0)
    failed = _safe_int(stats.get("requests_failed"), 0, 0)
    status_code = _dominant_entry(stats.get("status_histogram"))
    error_kind = _dominant_entry(stats.get("error_kind_counts"))
    detail_parts = []
    if status_code:
        detail_parts.append(f"HTTP {status_code}")
    if error_kind:
        detail_parts.append(error_kind)
    detail = " / ".join(detail_parts) if detail_parts else "请检查结果面板"
    if total == 0 or failed == 0:
        return "✅ 完成", "已完成", "green", "压测完成", "positive"
    if success == 0:
        return "❌ 全部失败", "失败", "red", f"压测失败：{detail}", "negative"
    return (
        "⚠️ 部分失败",
        "部分失败",
        "orange",
        f"压测完成，但有 {failed}/{total} 个请求失败（{detail}）",
        "warning",
    )


def _augmented_stat_rows(stats: dict[str, Any]) -> list[dict[str, str]]:
    """Wrap :func:`_stat_rows` to surface retry-related metrics that users
    care about but that the standard 18-row table hides.

    Concretely, we add two rows (only when retry data is present):
      - 最终尝试延迟 p99（不含 429/网络重试的 backoff） — 解决 U51
      - 重试总耗时 p99（端到端 - 最终） — 直观看出"重试污染"了 p99
    """
    rows = _stat_rows(stats)
    final = stats.get("final_attempt_latency_ms_p99")
    retry_gap_p99 = None
    if (
        stats.get("latency_ms_p99") is not None
        and final is not None
    ):
        retry_gap_p99 = float(stats["latency_ms_p99"]) - float(final)
    if final is not None:
        rows.append(
            {
                "指标": "最终尝试延迟 p99 ms（不含重试）",
                "值": f"{float(final):.1f}",
            }
        )
    if retry_gap_p99 is not None and retry_gap_p99 > 1.0:
        rows.append(
            {
                "指标": "重试拖尾 ms (p99 端到端 − 最终)",
                "值": f"{retry_gap_p99:.1f}",
            }
        )
    return rows


def _recommended_concurrency(stats_list: list[dict[str, Any]]) -> int | None:
    candidates: list[int] = []
    for stat in stats_list:
        concurrency = _safe_int(stat.get("concurrency_level"), 0, 0)
        final_success = _safe_float(stat.get("success_rate_pct"), 0.0, 0.0)
        attempt_success = _safe_float(stat.get("http_attempt_success_rate_pct"), 0.0, 0.0)
        if (
            concurrency > 0
            and final_success >= _RECOMMENDED_CONCURRENCY_SUCCESS_RATE_PCT
            and attempt_success >= _RECOMMENDED_CONCURRENCY_SUCCESS_RATE_PCT
        ):
            candidates.append(concurrency)
    return max(candidates) if candidates else None


def _sweep_completion_feedback(
    stats_list: list[dict[str, Any]],
) -> tuple[str, str, str, str, str]:
    if not stats_list:
        return "❌ 无结果", "失败", "red", "并发扫描未产生有效结果", "negative"
    best_success = max(
        (_safe_float(stat.get("success_rate_pct"), 0.0, 0.0) for stat in stats_list), default=0.0
    )
    recommendation = _recommended_concurrency(stats_list)
    if recommendation is not None:
        return (
            "✅ 扫描完成",
            "已完成",
            "green",
            f"建议最大并发：{recommendation}（按 >={int(_RECOMMENDED_CONCURRENCY_SUCCESS_RATE_PCT)}% 最终/HTTP 尝试成功率）",
            "positive",
        )
    if best_success <= 0:
        return "❌ 全部失败", "失败", "red", "并发扫描完成，但所有档位都失败了", "negative"
    return (
        "⚠️ 扫描完成",
        "部分失败",
        "orange",
        f"扫描完成，但未找到满足 >={int(_RECOMMENDED_CONCURRENCY_SUCCESS_RATE_PCT)}% 稳定成功率的建议并发",
        "warning",
    )


def _wait_for_port(host: str, port: int, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _open_dual_windows(protocol: str, host: str, port: int, shutdown_event: mp.Event) -> None:
    _configure_webview2_browser_args()

    import webview

    if not _wait_for_port(host, port):
        shutdown_event.set()
        return

    webview.settings["ALLOW_DOWNLOADS"] = True
    closing = threading.Event()

    control_window = webview.create_window(
        title=f"LLM Bench Control v{__version__}",
        url=f"{protocol}://{host}:{port}/control",
        width=_CONTROL_WINDOW_WIDTH,
        height=_CONTROL_WINDOW_HEIGHT,
        x=40,
        y=40,
        min_size=(460, 760),
    )
    monitor_window = webview.create_window(
        title=f"LLM Bench Monitor v{__version__}",
        url=f"{protocol}://{host}:{port}/monitor",
        width=_MONITOR_WINDOW_WIDTH,
        height=_MONITOR_WINDOW_HEIGHT,
        x=40 + _CONTROL_WINDOW_WIDTH + _WINDOW_GAP,
        y=40,
        min_size=(900, 760),
    )
    assert control_window is not None
    assert monitor_window is not None

    # L21: only tear down when BOTH windows are closed. Closing one (e.g. just
    # the monitor) should NOT kill a running benchmark.
    closed_count = {"n": 0}
    closed_lock = threading.Lock()

    def on_window_closed() -> None:
        with closed_lock:
            closed_count["n"] += 1
            if closed_count["n"] < 2:
                return
        if closing.is_set():
            return
        closing.set()
        shutdown_event.set()
        for window in (control_window, monitor_window):
            with suppress(Exception):
                window.destroy()

    control_window.events.closed += on_window_closed
    monitor_window.events.closed += on_window_closed
    webview.start()


def _start_dual_windows(protocol: str, host: str, port: int) -> mp.Event:
    shutdown_event = mp.Event()

    def watch_shutdown() -> None:
        shutdown_event.wait()
        while not hasattr(Server, "instance"):
            time.sleep(0.1)
        Server.instance.should_exit = True

    threading.Thread(target=watch_shutdown, daemon=True).start()
    process = mp.Process(
        target=_open_dual_windows,
        args=(protocol, host, port, shutdown_event),
        daemon=True,
    )
    process.start()
    return shutdown_event


def _apply_page_shell(scroll_content: bool) -> None:
    # Dark mode is intentionally not supported: force light theme on every
    # page so a stale preferences.json (or any future toggle) can't flip the
    # app palette. The whole UI is now gray-first.
    ui.dark_mode(False)
    ui.query("html").style("height:100%")
    ui.query("body").style("margin:0; height:100%")
    ui.query(".q-page").style("display:flex; flex-direction:column; height:100%")
    overflow = "overflow:auto" if scroll_content else "overflow:hidden"
    ui.query(".nicegui-content").style(f"display:flex; flex-direction:column; flex:1; {overflow}")


def _build_header(title: str, app_state: _AppState) -> None:
    with ui.header().classes(
        "items-center justify-between px-6 py-3 bg-slate-700 text-white shadow"
    ):
        ui.label(title).classes("text-xl font-bold tracking-wide")
        with ui.row().classes("items-center gap-3"):
            # i18n: language picker (zh-CN / en). State lives in the
            # mutable _CURRENT_LANG cell; switch doesn't trigger a full
            # re-render — users re-open windows or restart to see all
            # strings translated. The set of translated strings is
            # intentionally small (see _I18N_*).
            ui.select(
                options={"zh": "中文", "en": "English"},
                value=_CURRENT_LANG[0],
                on_change=lambda e: _CURRENT_LANG.__setitem__(0, e.value or "zh"),
            ).props("dense color=white").classes("text-xs w-24")
            status_badge = ui.badge(
                app_state.status_text, color=app_state.status_color
            ).classes("text-sm px-3 py-1")

    def _refresh_status() -> None:
        status_badge.set_text(app_state.status_text)
        status_badge.props(f"color={app_state.status_color}")

    ui.timer(0.25, _refresh_status)


def _build_runtime_payload(settings: dict[str, Any]) -> dict[str, Any]:
    norm_url, err = _normalize_base_url(settings["base_url"])
    if err:
        raise ValueError(err)
    _, _, proxy_err = _resolve_proxy_inputs(settings["proxy_mode"], settings.get("proxy_url") or "")
    if proxy_err:
        raise ValueError(proxy_err)
    prompts = _resolve_prompt_list(settings)
    prompt_weights = _resolve_prompt_weights(settings, prompts)
    if settings["custom_enabled"]:
        body_template, body_err = _parse_custom_body(settings["custom_body_json"])
        if body_err:
            raise ValueError(body_err)
        stream_flag = bool(settings["custom_stream"])
        endpoint = _resolve_endpoint(norm_url or _DEFAULT_BASE_URL, settings["custom_endpoint"])
        # H2: in custom mode the body is the user's authoritative payload — runner
        # MUST NOT mutate it. Force-empty prompts so _body_for_index is a no-op.
        prompts = []
    else:
        body_template = _build_standard_request_body(settings)
        stream_flag = bool(settings["stream"])
        endpoint = _resolve_endpoint(norm_url or _DEFAULT_BASE_URL)
        # Standard mode needs at least one prompt to send. If the user
        # hasn't filled any in (e.g. they only came here to test
        # connectivity), fall back to a tiny default probe so the request
        # is well-formed.
        if not prompts:
            prompts = [_DEFAULT_PROMPT]
            prompt_weights = [1.0]
    return {
        "endpoint": endpoint,
        "stream_flag": stream_flag,
        "body_template": body_template,
        "prompts": prompts,
        "prompt_strategy": settings.get("prompt_strategy") or "sequential",
        "prompt_weights": prompt_weights,
        "proxy_mode": settings["proxy_mode"],
        "proxy_url": settings.get("proxy_url"),
    }


def _is_private_or_loopback(host: str) -> bool:
    """True if the resolved host is in a private/link-local/loopback range.

    Sec#2: prevents SSRF via the Base URL TCP probe AND the replay
    path. Resolves the hostname so DNS-based attacks against internal
    zones like 169.254.169.254 IMDS are still caught.

    Rejected ranges (IPv4):
      - 0.0.0.0/8 (unspecified / "this network")
      - 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (RFC1918 private)
      - 100.64.0.0/10 (CGN / carrier-grade NAT — RFC6598)
      - 127.0.0.0/8 (loopback)
      - 169.254.0.0/16 (link-local incl. cloud IMDS 169.254.169.254)
      - 224.0.0.0/4 (multicast)
      - 240.0.0.0/4 (reserved / broadcast)

    Rejected ranges (IPv6):
      - :: (unspecified)
      - ::1 (loopback)
      - fe80::/10 (link-local)
      - fc00::/7 (ULA — unique local)
      - ff00::/8 (multicast)
    """
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
        # CGN 100.64.0.0/10 — not flagged by ipaddress.is_private in
        # older Pythons, so we check explicitly.
        if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
    return False


def _parse_base_for_probe(url: str) -> tuple[str, int, str]:
    """Extract (host, port, scheme) for a TCP reachability probe.

    Returns the host and inferred port: 443 for https, 80 for http, and
    whatever the explicit port is when the user provided one. Raises
    ValueError if the URL is malformed.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url if "://" in url else f"http://{url}")
    if not parsed.hostname:
        raise ValueError("缺少主机名")
    if parsed.port is not None:
        return parsed.hostname, int(parsed.port), parsed.scheme or "http"
    if parsed.scheme == "https":
        return parsed.hostname, 443, "https"
    return parsed.hostname, 80, parsed.scheme or "http"


async def _tcp_probe(
    host: str, port: int, *, timeout: float = 2.0, allow_private: bool = False
) -> tuple[bool, float | str]:
    """Async TCP connect probe. Returns (ok, latency_ms_or_error_string).

    Sec#2: refuses to probe RFC1918 / link-local / loopback / multicast
    / CGN / IPv6 ULA addresses unless the caller has opted in via
    ``allow_private=True``.

    Perf#3: caches the result for ``_PORT_PROBE_TTL_S`` seconds keyed
    by (host, port). Bypassing the cache requires ``bypass_cache=True``.
    """
    if not allow_private and _is_private_or_loopback(host):
        return False, "refused: private/loopback address (SSRF protection)"
    # Cache check (per-process; not persisted).
    cached = _PORT_PROBE_CACHE.get((host, port))
    if cached is not None:
        ok, detail, expires_mono = cached
        if time.perf_counter() < expires_mono:
            return ok, detail
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    try:
        fut = loop.create_connection(asyncio.Protocol, host=host, port=port)
        await asyncio.wait_for(fut, timeout=timeout)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        _PORT_PROBE_CACHE[(host, port)] = (
            True,
            float(elapsed_ms),
            time.perf_counter() + _PORT_PROBE_TTL_S,
        )
        return True, elapsed_ms
    except (TimeoutError, OSError) as exc:
        detail = str(exc) or "timeout"
        _PORT_PROBE_CACHE[(host, port)] = (
            False,
            detail,
            time.perf_counter() + _PORT_PROBE_TTL_S,
        )
        return False, detail


def _safe_create_bench_task(
    coro: Any,
    *,
    on_error: Callable[[BaseException], None],
) -> asyncio.Task[Any]:
    """启动一个压测后台 task 并安装异常观察器。

    H1 修复：替换裸 ``asyncio.create_task(coro)``，避免 task 异常后
    busy 永远卡 True / 没有 notify。
    """
    task = asyncio.create_task(coro)
    task.add_done_callback(lambda t: t.exception() and on_error(t.exception() or BaseException()))
    return task


# Heuristics for "weak / placeholder / dev" API keys — caught before
# the user starts a benchmark so they don't burn a run on a 401.
_WEAK_KEY_PATTERNS = [
    "your-key",
    "your_key",
    "yourkey",
    "placeholder",
    "example",
    "sk-xxxxxx",
    "sk-0000",
    "test-key",
    "fake-key",
    "abc123",
    "changeme",
    "todo-replace",
]

# Real-key formats — these are HIGH entropy and look legitimate, so the
# weak-key heuristic must NOT flag them. Listing them explicitly lets the
# secret-scan dialog show "looks like a real OpenAI key" (informational,
# not blocking) and helps prevent accidental-paste-and-save.
_LIVE_KEY_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^sk-[A-Za-z0-9_\-]{20,}"),  # OpenAI / DeepSeek / Moonshot
    re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}"),  # Anthropic
    re.compile(r"^xai-[A-Za-z0-9]{20,}"),
    re.compile(r"^AIza[0-9A-Za-z_\-]{30,}"),  # Google
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub
    re.compile(r"^xox[baprs]-[A-Za-z0-9_-]{10,}"),  # Slack
    re.compile(r"^sk_live_[A-Za-z0-9]{20,}"),  # Stripe
    re.compile(r"^AKIA[0-9A-Z]{16}"),  # AWS
)


def _looks_like_weak_key(key: str) -> bool:
    """Heuristic: detect placeholder / dev / weak API keys before pressing Start.

    Real production keys (matched by _LIVE_KEY_REGEXES) are *not* flagged
    here — they're high-entropy and would falsely trip the placeholder
    detector. The weak-key check focuses on obvious dev/placeholder text
    so we don't bother real users with amber dialogs.
    """
    if not key:
        return True
    stripped = key.strip().lower()
    if len(stripped) < 10:
        return True
    if any(p in stripped for p in _WEAK_KEY_PATTERNS):
        return True
    return stripped.startswith("sk-") and len(set(stripped[3:])) < 4


def _looks_like_real_key(key: str) -> bool:
    """True if the key matches a known production credential format.

    Used to detect accidental-paste-of-a-real-key: a real key in
    `last.yaml` means the user pasted a live secret that will be silently
    re-loaded on next launch. We want to surface this in the secret scan.
    """
    return any(rx.match(key.strip()) for rx in _LIVE_KEY_REGEXES)


def sanitize_snapshot_for_disk(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Strip secrets from a config snapshot before persisting to disk.

    The api_key is *always* replaced with a non-secret marker
    ``__from_ui__`` before writing. On load, the marker means
    'key will come from env / keyring / re-paste'. This guarantees
    secrets never land on disk even if the env var gets unset later.

    This is the single chokepoint for "secret-leak-to-disk" prevention;
    the load path also reads it back as a non-secret marker.
    """
    out = dict(snapshot)
    raw_key = out.get("api_key")
    if raw_key:
        out["api_key"] = "__from_ui__"
    return out


def _parse_loadcurve_profile(raw: str) -> list[tuple[float, float]]:
    """Parse the load-curve textarea into a list of (duration_s, target_rps).

    Each non-comment, non-empty line must be "<duration>:<rps>". Malformed
    lines are silently dropped (so the user can paste commented examples).
    """
    out: list[tuple[float, float]] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        try:
            dur_s, _, rps_s = s.partition(":")
            d = float(dur_s.strip())
            r = float(rps_s.strip())
        except ValueError:
            continue
        if d <= 0 or r <= 0:
            continue
        out.append((d, r))
    return out


async def _execute_loadcurve(
    app_state: _AppState,
    profile: list[tuple[float, float]],
    notify: Callable[[str, str], None],
) -> None:
    """Run a piecewise-constant RPS profile by chaining fixed-RPS runs.

    Each phase uses the same _execute_run("rps", ...) machinery; the
    per-phase summary is concatenated into a single history entry tagged
    with mode="loadcurve".
    """
    # Re-collect settings at run time from the live widget dict registered
    # by the load-curve tab. The function delegates to _loadcurve_capture_widgets
    # so it sees the current form values, not stale closures.
    from datetime import UTC, datetime  # local import: keeps module surface small

    from llm_bench import __version__ as _ver
    from llm_bench.models import build_stats_dict
    from llm_bench.runner import run_benchmark

    all_phase_stats: list[dict[str, Any]] = []
    wall_start = time.perf_counter()
    for idx, (duration_s, rps) in enumerate(profile, start=1):
        if app_state.is_busy():
            break
        # Run this phase as an RPS run via the underlying engine, but we
        # need real settings. The user has already configured widgets, so
        # we look them up through a "phase" settings dict.
        # NOTE: this implementation is a thin wrapper around run_benchmark
        # and shares the engine's should_stop hook with the user's stop button.
        # We construct a minimal settings dict from the existing rps_start_btn's
        # parent page widgets by reusing _collect_common_settings lazily
        # through the load-curve page closure.
        # (Implementation detail: we capture widgets from the page at call time.)
        phase_settings = _loadcurve_capture_widgets(app_state)
        phase_settings.update(
            {
                "rps_target": rps,
                "rps_duration": duration_s,
            }
        )
        # Mark the "rps" run as busy so concurrent clicks are blocked.
        # Test#2: do NOT call reset() here — that would create a brand
        # new stop_event and silently discard a stop signal the user
        # gave between phases. reset() now preserves stop_event; we only
        # need to mark busy + clear per-phase metric accumulators.
        rps = app_state.run_states["rps"]
        rps.busy = True
        rps.status = "运行中..."
        rps.log_lines = []
        rps.stats = {}
        rps.raw_results = []
        rps.inflight_samples = []
        rps.started_at_mono = None
        rps.target_total = None
        rps.target_duration_s = None
        rps.chart_refresh_mode = "interval"
        try:
            runtime = _build_runtime_payload(phase_settings)
        except ValueError as exc:
            notify(f"负载曲线配置不合法：{exc}", "negative")
            return
        try:
            summary = await run_benchmark(
                url=runtime["endpoint"],
                headers=_headers(_resolve_api_key(phase_settings["api_key"])),
                body_template=runtime["body_template"],
                concurrency=phase_settings["concurrency"],
                total_requests=None,
                duration_s=None,
                stream=runtime["stream_flag"],
                timeout_s=phase_settings["timeout_s"],
                http2=phase_settings["http2"],
                warmup_requests=phase_settings["warmup"],
                retry_on_429=phase_settings["retry_on_429"],
                retry_on_network=phase_settings["retry_on_network"],
                retry_on_5xx=phase_settings["retry_on_5xx"],
                base_backoff_s=phase_settings["base_backoff_s"],
                prompts=runtime["prompts"],
                prompt_strategy=runtime["prompt_strategy"],
                prompt_weights=runtime["prompt_weights"],
                target_rps=rps,
                rps_duration_s=duration_s,
                proxy_mode=runtime["proxy_mode"],
                proxy_url=runtime["proxy_url"],
                should_stop=app_state.run_states["rps"].stop_event.is_set,
            )
        except Exception as exc:
            notify(f"阶段 {idx} 失败：{exc}", "negative")
            continue
        stats = build_stats_dict(
            summary,
            metadata={
                "bench_start_utc": datetime.now(UTC).isoformat(),
                "llm_bench_version": _ver,
                "endpoint": runtime["endpoint"],
                "model": phase_settings["model"],
                "concurrency": phase_settings["concurrency"],
                "mode": "loadcurve",
                "target_rps": rps,
                "rps_duration_s": duration_s,
                "phase": idx,
                "total_phases": len(profile),
                "proxy_mode": runtime["proxy_mode"],
            },
        )
        all_phase_stats.append(stats)
        app_state.add_history(stats)
        notify(f"阶段 {idx}/{len(profile)} 完成：{rps} req/s × {duration_s}s", "positive")

    wall_s = time.perf_counter() - wall_start
    notify(f"负载曲线完成：{len(all_phase_stats)} 阶段 / {wall_s:.0f}s", "positive")


# Module-level placeholder — the actual capture happens at first call via
# the bound widget dict registered by the load-curve tab when it builds.
_loadcurve_widgets_ref: list[dict[str, Any]] = []


def _register_loadcurve_widgets(widgets: dict[str, Any]) -> None:
    """Called by the load-curve tab builder to expose its widgets to
    _execute_loadcurve (which runs in a separate task and needs to
    re-collect settings from the live form)."""
    _loadcurve_widgets_ref.clear()
    _loadcurve_widgets_ref.append(widgets)


def _loadcurve_capture_widgets(_app_state: _AppState) -> dict[str, Any]:
    """Pull a fresh settings dict from the registered load-curve widgets."""
    if not _loadcurve_widgets_ref:
        return {}
    return _collect_common_settings(_loadcurve_widgets_ref[0])


async def _execute_run(
    app_state: _AppState,
    settings: dict[str, Any],
    mode: str,
    notify: Callable[[str, str], None],
) -> None:
    state = app_state.run_states[mode]
    resolved_key = _resolve_api_key(settings["api_key"])
    if not resolved_key:
        notify("输入框和环境变量都没有 API Key", "negative")
        return
    if app_state.is_busy():
        notify("已有任务运行中", "warning")
        return

    try:
        runtime = _build_runtime_payload(settings)
    except ValueError as exc:
        notify(f"配置不合法：{exc}", "negative")
        return

    state.reset()
    # Test#2: this is the START-button entry point — give the new run a
    # fresh stop_event. Internal phase transitions inside a multi-phase
    # run must NOT clear the event (see _execute_loadcurve).
    state.fresh_stop_event()
    app_state.set_status("运行中", "orange")
    state.chart_refresh_mode = str(settings.get("chart_refresh_mode") or "interval")
    state.chart_refresh_interval_s = _safe_float(settings.get("chart_refresh_interval_s"), 0.3, 0.2)
    state.chart_refresh_every_n = _safe_int(settings.get("chart_refresh_every_n"), 5, 1)

    if mode == "rps":
        mode_payload: dict[str, Any] = {
            "target_rps": _safe_float(settings["rps_target"], 5.0, 0.1),
            "rps_duration_s": _safe_float(settings["rps_duration"], 30.0, 1.0),
            "total_requests": None,
            "duration_s": None,
        }
    else:
        dur = _safe_float(settings["run_duration"], 0.0, 0.0)
        mode_payload = {
            "total_requests": None if dur > 0 else _safe_int(settings["run_total"], 20, 1),
            "duration_s": dur if dur > 0 else None,
            "target_rps": None,
            "rps_duration_s": None,
        }

    state.started_at_mono = time.perf_counter()
    state.target_total = mode_payload.get("total_requests")
    state.target_duration_s = mode_payload.get("rps_duration_s") or mode_payload.get("duration_s")
    state.log_lines.append(
        f"[{datetime.now():%H:%M:%S}] START mode={mode} model={settings['model']} "
        f"concurrency={settings['concurrency']} endpoint={runtime['endpoint']} "
        f"prompts={len(runtime['prompts']) if runtime['prompts'] else 0} strategy={runtime['prompt_strategy']}"
    )

    progress_stride = max(1, settings["concurrency"] // 2 + 1)
    progress_state = {
        "last_total": 0,
        "last_prompt_tokens": 0,
        "last_completion_tokens": 0,
        "last_mono": time.perf_counter(),
    }

    def on_progress(summary: Any) -> None:
        if summary.total % progress_stride != 0:
            return
        now_mono = time.perf_counter()
        delta_t = max(1e-9, now_mono - progress_state["last_mono"])
        delta_total = max(0, summary.total - progress_state["last_total"])
        delta_completion = max(
            0, summary.completion_tokens - progress_state["last_completion_tokens"]
        )
        req_s = delta_total / delta_t
        tok_s = delta_completion / delta_t if delta_completion else 0.0
        latest_latency = summary.latencies_ms[-1] if summary.latencies_ms else None
        inflight = summary.in_flight_samples[-1] if summary.in_flight_samples else 0
        err_brief = ", ".join(
            f"{key}x{int(value)}"
            for key, value in sorted(summary.error_kind_counts.items())
            if int(value) > 0
        )
        err_text = f" | err: {err_brief}" if err_brief else ""
        state.log_lines.append(
            f"[{datetime.now():%H:%M:%S}] OK={summary.success} FAIL={summary.failed} "
            f"TOTAL={summary.total} INFLIGHT={inflight} | req/s={_v(req_s)} lat={_v(latest_latency)}ms "
            f"tok/s={_v(tok_s)} | tokens: prompt={summary.prompt_tokens} completion={summary.completion_tokens}"
            f"{err_text}"
        )
        progress_state["last_total"] = summary.total
        progress_state["last_prompt_tokens"] = summary.prompt_tokens
        progress_state["last_completion_tokens"] = summary.completion_tokens
        progress_state["last_mono"] = now_mono

    try:
        summary = await run_benchmark(
            url=runtime["endpoint"],
            headers=_headers(resolved_key),
            body_template=runtime["body_template"],
            concurrency=settings["concurrency"],
            total_requests=mode_payload.get("total_requests"),
            duration_s=mode_payload.get("duration_s"),
            stream=runtime["stream_flag"],
            timeout_s=settings["timeout_s"],
            http2=settings["http2"],
            warmup_requests=settings["warmup"],
            retry_on_429=settings["retry_on_429"],
            retry_on_network=settings["retry_on_network"],
            retry_on_5xx=settings["retry_on_5xx"],
            base_backoff_s=settings["base_backoff_s"],
            prompts=runtime["prompts"],
            prompt_strategy=runtime["prompt_strategy"],
            prompt_weights=runtime["prompt_weights"],
            target_rps=mode_payload.get("target_rps"),
            rps_duration_s=mode_payload.get("rps_duration_s"),
            raw_results=state.raw_results,
            proxy_mode=runtime["proxy_mode"],
            proxy_url=runtime["proxy_url"],
            progress_callback=on_progress,
            progress_every_n=1,
            should_stop=state.stop_event.is_set,
        )
        stats = build_stats_dict(
            summary,
            metadata={
                "bench_start_utc": datetime.now(UTC).isoformat(),
                "llm_bench_version": __version__,
                "endpoint": runtime["endpoint"],
                "model": settings["model"],
                "concurrency": settings["concurrency"],
                "mode": mode,
                "target_rps": mode_payload.get("target_rps"),
                "rps_duration_s": mode_payload.get("rps_duration_s"),
                "proxy_mode": runtime["proxy_mode"],
                "prompt_strategy": runtime["prompt_strategy"],
            },
        )
        state.stats = stats
        state.inflight_samples = list(summary.in_flight_samples)
        prompt_tokens_total = int(stats.get("prompt_tokens_total") or 0)
        completion_tokens_total = int(stats.get("completion_tokens_total") or 0)
        state.consumed_prompt_tokens += prompt_tokens_total
        state.consumed_completion_tokens += completion_tokens_total
        app_state.add_consumed_tokens(prompt_tokens_total, completion_tokens_total)
        app_state.add_history(stats)
        state.log_lines.append(
            f"[{datetime.now():%H:%M:%S}] END req/s={_v(stats.get('throughput_rps'))} "
            f"p95={_v(stats.get('latency_ms_p95'))} "
            f"tokens(prompt/completion)={prompt_tokens_total}/{completion_tokens_total}"
        )
        state.status, app_text, app_color, notify_text, notify_level = _run_completion_feedback(
            stats
        )
        app_state.set_status(app_text, app_color)
        notify(notify_text, notify_level)
    except asyncio.CancelledError:
        state.status = "已停止"
        app_state.set_status("已停止", "gray")
        notify("任务已停止", "warning")
        return
    except Exception as exc:
        state.status = "失败"
        state.log_lines.append(f"[{datetime.now():%H:%M:%S}] ERROR: {exc}")
        app_state.set_status("失败", "red")
        notify(f"压测失败：{exc}", "negative")
        return
    finally:
        state.busy = False


async def _execute_sweep(
    app_state: _AppState,
    settings: dict[str, Any],
    notify: Callable[[str, str], None],
    *,
    probe_mode: bool = False,
) -> None:
    sweep_state = app_state.sweep_state
    resolved_key = _resolve_api_key(settings["api_key"])
    if not resolved_key:
        notify("输入框和环境变量都没有 API Key", "negative")
        return
    if app_state.is_busy():
        notify("已有任务运行中", "warning")
        return

    try:
        raw_levels = settings["sweep_levels"].replace(";", ",")
        levels = [max(1, int(x.strip())) for x in raw_levels.split(",") if x.strip()]
    except ValueError:
        notify("并发级别只能填整数，例如：1,2,4,8,16", "negative")
        return
    if not levels:
        notify("并发级别不能为空", "negative")
        return

    try:
        runtime = _build_runtime_payload(settings)
    except ValueError as exc:
        notify(f"配置不合法：{exc}", "negative")
        return

    sweep_state.reset()
    # Test#2: start-button entry point — give the new sweep a fresh event.
    sweep_state.fresh_stop_event()
    app_state.set_status("扫描中", "orange")
    sweep_state.chart_refresh_mode = str(settings.get("chart_refresh_mode") or "interval")
    sweep_state.chart_refresh_interval_s = _safe_float(
        settings.get("chart_refresh_interval_s"), 0.3, 0.2
    )
    sweep_state.chart_refresh_every_n = _safe_int(settings.get("chart_refresh_every_n"), 5, 1)
    per_n = _safe_int(settings["sweep_per"], 40, 1)
    proxy_url_val = settings.get("proxy_url")
    shared_proxy = proxy_url_val if settings["proxy_mode"] == "custom" else None
    shared_trust_env = settings["proxy_mode"] == "system"

    try:
        async with httpx.AsyncClient(
            http2=settings["http2"],
            limits=limits_for_concurrency(max(levels)),
            proxy=shared_proxy,
            trust_env=shared_trust_env,
        ) as shared_client:
            for concurrency in levels:
                if sweep_state.stop_event.is_set():
                    break
                sweep_state.log_lines.append(
                    f"[{datetime.now():%H:%M:%S}] START level={concurrency} per={per_n} "
                    f"strategy={runtime['prompt_strategy']}"
                )
                # UX#5: collect this level's raw results so the monitor
                # can replay individual requests after the sweep ends.
                level_raw_results: list[Any] = []
                summary = await run_benchmark(
                    url=runtime["endpoint"],
                    headers=_headers(resolved_key),
                    body_template=runtime["body_template"],
                    concurrency=concurrency,
                    total_requests=per_n,
                    duration_s=None,
                    stream=runtime["stream_flag"],
                    timeout_s=settings["timeout_s"],
                    http2=settings["http2"],
                    warmup_requests=settings["warmup"],
                    retry_on_429=settings["retry_on_429"],
                    retry_on_network=settings["retry_on_network"],
                    retry_on_5xx=settings["retry_on_5xx"],
                    base_backoff_s=settings["base_backoff_s"],
                    prompts=runtime["prompts"],
                    prompt_strategy=runtime["prompt_strategy"],
                    prompt_weights=runtime["prompt_weights"],
                    proxy_mode=settings["proxy_mode"],
                    proxy_url=proxy_url_val,
                    shared_client=shared_client,
                    raw_results=level_raw_results,
                    should_stop=sweep_state.stop_event.is_set,
                )
                stat = build_stats_dict(
                    summary,
                    metadata={
                        "bench_start_utc": datetime.now(UTC).isoformat(),
                        "llm_bench_version": __version__,
                        "endpoint": runtime["endpoint"],
                        "model": settings["model"],
                        "concurrency": concurrency,
                        "mode": "sweep",
                    },
                )
                stat["concurrency_level"] = concurrency
                # L11: if the user clicked Stop during this level, the data we
                # just collected is partial. Mark it so the chart / table can
                # render it differently (e.g. dimmer color).
                if sweep_state.stop_event.is_set():
                    stat["partial"] = True
                sweep_state.all_stats.append(stat)
                # UX#5 + Perf#1: cap per-level raw_results to keep memory
                # bounded. A 50K sweep at 200 req/level × 250 levels would
                # otherwise hold every request's full result. The cap is
                # per-level (first N are kept; later ones summarized
                # only in the stats dict) so the user can still replay a
                # representative sample.
                kept = level_raw_results[:_MAX_RAW_PER_LEVEL]
                truncated = len(level_raw_results) - len(kept)
                sweep_state.raw_results_per_level.append(kept)
                sweep_state.raw_results_levels.append(concurrency)
                sweep_state.raw_results_stats_indices.append(len(sweep_state.all_stats) - 1)
                if truncated > 0:
                    # Annotate the stat so the monitor can warn.
                    stat["raw_results_truncated"] = truncated
                    sweep_state.log_lines.append(
                        f"[{datetime.now():%H:%M:%S}] NOTE: {t('sweep_truncated_n', n=truncated)}"
                        f" ({_MAX_RAW_PER_LEVEL})"
                    )
                prompt_tokens_total = int(stat.get("prompt_tokens_total") or 0)
                completion_tokens_total = int(stat.get("completion_tokens_total") or 0)
                sweep_state.consumed_prompt_tokens += prompt_tokens_total
                sweep_state.consumed_completion_tokens += completion_tokens_total
                app_state.add_consumed_tokens(prompt_tokens_total, completion_tokens_total)
                app_state.add_history(stat)
                sweep_state.rows.append(
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
                sweep_state.log_lines.append(
                    f"[{datetime.now():%H:%M:%S}] concurrency={concurrency} "
                    f"success={_v(stat.get('success_rate_pct'))}% req/s={_v(stat.get('throughput_rps'))} "
                    f"avg={_v(stat.get('latency_ms_mean'))}ms p95={_v(stat.get('latency_ms_p95'))} "
                    f"tok/s={_v(stat.get('throughput_completion_tok_s'))} "
                    f"tokens(prompt/completion)={prompt_tokens_total}/{completion_tokens_total}"
                )
        _, app_text, app_color, notify_text, notify_level = _sweep_completion_feedback(
            sweep_state.all_stats
        )
        if probe_mode and notify_level == "positive":
            notify_text = f"探测完成：{notify_text}"
        sweep_state.log_lines.append(f"[{datetime.now():%H:%M:%S}] {notify_text}")
        # L8 fix: write status BEFORE clearing busy, so a 0.2s timer that reads
        # busy=False never sees the old "扫描中" string.
        app_state.set_status(app_text, app_color)
        sweep_state.busy = False
        notify(notify_text, notify_level)
    except asyncio.CancelledError:
        app_state.set_status("已停止", "gray")
        notify("扫描已停止", "warning")
        return
    except Exception as exc:
        sweep_state.log_lines.append(f"[{datetime.now():%H:%M:%S}] ERROR: {exc}")
        app_state.set_status("失败", "red")
        notify(f"扫描失败：{exc}", "negative")
        return
    finally:
        sweep_state.busy = False


def _build_config_form(widgets: dict[str, Any]) -> dict[str, Any]:
    panels: dict[str, Any] = {}

    with ui.column().classes("w-full gap-4"):
        ui.label("控制台").classes("text-lg font-bold text-slate-700")
        ui.label("专注于配置、启动与停止任务。监看结果请看另一扇窗口。").classes(
            "text-xs text-slate-500"
        )
        endpoint_preview = ui.label("").classes("text-xs text-slate-400 break-all")

        # Let Tailwind breakpoints drive the column count on resize.
        with ui.grid().classes(_CONTROL_GRID_CLASSES):
            with (
                ui.expansion("基础连接", icon="link", value=True)
                .classes(_CONTROL_PANEL_CLASSES)
                .props("expand-separator switch-toggle-side") as panels["base_connection"],
                ui.grid(columns=1)
                .classes("w-full gap-3")
                .style("grid-template-columns:repeat(auto-fit,minmax(180px,1fr));"),
            ):
                widgets["base_url"] = ui.input("Base URL *", value=_DEFAULT_BASE_URL).classes(
                    "w-full col-span-full"
                )
                _attach_tooltip(widgets["base_url"], _TOOLTIPS["base_url"])

                # T6: live port reachability badge. We do a plain TCP
                # connect (no HTTP) so the probe is fast and doesn't
                # generate noise on the server's request logs. Cached
                # for 30s to avoid hammering during typing.
                with ui.row().classes("w-full col-span-full items-center gap-2"):
                    port_status = ui.badge("⚪ 未检测", color="grey").classes("text-xs")
                    _attach_tooltip(port_status, _TOOLTIPS["port_status"])

                    async def _check_port() -> None:
                        url = widgets["base_url"].value or ""
                        try:
                            host, port, scheme = _parse_base_for_probe(url)
                        except ValueError as exc:
                            port_status.set_text(f"❌ URL 错误: {exc}")
                            port_status.classes(remove="bg-slate-100 bg-emerald-100 bg-red-100 text-slate-700 text-emerald-700 text-red-700")
                            port_status.classes(add="bg-red-100 text-red-700")
                            return
                        port_status.set_text("🟡 探测中…")
                        port_status.classes(remove="bg-slate-100 bg-emerald-100 bg-red-100 text-slate-700 text-emerald-700 text-red-700")
                        port_status.classes(add="bg-slate-100 text-slate-700")
                        ok, ms_or_err = await _tcp_probe(host, port, timeout=2.0)
                        if ok:
                            port_status.set_text(f"🟢 {host}:{port} 可达（{ms_or_err:.0f} ms）")
                            port_status.classes(remove="bg-slate-100 bg-red-100 text-slate-700 text-red-700")
                            port_status.classes(add="bg-emerald-100 text-emerald-700")
                        else:
                            port_status.set_text(f"🔴 {host}:{port} 不可达（{ms_or_err}）")
                            port_status.classes(remove="bg-slate-100 bg-emerald-100 text-slate-700 text-emerald-700")
                            port_status.classes(add="bg-red-100 text-red-700")

                    port_check_btn = ui.button("探测", icon="network_check").props(
                        "outline dense size=sm"
                    )
                    # Perf#3: in-flight guard wraps _check_port so rapid
                    # clicks don't queue multiple async probes (each
                    # opens a TCP socket).
                    _port_probe_inflight: dict[str, bool] = {"running": False}

                    def _check_port_guarded() -> None:
                        if _port_probe_inflight["running"]:
                            return
                        _port_probe_inflight["running"] = True
                        port_check_btn.disable()

                        import asyncio

                        async def _run_and_release() -> None:
                            try:
                                await _check_port()
                            finally:
                                _port_probe_inflight["running"] = False
                                port_check_btn.enable()

                        asyncio.create_task(_run_and_release())

                    port_check_btn.on_click(_check_port_guarded)

                    # UX#2: auto-trigger a probe 600ms after the user
                    # stops typing in the Base URL field. Debounced so
                    # rapid keystrokes don't fire N probes.
                    _port_probe_pending: dict[str, Any] = {"timer": None}

                    def _schedule_port_probe() -> None:
                        prev = _port_probe_pending["timer"]
                        if prev is not None:
                            prev.cancel()
                        _port_probe_pending["timer"] = ui.timer(
                            0.6, _check_port, once=True
                        )

                    widgets["base_url"].on_value_change(
                        lambda _: _schedule_port_probe()
                    )

                # URL templates: one-click presets for common providers. Saves
                # the user from copy-pasting URLs and reduces typo risk.
                with ui.row().classes("w-full col-span-full gap-1 flex-wrap"):
                    ui.label("快速模板：").classes("text-xs text-slate-500 self-center")
                    for label, url in [
                        ("OpenAI", "https://api.openai.com/v1"),
                        ("Azure", "https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOY"),
                        ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4"),
                        ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                        ("DeepSeek", "https://api.deepseek.com/v1"),
                        ("月之暗面", "https://api.moonshot.cn/v1"),
                        ("vLLM", "http://localhost:8000/v1"),
                        ("Ollama", "http://localhost:11434/v1"),
                    ]:

                        def _apply(_url: str = url, _label: str = label) -> None:
                            widgets["base_url"].value = _url
                            ui.notify(f"已应用 {_label} 模板，记得修改占位符", type="info")

                        ui.button(label, on_click=_apply).props("outline dense size=sm")
                widgets["api_key"] = ui.input(
                    "API Key *",
                    password=True,
                    password_toggle_button=True,
                    value=env_api_key() or "",
                ).classes("w-full col-span-full")
                _attach_tooltip(widgets["api_key"], _TOOLTIPS["api_key"])
                widgets["model"] = ui.input("Model *", value=_DEFAULT_MODEL).classes("w-full")
                _attach_tooltip(widgets["model"], _TOOLTIPS["model"])
                widgets["concurrency"] = ui.number("并发上限", value=5, min=1, step=1).classes(
                    "w-full"
                )
                _attach_tooltip(widgets["concurrency"], _TOOLTIPS["concurrency"])
                model_override_hint = ui.label("当前以自定义请求体 JSON 中的 model 为准。").classes(
                    "text-xs text-slate-500 col-span-full"
                )
                model_override_hint.set_visibility(False)

            with (
                ui.expansion("网络与诊断", icon="wifi", value=False)
                .classes(_CONTROL_PANEL_CLASSES)
                .props("expand-separator switch-toggle-side") as panels["network"]
            ):
                with (
                    ui.grid(columns=1)
                    .classes("w-full gap-3")
                    .style("grid-template-columns:repeat(auto-fit,minmax(180px,1fr));")
                ):
                    widgets["proxy_mode_label"] = ui.select(
                        options=_PROXY_OPTIONS,
                        value="直连",
                        label="代理模式",
                    ).classes("w-full")
                    _attach_tooltip(widgets["proxy_mode_label"], _TOOLTIPS["proxy_mode"])
                    widgets["proxy_url_input"] = ui.input(
                        "代理地址", value="http://127.0.0.1:7890"
                    ).classes("w-full col-span-full")
                    _attach_tooltip(widgets["proxy_url_input"], _TOOLTIPS["proxy_url"])
                    widgets["proxy_url_input"].set_visibility(False)
                    widgets["proxy_mode_label"].on_value_change(
                        lambda e: widgets["proxy_url_input"].set_visibility(e.value == "自定义代理")
                    )
                    widgets["conn_timeout"] = ui.number(
                        "连通性超时（秒）", value=10, min=1, step=1
                    ).classes("w-full")
                    _attach_tooltip(widgets["conn_timeout"], _TOOLTIPS["conn_timeout"])
                    conn_status = ui.label("尚未测试连通性").classes(
                        "text-xs text-slate-500 col-span-full min-h-10"
                    )

                async def _test_connectivity() -> None:
                    # M7: cap timeout and disable button for the duration of the
                    # probe so a stuck server (or repeated clicks) doesn't pile
                    # up parallel tasks. Also cap timeout to 60s as a safety
                    # belt — the user-editable conn_timeout has no upper bound.
                    probe_btn.disable()
                    conn_status.set_text("正在发起真实 POST 测试...")
                    try:
                        try:
                            settings = _collect_common_settings(widgets)
                            runtime = _build_runtime_payload(settings)
                        except ValueError as exc:
                            conn_status.set_text(f"❌ 配置不合法：{exc}")
                            return
                        resolved_key = _resolve_api_key(widgets["api_key"].value or "")
                        headers = (
                            _headers(resolved_key)
                            if resolved_key
                            else {"Content-Type": "application/json"}
                        )
                        try:
                            result = await probe_connectivity(
                                url=runtime["endpoint"],
                                timeout_s=min(
                                    60.0, _safe_float(widgets["conn_timeout"].value, 10.0, 1.0)
                                ),
                                http2=widgets["http2"].value,
                                method="POST",
                                headers=headers,
                                json_body=runtime["body_template"],
                                proxy_mode=_PROXY_LABEL_TO_VALUE.get(
                                    widgets["proxy_mode_label"].value, "direct"
                                ),
                                proxy_url=(widgets["proxy_url_input"].value or "").strip() or None,
                            )
                        except Exception as exc:
                            conn_status.set_text(f"❌ 测试请求失败：{exc}")
                            return
                        if result.get("ok"):
                            conn_status.set_text(
                                f"✅ POST 正常｜status={result.get('status_code')}｜耗时={_v(result.get('elapsed_ms'))}ms"
                            )
                        else:
                            conn_status.set_text(
                                f"❌ POST 失败｜status={result.get('status_code') or '-'}｜"
                                f"{result.get('error_kind') or 'unknown'}｜{_preview_text(result.get('response_text'))}"
                            )
                    finally:
                        probe_btn.enable()

                probe_btn = (
                    ui.button("测试连接", icon="network_check", on_click=_test_connectivity)
                    .props("color=dark outline")
                    .classes("mt-1 w-full")
                )

            with (
                ui.expansion("请求输入", icon="edit", value=True)
                .classes(_CONTROL_PANEL_WIDE_CLASSES)
                .props("expand-separator switch-toggle-side") as panels["request_input"],
                ui.column().classes("w-full gap-3"),
            ):
                widgets["request_mode"] = ui.toggle(
                    {"standard": "普通模式", "custom": "全自定义"},
                    value="standard",
                ).classes("w-full")
                request_mode_hint = ui.label(
                    "普通模式会基于基础配置拼装请求体；全自定义模式会直接发送你填写的 JSON。"
                ).classes("text-xs text-slate-500")

                prompt_items: list[str] = []
                prompt_weights: list[float] = []

                def _get_prompts() -> list[str]:
                    return [item.strip() for item in prompt_items if item.strip()]

                def _get_prompt_weights() -> list[float]:
                    prompts = _get_prompts()
                    out: list[float] = []
                    for idx in range(len(prompts)):
                        try:
                            raw = float(prompt_weights[idx]) if idx < len(prompt_weights) else 1.0
                        except (TypeError, ValueError):
                            raw = 1.0
                        out.append(raw if raw > 0 else 1.0)
                    return out

                def _estimate_total_requests() -> int:
                    run_duration = _safe_float(widgets["run_duration"].value, 0.0, 0.0)
                    if run_duration > 0:
                        target_rps = _safe_float(widgets["rps_target"].value, 5.0, 0.1)
                        rps_duration = _safe_float(widgets["rps_duration"].value, 30.0, 1.0)
                        return max(1, int(target_rps * rps_duration))
                    return _safe_int(widgets["run_total"].value, 20, 1)

                with ui.column().classes("w-full gap-3") as request_standard_controls:
                    with (
                        ui.grid(columns=1)
                        .classes("w-full gap-3")
                        .style("grid-template-columns:repeat(auto-fit,minmax(180px,1fr));")
                    ):
                        widgets["max_tokens"] = ui.number(
                            "max_tokens", value=128, min=1, step=1
                        ).classes("w-full")
                        _attach_tooltip(widgets["max_tokens"], _TOOLTIPS["max_tokens"])
                        widgets["temperature"] = ui.number(
                            "temperature", value=0.2, min=0.0, step=0.1, format="%.1f"
                        ).classes("w-full")
                        _attach_tooltip(widgets["temperature"], _TOOLTIPS["temperature"])
                        widgets["stream"] = ui.switch("流式输出", value=False).classes(
                            "col-span-full"
                        )
                        _attach_tooltip(widgets["stream"], _TOOLTIPS["stream"])

                    ui.label("多 Prompt（支持顺序循环、随机挑选、加权随机）").classes(
                        "text-xs text-slate-500"
                    )
                    ui.label("普通/自定义模式共用这组 Prompt；实时预览默认展示第 1 条。").classes(
                        "text-xs text-slate-400"
                    )
                    widgets["prompt_strategy"] = ui.select(
                        options=_PROMPT_STRATEGY_OPTIONS,
                        value="sequential",
                        label="Prompt 选择策略",
                    ).classes("w-full")
                    _attach_tooltip(widgets["prompt_strategy"], _TOOLTIPS["prompt_strategy"])
                    # T1-4: short inline hint that the user sees without hovering.
                    ui.label(
                        "sequential=按顺序；random=均匀随机；weighted=按右侧权重采样"
                    ).classes("text-xs text-slate-500")

                    def _render_prompts() -> None:
                        prompt_editor.clear()
                        prompt_count_label.set_text(f"当前 {len(_get_prompts())} 条")
                        strategy = widgets["prompt_strategy"].value
                        weighted = strategy == "weighted"
                        with prompt_editor:
                            if not prompt_items:
                                ui.label("当前未配置多 Prompt，将使用默认 Prompt。").classes(
                                    "text-xs text-slate-400"
                                )
                                return
                            while len(prompt_weights) < len(prompt_items):
                                prompt_weights.append(1.0)
                            for index, prompt in enumerate(prompt_items):
                                with ui.row().classes("w-full items-start gap-2"):
                                    ui.badge(str(index + 1)).classes("mt-2")
                                    prompt_box = ui.textarea(value=prompt).classes(
                                        "flex-1 font-mono text-sm"
                                    )
                                    prompt_box.props("autogrow rows=2")
                                    prompt_box.on_value_change(
                                        lambda e, i=index: (
                                            prompt_items.__setitem__(i, e.value),
                                            _refresh_request_preview(),
                                            _refresh_token_estimation(),
                                        )
                                    )
                                    # T1-4: always show weight column. When not
                                    # in 'weighted' mode, the input is disabled
                                    # and dimmed — but its presence signals that
                                    # the field exists and where to find it.
                                    weight_input = ui.number(
                                        label="权重" if weighted else "权重 (仅 weighted 生效)",
                                        value=float(
                                            prompt_weights[index]
                                            if index < len(prompt_weights)
                                            else 1.0
                                        ),
                                        min=0.1,
                                        step=0.1,
                                        format="%.1f",
                                    ).classes("w-28" if weighted else "w-36 opacity-60")
                                    if not weighted:
                                        weight_input.disable()
                                    weight_input.on_value_change(
                                        lambda e, i=index: (
                                            prompt_weights.__setitem__(
                                                i, _safe_float(e.value, 1.0, 0.1)
                                            ),
                                            _refresh_token_estimation(),
                                        )
                                    )
                                    ui.button(
                                        icon="delete", on_click=lambda i=index: _remove_prompt(i)
                                    ).props("flat color=red")

                    def _set_prompts(items: list[str], weights: list[float] | None = None) -> None:
                        prompt_items[:] = list(items)
                        if weights is None:
                            prompt_weights[:] = [1.0] * len(prompt_items)
                        else:
                            prompt_weights[:] = [
                                max(0.1, _safe_float(weight, 1.0, 0.1)) for weight in weights
                            ][: len(prompt_items)]
                            while len(prompt_weights) < len(prompt_items):
                                prompt_weights.append(1.0)
                        _render_prompts()
                        _refresh_request_preview()
                        _refresh_token_estimation()

                    def _set_prompt_weights(weights: list[float]) -> None:
                        _set_prompts(prompt_items, weights)

                    def _add_prompt(default_text: str = "") -> None:
                        prompt_items.append(default_text)
                        prompt_weights.append(1.0)
                        _render_prompts()
                        _refresh_request_preview()
                        _refresh_token_estimation()

                    def _remove_prompt(index: int) -> None:
                        if 0 <= index < len(prompt_items):
                            prompt_items.pop(index)
                            if 0 <= index < len(prompt_weights):
                                prompt_weights.pop(index)
                            _render_prompts()
                            _refresh_request_preview()
                            _refresh_token_estimation()

                    async def _handle_prompt_upload(e: events.UploadEventArguments) -> None:
                        try:
                            imported = _parse_prompt_upload_text(e.file.name, await e.file.text())
                        except (ValueError, json.JSONDecodeError) as exc:
                            ui.notify(f"导入 Prompt 失败：{exc}", type="negative")
                            return
                        _set_prompts(imported)
                        ui.notify(f"已导入 {len(imported)} 条 Prompt", type="positive")

                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        prompt_count_label = ui.label("当前 0 条").classes("text-xs text-slate-500")
                        ui.button("新增 Prompt", icon="add", on_click=lambda: _add_prompt()).props(
                            "outline color=dark"
                        )
                        ui.button(
                            "清空", icon="clear_all", on_click=lambda: _set_prompts([])
                        ).props("outline")
                        prompt_upload = ui.upload(
                            on_upload=_handle_prompt_upload,
                            max_file_size=_PROMPT_IMPORT_MAX_BYTES,
                            on_rejected=lambda: ui.notify("文件过大，无法导入", type="negative"),
                        ).props("accept=.txt,.json")
                        prompt_upload.classes("max-w-full")
                    prompt_editor = ui.column().classes("w-full gap-2")
                    widgets["get_prompts"] = _get_prompts
                    widgets["set_prompts"] = _set_prompts
                    widgets["get_prompt_weights"] = _get_prompt_weights
                    widgets["set_prompt_weights"] = _set_prompt_weights
                    _render_prompts()

                    ui.label("附加请求体 JSON（递归合并到基础请求体）").classes(
                        "text-xs text-slate-500"
                    )
                    ui.label(
                        '示例：{"thinking": {"type": "enabled"}}；同名字段以后填的附加 JSON 为准。'
                    ).classes("text-xs text-slate-400")
                    widgets["append_body_json"] = ui.textarea(placeholder="留空则不附加").classes(
                        "w-full font-mono text-sm"
                    )
                    widgets["append_body_json"].props("rows=6")
                    _attach_tooltip(widgets["append_body_json"], _TOOLTIPS["append_body_json"])
                    preview_hint = ui.label("实时预览完整请求体（当前展示第 1 条 Prompt）").classes(
                        "text-xs text-slate-500"
                    )
                    request_preview = ui.code("", language="json").classes(
                        "w-full text-xs max-h-72 overflow-auto border rounded"
                    )
                    token_estimate_hint = ui.label("Token 预估（本地估算）").classes(
                        "text-xs text-slate-500"
                    )
                    token_estimate = ui.code("", language="json").classes(
                        "w-full text-xs max-h-72 overflow-auto border rounded"
                    )
                    prerun_hint = ui.label("精确预跑结果").classes("text-xs text-slate-500")
                    prerun_estimate = ui.code("", language="json").classes(
                        "w-full text-xs max-h-72 overflow-auto border rounded"
                    )
                    prerun_btn = ui.button("精确预跑估算", icon="science").props(
                        "outline color=dark"
                    )

                    async def _run_prerun_estimation() -> None:
                        settings = _collect_common_settings(widgets) | {
                            "run_total": widgets["run_total"].value,
                            "run_duration": widgets["run_duration"].value,
                            "rps_target": widgets["rps_target"].value,
                            "rps_duration": widgets["rps_duration"].value,
                        }
                        total_requests = _estimate_total_requests()
                        try:
                            runtime = _build_runtime_payload(settings)
                        except ValueError as exc:
                            ui.notify(f"配置不合法：{exc}", type="negative")
                            return
                        resolved_key = _resolve_api_key(settings["api_key"])
                        if not resolved_key:
                            ui.notify("请先填写 API Key", type="warning")
                            return
                        prerun_btn.disable()
                        prerun_hint.set_text("精确预跑中...")
                        try:
                            result = await estimate_tokens_prerun(
                                url=runtime["endpoint"],
                                headers=_headers(resolved_key),
                                body_template=runtime["body_template"],
                                prompts=runtime["prompts"],
                                stream=runtime["stream_flag"],
                                timeout_s=settings["timeout_s"],
                                http2=settings["http2"],
                                proxy_mode=runtime["proxy_mode"],
                                proxy_url=runtime["proxy_url"],
                                total_requests=total_requests,
                                prompt_strategy=runtime["prompt_strategy"],
                                prompt_weights=runtime["prompt_weights"],
                            )
                        except Exception as exc:
                            prerun_hint.set_text(f"精确预跑失败：{exc}")
                            ui.notify(f"精确预跑失败：{exc}", type="negative")
                        else:
                            prerun_hint.set_text(
                                f"精确预跑完成（预计总请求 {result['total_requests']}，耗时 {_v(result['wall_seconds'])}s）"
                            )
                            prerun_estimate.set_content(
                                json.dumps(result, ensure_ascii=False, indent=2)
                            )
                            ui.notify("精确预跑估算完成", type="positive")
                        finally:
                            prerun_btn.enable()

                    def _refresh_token_estimation() -> None:
                        try:
                            settings = _collect_common_settings(widgets) | {
                                "run_total": widgets["run_total"].value,
                                "run_duration": widgets["run_duration"].value,
                                "rps_target": widgets["rps_target"].value,
                                "rps_duration": widgets["rps_duration"].value,
                            }
                            runtime = _build_runtime_payload(settings)
                            estimate = estimate_tokens_local(
                                body_template=runtime["body_template"],
                                prompts=runtime["prompts"],
                                model=str(settings.get("model") or ""),
                                total_requests=_estimate_total_requests(),
                                max_tokens=_safe_int(settings["max_tokens"], 128, 1),
                                prompt_strategy=runtime["prompt_strategy"],
                                prompt_weights=runtime["prompt_weights"],
                            )
                            token_estimate_hint.set_text(
                                f"Token 预估（本地估算｜预计总请求 {estimate['total_requests']}）"
                            )
                            token_estimate.set_content(
                                json.dumps(estimate, ensure_ascii=False, indent=2)
                            )
                        except Exception as exc:
                            token_estimate_hint.set_text("Token 预估（本地估算失败）")
                            token_estimate.set_content(
                                json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)
                            )

                    prerun_btn.on_click(_run_prerun_estimation)

                with ui.column().classes("w-full gap-3") as request_custom_controls:
                    ui.label(
                        "全自定义模式会直接发送下面的 JSON；若配置了多 Prompt，会替换第一个 role=user 消息。"
                    ).classes("text-xs text-slate-500")
                    with (
                        ui.grid(columns=1)
                        .classes("w-full gap-3")
                        .style("grid-template-columns:repeat(auto-fit,minmax(220px,1fr));")
                    ):
                        widgets["custom_stream"] = ui.switch("按流式响应解析", value=False).classes(
                            "w-full"
                        )
                        _attach_tooltip(widgets["custom_stream"], _TOOLTIPS["custom_stream"])
                        widgets["custom_endpoint"] = ui.input(
                            "请求路径 / 完整 URL", value="/chat/completions"
                        ).classes("w-full col-span-full")
                        _attach_tooltip(widgets["custom_endpoint"], _TOOLTIPS["custom_endpoint"])
                    ui.label("自定义请求体 JSON").classes("text-xs text-slate-500")
                    widgets["custom_body_json"] = ui.textarea(value=_DEFAULT_CUSTOM_BODY).classes(
                        "w-full font-mono text-sm"
                    )
                    widgets["custom_body_json"].props("rows=14")
                    _attach_tooltip(widgets["custom_body_json"], _TOOLTIPS["custom_body_json"])

            with (
                ui.expansion("高级控制", icon="tune", value=False)
                .classes(_CONTROL_PANEL_WIDE_CLASSES)
                .props("expand-separator switch-toggle-side") as panels["advanced"],
                ui.grid(columns=1)
                .classes("w-full gap-3")
                .style("grid-template-columns:repeat(auto-fit,minmax(180px,1fr));"),
            ):
                widgets["timeout_s"] = ui.number("超时（秒）", value=120, min=1, step=1).classes(
                    "w-full"
                )
                _attach_tooltip(widgets["timeout_s"], _TOOLTIPS["timeout_s"])
                widgets["warmup"] = ui.number("预热请求数", value=0, min=0, step=1).classes(
                    "w-full"
                )
                _attach_tooltip(widgets["warmup"], _TOOLTIPS["warmup"])
                widgets["retry_on_429"] = ui.number("429 重试次数", value=3, min=0, step=1).classes(
                    "w-full"
                )
                _attach_tooltip(widgets["retry_on_429"], _TOOLTIPS["retry_on_429"])
                widgets["retry_on_network"] = ui.number(
                    "网络错误重试", value=1, min=0, step=1
                ).classes("w-full")
                _attach_tooltip(widgets["retry_on_network"], _TOOLTIPS["retry_on_network"])
                widgets["retry_on_5xx"] = ui.number("5xx 重试次数", value=1, min=0, step=1).classes(
                    "w-full"
                )
                _attach_tooltip(widgets["retry_on_5xx"], _TOOLTIPS["retry_on_5xx"])
                widgets["base_backoff_s"] = ui.number(
                    "退避基数（秒）", value=1.0, min=0.1, step=0.1, format="%.1f"
                ).classes("w-full")
                _attach_tooltip(widgets["base_backoff_s"], _TOOLTIPS["base_backoff_s"])
                widgets["http2"] = ui.switch("HTTP/2", value=False).classes("col-span-full")
                _attach_tooltip(widgets["http2"], _TOOLTIPS["http2"])
                widgets["chart_refresh_mode"] = ui.select(
                    options={"interval": "图表按时间刷新", "requests": "图表按请求数刷新"},
                    value="interval",
                    label="图表刷新模式",
                ).classes("w-full")
                widgets["chart_refresh_interval_s"] = ui.number(
                    "图表刷新间隔（秒）",
                    value=0.3,
                    min=0.2,
                    step=0.1,
                    format="%.1f",
                ).classes("w-full")
                widgets["chart_refresh_every_n"] = ui.number(
                    "图表每 N 个请求刷新",
                    value=5,
                    min=1,
                    step=1,
                ).classes("w-full")

        def _update_preview(*_: Any) -> None:
            base = widgets["base_url"].value
            norm, err = _normalize_base_url(base or "")
            if err:
                endpoint_preview.set_text(f"❌ Base URL 不合法：{err}")
                endpoint_preview.classes(replace="text-xs text-red-500 break-all")
                return
            endpoint = _resolve_endpoint(
                base,
                widgets["custom_endpoint"].value
                if widgets["request_mode"].value == "custom"
                else None,
            )
            # Color-code: green if looks like a chat endpoint, amber if not.
            color = "text-emerald-600" if "/chat/completions" in endpoint else "text-slate-600"
            endpoint_preview.set_text(f"请求地址：{endpoint}")
            endpoint_preview.classes(replace=f"text-xs {color} break-all")

        def _refresh_request_preview(*_: Any) -> None:
            try:
                settings = _collect_common_settings(widgets)
                if widgets["request_mode"].value == "custom":
                    preview_body, parse_err = _parse_custom_body(settings["custom_body_json"])
                    if parse_err:
                        raise ValueError(parse_err)
                else:
                    preview_body = _build_standard_request_body(settings)
                prompts = _resolve_prompt_list(settings)
                if prompts:
                    preview_body = _apply_preview_prompt(preview_body, prompts[0])
                request_preview.set_content(json.dumps(preview_body, ensure_ascii=False, indent=2))
                preview_hint.set_text(
                    "实时预览完整请求体"
                    + (
                        f"（当前展示第 1/{len(prompts)} 条 Prompt）"
                        if prompts
                        else "（当前使用默认 Prompt）"
                    )
                )
            except ValueError as exc:
                request_preview.set_content(
                    json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)
                )
                preview_hint.set_text("实时预览完整请求体（当前配置存在问题）")
            _refresh_token_estimation()

        async def _maybe_migrate_standard_to_custom() -> None:
            settings = _collect_common_settings(widgets)
            has_standard_values = bool(
                _resolve_prompt_list(settings)
                or (settings.get("append_body_json") or "").strip()
                or bool(settings.get("stream"))
                or _safe_int(settings.get("max_tokens"), 128, 1) != 128
                or abs(_safe_float(settings.get("temperature"), 0.2, 0.0) - 0.2) > 1e-9
                or (str(settings.get("model") or "").strip() != _DEFAULT_MODEL)
            )
            if not has_standard_values:
                return
            with ui.dialog() as dialog, ui.card().classes("w-[30rem]"):
                ui.label("检测到普通模式已有配置").classes("text-base font-semibold")
                ui.label("是否迁移到自定义请求体？").classes("text-sm text-slate-500")
                with ui.row().classes("justify-end w-full gap-2"):
                    ui.button("不迁移", on_click=lambda: dialog.submit("skip")).props("flat")
                    ui.button("迁移", on_click=lambda: dialog.submit("migrate")).props(
                        "color=dark"
                    )
            dialog.open()
            decision = await dialog
            if decision != "migrate":
                return
            migrated = _build_standard_request_body(settings)
            _set_widget_value(widgets["custom_stream"], bool(settings["stream"]))
            _set_widget_value(widgets["custom_endpoint"], "/chat/completions")
            _set_widget_value(
                widgets["custom_body_json"], json.dumps(migrated, ensure_ascii=False, indent=2)
            )
            ui.notify("已迁移普通模式配置到自定义请求体", type="positive")

        def _sync_request_mode_visibility(*_: Any) -> None:
            custom_enabled = widgets["request_mode"].value == "custom"
            widgets["model"].set_visibility(not custom_enabled)
            model_override_hint.set_visibility(custom_enabled)
            # H2 fix: in custom mode, hide the standard controls so it's visually
            # obvious that the GUI is no longer driving model / prompts / stream
            # for the actual outgoing request. (Even if some standard widgets are
            # still editable, the runner now ignores them via the empty prompts
            # list in _build_runtime_payload.)
            request_standard_controls.set_visibility(not custom_enabled)
            request_custom_controls.set_visibility(custom_enabled)
            request_mode_hint.set_text(
                "当前为全自定义模式：将直接发送自定义 JSON，采样参数仅用于迁移参考。"
                if custom_enabled
                else "当前为普通模式：将基于基础配置拼装请求体。"
            )
            _refresh_request_preview()

        def _sync_chart_refresh_inputs(*_: Any) -> None:
            by_requests = widgets["chart_refresh_mode"].value == "requests"
            widgets["chart_refresh_interval_s"].set_visibility(not by_requests)
            widgets["chart_refresh_every_n"].set_visibility(by_requests)

        mode_tracker = {"value": widgets["request_mode"].value}

        async def _handle_request_mode_change(e: events.ValueChangeEventArguments) -> None:
            previous = mode_tracker["value"]
            mode_tracker["value"] = str(e.value)
            if previous == "standard" and e.value == "custom":
                await _maybe_migrate_standard_to_custom()
            _update_preview()
            _sync_request_mode_visibility()

        widgets["base_url"].on_value_change(_update_preview)
        widgets["custom_endpoint"].on_value_change(_update_preview)
        widgets["request_mode"].on_value_change(_handle_request_mode_change)
        widgets["model"].on_value_change(_refresh_request_preview)
        widgets["max_tokens"].on_value_change(_refresh_request_preview)
        widgets["temperature"].on_value_change(_refresh_request_preview)
        widgets["stream"].on_value_change(_refresh_request_preview)
        widgets["append_body_json"].on_value_change(_refresh_request_preview)
        widgets["custom_body_json"].on_value_change(_refresh_request_preview)
        widgets["custom_stream"].on_value_change(_refresh_request_preview)
        widgets["prompt_strategy"].on_value_change(
            lambda _: (
                _render_prompts(),
                _refresh_request_preview(),
            )
        )
        widgets["run_total"].on_value_change(lambda _: _refresh_token_estimation())
        widgets["run_duration"].on_value_change(lambda _: _refresh_token_estimation())
        widgets["rps_target"].on_value_change(lambda _: _refresh_token_estimation())
        widgets["rps_duration"].on_value_change(lambda _: _refresh_token_estimation())
        widgets["chart_refresh_mode"].on_value_change(_sync_chart_refresh_inputs)
        widgets["refresh_request_ui"] = lambda: (_sync_request_mode_visibility(), _update_preview())
        _sync_request_mode_visibility()
        _sync_chart_refresh_inputs()
        _update_preview()

    return panels


def _collect_common_settings(widgets: dict[str, Any]) -> dict[str, Any]:
    prompt_items = widgets["get_prompts"]() if callable(widgets.get("get_prompts")) else []
    prompt_weights = (
        widgets["get_prompt_weights"]() if callable(widgets.get("get_prompt_weights")) else []
    )
    request_mode = widgets["request_mode"].value if "request_mode" in widgets else "standard"
    return {
        "base_url": widgets["base_url"].value,
        "api_key": widgets["api_key"].value,
        "model": widgets["model"].value,
        "concurrency": int(widgets["concurrency"].value or 5),
        "max_tokens": int(widgets["max_tokens"].value or 128),
        "temperature": float(widgets["temperature"].value or 0.2),
        "timeout_s": float(widgets["timeout_s"].value or 120),
        "warmup": int(widgets["warmup"].value or 0),
        "retry_on_429": int(widgets["retry_on_429"].value or 3),
        "retry_on_network": int(widgets["retry_on_network"].value or 1),
        "retry_on_5xx": int(widgets["retry_on_5xx"].value or 1),
        "base_backoff_s": float(widgets["base_backoff_s"].value or 1.0),
        "stream": widgets["stream"].value,
        "http2": widgets["http2"].value,
        "proxy_mode": _PROXY_LABEL_TO_VALUE.get(widgets["proxy_mode_label"].value, "direct"),
        "proxy_url": (widgets["proxy_url_input"].value or "").strip() or None,
        "custom_enabled": request_mode == "custom",
        "custom_endpoint": widgets["custom_endpoint"].value,
        "custom_stream": widgets["custom_stream"].value,
        "custom_body_json": widgets["custom_body_json"].value,
        "append_body_json": widgets["append_body_json"].value,
        # T3-4: store prompts as a multi-line string for human readability in
        # the YAML file. The internal list form is kept under prompts_list
        # so existing consumers / tests still work.
        "prompts": "\n".join(prompt_items),
        "prompts_list": prompt_items,
        "prompt_weights": prompt_weights,
        "prompt_strategy": widgets["prompt_strategy"].value
        if "prompt_strategy" in widgets
        else "sequential",
        "chart_refresh_mode": widgets["chart_refresh_mode"].value
        if "chart_refresh_mode" in widgets
        else "interval",
        "chart_refresh_interval_s": float(widgets["chart_refresh_interval_s"].value or 0.3)
        if "chart_refresh_interval_s" in widgets
        else 0.3,
        "chart_refresh_every_n": int(widgets["chart_refresh_every_n"].value or 5)
        if "chart_refresh_every_n" in widgets
        else 5,
        "prompts_raw": "\n".join(prompt_items),
    }


def _collect_config_snapshot(widgets: dict[str, Any]) -> dict[str, Any]:
    common = _collect_common_settings(widgets)
    return {
        "base_url": common["base_url"],
        "api_key": common["api_key"],
        "model": common["model"],
        "concurrency": common["concurrency"],
        "max_tokens": common["max_tokens"],
        "temperature": common["temperature"],
        "stream": common["stream"],
        "timeout_s": common["timeout_s"],
        "http2": common["http2"],
        "warmup": common["warmup"],
        "retry_on_429": common["retry_on_429"],
        "retry_on_network": common["retry_on_network"],
        "retry_on_5xx": common["retry_on_5xx"],
        "base_backoff_s": common["base_backoff_s"],
        "proxy_mode": common["proxy_mode"],
        "proxy_url": common["proxy_url"],
        "custom_enabled": common["custom_enabled"],
        "request_mode": "custom" if common["custom_enabled"] else "standard",
        "custom_endpoint": common["custom_endpoint"],
        "custom_stream": common["custom_stream"],
        "custom_body_json": common["custom_body_json"],
        "append_body_json": common["append_body_json"],
        "prompts": list(common["prompts_list"]),
        "prompts_text": common["prompts"],  # multi-line string (T3-4: YAML readability)
        "prompt_weights": list(common["prompt_weights"]),
        "prompt_strategy": common["prompt_strategy"],
        "chart_refresh_mode": common.get("chart_refresh_mode", "interval"),
        "chart_refresh_interval_s": common.get("chart_refresh_interval_s", 0.3),
        "chart_refresh_every_n": common.get("chart_refresh_every_n", 5),
        "run": {
            "total": int(widgets["run_total"].value or 20),
            "duration_s": int(widgets["run_duration"].value or 0),
        },
        "rps": {
            "target": float(widgets["rps_target"].value or 5.0),
            "duration_s": int(widgets["rps_duration"].value or 30),
        },
        "sweep": {
            "levels": str(widgets["sweep_levels"].value or "1,2,4,8,16"),
            "per": int(widgets["sweep_per"].value or 40),
        },
    }


def _set_widget_value(widget: Any, value: Any) -> None:
    if hasattr(widget, "set_value"):
        widget.set_value(value)
    else:
        widget.value = value


def _apply_config_snapshot(widgets: dict[str, Any], snapshot: dict[str, Any]) -> None:
    _set_widget_value(widgets["base_url"], snapshot.get("base_url", _DEFAULT_BASE_URL))
    _set_widget_value(widgets["api_key"], snapshot.get("api_key", ""))
    _set_widget_value(widgets["model"], snapshot.get("model", _DEFAULT_MODEL))
    _set_widget_value(widgets["concurrency"], snapshot.get("concurrency", 5))
    _set_widget_value(widgets["max_tokens"], snapshot.get("max_tokens", 128))
    _set_widget_value(widgets["temperature"], snapshot.get("temperature", 0.2))
    _set_widget_value(widgets["stream"], snapshot.get("stream", False))
    _set_widget_value(widgets["timeout_s"], snapshot.get("timeout_s", 120))
    _set_widget_value(widgets["http2"], snapshot.get("http2", False))
    _set_widget_value(widgets["warmup"], snapshot.get("warmup", 0))
    _set_widget_value(widgets["retry_on_429"], snapshot.get("retry_on_429", 3))
    _set_widget_value(widgets["retry_on_network"], snapshot.get("retry_on_network", 1))
    _set_widget_value(widgets["retry_on_5xx"], snapshot.get("retry_on_5xx", 1))
    _set_widget_value(widgets["base_backoff_s"], snapshot.get("base_backoff_s", 1.0))
    proxy_value = snapshot.get("proxy_mode", "direct")
    proxy_label = next(
        (label for label, value in _PROXY_LABEL_TO_VALUE.items() if value == proxy_value), "直连"
    )
    _set_widget_value(widgets["proxy_mode_label"], proxy_label)
    _set_widget_value(
        widgets["proxy_url_input"], snapshot.get("proxy_url", "http://127.0.0.1:7890") or ""
    )
    _set_widget_value(
        widgets["request_mode"],
        snapshot.get(
            "request_mode", "custom" if snapshot.get("custom_enabled", False) else "standard"
        ),
    )
    _set_widget_value(
        widgets["custom_endpoint"], snapshot.get("custom_endpoint", "/chat/completions")
    )
    _set_widget_value(widgets["custom_stream"], snapshot.get("custom_stream", False))
    _set_widget_value(
        widgets["custom_body_json"], snapshot.get("custom_body_json", _DEFAULT_CUSTOM_BODY)
    )
    _set_widget_value(widgets["append_body_json"], snapshot.get("append_body_json", ""))
    _set_widget_value(widgets["prompt_strategy"], snapshot.get("prompt_strategy", "sequential"))
    _set_widget_value(widgets["chart_refresh_mode"], snapshot.get("chart_refresh_mode", "interval"))
    _set_widget_value(
        widgets["chart_refresh_interval_s"], snapshot.get("chart_refresh_interval_s", 0.3)
    )
    _set_widget_value(widgets["chart_refresh_every_n"], snapshot.get("chart_refresh_every_n", 5))
    if callable(widgets.get("set_prompts")):
        widgets["set_prompts"](
            list(snapshot.get("prompts") or []),
            list(snapshot.get("prompt_weights") or []),
        )
    run_cfg = snapshot.get("run") or {}
    _set_widget_value(widgets["run_total"], run_cfg.get("total", 20))
    _set_widget_value(widgets["run_duration"], run_cfg.get("duration_s", 0))
    rps_cfg = snapshot.get("rps") or {}
    _set_widget_value(widgets["rps_target"], rps_cfg.get("target", 5.0))
    _set_widget_value(widgets["rps_duration"], rps_cfg.get("duration_s", 30))
    sweep_cfg = snapshot.get("sweep") or {}
    _set_widget_value(widgets["sweep_levels"], sweep_cfg.get("levels", "1,2,4,8,16"))
    _set_widget_value(widgets["sweep_per"], sweep_cfg.get("per", 40))
    refresh_request_ui = widgets.get("refresh_request_ui")
    if callable(refresh_request_ui):
        refresh_request_ui()


def _config_is_dirty(config_state: _ConfigState, widgets: dict[str, Any]) -> bool:
    return config_state.last_saved_snapshot != _snapshot_key(_collect_config_snapshot(widgets))


def _diff_snapshots(
    old: dict[str, Any], new: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    """Recursively diff two config dicts. Returns (dotted_key, old, new) for
    every changed leaf. The pure helper is split out so it's trivially
    testable; the GUI-facing wrapper around it loads the saved snapshot
    and calls into this.
    """
    diffs: list[tuple[str, Any, Any]] = []

    def _walk(prefix: str, o: Any, n: Any) -> None:
        if isinstance(o, dict) and isinstance(n, dict):
            for key in set(o) | set(n):
                _walk(f"{prefix}.{key}" if prefix else key, o.get(key), n.get(key))
        elif o != n:
            diffs.append((prefix, o, n))

    _walk("", old, new)
    return diffs


def _compute_config_diff(
    config_state: _ConfigState, widgets: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    """GUI wrapper around :func:`_diff_snapshots`. Loads the saved
    snapshot and compares it against a fresh collection from the form."""
    if config_state.last_saved_snapshot is None:
        return []
    try:
        old = json.loads(config_state.last_saved_snapshot)
    except (json.JSONDecodeError, TypeError):
        return []
    new = _collect_config_snapshot(widgets)
    return _diff_snapshots(old, new)


def _refresh_config_status(config_state: _ConfigState, widgets: dict[str, Any]) -> None:
    dirty = _config_is_dirty(config_state, widgets)
    current = config_state.current_name or "未命名"
    suffix = "未保存改动" if dirty else "已保存"
    widgets["config_status_label"].set_text(f"当前配置：{current}｜{suffix}")
    # T-diff: if a dirty badge is registered, update it.
    badge = widgets.get("config_diff_badge")
    if badge is None:
        return
    if not dirty:
        badge.set_text("")
        badge.set_visibility(False)
        return
    # UX#3: also show the badge on the very first dirty tick (no prior
    # save). Show a "未保存" label so the user knows the state.
    if config_state.last_saved_snapshot is None:
        badge.set_text(" 未保存 ")
        badge.set_visibility(True)
        badge.classes(
            remove="bg-slate-100 bg-slate-200 text-slate-700 text-slate-800"
        )
        badge.classes(add="bg-slate-100 text-slate-700")
        return
    diffs = _compute_config_diff(config_state, widgets)
    n = len(diffs)
    badge.set_text(f" {n} 个字段改动 ")
    badge.set_visibility(True)
    # Subtle shade shift: 1-2 fields lighter slate, 3+ fields darker slate
    # (was amber / orange — kept the "more = more visible" cue, just gray).
    badge.classes(remove="bg-slate-100 bg-slate-200 text-slate-700 text-slate-800")
    if n >= 3:
        badge.classes(add="bg-slate-200 text-slate-800")
    else:
        badge.classes(add="bg-slate-100 text-slate-700")


async def _prompt_config_name(initial_name: str | None = None) -> str | None:
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("保存配置").classes("text-base font-semibold")
        name_input = ui.input("配置文件名", value=initial_name or "default").classes("w-full")
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("保存", on_click=lambda: dialog.submit(name_input.value)).props(
                "color=dark"
            )
    dialog.open()
    result = await dialog
    normalized = _normalize_config_name(result or "")
    if result is not None and not normalized:
        ui.notify("配置文件名不能为空", type="warning")
    return normalized


async def _pick_config_name(title: str, action_label: str) -> str | None:
    names = _list_config_names()
    if not names:
        ui.notify("当前还没有配置文件", type="warning")
        return None
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label(title).classes("text-base font-semibold")
        select = ui.select(options=names, value=names[0], label="配置文件").classes("w-full")
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button(action_label, on_click=lambda: dialog.submit(select.value)).props(
                "color=dark"
            )
    dialog.open()
    result = await dialog
    return str(result) if result else None


async def _save_config_file(
    config_state: _ConfigState, widgets: dict[str, Any], *, save_as: bool
) -> bool:
    current_name = (
        config_state.current_name.removesuffix(".yaml") if config_state.current_name else None
    )
    target_name = config_state.current_name if (config_state.current_name and not save_as) else None
    if target_name is None:
        target_name = await _prompt_config_name(current_name)
        if not target_name:
            return False
    snapshot = _collect_config_snapshot(widgets)
    # Sec#1: strip API key from the snapshot before it hits disk.
    safe_snapshot = sanitize_snapshot_for_disk(snapshot)
    if safe_snapshot.get("api_key") == "__from_ui__" and snapshot.get("api_key"):
        ui.notify(
            "⚠️ API Key 来自界面输入，未写入 YAML（防止明文落盘）",
            type="warning",
        )
    _config_path(target_name).write_text(
        yaml.safe_dump(safe_snapshot, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # T2-1: mirror every save into last.yaml so the next launch auto-loads.
    # Failure is non-fatal — the named save is the source of truth.
    from contextlib import suppress

    with suppress(OSError):
        (config_dir() / "last.yaml").write_text(
            yaml.safe_dump(safe_snapshot, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    config_state.current_name = target_name
    config_state.last_saved_snapshot = _snapshot_key(safe_snapshot)
    _refresh_config_status(config_state, widgets)
    ui.notify(f"配置已保存：{target_name}", type="positive")
    return True


async def _load_config_file(config_state: _ConfigState, widgets: dict[str, Any]) -> bool:
    target_name = await _pick_config_name("加载配置", "加载")
    if not target_name:
        return False
    path = _config_path(target_name)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        ui.notify(f"配置文件不存在：{path}", type="negative")
        return False
    except OSError as exc:
        ui.notify(f"读取配置失败：{exc}", type="negative")
        return False
    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        ui.notify(f"YAML 解析失败：{exc}", type="negative")
        return False
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        ui.notify("配置文件格式错误：根节点必须是对象", type="negative")
        return False
    _apply_config_snapshot(widgets, payload)
    config_state.current_name = target_name
    config_state.last_saved_snapshot = _snapshot_key(_collect_config_snapshot(widgets))
    _refresh_config_status(config_state, widgets)
    ui.notify(f"已加载配置：{target_name}", type="positive")
    return True


async def _delete_config_file(config_state: _ConfigState, widgets: dict[str, Any]) -> bool:
    target_name = await _pick_config_name("删除配置", "删除")
    if not target_name:
        return False
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label(f"确认删除配置 `{target_name}` 吗？").classes("text-base")
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button("取消", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("删除", on_click=lambda: dialog.submit(True)).props("color=red")
    dialog.open()
    confirmed = await dialog
    if not confirmed:
        return False
    _config_path(target_name).unlink(missing_ok=True)
    if config_state.current_name == target_name:
        config_state.current_name = None
        config_state.last_saved_snapshot = None
    _refresh_config_status(config_state, widgets)
    ui.notify(f"已删除配置：{target_name}", type="positive")
    return True


async def _confirm_save_before_run(config_state: _ConfigState, widgets: dict[str, Any]) -> bool:
    if not _config_is_dirty(config_state, widgets):
        return True
    with ui.dialog() as dialog, ui.card().classes("w-[28rem]"):
        ui.label("运行前发现未保存改动").classes("text-base font-semibold")
        ui.label("是否先保存为配置文件？").classes("text-sm text-slate-500")
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button("取消运行", on_click=lambda: dialog.submit("cancel")).props("flat")
            ui.button("不保存直接运行", on_click=lambda: dialog.submit("skip")).props("outline")
            ui.button("保存后运行", on_click=lambda: dialog.submit("save")).props("color=dark")
    dialog.open()
    decision = await dialog
    if decision == "cancel":
        return False
    if decision == "skip":
        return True
    return await _save_config_file(config_state, widgets, save_as=False)


def _build_mode_controls(
    app_state: _AppState, widgets: dict[str, Any], config_state: _ConfigState
) -> None:
    with (
        ui.card().classes("w-full border border-slate-200 shadow-sm mb-4"),
        ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"),
    ):
        with ui.column().classes("gap-1"):
            ui.label("操作控制台").classes("text-sm font-semibold text-slate-700")
            with ui.row().classes("items-center gap-2"):
                widgets["config_status_label"] = ui.label("当前未保存到配置文件").classes(
                    "text-xs text-slate-500"
                )
                # T-diff: badge that lights up when the user has unsaved
                # changes. Click opens a detail dialog with the per-field
                # diff. Hidden by default; updated by _refresh_config_status.
                # Note: ui.badge() has no on_click; use a small button styled
                # to look like a badge so the click-to-show-diff handler works.
                widgets["config_diff_badge"] = (
                    ui.button("", icon="difference")
                    .props("flat dense color=dark outline")
                    .classes("text-xs px-2 py-0 min-w-0")
                )
                _attach_tooltip(widgets["config_diff_badge"], _TOOLTIPS["config_diff_badge"])
                widgets["config_diff_badge"].set_visibility(False)

                def _show_diff() -> None:
                    diffs = _compute_config_diff(config_state, widgets)
                    if not diffs:
                        return
                    with ui.dialog() as dialog, ui.card().classes(
                        "w-[40rem] max-w-full"
                    ):
                        ui.label(f"已改动 {len(diffs)} 个字段").classes(
                            "text-base font-semibold"
                        )
                        diff_text = "\n".join(
                            f"  {key}\n"
                            f"    旧: {json.dumps(old, ensure_ascii=False, default=str)[:200]}\n"
                            f"    新: {json.dumps(new, ensure_ascii=False, default=str)[:200]}"
                            for key, old, new in diffs
                        )
                        ui.code(diff_text, language="diff").classes("text-xs")
                        with ui.row().classes("justify-end w-full mt-2"):
                            ui.button(
                                "关闭", on_click=lambda: dialog.submit(None)
                            ).props("flat")
                    # Fire-and-forget: don't await. The dialog's close
                    # button handles teardown.
                    dialog.open()

                widgets["config_diff_badge"].on_click(_show_diff)

        with ui.row().classes("gap-2 flex-wrap"):
            widgets["config_save_btn"] = ui.button("保存", icon="save").props("color=dark")
            widgets["config_save_as_btn"] = ui.button("另存为", icon="copy_all").props("outline")
            widgets["config_load_btn"] = ui.button("加载", icon="folder_open").props("outline")
            widgets["config_delete_btn"] = ui.button("删除", icon="delete").props(
                "outline color=red"
            )

    with ui.tabs().classes(
        "w-full rounded-t-xl bg-slate-50 border border-slate-200 border-b-0"
    ) as mode_tabs:
        tab_run = ui.tab("单次压测", icon="play_arrow")
        tab_rps = ui.tab("固定 RPS", icon="speed")
        tab_sweep = ui.tab("并发扫描", icon="bar_chart")
        tab_loadcurve = ui.tab("负载曲线", icon="timeline")

    with ui.tab_panels(mode_tabs, value=tab_run).classes(
        "w-full border border-slate-200 border-t-0 rounded-b-xl bg-white shadow-sm overflow-hidden"
    ):
        with ui.tab_panel(tab_run).classes("p-4"):
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                widgets["run_total"] = ui.number("总请求数", value=20, min=1, step=1).classes(
                    "min-w-40 flex-1"
                )
                _attach_tooltip(widgets["run_total"], _TOOLTIPS["run_total"])
                widgets["run_duration"] = ui.number(
                    "时长（秒，0=按总数）", value=0, min=0, step=1
                ).classes("min-w-56 flex-1")
                _attach_tooltip(widgets["run_duration"], _TOOLTIPS["run_duration"])
            with ui.row().classes("mt-3 gap-3 w-full flex-wrap"):
                start_btn = (
                    ui.button("开始单次压测", icon="play_arrow")
                    .props("color=dark")
                    .classes("min-w-36")
                )
                widgets["run_start_btn"] = start_btn
                dryrun_btn = (
                    ui.button("试一次", icon="science")
                    .props("outline color=dark")
                    .classes("min-w-24")
                )
                stop_btn = (
                    ui.button("停止", icon="stop").props("outline color=red").classes("min-w-28")
                )
                widgets["run_stop_btn"] = stop_btn

            async def _dryrun_run() -> None:
                """Fire a single probe request and show its result inline, so
                the user can validate config without spending many tokens."""
                dryrun_btn.disable()
                try:
                    try:
                        settings = _collect_common_settings(widgets)
                        runtime = _build_runtime_payload(settings)
                    except ValueError as exc:
                        ui.notify(f"配置不合法：{exc}", type="negative")
                        return
                    resolved_key = _resolve_api_key(settings["api_key"])
                    if not resolved_key:
                        ui.notify("API Key 未设置", type="negative")
                        return
                    async with httpx.AsyncClient(
                        http2=settings["http2"],
                        proxy=settings.get("proxy_url") if settings["proxy_mode"] == "custom" else None,
                        trust_env=settings["proxy_mode"] == "system",
                        timeout=settings["timeout_s"],
                    ) as client:
                        result = await one_chat_request(
                            client,
                            runtime["endpoint"],
                            _headers(resolved_key),
                            runtime["body_template"],
                            stream=runtime["stream_flag"],
                            timeout_s=settings["timeout_s"],
                        )
                    if result.ok:
                        preview = (result.response_text or "").splitlines()[0][:120]
                        ui.notify(
                            f"✅ 试跑成功｜{result.latency_ms:.0f} ms｜"
                            f"tokens: p={result.prompt_tokens or 0} c={result.completion_tokens or 0}\n"
                            f"回应预览：{preview}",
                            type="positive",
                            timeout=8.0,
                        )
                    else:
                        ui.notify(
                            f"❌ 试跑失败｜status={result.status_code}｜kind={result.error_kind.value}\n"
                            f"原因：{(result.error or '').splitlines()[0][:200]}",
                            type="negative",
                            timeout=10.0,
                        )
                except Exception as exc:
                    ui.notify(f"试跑异常：{type(exc).__name__}: {exc}", type="negative")
                finally:
                    dryrun_btn.enable()

            async def _start_run() -> None:
                if not await _confirm_save_before_run(config_state, widgets):
                    return
                # Secret scan: if the API key looks like a placeholder,
                # block and ask the user to confirm — saves them from a
                # silent 401 and a wasted run.
                key = _resolve_api_key(widgets["api_key"].value or "")
                if key and _looks_like_weak_key(key):
                    with ui.dialog() as weak_dialog, ui.card().classes("w-[28rem]"):
                        ui.label("⚠️ API Key 看起来是占位符").classes(
                            "text-base font-semibold"
                        )
                        ui.label(
                            f"检测到：'{key[:20]}...'。\n"
                            "这通常是复制粘贴时漏改的占位符。\n"
                            "继续运行会得到 401。"
                        ).classes("text-xs text-slate-500")
                        with ui.row().classes("justify-end w-full gap-2 mt-2"):
                            ui.button(
                                "取消运行",
                                on_click=lambda: weak_dialog.submit(False),
                            ).props("flat")
                            ui.button(
                                "仍然继续",
                                on_click=lambda: weak_dialog.submit(True),
                            ).props("color=dark")
                    weak_dialog.open()
                    if not await weak_dialog:
                        return
                # T1-1 + T1-4: immediate visual feedback so the user knows
                # their click registered. The 0.25s timer has a window where
                # double-clicks could re-enter; disable right away.
                start_btn.disable()
                client_id = ui.context.client.id
                settings = _collect_common_settings(widgets) | {
                    "run_total": widgets["run_total"].value,
                    "run_duration": widgets["run_duration"].value,
                }
                _safe_create_bench_task(
                    _execute_run(
                        app_state, settings, "run", lambda m, t: _notify_client(client_id, m, t)
                    ),
                    on_error=lambda exc: _notify_client(client_id, f"压测失败：{exc}", "negative"),
                )
                ui.notify("压测已启动，请到 Monitor 窗口查看进度", type="ongoing", position="top")

            def _stop_run() -> None:
                app_state.run_states["run"].stop_event.set()
                app_state.set_status("停止中...", "orange")

            start_btn.on_click(_start_run)
            dryrun_btn.on_click(_dryrun_run)
            stop_btn.on_click(_stop_run)
            stop_btn.disable()

            def _refresh_buttons() -> None:
                if app_state.is_busy():
                    start_btn.disable()
                else:
                    start_btn.enable()
                if app_state.run_states["run"].busy:
                    stop_btn.enable()
                else:
                    stop_btn.disable()

            ui.timer(0.25, _refresh_buttons)

        with ui.tab_panel(tab_rps).classes("p-4"):
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                widgets["rps_target"] = ui.number(
                    "目标 RPS", value=5.0, min=0.1, step=0.5, format="%.1f"
                ).classes("min-w-40 flex-1")
                _attach_tooltip(widgets["rps_target"], _TOOLTIPS["rps_target"])
                widgets["rps_duration"] = ui.number(
                    "持续时长（秒）", value=30, min=1, step=1
                ).classes("min-w-40 flex-1")
                _attach_tooltip(widgets["rps_duration"], _TOOLTIPS["rps_duration"])
            # Theoretical RPS ceiling based on concurrency and timeout.
            rps_hint = ui.label("理论上限：— req/s").classes(
                "text-xs text-slate-500 mt-1"
            )

            def _refresh_rps_hint() -> None:
                # tab_rps is built before _build_config_form in _build_control_page,
                # so concurrency / timeout_s may not be registered yet on the
                # initial render. Be defensive: bail out and rely on the
                # on_value_change hooks (registered below) to refresh the hint
                # once the form is built.
                concurrency_w = widgets.get("concurrency")
                timeout_w = widgets.get("timeout_s")
                if concurrency_w is None or timeout_w is None:
                    return
                concurrency = _safe_int(concurrency_w.value, 5, 1)
                timeout_s = _safe_float(timeout_w.value, 120.0, 1.0)
                # If average latency is at most timeout_s, max sustainable RPS
                # = concurrency / timeout_s. This is the worst-case ceiling.
                ceiling = concurrency / max(0.1, timeout_s)
                rps_hint.set_text(
                    f"理论上限 ≈ {ceiling:.1f} req/s（并发 {concurrency} ÷ 超时 {timeout_s:.0f}s）"
                )

            _refresh_rps_hint()
            concurrency_w = widgets.get("concurrency")
            if concurrency_w is not None:
                concurrency_w.on_value_change(lambda _: _refresh_rps_hint())
            timeout_w = widgets.get("timeout_s")
            if timeout_w is not None:
                timeout_w.on_value_change(lambda _: _refresh_rps_hint())
            with ui.row().classes("mt-3 gap-3 w-full flex-wrap"):
                start_btn = (
                    ui.button("开始固定 RPS", icon="play_arrow")
                    .props("color=dark")
                    .classes("min-w-36")
                )
                widgets["rps_start_btn"] = start_btn
                stop_btn = (
                    ui.button("停止", icon="stop").props("outline color=red").classes("min-w-28")
                )
                widgets["rps_stop_btn"] = stop_btn

            async def _start_rps() -> None:
                if not await _confirm_save_before_run(config_state, widgets):
                    return
                start_btn.disable()
                client_id = ui.context.client.id
                settings = _collect_common_settings(widgets) | {
                    "rps_target": widgets["rps_target"].value,
                    "rps_duration": widgets["rps_duration"].value,
                }
                _safe_create_bench_task(
                    _execute_run(
                        app_state, settings, "rps", lambda m, t: _notify_client(client_id, m, t)
                    ),
                    on_error=lambda exc: _notify_client(client_id, f"压测失败：{exc}", "negative"),
                )
                ui.notify("固定 RPS 压测已启动", type="ongoing", position="top")

            def _stop_rps() -> None:
                app_state.run_states["rps"].stop_event.set()
                app_state.set_status("停止中...", "orange")

            start_btn.on_click(_start_rps)
            stop_btn.on_click(_stop_rps)
            stop_btn.disable()

            def _refresh_buttons() -> None:
                if app_state.is_busy():
                    start_btn.disable()
                else:
                    start_btn.enable()
                if app_state.run_states["rps"].busy:
                    stop_btn.enable()
                else:
                    stop_btn.disable()

            ui.timer(0.25, _refresh_buttons)

        with ui.tab_panel(tab_sweep).classes("p-4"):
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                widgets["sweep_levels"] = ui.input(
                    "并发级别（逗号分隔）", value="1,2,4,8,16"
                ).classes("min-w-56 flex-[2]")
                _attach_tooltip(widgets["sweep_levels"], _TOOLTIPS["sweep_levels"])
                widgets["sweep_per"] = ui.number("每档请求数", value=40, min=1, step=1).classes(
                    "min-w-40 flex-1"
                )
                _attach_tooltip(widgets["sweep_per"], _TOOLTIPS["sweep_per"])
            with ui.row().classes("mt-1 gap-1 flex-wrap items-center"):
                ui.label("推荐档位：").classes("text-xs text-slate-500")
                for preset in ("1,2,4,8", "1,5,10,20", "1,2,4,8,16,32,64", "1,10,100"):

                    def _apply_preset(p: str = preset) -> None:
                        widgets["sweep_levels"].value = p
                        ui.notify(f"已填入：{p}", type="info")

                    ui.button(preset, on_click=_apply_preset).props(
                        "outline dense size=sm"
                    )
            with ui.row().classes("mt-3 gap-3 w-full flex-wrap"):
                start_btn = (
                    ui.button("开始并发扫描", icon="play_arrow")
                    .props("color=dark")
                    .classes("min-w-36")
                )
                widgets["sweep_start_btn"] = start_btn
                probe_btn = (
                    ui.button("探测建议并发", icon="travel_explore")
                    .props("outline color=dark")
                    .classes("min-w-40")
                )
                stop_btn = (
                    ui.button("停止", icon="stop").props("outline color=red").classes("min-w-28")
                )
                widgets["sweep_stop_btn"] = stop_btn

            async def _start_sweep(*, probe_mode: bool) -> None:
                if not await _confirm_save_before_run(config_state, widgets):
                    return
                start_btn.disable()
                probe_btn.disable()
                client_id = ui.context.client.id
                settings = _collect_common_settings(widgets) | {
                    "sweep_levels": widgets["sweep_levels"].value,
                    "sweep_per": widgets["sweep_per"].value,
                }
                _safe_create_bench_task(
                    _execute_sweep(
                        app_state,
                        settings,
                        lambda m, t: _notify_client(client_id, m, t),
                        probe_mode=probe_mode,
                    ),
                    on_error=lambda exc: _notify_client(client_id, f"扫描失败：{exc}", "negative"),
                )
                ui.notify(
                    "扫描已启动，每档完成会即时更新图表"
                    if not probe_mode
                    else "探测模式已启动",
                    type="ongoing",
                    position="top",
                )

            def _stop_sweep() -> None:
                app_state.sweep_state.stop_event.set()
                app_state.set_status("停止中...", "orange")

            async def _start_sweep_scan() -> None:
                await _start_sweep(probe_mode=False)

            async def _start_sweep_probe() -> None:
                await _start_sweep(probe_mode=True)

            start_btn.on_click(_start_sweep_scan)
            probe_btn.on_click(_start_sweep_probe)
            stop_btn.on_click(_stop_sweep)
            stop_btn.disable()

            def _refresh_buttons() -> None:
                if app_state.is_busy():
                    start_btn.disable()
                    probe_btn.disable()
                else:
                    start_btn.enable()
                    probe_btn.enable()
                if app_state.sweep_state.busy:
                    stop_btn.enable()
                else:
                    stop_btn.disable()

            ui.timer(0.25, _refresh_buttons)

        with ui.tab_panel(tab_loadcurve).classes("p-4"):
            # Load-curve editor: define a piecewise-constant RPS profile
            # (e.g. 5→10→20→10 over 60s) and run it. Each line is one
            # phase: "<duration_s>:<rps>".
            ui.label("负载曲线（多阶段 RPS）").classes("text-base font-semibold")
            ui.label(
                "每行一个阶段，格式：<持续秒数>:<目标 RPS>。\n"
                "示例：\n"
                "  30:5   # 30 秒 5 req/s\n"
                "  30:20  # 30 秒 20 req/s\n"
                "  30:50  # 30 秒 50 req/s\n"
                "总时长 = 各阶段时长之和。"
            ).classes("text-xs text-slate-500")
            widgets["loadcurve_profile"] = ui.textarea(
                label="负载曲线",
                value="30:5\n30:20\n30:50",
            ).classes("w-full font-mono text-sm").props("rows=6")
            _attach_tooltip(
                widgets["loadcurve_profile"],
                "每行 <秒数>:<rps>。支持 # 开头注释行。",
            )

            loadcurve_summary = ui.label("总时长 0s｜最高 RPS 0").classes(
                "text-sm text-slate-600 mt-2"
            )

            # Step chart preview: renders the piecewise-constant RPS profile
            # as a staircase so the user can see what the engine will run.
            loadcurve_chart = ui.echart(
                {
                    "title": {"text": "负载曲线预览", "left": "center", "textStyle": {"fontSize": 13}},
                    "xAxis": {
                        "type": "value",
                        "name": "时间 (s)",
                        "nameLocation": "middle",
                        "nameGap": 22,
                    },
                    "yAxis": {
                        "type": "value",
                        "name": "RPS",
                        "nameLocation": "middle",
                        "nameGap": 35,
                    },
                    "tooltip": {"trigger": "axis", "formatter": "第 {b}s: {c} req/s"},
                    "series": [
                        {
                            "name": "RPS",
                            "type": "line",
                            "step": "end",
                            "data": [],
                            "areaStyle": {"opacity": 0.2},
                            "lineStyle": {"width": 2, "color": "#475569"},
                            "itemStyle": {"color": "#475569"},
                        }
                    ],
                    "grid": {"left": 60, "right": 20, "top": 40, "bottom": 50},
                }
            ).classes("w-full h-48 mt-2")
            # UX#10 polish: ECharts canvas swallows mousemove, so the
            # NiceGUI tooltip bound to the chart never fires. Replace
            # with a permanent small caption below the chart — visible
            # at all times, which is also better for users studying
            # the curve (vs. having to hover for context).
            ui.label(_TOOLTIPS["loadcurve_chart"]).classes(
                "text-xs text-slate-500 mt-1 italic"
            )

            def _refresh_loadcurve_summary() -> None:
                parsed = _parse_loadcurve_profile(widgets["loadcurve_profile"].value)
                if not parsed:
                    # UX#7: when every line is malformed (or empty),
                    # make the cause obvious instead of silently showing
                    # "总时长 0s".
                    loadcurve_summary.set_text(t("loadcurve_malformed"))
                    loadcurve_summary.classes(
                        remove="text-slate-600 text-slate-700 text-emerald-700"
                    )
                    loadcurve_summary.classes(add="text-slate-700")
                    step_data: list[list[float]] = []
                    loadcurve_chart.options["series"][0]["data"] = step_data
                    loadcurve_chart.update()
                    return
                # Valid profile: standard slate summary line.
                total_s = sum(p[0] for p in parsed)
                max_rps = max((p[1] for p in parsed), default=0)
                loadcurve_summary.set_text(
                    t("loadcurve_total", total=total_s, n=len(parsed), max_rps=max_rps)
                )
                loadcurve_summary.classes(
                    remove="text-slate-600 text-slate-700 text-emerald-700"
                )
                loadcurve_summary.classes(add="text-slate-600")
                # Build step-chart points: (0, 0), (d0, r0), (d0+d1, r0),
                # (d0+d1, r1), ... so the staircase shows the piecewise-
                # constant profile.
                step_data: list[list[float]] = [[0.0, 0.0]]
                cum = 0.0
                for dur, rps in parsed:
                    cum += dur
                    step_data.append([cum - dur, rps])
                    step_data.append([cum, rps])
                loadcurve_chart.options["series"][0]["data"] = step_data
                loadcurve_chart.update()

            # Perf#2: debounce the chart re-render so rapid keystrokes
            # don't fire an ECharts update per char. 150ms idle is below
            # the human-perceptible threshold but batches bursts.
            _loadcurve_refresh_pending: dict[str, Any] = {"timer": None}

            def _schedule_loadcurve_refresh() -> None:
                prev = _loadcurve_refresh_pending["timer"]
                if prev is not None:
                    prev.cancel()
                _loadcurve_refresh_pending["timer"] = ui.timer(
                    0.15, _refresh_loadcurve_summary, once=True
                )

            _refresh_loadcurve_summary()
            widgets["loadcurve_profile"].on_value_change(
                lambda _: _schedule_loadcurve_refresh()
            )

            with ui.row().classes("mt-3 gap-3 w-full flex-wrap"):
                start_curve_btn = (
                    ui.button("按曲线运行", icon="play_arrow")
                    .props("color=dark")
                    .classes("min-w-36")
                )
                stop_curve_btn = (
                    ui.button("停止", icon="stop")
                    .props("outline color=red")
                    .classes("min-w-28")
                )
                stop_curve_btn.disable()

            async def _start_loadcurve() -> None:
                parsed = _parse_loadcurve_profile(widgets["loadcurve_profile"].value)
                if not parsed:
                    ui.notify("请至少定义一个阶段", type="negative")
                    return
                start_curve_btn.disable()
                client_id = ui.context.client.id

                def notify(message: str, level: str) -> None:
                    _notify_client(client_id, message, level)

                _safe_create_bench_task(
                    _execute_loadcurve(app_state, parsed, notify),
                    on_error=lambda exc: _notify_client(
                        client_id, f"负载曲线运行失败：{exc}", "negative"
                    ),
                )
                ui.notify(
                    f"负载曲线已启动，{len(parsed)} 阶段，"
                    f"总时长 {sum(p[0] for p in parsed)}s",
                    type="ongoing",
                )

            def _stop_loadcurve() -> None:
                # Test#2 fix: _execute_loadcurve runs each phase under the
                # "rps" mode's stop_event (it's just sequential RPS runs),
                # so the curve's own stop button only needs to flip
                # that one event. Previously it also flipped run/sweep,
                # which leaked state into unrelated modes.
                app_state.run_states["rps"].stop_event.set()
                app_state.set_status("停止中...", "orange")

            start_curve_btn.on_click(_start_loadcurve)
            stop_curve_btn.on_click(_stop_loadcurve)

            def _refresh_curve_buttons() -> None:
                if app_state.is_busy():
                    start_curve_btn.disable()
                else:
                    start_curve_btn.enable()
                if any(s.busy for s in app_state.run_states.values()) or app_state.sweep_state.busy:
                    stop_curve_btn.enable()
                else:
                    stop_curve_btn.disable()

            ui.timer(0.25, _refresh_curve_buttons)

            # Register the live widget dict so _execute_loadcurve can
            # re-collect settings at run time.
            _register_loadcurve_widgets(widgets)

    # T3-3: keyboard shortcuts — Ctrl+Enter to start the active mode's run,
    # Escape to stop. Page-scoped; only fires when the Control window has
    # focus so it never interferes with typing in input fields.
    # ui.keyboard in this NiceGUI version does not accept a `js=` filter,
    # so we read the key/modifier state from the event args in Python.
    def _on_ctrl_enter(e: events.KeyEventArguments) -> None:
        if e.key != "Enter" or not (e.modifiers.ctrl or e.modifiers.meta):
            return
        if app_state.is_busy():
            return
        # Re-resolve whichever start button is currently enabled and click it.
        for tab_start in (widgets.get("run_start_btn"), widgets.get("rps_start_btn"), widgets.get("sweep_start_btn")):
            if tab_start is not None and tab_start.enabled:
                tab_start.click()
                return

    def _on_escape(e: events.KeyEventArguments) -> None:
        if e.key != "Escape":
            return
        # Stop whichever is currently busy. The stop button toggles its
        # own disable() so we can pick any one — clicking a disabled one
        # is a no-op.
        for tab_stop in (widgets.get("run_stop_btn"), widgets.get("rps_stop_btn"), widgets.get("sweep_stop_btn")):
            if tab_stop is not None and tab_stop.enabled:
                tab_stop.click()
                return

    ui.keyboard(on_key=_on_ctrl_enter)
    ui.keyboard(on_key=_on_escape)


async def _build_control_page(app_state: _AppState) -> None:
    _apply_page_shell(scroll_content=True)
    _apply_control_page_css()
    _build_header(f"LLM Bench Control  v{__version__}", app_state)
    config_state = _ConfigState()
    widgets: dict[str, Any] = {}
    with ui.column().classes("w-full flex-1 overflow-auto p-4 gap-4"):
        _build_mode_controls(app_state, widgets, config_state)
        panels = _build_config_form(widgets)

    async def _save_current_config() -> None:
        await _save_config_file(config_state, widgets, save_as=False)

    async def _save_config_as() -> None:
        await _save_config_file(config_state, widgets, save_as=True)

    async def _load_config() -> None:
        await _load_config_file(config_state, widgets)

    async def _delete_config() -> None:
        await _delete_config_file(config_state, widgets)

    widgets["config_save_btn"].on_click(_save_current_config)
    widgets["config_save_as_btn"].on_click(_save_config_as)
    widgets["config_load_btn"].on_click(_load_config)
    widgets["config_delete_btn"].on_click(_delete_config)
    _refresh_config_status(config_state, widgets)
    await ui.context.client.connected()
    client_id = ui.context.client.id
    layout_state: dict[str, Any] = {"mode": None}
    await _sync_control_layout(panels, layout_state)
    ui.timer(0.5, lambda: asyncio.create_task(_sync_control_layout(panels, layout_state)))
    ui.timer(0.4, lambda: _refresh_config_status(config_state, widgets))
    # T2-1: auto-load the most recently saved config on first launch so the
    # user doesn't have to navigate the picker every session. Skipped if the
    # file is missing or malformed (silently — startup shouldn't be blocked).
    last_path = config_dir() / "last.yaml"

    async def _auto_load_last() -> None:
        if not last_path.exists():
            return
        try:
            raw = last_path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            payload = yaml.safe_load(raw)
        except yaml.YAMLError:
            return
        if not isinstance(payload, dict):
            return
        _apply_config_snapshot(widgets, payload)
        config_state.last_saved_snapshot = _snapshot_key(_collect_config_snapshot(widgets))
        _refresh_config_status(config_state, widgets)
        _notify_client(client_id, "已自动加载上次配置：last.yaml", "info", position="bottom")

    ui.timer(
        0.6,
        lambda: _safe_create_bench_task(
            _auto_load_last(),
            on_error=lambda exc: _notify_client(
                client_id, f"自动加载 last.yaml 失败：{exc}", "negative"
            ),
        ),
        once=True,
    )


def _build_run_monitor_panel(mode: str, state: _RunState, app_state: _AppState) -> None:
    ui.label("监看结果会实时从控制窗口同步。").classes("text-xs text-slate-500 mb-2")
    status_label = ui.label(state.status).classes("text-sm text-slate-500 mb-2")
    progress_summary = ui.label("等待任务启动。").classes("text-sm text-slate-600")
    progress_meta = ui.label("已完成 0｜成功 0｜失败 0｜在飞 0｜ETA -").classes(
        "text-xs text-slate-500 mb-2"
    )
    progress_bar = (
        ui.linear_progress(value=0).props("rounded stripe color=dark").classes("w-full mb-4")
    )

    with ui.row().classes("w-full items-center gap-3 mb-3 flex-wrap"):
        refresh_mode = ui.select(
            options={"interval": "按时间刷新", "requests": "按请求数刷新"},
            value=state.chart_refresh_mode,
            label="图表刷新模式",
        ).classes("w-44")
        refresh_interval = ui.select(
            options={0.3: "0.3s", 1.0: "1s", 3.0: "3s", 5.0: "5s"},
            value=state.chart_refresh_interval_s,
            label="刷新间隔",
        ).classes("w-32")
        refresh_every_n = ui.number(
            "每 N 请求刷新", value=state.chart_refresh_every_n, min=1, step=1
        ).classes("w-36")

    def _sync_refresh_controls() -> None:
        by_requests = refresh_mode.value == "requests"
        refresh_interval.set_visibility(not by_requests)
        refresh_every_n.set_visibility(by_requests)
        state.chart_refresh_mode = str(refresh_mode.value or "interval")
        state.chart_refresh_interval_s = _safe_float(refresh_interval.value, 0.3, 0.2)
        state.chart_refresh_every_n = _safe_int(refresh_every_n.value, 5, 1)

    refresh_mode.on_value_change(lambda _: _sync_refresh_controls())
    refresh_interval.on_value_change(lambda _: _sync_refresh_controls())
    refresh_every_n.on_value_change(lambda _: _sync_refresh_controls())
    _sync_refresh_controls()

    kpi_keys = [
        ("吞吐 req/s", "throughput_rps"),
        ("延迟 p50 ms", "latency_ms_p50"),
        ("延迟 p99 ms", "latency_ms_p99"),
        ("成功率 %", "success_rate_pct"),
        ("tok/s", "throughput_completion_tok_s"),
    ]
    kpi_labels: dict[str, Any] = {}
    with ui.row().classes("w-full gap-3 mb-4"):
        for title, key in kpi_keys:
            with ui.card().classes("flex-1 min-w-24 text-center py-3"):
                ui.label(title).classes("text-xs text-slate-500")
                kpi_labels[key] = ui.label("-").classes("text-2xl font-bold text-slate-700 mt-1")

    token_kpi_labels: dict[str, Any] = {}
    with ui.row().classes("w-full gap-3 mb-4 items-stretch"):
        for title, key in [
            ("Prompt Token 消耗", "prompt"),
            ("Completion Token 消耗", "completion"),
            ("Total Token 消耗", "total"),
        ]:
            with ui.card().classes("flex-1 min-w-24 text-center py-3"):
                ui.label(title).classes("text-xs text-slate-500")
                token_kpi_labels[key] = ui.label("0").classes(
                    "text-2xl font-bold text-slate-700 mt-1"
                )
        with ui.column().classes("justify-center"):
            ui.button("重置 Token 计数", on_click=app_state.reset_consumed_tokens).props(
                "outline color=red"
            )

    with ui.tabs().classes("w-full") as result_tabs:
        tab_overview = ui.tab("概览", icon="table_chart")
        tab_charts = ui.tab("图表", icon="bar_chart")
        tab_responses = ui.tab("响应", icon="forum")
        tab_log = ui.tab("日志", icon="terminal")

    with ui.tab_panels(result_tabs, value=tab_overview).classes("w-full border rounded"):
        with ui.tab_panel(tab_overview).classes("p-3"):
            # T2-2: error diagnostic banner — shows the dominant error kind
            # and one sample error message so the user doesn't have to dig
            # into the log tab to figure out "what went wrong".
            error_banner = (
                ui.label("")
                .classes(
                    "w-full text-sm rounded px-3 py-2 mb-3 bg-slate-50 text-slate-500"
                )
                .style("white-space: pre-wrap")
            )
            stat_table = ui.table(
                columns=[
                    {
                        "name": "metric",
                        "label": "指标",
                        "field": "指标",
                        "align": "left",
                        "sortable": False,
                    },
                    {
                        "name": "value",
                        "label": "值",
                        "field": "值",
                        "align": "left",
                        "sortable": False,
                    },
                ],
                rows=[],
                row_key="指标",
            ).classes("w-full")
            stat_table.props("dense flat")

        with ui.tab_panel(tab_charts).classes("p-3"):
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
                        "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#475569"}}],
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
                        "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#475569"}}],
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
                            "lineStyle": {"color": "#475569"},
                            "itemStyle": {"color": "#475569"},
                        }
                    ],
                }
            ).classes("w-full h-52 mt-2")
            throughput_chart = ui.echart(
                {
                    "title": {"text": "时序吞吐（req/s & tok/s）", "textStyle": {"fontSize": 13}},
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": ["req/s", "tok/s"]},
                    "xAxis": {"type": "category", "data": [], "name": "bucket"},
                    "yAxis": {"type": "value"},
                    "series": [
                        {"name": "req/s", "type": "line", "data": [], "smooth": True},
                        {"name": "tok/s", "type": "line", "data": [], "smooth": True},
                    ],
                }
            ).classes("w-full h-52 mt-2")
            token_cumulative_chart = ui.echart(
                {
                    "title": {"text": "Token 累积时序", "textStyle": {"fontSize": 13}},
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": ["prompt", "completion"]},
                    "xAxis": {"type": "category", "data": [], "name": "bucket"},
                    "yAxis": {"type": "value", "name": "tokens"},
                    "series": [
                        {
                            "name": "prompt",
                            "type": "line",
                            "data": [],
                            "areaStyle": {"opacity": 0.2},
                        },
                        {
                            "name": "completion",
                            "type": "line",
                            "data": [],
                            "areaStyle": {"opacity": 0.2},
                        },
                    ],
                }
            ).classes("w-full h-52 mt-2")

        with ui.tab_panel(tab_responses).classes("p-3"):
            response_meta = ui.label("选择一条请求查看 AI 回应或错误响应。").classes(
                "text-xs text-slate-500 mb-2"
            )
            replay_btn = ui.button("🔁 重放选中", icon="replay").props(
                "outline color=dark"
            )
            _attach_tooltip(replay_btn, _TOOLTIPS["replay_btn"])
            replay_btn.disable()
            with ui.row().classes("w-full gap-3 mb-3 items-end flex-wrap"):
                response_filter = ui.select(
                    options={"all": "全部", "success": "仅成功", "failed": "仅失败"},
                    value="all",
                    label="按状态筛选",
                ).classes("w-44")
                # T3-2: keyword search across response text + error message.
                response_search = (
                    ui.input(label="关键字搜索", placeholder="匹配响应文本或错误信息")
                    .classes("flex-1 min-w-48")
                    .props("clearable dense")
                )
            response_table = ui.table(
                columns=[
                    {"name": "idx", "label": "#", "field": "#", "align": "center"},
                    {"name": "status", "label": "HTTP", "field": "HTTP", "align": "center"},
                    {"name": "ok", "label": "OK", "field": "OK", "align": "center"},
                    {
                        "name": "latency",
                        "label": "latency ms",
                        "field": "latency ms",
                        "align": "center",
                    },
                    {
                        "name": "tokens",
                        "label": "completion tok",
                        "field": "completion tok",
                        "align": "center",
                    },
                    {"name": "preview", "label": "回应预览", "field": "回应预览", "align": "left"},
                ],
                rows=[],
                row_key="id",
                selection="single",
            ).classes("w-full")
            response_table.props("dense flat")
            response_detail = (
                ui.textarea(value="")
                .classes("w-full mt-3 font-mono text-xs")
                .props("readonly autogrow rows=12")
            )

        with ui.tab_panel(tab_log).classes("p-3"), ui.row().classes("w-full gap-4"):
            live_log = ui.log(max_lines=600).classes("w-full h-72 font-mono text-xs border rounded")
            full_log = ui.code("", language="json").classes(
                "w-full text-xs max-h-72 overflow-auto border rounded"
            )

    with ui.row().classes("mt-3 gap-3"):
        export_json_btn = ui.button("导出 JSON", icon="download").props("outline")
        export_csv_btn = ui.button("导出 CSV", icon="download").props("outline")
        export_json_btn.disable()
        export_csv_btn.disable()

    def _export_json() -> None:
        if not state.stats:
            return
        data = json.dumps(state.stats, ensure_ascii=False, indent=2).encode("utf-8")
        _download_bytes(
            data, f"bench_{mode}_{_timestamp_slug()}.json", "application/json; charset=utf-8"
        )

    async def _export_csv() -> None:
        if not state.raw_results:
            return
        # Preview first 3 rows before actually downloading — catches the
        # "I forgot to deselect the filter" / "wrong field" issue early.
        sample = state.raw_results[:3]
        preview = _csv_bytes(sample).decode("utf-8-sig")
        first_lines = "\n".join(preview.splitlines()[:4])  # header + 3 rows
        with ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full"):
            ui.label(f"CSV 预览（前 3 条 + 表头，共 {len(state.raw_results)} 条）").classes(
                "text-base font-semibold"
            )
            ui.code(first_lines, language="text").classes("text-xs")
            with ui.row().classes("justify-end w-full gap-2 mt-2"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("确认导出", on_click=lambda: dialog.submit(True)).props("color=dark")
        dialog.open()
        if not await dialog:
            return
        _download_bytes(
            _csv_bytes(state.raw_results),
            f"bench_{mode}_{_timestamp_slug()}.csv",
            "text/csv; charset=utf-8",
        )

    export_json_btn.on_click(_export_json)
    export_csv_btn.on_click(_export_csv)
    cache: dict[str, Any] = {
        "log_count": 0,
        "preview": "",
        "response_selected_id": None,
        "last_chart_total": -1,
        "last_chart_mono": 0.0,
        "last_chart_stats_total": None,
    }

    def _show_response_detail(row_id: int | None) -> None:
        cache["response_selected_id"] = row_id
        if row_id is None or row_id < 1 or row_id > len(state.raw_results):
            response_meta.set_text("选择一条请求查看 AI 回应或错误响应。")
            response_detail.set_value("")
            replay_btn.disable()
            return
        result = state.raw_results[row_id - 1]
        response_meta.set_text(
            f"第 {row_id} 条｜HTTP {result.status_code or '-'}｜"
            f"{'成功' if result.ok else '失败'}｜latency={_v(result.latency_ms)} ms"
        )
        response_detail.set_value(
            result.raw_response_text or result.error or result.response_text or ""
        )
        replay_btn.enable()

    async def _replay_selected() -> None:
        """Re-fire the original request and show the new response inline.

        Useful for diagnosing intermittent failures — does the same request
        always produce the same status/latency? The original body is
        snapshotted into RequestResult.raw_request_body, so we faithfully
        re-send exactly what was sent before.
        """
        sid = cache.get("response_selected_id")
        if sid is None or sid < 1 or sid > len(state.raw_results):
            return
        replay_btn.disable()
        try:
            original = state.raw_results[sid - 1]
            if not original.raw_request_body:
                ui.notify(
                    "⚠️ 该结果没有保存原始 body（老版本数据），无法深度重放",
                    type="warning",
                )
                return
            # Pull the live config from the Control page widgets.
            live_settings = _loadcurve_capture_widgets(app_state)
            if not live_settings:
                ui.notify("无法读取当前 Control 配置", "negative")
                return
            try:
                runtime = _build_runtime_payload(live_settings)
            except ValueError as exc:
                ui.notify(f"配置不合法：{exc}", "negative")
                return
            try:
                body = json.loads(original.raw_request_body)
            except json.JSONDecodeError as exc:
                ui.notify(f"原 body 不是合法 JSON：{exc}", "negative")
                return
            resolved_key = _resolve_api_key(live_settings["api_key"])
            if not resolved_key:
                ui.notify("API Key 未设置", "negative")
                return
            # Sec#2 polish: SSRF guard — refuse replay if the resolved
            # endpoint host is in a private/link-local/loopback range.
            # Mirrors the gate on the TCP probe. Without this, a user
            # who pastes https://169.254.169.254/v1/chat/completions as
            # base_url could re-fire requests at IMDS from a path that
            # the path-suffix check (below) considers "safe".
            try:
                _endpoint_host, _endpoint_port, _ = _parse_base_for_probe(
                    runtime["endpoint"]
                )
            except ValueError as exc:
                ui.notify(f"重放端点无法解析：{exc}", "negative")
                return
            if _is_private_or_loopback(_endpoint_host):
                ui.notify(
                    "❌ 重放端点是私有/回环地址，已被 SSRF 防护拒绝",
                    "negative",
                )
                return
            # Also check the proxy URL — a public-looking endpoint via a
            # localhost proxy is still an internal hit.
            if live_settings.get("proxy_mode") == "custom":
                proxy_url_val = live_settings.get("proxy_url") or ""
                if proxy_url_val:
                    from urllib.parse import urlparse as _urlparse_for_proxy

                    try:
                        proxy_host = _urlparse_for_proxy(
                            proxy_url_val
                            if "://" in proxy_url_val
                            else f"http://{proxy_url_val}"
                        ).hostname
                    except ValueError:
                        proxy_host = None
                    if proxy_host and _is_private_or_loopback(proxy_host):
                        ui.notify(
                            "❌ 重放代理是私有/回环地址，已被 SSRF 防护拒绝",
                            "negative",
                        )
                        return

            # Sec#3: confirm before replaying to a non-chat endpoint. The
            # captured body might be a mutation (delete-and-recreate) and
            # the user may have switched the endpoint in the live UI to
            # something that interprets messages as a write command.
            endpoint = runtime["endpoint"].rstrip("/")
            is_safe_endpoint = (
                endpoint.endswith("/chat/completions")
                or endpoint.endswith("/completions")
                or endpoint.endswith("/responses")
            )
            if not is_safe_endpoint:
                with ui.dialog() as confirm, ui.card().classes("w-[36rem]"):
                    ui.label("⚠️ 端点不是只读 chat endpoint").classes(
                        "text-base font-semibold"
                    )
                    ui.label(f"目标：{endpoint}").classes("text-xs text-slate-500")
                    ui.label("原 body 预览：").classes("text-xs text-slate-500 mt-2")
                    ui.code(
                        original.raw_request_body[:400], language="json"
                    ).classes("text-xs")
                    with ui.row().classes("justify-end w-full gap-2 mt-2"):
                        ui.button(
                            "取消", on_click=lambda: confirm.submit(False)
                        ).props("flat")
                        ui.button(
                            "仍然重放",
                            on_click=lambda: confirm.submit(True),
                        ).props("color=dark")
                confirm.open()
                if not await confirm:
                    return
            ui.notify(
                f"🔁 重放中：{_v(original.latency_ms)} ms（原结果）",
                type="ongoing",
            )
            # Fire the same body, same endpoint, same stream mode.
            async with httpx.AsyncClient(
                http2=live_settings["http2"],
                proxy=(
                    live_settings.get("proxy_url")
                    if live_settings["proxy_mode"] == "custom"
                    else None
                ),
                trust_env=live_settings["proxy_mode"] == "system",
                timeout=live_settings["timeout_s"],
            ) as client:
                replay_result = await one_chat_request(
                    client,
                    runtime["endpoint"],
                    _headers(resolved_key),
                    body,
                    stream=runtime["stream_flag"],
                    timeout_s=live_settings["timeout_s"],
                )
            # Compare and notify.
            old_status = original.status_code or "-"
            new_status = replay_result.status_code or "-"
            old_lat = original.latency_ms
            new_lat = replay_result.latency_ms
            delta = new_lat - old_lat
            sign = "+" if delta >= 0 else ""
            same_status = old_status == new_status
            status_note = "✅ 一致" if same_status else "⚠️ 状态不同"
            ui.notify(
                f"🔁 重放结果：{new_status} ({status_note})｜{_v(new_lat)} ms ({sign}{_v(delta)} ms)",
                type="positive" if same_status and replay_result.ok else "warning",
                timeout=8.0,
            )
            # Show the new response text in the detail area.
            response_detail.set_value(
                f"─── 原结果 ({old_status}, {_v(old_lat)} ms) ───\n"
                + (original.raw_response_text or original.response_text or "(empty)")
                + f"\n\n─── 重放结果 ({new_status}, {_v(new_lat)} ms) ───\n"
                + (replay_result.raw_response_text or replay_result.response_text or "(empty)")
            )
        except Exception as exc:
            ui.notify(f"重放失败：{type(exc).__name__}: {exc}", type="negative")
        finally:
            replay_btn.enable()

    replay_btn.on_click(_replay_selected)

    response_table.on_select(
        lambda e: (
            _show_response_detail(int(e.selection[0]["id"]))
            if getattr(e, "selection", [])
            else _show_response_detail(None)
        )
    )

    def _should_refresh_charts(finished: int, stats: dict[str, Any] | None) -> bool:
        if not finished and not stats:
            return False
        now_mono = time.perf_counter()
        if state.chart_refresh_mode == "requests":
            every_n = max(1, state.chart_refresh_every_n)
            stats_total = stats.get("requests_total") if stats else None
            force_final = stats_total is not None and stats_total != cache["last_chart_stats_total"]
            if force_final or (finished - cache["last_chart_total"] >= every_n):
                cache["last_chart_total"] = finished
                cache["last_chart_stats_total"] = stats_total
                cache["last_chart_mono"] = now_mono
                return True
            return False
        interval_s = max(0.2, state.chart_refresh_interval_s)
        if now_mono - cache["last_chart_mono"] >= interval_s:
            cache["last_chart_total"] = finished
            cache["last_chart_stats_total"] = stats.get("requests_total") if stats else None
            cache["last_chart_mono"] = now_mono
            return True
        return False

    def _refresh_charts(stats: dict[str, Any] | None) -> None:
        lat_keys = [
            "latency_ms_p50",
            "latency_ms_p75",
            "latency_ms_p90",
            "latency_ms_p95",
            "latency_ms_p99",
            "latency_ms_p99_9",
        ]
        latency_chart.options["series"][0]["data"] = (
            [round(float(stats.get(k) or 0), 2) for k in lat_keys] if stats else []
        )
        latency_chart.update()

        stream_keys = [
            "ttft_ms_p50",
            "ttft_ms_p95",
            "tpot_ms_p50",
            "tpot_ms_p95",
            "itl_ms_p50",
            "itl_ms_p95",
        ]
        stream_chart.options["series"][0]["data"] = (
            [round(float(stats.get(k) or 0), 2) for k in stream_keys] if stats else []
        )
        stream_chart.update()

        # M6: x-axis is wall-clock seconds at 100ms cadence (matches sample_inflight_ms).
        # Capped to first 600 samples (~60s) to keep labels readable.
        samples = state.inflight_samples
        if len(samples) > 600:
            samples = samples[-600:]
        inflight_chart.options["xAxis"]["data"] = [f"{(i * 0.1):.1f}s" for i in range(len(samples))]
        inflight_chart.options["series"][0]["data"] = list(samples)
        inflight_chart.update()

        timeline = list(stats.get("timeline") or []) if stats else []
        xs = [str(i + 1) for i in range(len(timeline))]
        req_series = [round(float(item.get("rps_success") or 0.0), 3) for item in timeline]
        tok_series = [
            round(float(item.get("throughput_completion_tok_s_bucket") or 0.0), 3)
            for item in timeline
        ]
        throughput_chart.options["xAxis"]["data"] = xs
        throughput_chart.options["series"][0]["data"] = req_series
        throughput_chart.options["series"][1]["data"] = tok_series
        throughput_chart.update()

        cum_prompt: list[float] = []
        cum_completion: list[float] = []
        prompt_running = 0.0
        completion_running = 0.0
        for item in timeline:
            prompt_running += float(item.get("prompt_tokens_bucket") or 0.0)
            completion_running += float(item.get("completion_tokens_bucket") or 0.0)
            cum_prompt.append(round(prompt_running, 3))
            cum_completion.append(round(completion_running, 3))
        token_cumulative_chart.options["xAxis"]["data"] = xs
        token_cumulative_chart.options["series"][0]["data"] = cum_prompt
        token_cumulative_chart.options["series"][1]["data"] = cum_completion
        token_cumulative_chart.update()

    def _refresh() -> None:
        status_label.set_text(state.status or "就绪")
        stats = state.stats
        finished = len(state.raw_results)
        success = sum(1 for result in state.raw_results if result.ok)
        failed = finished - success
        inflight = state.inflight_samples[-1] if state.inflight_samples else 0
        elapsed: float | None = None
        if state.started_at_mono is not None:
            elapsed = max(0.0, time.perf_counter() - state.started_at_mono)
        elif stats:
            elapsed = float(stats.get("wall_seconds") or 0.0)
        progress_value = 0.0
        eta: float | None = None
        if state.target_total:
            progress_value = min(1.0, finished / max(1, state.target_total))
            if elapsed and finished > 0 and finished < state.target_total:
                eta = max(0.0, (elapsed / finished) * (state.target_total - finished))
            progress_summary.set_text(
                f"按总数推进：{finished}/{state.target_total} 请求"
                + ("（已完成）" if progress_value >= 1 else "")
            )
        elif state.target_duration_s:
            duration_s = max(0.1, float(state.target_duration_s))
            current_elapsed = min(elapsed or 0.0, duration_s)
            progress_value = min(1.0, current_elapsed / duration_s)
            eta = max(0.0, duration_s - current_elapsed) if progress_value < 1 else 0.0
            progress_summary.set_text(f"按时长推进：{_v(current_elapsed)}s / {_v(duration_s)}s")
        else:
            progress_summary.set_text("等待任务启动。")
        progress_meta.set_text(
            f"已完成 {finished}｜成功 {success}｜失败 {failed}｜在飞 {inflight}｜ETA {_format_eta(eta)}"
        )
        progress_bar.set_value(progress_value if (state.busy or finished or stats) else 0.0)

        for key, label in kpi_labels.items():
            suffix = " %" if key == "success_rate_pct" else ""
            value = stats.get(key) if stats else None
            if not stats:
                # T1-2: data not ready yet — show "待样本" instead of "-" so
                # the user understands the panel is waiting, not broken.
                label.set_text("待样本")
                label.classes(replace="text-slate-400")
                continue
            if value is None:
                label.set_text("-")
                label.classes(replace="text-slate-400")
                continue
            label.set_text(f"{_v(value)}{suffix}")
            # Color the active value to make it pop against the empty state.
            label.classes(replace="text-slate-700")
        token_kpi_labels["prompt"].set_text(str(app_state.consumed_prompt_tokens))
        token_kpi_labels["completion"].set_text(str(app_state.consumed_completion_tokens))
        token_kpi_labels["total"].set_text(str(app_state.consumed_total_tokens))

        stat_table.rows[:] = _augmented_stat_rows(stats) if stats else []
        stat_table.update()

        # T2-2: error diagnostic banner.
        if stats:
            error_kinds = stats.get("error_kind_counts") or {}
            sample_errors = stats.get("errors_sample") or []
            if error_kinds:
                top_kind, top_count = max(error_kinds.items(), key=lambda kv: int(kv[1]))
                pct = (100.0 * int(top_count) / max(1, int(stats.get("requests_total", 0) or 0)))
                sample = (sample_errors[0] if sample_errors else "").splitlines()[0][:120]
                banner = (
                    f"⚠️ 主要错误：{top_kind} ×{top_count} ({pct:.0f}%)"
                    + (f"\n   示例：{sample}" if sample else "")
                )
                error_banner.set_text(banner)
                error_banner.classes(
                    replace="w-full text-sm rounded px-3 py-2 mb-3 bg-slate-100 text-slate-800"
                )
            else:
                error_banner.set_text("✅ 全部请求成功")
                error_banner.classes(
                    replace="w-full text-sm rounded px-3 py-2 mb-3 bg-emerald-50 text-emerald-900"
                )
        else:
            error_banner.set_text("等待压测完成。")
            error_banner.classes(
                replace="w-full text-sm rounded px-3 py-2 mb-3 bg-slate-50 text-slate-500"
            )

        if _should_refresh_charts(finished, stats):
            _refresh_charts(stats)

        filter_mode = response_filter.value or "all"
        keyword = (response_search.value or "").strip().lower()
        filtered_rows = []
        for raw_idx, raw_result in enumerate(state.raw_results, start=1):
            if filter_mode == "success" and not raw_result.ok:
                continue
            if filter_mode == "failed" and raw_result.ok:
                continue
            if keyword:
                haystack = (
                    (raw_result.response_text or "")
                    + " "
                    + (raw_result.error or "")
                ).lower()
                if keyword not in haystack:
                    continue
            filtered_rows.append(
                {
                    "id": raw_idx,
                    "#": raw_idx,
                    "HTTP": str(raw_result.status_code or "-"),
                    "OK": "Y" if raw_result.ok else "N",
                    "latency ms": _v(raw_result.latency_ms),
                    "completion tok": str(raw_result.completion_tokens or "-"),
                    "回应预览": _preview_text(raw_result.response_text),
                }
            )
        response_table.rows[:] = filtered_rows
        response_table.update()
        selected_id = cache["response_selected_id"]
        if selected_id is not None and selected_id <= len(state.raw_results):
            _show_response_detail(selected_id)
        elif selected_id is not None:
            _show_response_detail(None)

        if len(state.log_lines) < cache["log_count"]:
            live_log.clear()
            cache["log_count"] = 0
        for line in state.log_lines[cache["log_count"] :]:
            live_log.push(line)
        cache["log_count"] = len(state.log_lines)

        preview = _stats_log_preview(stats) if stats else ""
        if preview != cache["preview"]:
            full_log.set_content(preview)
            cache["preview"] = preview

        if stats:
            export_json_btn.enable()
        else:
            export_json_btn.disable()
        if state.raw_results:
            export_csv_btn.enable()
        else:
            export_csv_btn.disable()

    ui.timer(0.2, _refresh)


def _build_sweep_monitor_panel(sweep_state: _SweepState, app_state: _AppState) -> None:
    with ui.row().classes("w-full items-center gap-3 mb-3 flex-wrap"):
        refresh_mode = ui.select(
            options={"interval": "按时间刷新", "requests": "按请求数刷新"},
            value=sweep_state.chart_refresh_mode,
            label="图表刷新模式",
        ).classes("w-44")
        refresh_interval = ui.select(
            options={0.3: "0.3s", 1.0: "1s", 3.0: "3s", 5.0: "5s"},
            value=sweep_state.chart_refresh_interval_s,
            label="刷新间隔",
        ).classes("w-32")
        refresh_every_n = ui.number(
            "每 N 请求刷新", value=sweep_state.chart_refresh_every_n, min=1, step=1
        ).classes("w-36")

    def _sync_refresh_controls() -> None:
        by_requests = refresh_mode.value == "requests"
        refresh_interval.set_visibility(not by_requests)
        refresh_every_n.set_visibility(by_requests)
        sweep_state.chart_refresh_mode = str(refresh_mode.value or "interval")
        sweep_state.chart_refresh_interval_s = _safe_float(refresh_interval.value, 0.3, 0.2)
        sweep_state.chart_refresh_every_n = _safe_int(refresh_every_n.value, 5, 1)

    refresh_mode.on_value_change(lambda _: _sync_refresh_controls())
    refresh_interval.on_value_change(lambda _: _sync_refresh_controls())
    refresh_every_n.on_value_change(lambda _: _sync_refresh_controls())
    _sync_refresh_controls()

    kpi_labels: dict[str, Any] = {}
    with ui.row().classes("w-full gap-3 mb-4"):
        for title, key in [
            ("档位数", "levels"),
            ("最佳 req/s", "best_rps"),
            ("最低 p95 ms", "best_p95"),
            (f"建议并发 (>={int(_RECOMMENDED_CONCURRENCY_SUCCESS_RATE_PCT)}%)", "recommended"),
        ]:
            with ui.card().classes("flex-1 text-center py-3"):
                ui.label(title).classes("text-xs text-slate-500")
                kpi_labels[key] = ui.label("-").classes("text-2xl font-bold text-slate-700 mt-1")
    with ui.row().classes("w-full gap-3 mb-4"):
        with ui.card().classes("flex-1 text-center py-3"):
            ui.label("Prompt Token 累计").classes("text-xs text-slate-500")
            token_prompt_label = ui.label("0").classes("text-2xl font-bold text-slate-700 mt-1")
        with ui.card().classes("flex-1 text-center py-3"):
            ui.label("Completion Token 累计").classes("text-xs text-slate-500")
            token_completion_label = ui.label("0").classes("text-2xl font-bold text-slate-700 mt-1")
        with ui.card().classes("flex-1 text-center py-3"):
            ui.label("Token 总累计").classes("text-xs text-slate-500")
            token_total_label = ui.label("0").classes("text-2xl font-bold text-slate-700 mt-1")
        with ui.column().classes("justify-center"):
            ui.button("重置 Token 计数", on_click=app_state.reset_consumed_tokens).props(
                "outline color=red"
            )

    with ui.tabs().classes("w-full") as sweep_tabs:
        tab_overview = ui.tab("概览", icon="table_chart")
        tab_charts = ui.tab("图表", icon="bar_chart")
        tab_log = ui.tab("日志", icon="terminal")

    with ui.tab_panels(sweep_tabs, value=tab_overview).classes("w-full border rounded"):
        with ui.tab_panel(tab_overview).classes("p-3"):
            # UX#5: export button for per-level raw_results so the user
            # can drill into individual requests from the sweep.
            with ui.row().classes("w-full items-center gap-2 mb-2"):
                export_sweep_raw_btn = ui.button(
                    t("sweep_export_csv_btn"),
                    icon="download",
                ).props("outline color=dark")
                export_sweep_raw_btn.disable()
                _attach_tooltip(export_sweep_raw_btn, _TOOLTIPS["sweep_raw_export_btn"])

                def _export_sweep_raw() -> None:
                    if not sweep_state.raw_results_per_level:
                        ui.notify(t("sweep_no_raw_results"), "warning")
                        return
                    flat: list[Any] = []
                    for _level, rrs in zip(
                        sweep_state.raw_results_levels,
                        sweep_state.raw_results_per_level,
                        strict=False,
                    ):
                        for rr in rrs:
                            flat.append(rr)
                    if not flat:
                        ui.notify(t("sweep_all_levels_empty"), "warning")
                        return
                    _download_bytes(
                        _csv_bytes(flat),
                        f"sweep_raw_{_timestamp_slug()}.csv",
                        "text/csv; charset=utf-8",
                    )
                    # UX#4: tell the user where to find a corresponding
                    # in-memory row for replay — the CSV is just a
                    # download, but the same requests are still in
                    # app_state.history (as one stat per level). The
                    # user can find the matching stat in the history
                    # tab and re-run that level to get replayable
                    # raw_results.
                    ui.notify(
                        t("sweep_exported_n_followup", n=len(flat)),
                        type="positive",
                        timeout=10.0,
                    )

                export_sweep_raw_btn.on_click(_export_sweep_raw)
                sweep_raw_count_badge = ui.badge("", color="grey").classes("text-xs")

            sweep_table = ui.table(
                columns=[
                    {"name": "concurrency", "label": "并发", "field": "并发", "align": "center"},
                    {"name": "success", "label": "成功率%", "field": "成功率%", "align": "center"},
                    {"name": "p50", "label": "p50 ms", "field": "p50 ms", "align": "center"},
                    {"name": "p95", "label": "p95 ms", "field": "p95 ms", "align": "center"},
                    {"name": "p99", "label": "p99 ms", "field": "p99 ms", "align": "center"},
                    {"name": "rps", "label": "req/s", "field": "req/s", "align": "center"},
                    {"name": "toks", "label": "tok/s", "field": "tok/s", "align": "center"},
                ],
                rows=[],
                row_key="并发",
            ).classes("w-full")
            sweep_table.props("dense flat")

        with ui.tab_panel(tab_charts).classes("p-3"), ui.row().classes("w-full gap-4"):
            sweep_lat_chart = ui.echart(
                {
                    "title": {"text": "延迟随并发变化", "textStyle": {"fontSize": 13}},
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": ["p50", "p95", "p99"]},
                    "xAxis": {"type": "category", "data": [], "name": "并发"},
                    "yAxis": {"type": "value", "name": "ms"},
                    "series": [
                        {"name": "p50", "type": "line", "data": [], "smooth": True},
                        {"name": "p95", "type": "line", "data": [], "smooth": True},
                        {"name": "p99", "type": "line", "data": [], "smooth": True},
                    ],
                }
            ).classes("flex-1 h-72")
            sweep_rps_chart = ui.echart(
                {
                    "title": {"text": "吞吐随并发变化", "textStyle": {"fontSize": 13}},
                    "tooltip": {},
                    "xAxis": {"type": "category", "data": [], "name": "并发"},
                    "yAxis": {"type": "value", "name": "req/s"},
                    "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#475569"}}],
                }
            ).classes("flex-1 h-72")
            sweep_tok_chart = ui.echart(
                {
                    "title": {"text": "Token 吞吐随并发变化", "textStyle": {"fontSize": 13}},
                    "tooltip": {},
                    "xAxis": {"type": "category", "data": [], "name": "并发"},
                    "yAxis": {"type": "value", "name": "tok/s"},
                    "series": [{"type": "bar", "data": [], "itemStyle": {"color": "#475569"}}],
                }
            ).classes("flex-1 h-72")

        with ui.tab_panel(tab_log).classes("p-3"):
            sweep_log = ui.log(max_lines=500).classes(
                "w-full h-72 font-mono text-xs border rounded"
            )

    export_btn = ui.button("导出扫描 JSON", icon="download").props("outline")
    export_btn.disable()

    def _export() -> None:
        if not sweep_state.all_stats:
            return
        data = json.dumps(sweep_state.all_stats, ensure_ascii=False, indent=2).encode("utf-8")
        _download_bytes(
            data, f"bench_sweep_{_timestamp_slug()}.json", "application/json; charset=utf-8"
        )

    export_btn.on_click(_export)
    cache = {"log_count": 0, "last_chart_count": -1, "last_chart_mono": 0.0}

    def _should_refresh_charts() -> bool:
        count = len(sweep_state.all_stats)
        if sweep_state.chart_refresh_mode == "requests":
            every_n = max(1, sweep_state.chart_refresh_every_n)
            if count - cache["last_chart_count"] >= every_n:
                cache["last_chart_count"] = count
                cache["last_chart_mono"] = time.perf_counter()
                return True
            return False
        now_mono = time.perf_counter()
        if now_mono - cache["last_chart_mono"] >= max(0.2, sweep_state.chart_refresh_interval_s):
            cache["last_chart_count"] = count
            cache["last_chart_mono"] = now_mono
            return True
        return False

    def _refresh() -> None:
        sweep_table.rows[:] = list(sweep_state.rows)
        sweep_table.update()
        # UX#5: enable the export button when there are raw_results
        # captured for at least one level, and show the count.
        total_raw = sum(len(rr) for rr in sweep_state.raw_results_per_level)
        if total_raw > 0:
            export_sweep_raw_btn.enable()
            sweep_raw_count_badge.set_text(t("sweep_raw_count_badge", n=total_raw))
            sweep_raw_count_badge.set_visibility(True)
        else:
            export_sweep_raw_btn.disable()
            sweep_raw_count_badge.set_visibility(False)
        if _should_refresh_charts():
            xs = [
                str(s.get("concurrency_level", i + 1)) for i, s in enumerate(sweep_state.all_stats)
            ]
            sweep_lat_chart.options["xAxis"]["data"] = xs
            sweep_rps_chart.options["xAxis"]["data"] = xs
            sweep_tok_chart.options["xAxis"]["data"] = xs
            for i, key in enumerate(["latency_ms_p50", "latency_ms_p95", "latency_ms_p99"]):
                sweep_lat_chart.options["series"][i]["data"] = [
                    round(float(s.get(key) or 0), 2) for s in sweep_state.all_stats
                ]
            sweep_rps_chart.options["series"][0]["data"] = [
                round(float(s.get("throughput_rps") or 0), 2) for s in sweep_state.all_stats
            ]
            sweep_tok_chart.options["series"][0]["data"] = [
                round(float(s.get("throughput_completion_tok_s") or 0), 2)
                for s in sweep_state.all_stats
            ]
            sweep_lat_chart.update()
            sweep_rps_chart.update()
            sweep_tok_chart.update()

        kpi_labels["levels"].set_text(str(len(sweep_state.all_stats)))
        best_rps = max(
            (float(s.get("throughput_rps") or 0) for s in sweep_state.all_stats), default=0.0
        )
        p95_vals = [
            float(s.get("latency_ms_p95") or 0)
            for s in sweep_state.all_stats
            if s.get("latency_ms_p95")
        ]
        recommendation = _recommended_concurrency(sweep_state.all_stats)
        kpi_labels["best_rps"].set_text(_v(best_rps))
        kpi_labels["best_p95"].set_text(_v(min(p95_vals) if p95_vals else 0.0))
        kpi_labels["recommended"].set_text(str(recommendation or "-"))
        token_prompt_label.set_text(str(app_state.consumed_prompt_tokens))
        token_completion_label.set_text(str(app_state.consumed_completion_tokens))
        token_total_label.set_text(str(app_state.consumed_total_tokens))

        if len(sweep_state.log_lines) < cache["log_count"]:
            sweep_log.clear()
            cache["log_count"] = 0
        for line in sweep_state.log_lines[cache["log_count"] :]:
            sweep_log.push(line)
        cache["log_count"] = len(sweep_state.log_lines)

        if sweep_state.all_stats:
            export_btn.enable()
        else:
            export_btn.disable()

    ui.timer(0.2, _refresh)


# ── A/B compare board helpers (module-level so they're testable) ─────────
_AB_METRIC_KEYS: list[tuple[str, str, str]] = [
    ("p50 ms", "latency_ms_p50", "min"),
    ("p95 ms", "latency_ms_p95", "min"),
    ("p99 ms", "latency_ms_p99", "min"),
    ("p99.9 ms", "latency_ms_p99_9", "min"),
    ("req/s", "throughput_rps", "max"),
    ("成功率 %", "success_rate_pct", "max"),
    ("completion tok/s", "throughput_completion_tok_s", "max"),
    ("HTTP 尝试成功率 %", "http_attempt_success_rate_pct", "max"),
]


def _ab_pick_view_rows(selected_stats: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Side-by-side comparison: best/worst per metric over the selected set."""
    if len(selected_stats) < 2:
        return []
    rows: list[dict[str, str]] = []
    for label, key, direction in _AB_METRIC_KEYS:
        values = [s.get(key) for s in selected_stats]
        present = [v for v in values if v is not None]
        if not present:
            continue
        if direction == "min":
            best = min(present)
            worst = max(present)
        else:
            best = max(present)
            worst = min(present)
        rows.append(
            {"metric": label, "best": f"{float(best):.2f}", "worst": f"{float(worst):.2f}"}
        )
    return rows


_AB_CACHE: dict[tuple[int, int, str], list[dict[str, str]]] = {}


def _ab_group_view_rows(
    history: list[dict[str, Any]], group_key: str
) -> list[dict[str, str]]:
    """Group-by view: pick the entry with lowest p99 from each group.

    Perf#2: cached by (history-id, len, group_key). The history list
    mutates in place (new entries appended by add_history), but the
    *length* is the cheapest stable signature for our purposes —
    rebuilding the grouping is O(N) but cheap enough; the cache key
    just prevents re-computing every 0.5s tick."""
    cache_key = (id(history), len(history), group_key)
    cached = _AB_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not history:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for stat in history:
        meta = stat.get("metadata") or {}
        k = str(meta.get(group_key, "?"))
        groups.setdefault(k, []).append(stat)
    rows: list[dict[str, str]] = []
    for group_name, stats in sorted(groups.items()):
        candidates = [
            (s.get("latency_ms_p99"), s)
            for s in stats
            if s.get("latency_ms_p99") is not None
        ]
        if not candidates:
            continue
        best_p99, best_stat = min(candidates, key=lambda kv: float(kv[0]))
        meta = best_stat.get("metadata") or {}
        rows.append(
            {
                "metric": (
                    f"{group_name} | c={meta.get('concurrency', '?')} | "
                    f"{_v(best_stat.get('throughput_rps'))} req/s"
                ),
                "best": f"p99 {float(best_p99):.1f} ms",
                "worst": f"{len(stats)} 个样本",
            }
        )
    _AB_CACHE[cache_key] = rows
    return rows


def _ab_rank_view_rows(
    history: list[dict[str, Any]], metric: str, top_n: int = 20
) -> list[dict[str, str]]:
    """Rank view: sort all entries by the chosen metric, return top N.

    Same caching strategy as :func:`_ab_group_view_rows`."""
    cache_key = (id(history), len(history), f"rank:{metric}:{top_n}")
    cached = _AB_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not history:
        return []
    direction = "min" if "latency" in metric else "max"
    candidates = [
        (s.get(metric), idx, s)
        for idx, s in enumerate(history, start=1)
        if s.get(metric) is not None
    ]
    if not candidates:
        return []
    candidates.sort(key=lambda kv: float(kv[0]), reverse=(direction == "max"))
    rows: list[dict[str, str]] = []
    for value, idx, stat in candidates[:top_n]:
        meta = stat.get("metadata") or {}
        rows.append(
            {
                "idx": str(idx),
                "label": (
                    f"{meta.get('model', '?')} c={meta.get('concurrency', '?')} "
                    f"{meta.get('mode', '?')}"
                ),
                "metric": f"{float(value):.2f}",
            }
        )
    _AB_CACHE[cache_key] = rows
    return rows


def _build_compare_panel(app_state: _AppState) -> None:
    """A/B compare board: group, filter, sort, and rank historical results.

    Three view modes:
      - 'all': raw selection of 2-6 entries, side-by-side comparison table
      - 'group': group by (model, mode), show aggregated best-per-group
      - 'rank': rank all entries by a single chosen metric, show top N
    """
    ui.label("A/B 看板").classes("text-base font-semibold")
    ui.label(
        "支持 3 种视图：原始对比 / 按 (model, mode) 分组 / 按单指标全量排名。"
        "建议对比同一服务不同模型、同一模型不同并发、或不同服务同模型。"
    ).classes("text-xs text-slate-500")

    # View mode + group key + rank metric controls.
    with ui.row().classes("w-full items-end gap-3 flex-wrap my-2"):
        view_mode = ui.select(
            options={"pick": t("view_pick"), "group": t("view_group"), "rank": t("view_rank")},
            value="pick",
            label="视图",
        ).classes("min-w-40")
        _attach_tooltip(view_mode, t("ab_view_tooltip"))
        group_key = ui.select(
            options={"model": "按 model", "concurrency": "按 concurrency", "mode": "按 mode"},
            value="model",
            label="分组键",
        ).classes("min-w-40")
        _attach_tooltip(group_key, _TOOLTIPS["ab_group_key"])
        rank_metric = ui.select(
            options={
                "latency_ms_p50": "p50 ms（越小越好）",
                "latency_ms_p95": "p95 ms（越小越好）",
                "latency_ms_p99": "p99 ms（越小越好）",
                "throughput_rps": "req/s（越大越好）",
                "success_rate_pct": "成功率%（越大越好）",
            },
            value="latency_ms_p99",
            label="排名指标",
        ).classes("min-w-48")
        _attach_tooltip(rank_metric, _TOOLTIPS["ab_rank_metric"])

    # Picker — checkboxes for each history entry (used by 'pick' view).
    selection: dict[int, bool] = {}

    def _render_selection() -> None:
        selection_panel.clear()
        if not app_state.history:
            with selection_panel:
                ui.label("暂无历史记录").classes("text-sm text-slate-400")
            return
        with selection_panel:
            for idx, stat in enumerate(app_state.history, start=1):
                meta = stat.get("metadata") or {}
                label = f"#{idx} {(meta.get('bench_start_utc') or '')[:19]} | {meta.get('model', '?')} | c={meta.get('concurrency', '?')}"
                ui.checkbox(
                    text=label,
                    value=selection.get(idx, False),
                    on_change=lambda e, i=idx: selection.update({i: bool(e.value)}),
                )

    selected_badge = ui.badge(t("ab_selected_count", n=0), color="grey").classes("text-xs")
    selection_panel = ui.column().classes("w-full gap-1 my-3")
    _render_selection()
    ui.timer(1.0, _render_selection)

    compare_table = (
        ui.table(
            columns=[
                {"name": "metric", "label": "指标", "field": "metric", "align": "left"},
                {"name": "best", "label": "最优", "field": "best", "align": "center"},
                {"name": "worst", "label": "最差", "field": "worst", "align": "center"},
            ],
            rows=[],
            row_key="metric",
        )
        .props("dense flat")
        .classes("w-full")
    )

    detail_table = (
        ui.table(
            columns=[
                {"name": "idx", "label": "#", "field": "idx", "align": "center"},
                {"name": "label", "label": "配置", "field": "label", "align": "left"},
                {"name": "metric", "label": "指标", "field": "metric", "align": "center"},
            ],
            rows=[],
            row_key="idx",
        )
        .props("dense flat")
        .classes("w-full")
    )

    def _selected_stats() -> list[dict[str, Any]]:
        return [
            app_state.history[i - 1]
            for i, on in selection.items()
            if on and 0 < i <= len(app_state.history)
        ]

    def _refresh_compare() -> None:
        mode = view_mode.value or "pick"
        # UX#4: empty state — fewer than 2 selected entries show a single
        # hint row so the user knows they need to tick more checkboxes.
        if mode == "pick":
            selected = _selected_stats()
            selected_badge.set_text(t("ab_selected_count", n=len(selected)))
            rows = _ab_pick_view_rows(selected)
            if not selected:
                compare_table.rows[:] = [{"metric": t("select_at_least_two"), "best": "-", "worst": "-"}]
            elif not rows:
                compare_table.rows[:] = []
            else:
                compare_table.rows[:] = rows
            compare_table.update()
        elif mode == "group":
            rows = _ab_group_view_rows(app_state.history, group_key.value or "model")
            if not app_state.history:
                compare_table.rows[:] = [{"metric": t("no_history"), "best": "-", "worst": "-"}]
            elif not rows:
                compare_table.rows[:] = [{"metric": t("ab_no_group_candidates"), "best": "-", "worst": "-"}]
            else:
                compare_table.rows[:] = rows
            compare_table.update()
        else:  # rank
            rows = _ab_rank_view_rows(app_state.history, rank_metric.value or "latency_ms_p99")
            if not app_state.history:
                detail_table.rows[:] = [{"idx": "-", "label": t("no_history"), "metric": "-"}]
            elif not rows:
                detail_table.rows[:] = [{"idx": "-", "label": t("ab_no_group_candidates"), "metric": "-"}]
            else:
                detail_table.rows[:] = rows
            detail_table.update()

    def _toggle_visibility() -> None:
        mode = view_mode.value or "pick"
        is_rank = mode == "rank"
        compare_table.set_visibility(not is_rank)
        detail_table.set_visibility(is_rank)
        selection_panel.set_visibility(mode == "pick")
        group_key.set_visibility(mode == "group")
        rank_metric.set_visibility(mode == "rank")

    def _on_view_change() -> None:
        _refresh_compare()
        _toggle_visibility()

    view_mode.on_value_change(lambda _: _on_view_change())
    group_key.on_value_change(lambda _: _refresh_compare())
    rank_metric.on_value_change(lambda _: _refresh_compare())

    ui.timer(0.5, _refresh_compare)
    _toggle_visibility()


def _build_history_monitor_panel(app_state: _AppState) -> None:
    detail_json = ui.code("", language="json").classes("w-full mt-4 text-xs max-h-96 overflow-auto")
    hist_table = ui.table(
        columns=[
            {"name": "idx", "label": "#", "field": "#", "align": "center", "sortable": True},
            {"name": "time", "label": "时间", "field": "时间", "align": "left"},
            {"name": "mode", "label": "模式", "field": "模式", "align": "center"},
            {"name": "model", "label": "模型", "field": "模型", "align": "left"},
            {"name": "concurrency", "label": "并发", "field": "并发", "align": "center"},
            {"name": "success", "label": "成功率%", "field": "成功率%", "align": "center"},
            {"name": "rps", "label": "req/s", "field": "req/s", "align": "center"},
            {"name": "p50", "label": "p50 ms", "field": "p50 ms", "align": "center"},
            {"name": "p99", "label": "p99 ms", "field": "p99 ms", "align": "center"},
            {
                "name": "prompt_tokens",
                "label": "prompt tok",
                "field": "prompt tok",
                "align": "center",
            },
            {
                "name": "completion_tokens",
                "label": "completion tok",
                "field": "completion tok",
                "align": "center",
            },
            {"name": "total_tokens", "label": "total tok", "field": "total tok", "align": "center"},
        ],
        rows=[],
        row_key="id",
        selection="single",
        on_select=lambda e: (
            detail_json.set_content(
                _stats_log_preview(
                    app_state.history[int(e.selection[0]["id"]) - 1], max_chars=10_000_000
                )
            )
            if getattr(e, "selection", [])
            else None
        ),
    ).classes("w-full")
    hist_table.props("dense flat")

    export_btn = ui.button("导出全部 JSON", icon="download").props("outline")
    clear_btn = ui.button("清空历史", icon="delete_sweep").props("outline color=red")

    async def _clear_history() -> None:
        # T1-3: confirm before destructive action. Show a modal with the
        # count so the user knows what they're about to lose.
        if not app_state.history:
            ui.notify("历史已经为空", type="info")
            return
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label(f"确认清空全部 {len(app_state.history)} 条历史？").classes(
                "text-base font-semibold"
            )
            ui.label("此操作不可撤销。建议先导出 JSON 备份。").classes("text-xs text-slate-500")
            with ui.row().classes("justify-end w-full gap-2 mt-2"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("清空", on_click=lambda: dialog.submit(True)).props("color=red")
        dialog.open()
        if not await dialog:
            return
        app_state.history.clear()
        detail_json.set_content("")
        ui.notify("历史已清空", type="positive")

    def _export() -> None:
        if not app_state.history:
            ui.notify("暂无历史记录", type="warning")
            return
        _download_bytes(
            json.dumps(app_state.history, ensure_ascii=False, indent=2).encode("utf-8"),
            f"bench_history_{_timestamp_slug()}.json",
            "application/json; charset=utf-8",
        )

    export_btn.on_click(_export)
    clear_btn.on_click(_clear_history)
    _HIST_CACHE: dict[str, int] = {"len": -1}

    def _refresh() -> None:
        # Perf#1: skip the rebuild when history length hasn't changed.
        # 0.5s tick * O(history) rows is wasteful when nothing happened.
        if len(app_state.history) == _HIST_CACHE["len"]:
            return
        _HIST_CACHE["len"] = len(app_state.history)
        hist_table.rows[:] = [
            {
                "id": idx,
                "#": idx,
                "时间": (stat.get("metadata") or {})
                .get("bench_start_utc", "")[:19]
                .replace("T", " "),
                "模式": str((stat.get("metadata") or {}).get("mode", "-")),
                "模型": str((stat.get("metadata") or {}).get("model", "-")),
                "并发": str((stat.get("metadata") or {}).get("concurrency", "-")),
                "成功率%": _v(stat.get("success_rate_pct")),
                "req/s": _v(stat.get("throughput_rps")),
                "p50 ms": _v(stat.get("latency_ms_p50")),
                "p99 ms": _v(stat.get("latency_ms_p99")),
                "prompt tok": str(int(stat.get("prompt_tokens_total") or 0)),
                "completion tok": str(int(stat.get("completion_tokens_total") or 0)),
                "total tok": str(
                    int(stat.get("prompt_tokens_total") or 0)
                    + int(stat.get("completion_tokens_total") or 0)
                ),
            }
            for idx, stat in enumerate(app_state.history, start=1)
        ]
        hist_table.update()

    ui.timer(0.5, _refresh)


def _build_monitor_page(app_state: _AppState) -> None:
    _apply_page_shell(scroll_content=False)
    _build_header(f"LLM Bench Monitor  v{__version__}", app_state)
    with ui.column().classes("w-full flex-1 min-h-0 overflow-hidden"):
        with ui.tabs().classes("w-full bg-slate-50 border-b") as right_tabs:
            tab_run = ui.tab("单次压测", icon="play_arrow")
            tab_rps = ui.tab("固定 RPS", icon="speed")
            tab_sweep = ui.tab("并发扫描", icon="bar_chart")
            tab_history = ui.tab("历史记录", icon="history")
            tab_compare = ui.tab("对比", icon="compare_arrows")

        with ui.tab_panels(right_tabs, value=tab_run).classes(
            "w-full flex-1 min-h-0 overflow-hidden"
        ):
            with ui.tab_panel(tab_run).classes("p-4 h-full overflow-auto"):
                _build_run_monitor_panel("run", app_state.run_states["run"], app_state)
            with ui.tab_panel(tab_rps).classes("p-4 h-full overflow-auto"):
                _build_run_monitor_panel("rps", app_state.run_states["rps"], app_state)
            with ui.tab_panel(tab_sweep).classes("p-4 h-full overflow-auto"):
                _build_sweep_monitor_panel(app_state.sweep_state, app_state)
            with ui.tab_panel(tab_history).classes("p-4 h-full overflow-auto"):
                _build_history_monitor_panel(app_state)
            with ui.tab_panel(tab_compare).classes("p-4 h-full overflow-auto"):
                _build_compare_panel(app_state)


def launch() -> None:
    mp.freeze_support()
    app_state = _AppState()

    @ui.page("/")
    def root_page() -> None:
        ui.label("Use /control or /monitor")

    @ui.page("/control")
    async def control_page() -> None:
        await _build_control_page(app_state)

    @ui.page("/monitor")
    def monitor_page() -> None:
        _build_monitor_page(app_state)

    host = "127.0.0.1"
    port = find_open_port()
    shutdown_event = _start_dual_windows("http", host, port)
    try:
        ui.run(
            title=f"LLM Bench Desktop v{__version__}",
            host=host,
            port=port,
            show=False,
            native=False,
            reload=False,
        )
    except LocalProtocolError as exc:
        # NiceGUI hardcodes Uvicorn's wsproto backend; closing the desktop windows can
        # race with websocket shutdown and trigger this known "already closed" error.
        if not shutdown_event.is_set() or "ConnectionState.CLOSED" not in str(exc):
            raise
