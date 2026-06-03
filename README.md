# LLM Bench

**大模型 OpenAI-compatible API 压测工具（双窗口桌面 GUI）**

LLM Bench 是一个面向 Chat Completions / Responses 兼容接口的轻量压测工具。当前主入口是 `NiceGUI + pywebview` 双窗口桌面界面：`Control` 负责配置与启动，`Monitor` 负责实时监看图表、日志、响应样本、历史记录和 A/B 对比。

支持单次压测、固定 RPS、并发扫描、负载曲线四类测试，并支持标准请求体、附加 JSON、全自定义请求体、多 Prompt、代理、重试、预热、Token 预估、请求重放和 JSON/CSV 导出。

---

## 功能特性

| 类别 | 功能 |
|------|------|
| **压测模式** | 固定总请求数、固定时长、固定 RPS、并发扫描、负载曲线（多阶段 RPS） |
| **实时监看** | 运行中实时刷新 KPI、延迟分位、流式指标、在飞请求、吞吐趋势、Token 累积和请求日志 |
| **请求构造** | 标准 OpenAI 请求体、附加请求体 JSON、全自定义请求体、相对/完整 endpoint |
| **多 Prompt** | 顺序循环、均匀随机、加权随机，支持 `.txt` / `.json` 导入 |
| **Token 估算** | 本地估算 + 精确预跑估算，按当前模式推算预计请求量 |
| **可靠性** | 429/网络/5xx 分类重试、指数退避、连接池复用、预热请求、前置连通性探测 |
| **统计口径** | 逻辑请求端到端耗时、HTTP attempt 指标、最终尝试延迟、重试拖尾、错误分类 |
| **代理支持** | 直连 / 系统代理 / 自定义代理，支持常见 Clash 本地代理 |
| **诊断能力** | 主错误类型提示、响应样本表、选中请求深度重放、SSRF 防护 |
| **数据导出** | JSON 完整统计、逐请求 CSV、并发扫描 per-level raw results CSV |
| **会话分析** | 历史记录、分组视图、单指标排名、2-6 条结果 A/B 对比 |

---

## 快速开始

### 前置要求

