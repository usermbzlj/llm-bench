# LLM Bench

**大模型 Chat Completions API 压测工具（双窗口桌面 GUI）**

针对 OpenAI 兼容接口的高性能异步压测工具，提供 Windows 优先的 `NiceGUI + pywebview` 桌面 GUI，支持单次压测、固定 RPS、并发扫描三种测试模式，并提供“全自定义请求体覆盖”能力，实时展示延迟分位、TTFT/TPOT/ITL 流式指标、吞吐与并发趋势等核心图表。

---

## 功能特性

| 类别 | 功能 |
|------|------|
| **压测模式** | 固定总请求数、固定时长、固定 RPS（令牌桶）、并发扫描（多档位） |
| **自定义能力** | 在连接配置中开启“全自定义请求体（覆盖默认）”，可覆盖默认请求构造并对所有模式生效 |
| **性能指标** | 延迟 p50/p75/p90/p95/p99/p99.9、TTFT、TTFB、TPOT、ITL、tok/s |
| **实时可视化** | 延迟分位柱状图、流式指标对比图、吞吐趋势、在飞请求时序、实时请求日志栏 |
| **并发控制** | asyncio Semaphore 精确控制在飞请求数，Queue 分发无锁竞争 |
| **可靠性** | 429/网络/5xx 分类重试、连接池复用、预热请求、前置连通性测试 |
| **统计口径** | 默认按逻辑请求端到端耗时统计，同时补充 HTTP attempt 级指标与最终尝试延迟 |
| **代理支持** | 直连 / 系统代理 / 自定义代理地址（兼容 Clash 常见配置） |
| **多 Prompt** | 多条 Prompt 轮换发送，模拟真实多样化流量 |
| **数据导出** | JSON（完整统计）、CSV（逐请求原始数据） |
| **历史记录** | 会话内自动追加，支持点击查看详情、批量导出 |

---

## 快速开始

### 前置要求