- [uv](https://docs.astral.sh/uv/) >= 0.4
- Python >= 3.11（uv 会自动管理 Python 和虚拟环境）

```powershell
# Windows PowerShell 安装 uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 安装依赖

```bash
git clone <repo-url>
cd API_Test
uv sync
```

### 启动桌面 GUI

```bash
# 方式一：模块入口
uv run python -m llm_bench

# 方式二：项目脚本
uv run llm-bench
```

启动后会打开两个窗口：

- **Control**：连接、模型、请求体、Prompt、Token 估算、模式参数、启动/停止
- **Monitor**：实时 KPI、图表、响应样本、日志、并发扫描、历史记录、A/B 对比

### 命令行（headless / CI）

无需打开桌面窗口，可直接在终端 / CI / 无显示器服务器上压测，复用与 GUI 相同的引擎和 YAML 配置：

```bash
# 用 YAML 配置跑，把完整统计写入 JSON
uv run llm-bench bench --config bench.yaml --json result.json

# 直接用命令行参数（本地 vLLM，100 请求，并发 8）
uv run llm-bench bench --base-url http://localhost:8000/v1 --model qwen --total 100 -c 8

# 固定 RPS 压测 60 秒，逐请求结果导出 CSV
uv run llm-bench bench --config bench.yaml --rps 10 --rps-duration 60 --csv rows.csv
```

不带子命令（或 `llm-bench gui`）时仍然启动桌面 GUI，与之前行为一致。

最小 YAML 配置示例（字段同 `config.py` 的 `BenchConfig`）：

```yaml
base_url: http://localhost:8000/v1
model: qwen2.5-7b
concurrency: 8
max_tokens: 256
stream: true
prompts:
  - 用一句话解释量子纠缠
  - 写一首关于秋天的五言绝句
```

常用参数：

| 参数 | 说明 |
|------|------|
| `--config` | YAML 配置路径（缺省用内置默认值） |
| `--base-url` / `--url` | API 根路径 / 完整 endpoint（`--url` 优先） |
| `--model` / `--api-key` | 模型标识 / 密钥（缺省读 `LLM_API_KEY` / `OPENAI_API_KEY`） |
| `-c, --concurrency` | 并发数 |
| `--total` / `--duration` | 按总请求数 / 按时长（二选一，默认 total=20） |
| `--rps` / `--rps-duration` | 固定 RPS 目标 / 持续秒数 |
| `--stream` / `--no-stream` | 是否 SSE 流式（测 TTFT/ITL/TPOT 需开启） |
| `--prompts-file` | 每行一条 prompt 的文件 |
| `--json` / `--csv` | 写完整统计 JSON / 逐请求 CSV |
| `--fail-on-error` | 存在失败请求时以非 0 退出（CI 友好） |
| `-q, --quiet` | 不打印实时进度 |

完整参数见 `uv run llm-bench bench --help`。结束会打印核心指标摘要，`--json` 内容与 GUI 导出一致。

---

## 配置与保存

配置文件默认保存在 `~/.llm_bench/`，可通过 `LLM_BENCH_CONFIG_DIR` 改写。

每次保存配置时会同步写入 `last.yaml`，下次打开 Control 页面会自动加载上次配置。API Key 写盘前会被脱敏，真实密钥优先级为：

```text
界面输入 > LLM_API_KEY > OPENAI_API_KEY
```

常用配置字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| Base URL | API 根路径，标准模式会拼接 `/chat/completions` | `https://api.openai.com/v1` |
| API Key | Bearer Token，可为空后由环境变量补齐 | - |
| Model | 模型标识符 | `gpt-4o-mini` |
| 并发数 | 同时在飞的最大请求数 | `5` |
| 代理模式 | 直连 / 系统代理 / 自定义代理 | 直连 |
| max_tokens | 单次最大输出 token | `128` |
| temperature | 采样温度 | `0.2` |
| 超时 s | 单次请求超时 | `120` |
| 预热请求数 | 正式计时前请求数，不计入统计 | `0` |
| 429 / 网络 / 5xx 重试 | 分类重试次数 | `3 / 1 / 1` |
| 退避基数 s | 指数退避基础等待 | `1.0` |
| HTTP/2 | 是否启用 HTTP/2 | 关 |
| 图表刷新模式 | 按时间刷新或按完成请求数刷新 | 按时间 |

---

## 请求体与 Prompt

### 标准模式

标准模式会按 Base URL、Model、max_tokens、temperature、stream 和 Prompt 自动构造请求体。

可填写“附加请求体 JSON”，它会递归合并到基础请求体中，适合添加服务商特定字段，例如：

```json
{"thinking": {"type": "enabled"}}
```

### 全自定义模式

全自定义模式会直接发送用户提供的 JSON 请求体，并可单独设置请求路径或完整 URL。若配置了多 Prompt，工具会替换第一个 `role=user` 消息，便于用同一 body 模板做多样化压测。

### 多 Prompt

支持三种策略：

- `sequential`：按顺序循环
- `random`：均匀随机
- `weighted`：按每条 Prompt 的权重采样

Prompt 可手动新增，也可导入 `.txt` 或 `.json`。

---

## 压测模式

### 单次压测

单次压测支持两种结束条件：

- **固定总数**：发送指定数量的逻辑请求后结束
- **固定时长**：持续发送指定秒数，到时停止发新请求

Monitor 的“单次压测”页会在运行中实时刷新 KPI、延迟图、流式指标、在飞请求、吞吐趋势、Token 累积、日志和响应样本。

### 固定 RPS

固定 RPS 按目标速率持续发送请求，`concurrency` 是最大在飞上限。

当服务处理能力跟不上目标 RPS 时，调度器会跳过超出窗口的调度，不会在测试末尾无限补发拖尾请求。`rps_schedule_skipped` 可用于判断是否已经超过当前并发/服务能力。

适合测试：

- 指定 QPS 下的延迟稳定性
- 速率瓶颈和并发瓶颈的区别
- 接近生产流量形态的稳定压测

### 负载曲线

负载曲线是多阶段固定 RPS，格式为每行一个阶段：

```text
30:5
30:20
30:50
```

含义是 30 秒 5 req/s、30 秒 20 req/s、30 秒 50 req/s。支持 `#` 注释行。

Control 页会实时预览阶梯图；运行时复用 Monitor 的“固定 RPS”页，阶段内也会实时刷新图表和响应样本。每个阶段完成后会把该阶段统计写入历史记录。

### 并发扫描

并发扫描输入多个并发档位，例如：

```text
1,2,4,8,16,32
```

工具会按档位依次压测，并共享 HTTP 连接池。Monitor 的“并发扫描”页展示：

- 各档位成功率、p50/p95/p99、req/s、tok/s
- 延迟折线图
- 吞吐柱状图
- Token 吞吐图
- 推荐并发
- per-level raw results CSV 导出

---

## 实时图表

普通压测、固定 RPS、负载曲线都会在请求完成时通过进度回调更新监控状态，不必等待整轮测试结束。

当前实时图表包括：

- 延迟分位柱状图：p50/p75/p90/p95/p99/p99.9
- 流式指标图：TTFT、TPOT、ITL
- 在飞请求时序：100ms 采样
- 时序吞吐：按 1 秒 bucket 聚合 req/s 和 completion tok/s
- Token 累积时序：prompt / completion token 累计值

图表刷新可以在 Monitor 页切换：

- **按时间刷新**：0.3s / 1s / 3s / 5s
- **按请求数刷新**：每 N 个完成请求刷新一次

---

## 响应样本与重放

Monitor 的“响应”页会展示逐请求结果：

- HTTP 状态
- 成功/失败
- latency
- completion token
- 响应预览
- 原始响应/错误详情

选中一条请求后可以“重放选中”。重放会使用当时保存的原始请求 body，再结合当前 Control 配置中的 endpoint、API Key、代理和超时重新发送。为降低误操作风险，重放路径包含：

- 原始 body JSON 校验
- 私有/回环地址 SSRF 防护
- 非 chat/completions / completions / responses endpoint 的二次确认
- 非粘滞通知，避免重放提示长时间残留

---

## 指标说明

| 指标 | 含义 |
|------|------|
| **TTFT** | Time To First Token，首 token 到达时间（流式模式） |
| **TTFB** | Time To First Byte，首字节时间（非流式模式） |
| **TPOT** | Time Per Output Token，`(latency - TTFT) / completion_tokens` |
| **ITL** | Inter-Token Latency，相邻 token 间隔（流式模式） |
| **tok/s** | completion token 吞吐 |
| **在飞请求** | 已进入请求执行且尚未返回的请求数 |
| **goodput** | 成功请求数 / 总请求数 |
| **CV** | 延迟变异系数（std / mean） |
| **p99-p50** | 尾延迟展宽 |
| **HTTP attempt** | 含重试在内的实际 HTTP 尝试次数 |
| **final_attempt_latency** | 最后一次 HTTP 尝试耗时，不含前序失败与退避等待 |
| **rps_schedule_skipped** | 固定 RPS 模式因在飞上限而跳过的调度数 |

---

## 数据导出

### JSON

JSON 导出包含完整统计、timeline、错误分布和 metadata。

常用键：

- `requests_total` / `requests_success` / `requests_failed`
- `throughput_rps`
- `requests_per_sec`
- `http_attempts_per_sec`
- `latency_ms_p50` / `latency_ms_p95` / `latency_ms_p99` / `latency_ms_p99_9`
- `ttft_ms_*` / `ttfb_ms_*` / `tpot_ms_*` / `itl_ms_*`
- `prompt_tokens_total` / `completion_tokens_total`
- `timeline`
- `metadata`

示例：

```json
{
  "requests_total": 100,
  "requests_success": 98,
  "throughput_rps": 4.82,
  "latency_ms_p50": 312.4,
  "latency_ms_p99": 1205.7,
  "ttft_ms_p50": 89.3,
  "tpot_ms_p50": 22.1,
  "timeline": [
    {
      "t_start_s": 0.0,
      "t_end_s": 1.0,
      "requests": 5,
      "rps_success": 4.0
    }
  ],
  "metadata": {
    "model": "gpt-4o-mini",
    "mode": "rps",
    "endpoint": "https://api.openai.com/v1/chat/completions",
    "llm_bench_version": "0.3.0"
  }
}
```

### CSV

逐请求 CSV 字段包括：

```text
ok, status_code, latency_ms, final_attempt_latency_ms, ttft_ms, ttfb_ms,
tpot_ms, tokens_per_sec, attempt_count, retry_sleep_ms, prompt_tokens,
completion_tokens, total_tokens, output_chars, stream_chunks, itl_count,
itl_mean_ms, response_text, error_kind, error
```

并发扫描还支持导出每个档位的 per-level raw results。

---

## 开发工作流

```bash
# 安装/同步依赖
uv sync

# 添加运行时依赖
uv add <package>

# 添加开发依赖
uv add --group dev <package>

# lint
uv run ruff check llm_bench tests

# 自动修复 lint
uv run ruff check llm_bench tests --fix

# 格式化
uv run ruff format llm_bench tests

# 类型检查
uv run mypy llm_bench

# 运行测试
uv run pytest -q
```

---

## 项目结构

```text
llm_bench/
├── __init__.py      # 版本号
├── __main__.py      # 入口：路由到 CLI（无子命令→GUI，bench→headless）
├── cli.py           # 命令行 / headless 压测入口（复用引擎，不依赖 GUI）
├── gui_dual.py      # 当前主 GUI（Control + Monitor）
├── gui_ng.py        # 旧单窗口实现，保留复用工具和参考
├── runner.py        # 异步压测引擎
├── models.py        # RequestResult / BenchSummary / build_stats_dict
├── tokens.py        # 本地和精确预跑 Token 估算
└── config.py        # 配置目录、环境变量、pydantic 配置
```

### 核心模块

**`runner.py`**

- `run_benchmark()` 支持 total / duration / fixed RPS
- `progress_callback` 在请求完成时回传 `BenchSummary`，GUI 用它实时渲染图表
- `timeline_bucket_s` 支持按时间 bucket 聚合吞吐和 token
- `raw_results` 保存逐请求结果，用于响应表、CSV 和重放
- `_one_with_retry()` 实现分类重试和端到端逻辑请求统计
- SSE 解析采集 TTFT、ITL、TPOT

**`models.py`**

- `RequestResult`：单次逻辑请求结果
- `TimelineBucket`：时序分桶统计
- `BenchSummary`：聚合统计、错误分布、token、in-flight 样本
- `build_stats_dict()`：转换为可导出的统计字典

**`gui_dual.py`**

- Control / Monitor 双窗口
- 配置加载保存和 `last.yaml` 自动恢复
- 四类压测模式 UI
- 实时图表、响应样本、重放、历史记录和 A/B 对比
- WebView2 黑屏规避：默认注入 `--disable-gpu`，可用 `LLM_BENCH_WEBVIEW2_DISABLE_GPU=0` 关闭

---

## 依赖

| 包 | 用途 |
|----|------|
| `httpx[http2]` | 异步 HTTP、HTTP/2、SSE |
| `nicegui` | GUI 页面和组件 |
| `pywebview` | Windows 桌面窗口壳体 |
| `pydantic` | 配置模型 |
| `pydantic-settings` | 环境变量读取 |
| `pyyaml` | YAML 配置 |
| `tiktoken` | 本地 Token 估算 |

开发依赖见 `pyproject.toml` 的 `dependency-groups.dev`。

---

## 常见问题

**Q: 打开桌面窗口是纯黑的？**

Windows WebView2 在部分显卡/驱动组合下会出现黑屏。当前版本默认给 WebView2 注入 `--disable-gpu` 规避。如果你确认本机不需要该规避，可设置：

```powershell
$env:LLM_BENCH_WEBVIEW2_DISABLE_GPU="0"
uv run llm-bench
```

**Q: 如何测试本地模型（vLLM / Ollama）？**

Base URL 填本地 OpenAI-compatible 地址，例如：

- vLLM: `http://localhost:8000/v1`
- Ollama: `http://localhost:11434/v1`

API Key 填任意非空字符串即可，除非你的服务端强制校验。

**Q: 流式模式下 TPOT/ITL 为空？**

需要服务端按 SSE 返回包含 `content` 的 delta。部分服务会批量发送多个 token 或不返回 token 级 chunk，ITL 采样会变少或为空。

**Q: 为什么固定 RPS 达不到目标？**

固定 RPS 受 `concurrency` 和服务响应时间共同限制。如果在飞请求达到上限，调度器会跳过超额调度。查看 `rps_schedule_skipped`，必要时提高并发或降低目标 RPS。

**Q: 并发扫描结果波动很大？**

增加“每档请求数”（建议 >= 100）并设置预热请求。跨模型或跨服务对比时，建议保持 Prompt、stream、max_tokens、重试配置一致。

**Q: 429 重试后的延迟是否包含等待时间？**

包含。`latency_ms` 是逻辑请求端到端耗时，包含失败尝试、退避等待和最终尝试。若要看最后一次实际 HTTP 请求耗时，请看 `final_attempt_latency_ms`。

**Q: 报 `JSON decode: Expecting value` 怎么看？**

通常是服务端返回了空响应、HTML、代理错误页或非 JSON 内容。先看响应样本和错误分类，再检查 Base URL、endpoint、API Key、代理和服务端协议是否兼容。

---

## License

MIT