- [uv](https://docs.astral.sh/uv/) ≥ 0.4（推荐安装方式见下）
- Python ≥ 3.11（uv 会自动管理，无需手动安装）

```bash
# 安装 uv（Windows PowerShell）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 安装 uv（macOS / Linux）
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 克隆并初始化环境

```bash
git clone <repo-url>
cd API_Test

# 一键创建虚拟环境并安装所有依赖（含开发工具）
uv sync
```

### 启动桌面 GUI

```bash
# 方式一：通过模块入口
uv run python -m llm_bench

# 方式二：通过安装的脚本
uv run llm-bench
```

启动后会同时打开两个原生桌面窗口：

- `Control`：连接配置、请求参数、模式选择、启动与停止
- `Monitor`：实时图表、日志、扫描结果、历史记录

## 开发工作流

```bash
# 添加运行时依赖
uv add <package>

# 添加开发依赖
uv add --group dev <package>

# 代码格式化 & lint
uv run ruff check llm_bench --fix
uv run ruff format llm_bench

# 类型检查
uv run mypy llm_bench

# 运行测试
uv run pytest
```

---

## 界面说明

### 左侧：连接 & 模型配置

左侧配置面板一次填写，三个压测模式共用：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| Base URL | API 根路径，自动拼接 `/chat/completions`；非法路径会直接拦截 | `https://api.openai.com/v1` |
| API Key | Bearer Token，也可通过环境变量传入 | — |
| Model | 模型名称 | `gpt-4o-mini` |
| 并发数 | 同时在飞的最大请求数（Semaphore） | `5` |
| 代理模式 | 直连/系统代理/自定义代理 | `直连` |
| 代理地址 | 仅在“自定义代理”时生效 | `http://127.0.0.1:7890` |
| 连通性测试 | 压测前验证地址可达性和网络链路 | 按钮触发 |
| max_tokens | 单次生成最大 token 数 | `128` |
| temperature | 采样温度 | `0.2` |
| 超时 s | 单次请求超时秒数 | `120` |
| 预热请求数 | 正式计时前发送的预热请求（不计入统计） | `0` |
| 429 重试次数 | 遇到限速时的额外重试次数 | `3` |
| 网络错误重试 | 网络抖动、连接超时、代理错误时的重试次数 | `1` |
| 5xx 重试次数 | 服务端临时错误的重试次数 | `1` |
| 退避基数 s | 指数退避的基础等待时间 | `1.0` |
| 流式 (stream) | 开启 SSE 流式输出，采集 TTFT/ITL；启用全自定义请求体后隐藏 | 关 |
| HTTP/2 | 启用 HTTP/2（需服务端支持） | 关 |
| 多 Prompt | 每行一条，轮换发送；启用全自定义请求体后隐藏 | — |
| 全自定义请求体 | 自己提供完整 JSON 请求体，并覆盖默认模型/采样参数/Prompt | 关 |

> **API Key 优先级**：界面输入 > 环境变量 `LLM_API_KEY` > 环境变量 `OPENAI_API_KEY`

> **配置目录位置**：GUI 加载/保存的 YAML 配置默认在 `~/.llm_bench/`（跨 cwd 稳定），可通过 `LLM_BENCH_CONFIG_DIR` 环境变量改写。

---

### 单次压测

两种模式二选一：

- **固定总数**：发送指定数量的请求后结束
- **固定时长**：持续发送指定秒数后结束（时长 > 0 时生效）

压测进行中实时更新 5 个 KPI 卡片；完成后展示概览表、核心图表和详细日志。

日志页会分为“实时日志”和“运行日志 / 统计 JSON”两块，便于定位异常。

---

### 固定 RPS

按目标速率（每秒请求数）持续发送请求，`--concurrency` 作为在飞上限。

当服务处理能力跟不上目标 RPS 时，调度器会在时间窗口内跳过超额调度，而不是无限补发拖尾请求。

适合测试：
- 服务在特定 QPS 下的延迟稳定性
- 区分"并发瓶颈"与"速率瓶颈"
- 模拟真实生产流量形态

---

### 并发扫描

输入多个并发级别（如 `1,2,4,8,16`），依次压测每个档位并共享 HTTP 连接池。

完成后展示：
- **对比表格**：各档位成功率、延迟分位、TTFT/TPOT/ITL、吞吐、tok/s
- **延迟折线图**：p50/p95/p99 随并发变化趋势
- **吞吐柱状图**：req/s 随并发变化

---

### 历史记录

每次压测完成后自动追加，保存在当前 GUI 会话内。

- 点击任意行展开完整指标
- 支持导出全部历史为 JSON
- 支持一键清空

---

## 指标说明

| 指标 | 含义 |
|------|------|
| **TTFT** | Time To First Token，首 token 到达时间（流式模式） |
| **TTFB** | Time To First Byte，首字节时间（非流式模式） |
| **TPOT** | Time Per Output Token，`(latency - TTFT) / completion_tokens` |
| **ITL** | Inter-Token Latency，相邻 token 之间的时间间隔（流式模式） |
| **tok/s** | 单请求维度的生成速率，展示 p50/p95 分布 |
| **在飞请求** | 已进入 Semaphore 且尚未返回的请求数，100ms 采样一次 |
| **goodput** | 成功请求数 / 总请求数 |
| **CV** | 延迟变异系数（std/mean），衡量延迟稳定性 |
| **p99−p50** | 尾延迟展宽，衡量长尾效应 |

---

## 数据导出

### JSON（完整统计）

包含所有分位数、token 统计、错误分布、metadata（时间戳、模型、端点、版本）。

> **重要键名**：`requests_per_sec` 是逻辑请求 RPS；`http_attempts_per_sec` 是 HTTP attempt RPS（含重试）；`goodput_fraction` = `success / total`；百分位键统一 `p50 / p75 / p90 / p95 / p99 / p99_9`。

```json
{
  "requests_total": 100,
  "requests_success": 98,
  "throughput_rps": 4.82,
  "latency_ms_p50": 312.4,
  "latency_ms_p99": 1205.7,
  "ttft_ms_p50": 89.3,
  "tpot_ms_p50": 22.1,
  "itl_ms_p50": 24.8,
  "metadata": {
    "bench_start_utc": "2026-04-12T10:30:00+00:00",
    "model": "gpt-4o-mini",
    "endpoint": "https://api.openai.com/v1/chat/completions",
    "llm_bench_version": "0.3.0"
  }
}
```

### CSV（逐请求原始数据）

每行一次逻辑请求，字段包括：

`ok, status_code, latency_ms, final_attempt_latency_ms, ttft_ms, ttfb_ms, tpot_ms, tokens_per_sec, attempt_count, retry_sleep_ms, prompt_tokens, completion_tokens, total_tokens, output_chars, stream_chunks, itl_count, itl_mean_ms, response_text, error_kind, error`

> `response_text` 是 500 字符截断的模型输出，便于在 Excel 里快速定位样本。

---

## 项目结构

```
llm_bench/
├── __init__.py      # 版本号
├── __main__.py      # 入口：默认启动双窗口桌面 GUI
├── gui_dual.py      # 双窗口桌面 GUI（Control + Monitor）
├── gui_ng.py        # 旧的单窗口 NiceGUI 实现（保留参考）
├── runner.py        # 异步压测引擎（run_benchmark）
├── models.py        # 数据模型（RequestResult / BenchSummary / build_stats_dict）
└── config.py        # pydantic 配置模型 + 环境变量读取
```

### 核心模块

**`runner.py`** — 压测引擎

- `run_benchmark()` 支持三种模式：total / duration / rps
- asyncio Semaphore 精确控制并发，`do_one` 在 sem 内 mark_started/finished，in_flight 语义准确
- `_one_with_retry()` 实现 429 指数退避重试，并按逻辑请求输出端到端耗时
- `_sse_process_line()` 解析 SSE 流，采集 TTFT / ITL
- `inflight_sampler` 协程每 100ms 采样在飞请求数

**`models.py`** — 统计模型

- `RequestResult`：单次请求结果，含 `itl_ms[]`、`tpot_ms`、`tokens_per_sec`、`ttfb_ms`
- `BenchSummary`：聚合统计，含 `tpot_ms[]`、`tokens_per_sec_per_req[]`、`itl_ms_all[]`、`in_flight_samples[]`
- `build_stats_dict()`：输出完整统计字典，含所有分位数和 metadata

---

## 依赖

| 包 | 用途 |
|----|------|
| `httpx[http2]` | 异步 HTTP 客户端，支持 HTTP/2 和 SSE 流式 |
| `nicegui` | Web 技术栈驱动的桌面 GUI 与交互组件 |
| `pywebview` | 原生桌面窗口壳体 |
| `matplotlib` | 嵌入式图表绘制 |
| `pydantic` | 数据模型与校验 |
| `pydantic-settings` | 环境变量读取 |
| `pyyaml` | YAML 配置文件加载 |
| `rich` | （保留，未来 CLI 扩展用） |
| `typer` | （保留，未来 CLI 扩展用） |

---

## 常见问题

**Q: 如何测试本地部署的模型（如 vLLM / Ollama）？**

将 Base URL 改为本地地址，例如 `http://localhost:8000/v1`（vLLM）或 `http://localhost:11434/v1`（Ollama），API Key 填任意非空字符串。

**Q: 流式模式下 TPOT/ITL 为空？**

需要服务端在 SSE 流中返回包含 `content` 的 delta，且每个 token 单独一个 chunk。部分服务会批量发送，导致 ITL 采样点少。

**Q: 并发扫描时每档结果差异很大？**

可适当增加「每档请求数」（建议 ≥ 100）以减少统计噪声，或开启「预热请求数」消除冷启动影响。

**Q: 429 重试后延迟数据是否包含等待时间？**

包含。默认 `latency_ms` 统计逻辑请求的端到端耗时，覆盖失败尝试、退避等待和最终成功请求；若需看最后一次实际请求耗时，可查看 `final_attempt_latency_ms`。

---

## License

MIT
