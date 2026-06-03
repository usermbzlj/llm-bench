"""LLM API 异步压测引擎。

公共 API（``__all__``）：
    - :func:`run_benchmark`        — 压测主入口
    - :func:`one_chat_request`     — 一次 Chat Completions 请求
    - :func:`probe_connectivity`   — 前置连通性测试
    - :func:`resolve_proxy`        — GUI/CLI 代理配置 → httpx 参数
    - :func:`prompt_request_distribution` — 多 prompt 轮换分配
    - :func:`normalize_prompt_strategy` / :func:`normalize_prompt_weights`
    - :func:`limits_for_concurrency`      — httpx 共享连接池上限
    - :func:`failure_result_from_exception` — 异常隔离 helper
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx

from llm_bench.models import BenchSummary, ErrorKind, RequestResult

_RESPONSE_TEXT_LIMIT = 4000


def normalize_prompt_strategy(prompt_strategy: str | None) -> str:
    raw = (prompt_strategy or "sequential").strip().lower()
    if raw in {"sequential", "random", "weighted"}:
        return raw
    return "sequential"


def normalize_prompt_weights(prompts: list[str], prompt_weights: list[float] | None) -> list[float]:
    if not prompts:
        return []
    if not prompt_weights:
        return [1.0] * len(prompts)
    out: list[float] = []
    for index in range(len(prompts)):
        try:
            raw = float(prompt_weights[index]) if index < len(prompt_weights) else 1.0
        except (TypeError, ValueError):
            raw = 1.0
        out.append(raw if raw > 0 else 1.0)
    return out


def prompt_request_distribution(
    total_requests: int,
    prompts: list[str],
    *,
    prompt_strategy: str = "sequential",
    prompt_weights: list[float] | None = None,
) -> list[float]:
    if total_requests <= 0 or not prompts:
        return []
    strategy = normalize_prompt_strategy(prompt_strategy)
    n = len(prompts)
    if strategy == "sequential":
        base = total_requests // n
        remainder = total_requests % n
        return [float(base + (1 if idx < remainder else 0)) for idx in range(n)]
    if strategy == "random":
        each = float(total_requests) / float(n)
        return [each] * n
    weights = normalize_prompt_weights(prompts, prompt_weights)
    total_weight = sum(weights)
    if total_weight <= 0:
        each = float(total_requests) / float(n)
        return [each] * n
    return [float(total_requests) * (weight / total_weight) for weight in weights]


def _extract_usage(data: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    u = data.get("usage") or {}
    pt, ct, tt = u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens")

    def _i(x: Any) -> int | None:
        try:
            return int(x) if x is not None else None
        except (TypeError, ValueError):
            return None

    return _i(pt), _i(ct), _i(tt)


def _classify_error(
    *,
    status_code: int | None,
    err: str | None,
    exc: BaseException | None,
) -> ErrorKind:
    if exc is not None:
        if isinstance(exc, httpx.ProxyError):
            return ErrorKind.PROXY
        if isinstance(exc, httpx.ConnectError):
            return ErrorKind.CONNECT
        if isinstance(exc, httpx.TimeoutException):
            return ErrorKind.TIMEOUT
        if isinstance(exc, httpx.RequestError):
            return ErrorKind.NETWORK
    if err and "timeout" in err.lower():
        return ErrorKind.TIMEOUT
    if err and ("proxy" in err.lower() or "socks" in err.lower()):
        return ErrorKind.PROXY
    if status_code == 429:
        return ErrorKind.RATE_LIMIT
    if status_code in (401, 403):
        return ErrorKind.AUTH
    if status_code is not None and status_code >= 500:
        return ErrorKind.SERVER_ERROR
    if status_code is not None and 400 <= status_code < 500:
        return ErrorKind.CLIENT_ERROR
    if err and ("JSON" in err or "json" in err or "parse" in err.lower()):
        return ErrorKind.PARSE
    if err:
        return ErrorKind.OTHER
    return ErrorKind.NONE


def _raise_if_should_stop(should_stop: Callable[[], bool] | None) -> None:
    """模块级 stop 守卫：被 should_stop() 触发时抛 CancelledError。"""
    if should_stop is not None and should_stop():
        raise asyncio.CancelledError()


def _usage_from_dict(usage: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    try:
        pt = int(usage["prompt_tokens"]) if usage.get("prompt_tokens") is not None else None
        ct = int(usage["completion_tokens"]) if usage.get("completion_tokens") is not None else None
        tt = int(usage["total_tokens"]) if usage.get("total_tokens") is not None else None
        return pt, ct, tt
    except (TypeError, ValueError, KeyError):
        return None, None, None


def _clip_response_text(text: str | None, *, limit: int = _RESPONSE_TEXT_LIMIT) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    suffix = "\n... (响应内容已截断)"
    return cleaned[: max(0, limit - len(suffix))].rstrip() + suffix


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_to_text(item) for item in content)
    if isinstance(content, dict):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value
        if isinstance(text_value, dict):
            nested_value = text_value.get("value")
            if isinstance(nested_value, str):
                return nested_value
        nested_content = content.get("content")
        if nested_content is not None:
            return _content_to_text(nested_content)
    return ""


def _extract_response_text(data: dict[str, Any]) -> str | None:
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return _clip_response_text(output_text)

    for choice in data.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            text = _content_to_text(message.get("content"))
            if text.strip():
                return _clip_response_text(text)
        text = _content_to_text(choice.get("text"))
        if text.strip():
            return _clip_response_text(text)

    output_blocks = data.get("output")
    if isinstance(output_blocks, list):
        text = "".join(_content_to_text(block) for block in output_blocks)
        if text.strip():
            return _clip_response_text(text)
    return None


def _sse_process_line(
    line: str,
    *,
    usage_holder: list[dict[str, Any] | None],
    output_chars: list[int],
    stream_chunks: list[int],
    response_parts: list[str],
    itl_ms: list[float],
    prev_content_mono: list[float | None],
    ttft_holder: list[float | None],
    t0: float,
) -> None:
    line = line.strip()
    if not line.startswith("data:"):
        return
    payload = line[5:].strip()
    if payload == "[DONE]":
        return
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return
    stream_chunks[0] += 1
    u = obj.get("usage")
    if isinstance(u, dict):
        usage_holder[0] = u
    for choice in obj.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict):
            c = delta.get("content")
            if isinstance(c, str) and c:
                response_parts.append(c)
                output_chars[0] += len(c)
                now = time.perf_counter()
                if ttft_holder[0] is None:
                    ttft_holder[0] = (now - t0) * 1000.0
                prev = prev_content_mono[0]
                if prev is not None:
                    itl_ms.append((now - prev) * 1000.0)
                prev_content_mono[0] = now


def _finalize_derived_metrics(
    *,
    latency_ms: float,
    ttft_ms: float | None,
    completion_tokens: int | None,
) -> tuple[float | None, float | None]:
    tpot_ms: float | None = None
    tokens_per_sec: float | None = None
    if completion_tokens is not None and completion_tokens > 0 and latency_ms > 0:
        tokens_per_sec = completion_tokens / (latency_ms / 1000.0)
    if (
        completion_tokens is not None
        and completion_tokens > 0
        and ttft_ms is not None
        and latency_ms > ttft_ms
    ):
        tpot_ms = (latency_ms - ttft_ms) / float(completion_tokens)
    return tpot_ms, tokens_per_sec


def _pick_prompt_index(
    idx: int,
    prompts: list[str],
    *,
    prompt_strategy: str,
    prompt_weights: list[float] | None,
) -> int:
    if not prompts:
        return 0
    strategy = normalize_prompt_strategy(prompt_strategy)
    if strategy == "sequential":
        return idx % len(prompts)
    if strategy == "random":
        return random.randrange(len(prompts))
    weights = normalize_prompt_weights(prompts, prompt_weights)
    try:
        return random.choices(range(len(prompts)), weights=weights, k=1)[0]
    except (IndexError, ValueError):
        return idx % len(prompts)


def _body_for_index(
    body_template: dict[str, Any],
    idx: int,
    prompts: list[str] | None,
    stream: bool,
    *,
    prompt_strategy: str = "sequential",
    prompt_weights: list[float] | None = None,
) -> dict[str, Any]:
    body = copy.deepcopy(body_template)
    if stream:
        body["stream"] = True
    if prompts:
        prompt = prompts[
            _pick_prompt_index(
                idx, prompts, prompt_strategy=prompt_strategy, prompt_weights=prompt_weights
            )
        ]
        msgs = body.get("messages")
        # `body` is already a deep copy; mutate its messages list in place.
        if not isinstance(msgs, list) or not msgs:
            body["messages"] = [{"role": "user", "content": prompt}]
        else:
            placed = False
            for i, m in enumerate(msgs):
                if isinstance(m, dict) and m.get("role") == "user":
                    msgs[i] = {**m, "content": prompt}
                    placed = True
                    break
            if not placed:
                msgs.append({"role": "user", "content": prompt})
            body["messages"] = msgs
    return body


async def one_chat_request(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    stream: bool,
    timeout_s: float,
    should_stop: Callable[[], bool] | None = None,
) -> RequestResult:
    """发出一次 Chat Completions 请求并返回结果。

    Args:
        client: 复用的 httpx 异步客户端。
        url: 完整 endpoint URL。
        headers: 请求头（通常含 Authorization）。
        body: 已构造好的 JSON body。
        stream: 是否走 SSE 流式。
        timeout_s: 单次请求超时。
        should_stop: 每 ~1KB 流数据后会被调用一次；如果返回 True 则抛出
            ``asyncio.CancelledError`` 中断读取。可为 None 表示不可中断。
    """
    t0 = time.perf_counter()
    ttft_ms: float | None = None
    ttfb_ms: float | None = None
    status_code: int | None = None
    err: str | None = None
    err_kind = ErrorKind.NONE
    raw_len = 0
    prompt_t = completion_t = total_t = None
    json_ok = False
    output_chars = 0
    response_text: str | None = None
    raw_response_text: str | None = None
    stream_chunks = 0
    itl_ms: list[float] = []
    caught: BaseException | None = None
    # Capture the exact JSON body for replay. Done once at the top so both
    # the stream and non-stream branches share the same snapshot.
    try:
        raw_request_body: str | None = json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        raw_request_body = None

    def _check_stop() -> None:
        if should_stop is not None and should_stop():
            raise asyncio.CancelledError()

    try:
        if stream:
            usage_holder: list[dict[str, Any] | None] = [None]
            out_chars_list = [0]
            chunks_list = [0]
            response_parts: list[str] = []
            prev_content_mono: list[float | None] = [None]
            ttft_holder: list[float | None] = [None]

            async with client.stream(
                "POST", url, headers=headers, json=body, timeout=timeout_s
            ) as resp:
                status_code = resp.status_code
                # List-based line buffer is O(n); avoids O(n^2) `buf += piece` per chunk.
                buf_parts: list[str] = []
                pieces_all: list[str] = []
                async for piece in resp.aiter_text():
                    pieces_all.append(piece)
                    raw_len += len(piece.encode("utf-8", errors="replace"))
                    if ttfb_ms is None and piece:
                        ttfb_ms = (time.perf_counter() - t0) * 1000.0
                    buf_parts.append(piece)
                    # Periodically check stop without flushing full SSE lines.
                    if should_stop is not None and len(buf_parts) >= 8:
                        _check_stop()
                    # Drain complete lines from the buffer tail.
                    while True:
                        buf = "".join(buf_parts)
                        nl = buf.find("\n")
                        if nl < 0:
                            break
                        line = buf[:nl]
                        buf_parts = [buf[nl + 1 :]]
                        _sse_process_line(
                            line,
                            usage_holder=usage_holder,
                            output_chars=out_chars_list,
                            stream_chunks=chunks_list,
                            response_parts=response_parts,
                            itl_ms=itl_ms,
                            prev_content_mono=prev_content_mono,
                            ttft_holder=ttft_holder,
                            t0=t0,
                        )
                _check_stop()
                # Flush any trailing partial line.
                for line in "".join(buf_parts).splitlines():
                    _sse_process_line(
                        line,
                        usage_holder=usage_holder,
                        output_chars=out_chars_list,
                        stream_chunks=chunks_list,
                        response_parts=response_parts,
                        itl_ms=itl_ms,
                        prev_content_mono=prev_content_mono,
                        ttft_holder=ttft_holder,
                        t0=t0,
                    )

                response_text = _clip_response_text("".join(response_parts))
                raw_response_text = _clip_response_text("".join(pieces_all))
                if status_code != 200:
                    response_text = None
                    err = raw_response_text or resp.reason_phrase
                else:
                    json_ok = True
                    usage = usage_holder[0]
                    output_chars = out_chars_list[0]
                    stream_chunks = chunks_list[0]
                    ttft_ms = ttft_holder[0]
                    if usage:
                        prompt_t, completion_t, total_t = _usage_from_dict(usage)
        else:
            async with client.stream(
                "POST", url, headers=headers, json=body, timeout=timeout_s
            ) as resp:
                status_code = resp.status_code
                parts: list[bytes] = []
                async for chunk in resp.aiter_bytes():
                    raw_len += len(chunk)
                    if ttfb_ms is None and chunk:
                        ttfb_ms = (time.perf_counter() - t0) * 1000.0
                    parts.append(chunk)
                    if should_stop is not None and len(parts) >= 4:
                        _check_stop()
                _check_stop()
                raw_body = b"".join(parts)
                raw_text = raw_body.decode("utf-8", errors="replace")
                raw_response_text = _clip_response_text(raw_text)

            if status_code != 200:
                response_text = None
                err = raw_response_text or ""
            else:
                try:
                    data = json.loads(raw_text)
                    json_ok = True
                    prompt_t, completion_t, total_t = _extract_usage(data)
                    response_text = _extract_response_text(data)
                except json.JSONDecodeError as e:
                    response_text = None
                    err = f"JSON decode: {e}"
    except asyncio.CancelledError:
        # Raised by _check_stop(); let the caller (retry wrapper or scheduler) handle it.
        raise
    except httpx.TimeoutException as e:
        caught = e
        err = f"timeout: {e}"
    except httpx.RequestError as e:
        caught = e
        err = f"request_error: {e}"

    latency_ms = (time.perf_counter() - t0) * 1000.0
    ok = status_code == 200 and err is None
    if ok and not stream and not json_ok:
        ok = False
    if not ok and err_kind == ErrorKind.NONE:
        err_kind = _classify_error(status_code=status_code, err=err, exc=caught)

    # Per-attempt tpot / tokens_per_sec are intentionally NOT computed here:
    # _one_with_retry recomputes them on the end-to-end latency after all attempts
    # finish. Returning None here keeps the per-attempt result semantically "raw".

    return RequestResult(
        ok=ok,
        status_code=status_code,
        latency_ms=latency_ms,
        error=err,
        response_text=response_text,
        raw_response_text=raw_response_text,
        error_kind=err_kind,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        total_tokens=total_t,
        response_bytes=raw_len,
        ttft_ms=ttft_ms,
        ttfb_ms=ttfb_ms,
        json_parse_ok=json_ok,
        output_chars=output_chars,
        stream_chunks=stream_chunks,
        itl_ms=itl_ms,
        tpot_ms=None,
        tokens_per_sec=None,
        raw_request_body=raw_request_body,
    )


def failure_result_from_exception(
    exc: BaseException,
    *,
    attempt_count: int = 1,
) -> RequestResult:
    """把任务内未捕获的异常转成一个失败 RequestResult。

    用于异常隔离：让一个失败请求不会拖垮整个 benchmark。
    复用 ``_classify_error`` 推断 ErrorKind。
    """
    err_kind = _classify_error(status_code=None, err=str(exc), exc=exc)
    return RequestResult(
        ok=False,
        status_code=None,
        latency_ms=0.0,
        error=f"engine_error: {type(exc).__name__}: {exc}",
        error_kind=err_kind,
        attempt_count=attempt_count,
    )


async def _one_with_retry(
    send_once: Callable[[], Any],
    *,
    stream: bool,
    retry_on_429: int,
    retry_on_network: int,
    retry_on_5xx: int,
    base_backoff_s: float,
    attempt_callback: Callable[[RequestResult], Any] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RequestResult:
    def check_stop() -> None:
        _raise_if_should_stop(should_stop)

    started_at = time.perf_counter()
    last: RequestResult | None = None
    attempt_count = 0
    retry_sleep_ms = 0.0
    attempts = 1 + max(0, retry_on_429) + max(0, retry_on_network) + max(0, retry_on_5xx)
    r429_left = max(0, retry_on_429)
    net_left = max(0, retry_on_network)
    s5xx_left = max(0, retry_on_5xx)
    for retry_idx, _ in enumerate(range(attempts)):
        check_stop()
        attempt_count += 1
        last = await send_once()
        if attempt_callback is not None:
            attempt_callback(last)
        should_retry = False
        if last.error_kind == ErrorKind.RATE_LIMIT and r429_left > 0:
            r429_left -= 1
            should_retry = True
        elif (
            last.error_kind
            in (ErrorKind.NETWORK, ErrorKind.CONNECT, ErrorKind.TIMEOUT, ErrorKind.PROXY)
            and net_left > 0
        ):
            net_left -= 1
            should_retry = True
        elif last.error_kind == ErrorKind.SERVER_ERROR and s5xx_left > 0:
            s5xx_left -= 1
            should_retry = True
        if not should_retry:
            break
        delay = base_backoff_s * (2**retry_idx)
        retry_sleep_ms += delay * 1000.0
        await asyncio.sleep(delay)
        check_stop()
    assert last is not None
    total_latency_ms = (time.perf_counter() - started_at) * 1000.0
    final_attempt_latency_ms = last.latency_ms
    prefinal_ms = max(0.0, total_latency_ms - final_attempt_latency_ms)
    ttft_ms = (prefinal_ms + last.ttft_ms) if last.ttft_ms is not None else None
    ttfb_ms = (prefinal_ms + last.ttfb_ms) if last.ttfb_ms is not None else None
    tpot_ms, tokens_per_sec = _finalize_derived_metrics(
        latency_ms=total_latency_ms,
        ttft_ms=ttft_ms if stream else ttfb_ms,
        completion_tokens=last.completion_tokens,
    )
    return RequestResult(
        ok=last.ok,
        status_code=last.status_code,
        latency_ms=total_latency_ms,
        error=last.error,
        response_text=last.response_text,
        raw_response_text=last.raw_response_text,
        error_kind=last.error_kind,
        prompt_tokens=last.prompt_tokens,
        completion_tokens=last.completion_tokens,
        total_tokens=last.total_tokens,
        response_bytes=last.response_bytes,
        ttft_ms=ttft_ms,
        ttfb_ms=ttfb_ms,
        json_parse_ok=last.json_parse_ok,
        output_chars=last.output_chars,
        stream_chunks=last.stream_chunks,
        itl_ms=list(last.itl_ms),
        tpot_ms=tpot_ms,
        tokens_per_sec=tokens_per_sec,
        final_attempt_latency_ms=final_attempt_latency_ms,
        attempt_count=attempt_count,
        retry_sleep_ms=retry_sleep_ms,
        # Sec#1 polish: the retry wrapper previously dropped the
        # per-attempt `raw_request_body` snapshot, breaking deep
        # replay for the 100% of results that go through retries.
        raw_request_body=last.raw_request_body,
    )


async def _warmup(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body_template: dict[str, Any],
    *,
    n: int,
    stream: bool,
    timeout_s: float,
    concurrency: int,
    prompts: list[str] | None,
    prompt_strategy: str,
    prompt_weights: list[float] | None,
    retry_on_429: int,
    retry_on_network: int,
    retry_on_5xx: int,
    base_backoff_s: float = 1.0,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    if n <= 0:
        return
    sem = asyncio.Semaphore(max(1, concurrency))

    async def once(i: int) -> None:
        body = _body_for_index(
            body_template,
            i,
            prompts,
            stream,
            prompt_strategy=prompt_strategy,
            prompt_weights=prompt_weights,
        )

        async def send_once() -> RequestResult:
            async with sem:
                return await one_chat_request(
                    client,
                    url,
                    headers,
                    body,
                    stream=stream,
                    timeout_s=timeout_s,
                    should_stop=should_stop,
                )

        await _one_with_retry(
            send_once,
            stream=stream,
            retry_on_429=retry_on_429,
            retry_on_network=retry_on_network,
            retry_on_5xx=retry_on_5xx,
            base_backoff_s=base_backoff_s,
            should_stop=should_stop,
        )

    await asyncio.gather(*(once(i) for i in range(n)))


def limits_for_concurrency(concurrency: int) -> httpx.Limits:
    """用于创建共享 AsyncClient 时的连接池上限（与单次压测一致）。"""
    c = max(concurrency + 2, 32)
    return httpx.Limits(max_connections=c, max_keepalive_connections=c)


def _httpx_limits(concurrency: int) -> httpx.Limits:
    return limits_for_concurrency(concurrency)


def _normalize_proxy_mode(proxy_mode: str | None) -> str:
    raw = (proxy_mode or "direct").strip().lower()
    if raw in {"off", "none", "no", "direct"}:
        return "direct"
    if raw in {"system", "env"}:
        return "system"
    if raw in {"custom", "manual"}:
        return "custom"
    raise ValueError(f"未知代理模式: {proxy_mode}")


def resolve_proxy(
    proxy_mode: str | None,
    proxy_url: str | None,
    *,
    strict: bool = True,
) -> tuple[str | None, bool]:
    """把 GUI/CLI 的代理配置解析为 ``(proxy_url_or_None, trust_env)``。

    ``strict=True``（默认）会对 custom 模式做严格校验（必填地址、合法 scheme、
    合法 netloc），不合法抛 ``ValueError``。``strict=False`` 用于 token 估算等
    "best-effort" 路径：custom 但 URL 非法时静默回退到直连，避免阻塞估算流程。
    """
    mode = _normalize_proxy_mode(proxy_mode) if strict else _resolve_proxy_lenient_mode(proxy_mode)
    if mode == "direct":
        return None, False
    if mode == "system":
        return None, True
    raw = (proxy_url or "").strip()
    if not raw:
        if strict:
            raise ValueError("代理模式为 custom 时，必须填写代理地址")
        return None, False
    if not strict:
        return raw, False
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https", "socks5", "socks5h"}:
        raise ValueError("代理地址必须以 http://、https://、socks5:// 或 socks5h:// 开头")
    if not parsed.netloc:
        raise ValueError("代理地址格式不正确，缺少主机和端口")
    return raw, False


def _resolve_proxy_lenient_mode(proxy_mode: str | None) -> str:
    raw = (proxy_mode or "direct").strip().lower()
    if raw == "system":
        return "system"
    if raw == "custom":
        return "custom"
    return "direct"


@asynccontextmanager
async def _bench_http_client(
    *,
    http2: bool,
    limits: httpx.Limits,
    shared: httpx.AsyncClient | None,
    proxy: str | None,
    trust_env: bool,
) -> AsyncIterator[httpx.AsyncClient]:
    if shared is not None:
        yield shared
        return
    async with httpx.AsyncClient(
        http2=http2, limits=limits, proxy=proxy, trust_env=trust_env
    ) as client:
        yield client


async def probe_connectivity(
    *,
    url: str,
    timeout_s: float = 10.0,
    http2: bool = False,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    proxy_mode: str = "direct",
    proxy_url: str | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    proxy, trust_env = resolve_proxy(proxy_mode, proxy_url)
    method = (method or "GET").upper()
    try:
        async with httpx.AsyncClient(
            http2=http2,
            proxy=proxy,
            trust_env=trust_env,
            timeout=timeout_s,
            transport=transport,
        ) as client:
            resp = await client.request(
                method, url, headers=headers, json=json_body, follow_redirects=True
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        response_text = _clip_response_text(resp.text)
        ok = 200 <= resp.status_code < 300
        error_kind = _classify_error(
            status_code=resp.status_code,
            err=None if ok else response_text or f"HTTP {resp.status_code}",
            exc=None,
        )
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "detail": f"{method} {url} -> HTTP {resp.status_code}",
            "response_text": response_text,
            "error_kind": error_kind.value if error_kind.value else None,
            "proxy_mode": _normalize_proxy_mode(proxy_mode),
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        kind = _classify_error(status_code=None, err=str(exc), exc=exc)
        return {
            "ok": False,
            "status_code": None,
            "elapsed_ms": elapsed_ms,
            "detail": str(exc),
            "error_kind": kind.value or "other",
            "proxy_mode": _normalize_proxy_mode(proxy_mode),
        }


async def run_benchmark(
    *,
    url: str,
    headers: dict[str, str],
    body_template: dict[str, Any],
    concurrency: int,
    total_requests: int | None,
    duration_s: float | None,
    stream: bool,
    timeout_s: float,
    http2: bool,
    warmup_requests: int = 0,
    timeline_bucket_s: float | None = None,
    prompts: list[str] | None = None,
    prompt_strategy: str = "sequential",
    prompt_weights: list[float] | None = None,
    retry_on_429: int = 0,
    retry_on_network: int = 1,
    retry_on_5xx: int = 1,
    base_backoff_s: float = 1.0,
    target_rps: float | None = None,
    rps_duration_s: float | None = None,
    progress_callback: Callable[[BenchSummary], Any] | None = None,
    progress_every_n: int = 1,
    sample_inflight_ms: float = 100.0,
    shared_client: httpx.AsyncClient | None = None,
    raw_results: list[RequestResult] | None = None,
    proxy_mode: str = "direct",
    proxy_url: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> BenchSummary:
    concurrency = max(1, concurrency)
    prompt_strategy = normalize_prompt_strategy(prompt_strategy)
    rps_mode = target_rps is not None
    if rps_mode:
        if rps_duration_s is None or rps_duration_s <= 0:
            raise ValueError("RPS 模式需要正数 --rps-duration")
        if total_requests is not None or duration_s is not None:
            raise ValueError("RPS 模式不能与 --total 或 --duration 同时使用")
        assert target_rps is not None  # narrowed by rps_mode check above
        if target_rps <= 0:
            raise ValueError("--target-rps 须为正数")
    else:
        if total_requests is None and duration_s is None:
            total_requests = 20
        if total_requests is not None and duration_s is not None:
            raise ValueError("只能二选一：--total 或 --duration")

    limits = _httpx_limits(concurrency)
    sem = asyncio.Semaphore(concurrency)
    summary = BenchSummary()
    summary.timeline_bucket_s = timeline_bucket_s

    counters = {"started": 0, "finished": 0}
    ctr_lock = asyncio.Lock()
    stop_sampler = asyncio.Event()

    def stop_requested() -> bool:
        return bool(should_stop is not None and should_stop())

    def check_stop() -> None:
        if stop_requested():
            raise asyncio.CancelledError()

    async def mark_started() -> None:
        async with ctr_lock:
            counters["started"] += 1

    async def mark_finished() -> None:
        async with ctr_lock:
            counters["finished"] += 1

    async def inflight_sampler() -> None:
        while not stop_sampler.is_set():
            async with ctr_lock:
                inflight = counters["started"] - counters["finished"]
            summary.in_flight_samples.append(max(0, inflight))
            try:
                await asyncio.wait_for(stop_sampler.wait(), timeout=sample_inflight_ms / 1000.0)
            except TimeoutError:
                continue

    def maybe_progress() -> None:
        if progress_callback is None:
            return
        if progress_every_n <= 1 or summary.total % progress_every_n == 0:
            progress_callback(summary)

    raw_results_list = raw_results

    def record_result(r: RequestResult, *, now_mono: float | None = None) -> None:
        t = time.perf_counter() if now_mono is None else now_mono
        summary.add(r, now_mono=t)
        if raw_results_list is not None:
            raw_results_list.append(r)
        maybe_progress()

    def record_attempt(r: RequestResult) -> None:
        summary.add_attempt(r)

    proxy, trust_env = resolve_proxy(proxy_mode, proxy_url)
    async with _bench_http_client(
        http2=http2,
        limits=limits,
        shared=shared_client,
        proxy=proxy,
        trust_env=trust_env,
    ) as client:
        check_stop()
        if warmup_requests > 0:
            await _warmup(
                client,
                url,
                headers,
                body_template,
                n=warmup_requests,
                stream=stream,
                timeout_s=timeout_s,
                concurrency=concurrency,
                prompts=prompts,
                prompt_strategy=prompt_strategy,
                prompt_weights=prompt_weights,
                retry_on_429=retry_on_429,
                retry_on_network=retry_on_network,
                retry_on_5xx=retry_on_5xx,
                base_backoff_s=base_backoff_s,
                should_stop=stop_requested,
            )
            summary.warmup_total = warmup_requests

        sampler_task: asyncio.Task[None] | None = None
        if sample_inflight_ms > 0:
            sampler_task = asyncio.create_task(inflight_sampler())

        summary.wall_t0 = time.perf_counter()

        try:

            async def do_one(idx: int) -> RequestResult:
                body = _body_for_index(
                    body_template,
                    idx,
                    prompts,
                    stream,
                    prompt_strategy=prompt_strategy,
                    prompt_weights=prompt_weights,
                )

                async def send_once() -> RequestResult:
                    check_stop()
                    async with sem:
                        check_stop()
                        await mark_started()
                        try:
                            return await one_chat_request(
                                client,
                                url,
                                headers,
                                body,
                                stream=stream,
                                timeout_s=timeout_s,
                                should_stop=stop_requested,
                            )
                        finally:
                            await mark_finished()

                return await _one_with_retry(
                    send_once,
                    stream=stream,
                    retry_on_429=retry_on_429,
                    retry_on_network=retry_on_network,
                    retry_on_5xx=retry_on_5xx,
                    base_backoff_s=base_backoff_s,
                    attempt_callback=record_attempt,
                    should_stop=stop_requested,
                )

            async def safe_do_one(idx: int) -> RequestResult:
                """隔离 ``do_one`` 内的未捕获异常。``CancelledError`` 正常上抛。"""
                try:
                    return await do_one(idx)
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:  # noqa: BLE001 - intentional: keep the loop alive
                    return failure_result_from_exception(exc)

            if rps_mode:
                assert rps_duration_s is not None
                assert target_rps is not None
                wall_start = time.perf_counter()
                stop_at = wall_start + rps_duration_s
                interval = 1.0 / float(target_rps)
                next_fire = wall_start
                max_pending = max(1, concurrency)
                pending: set[asyncio.Task[RequestResult]] = set()
                req_idx = 0

                while True:
                    if stop_requested():
                        for task in pending:
                            task.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        break
                    now = time.perf_counter()
                    while next_fire < stop_at and next_fire <= now:
                        if len(pending) < max_pending:
                            pending.add(asyncio.create_task(safe_do_one(req_idx)))
                            req_idx += 1
                        else:
                            summary.rps_schedule_skipped += 1
                        next_fire += interval

                    if now >= stop_at and not pending:
                        break

                    if not pending:
                        sleep_for = min(max(0.0, stop_at - now), max(0.0, next_fire - now), 0.05)
                        if sleep_for > 0:
                            await asyncio.sleep(sleep_for)
                        continue

                    done, pending = await asyncio.wait(
                        pending, timeout=0.05, return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in done:
                        try:
                            r = await t
                        except asyncio.CancelledError:
                            raise
                        except BaseException as exc:  # noqa: BLE001
                            r = failure_result_from_exception(exc)
                        record_result(r, now_mono=time.perf_counter())

            elif total_requests is not None:
                next_idx = 0
                idx_lock = asyncio.Lock()

                async def total_worker() -> None:
                    nonlocal next_idx
                    while True:
                        if stop_requested():
                            return
                        async with idx_lock:
                            if next_idx >= total_requests:
                                return
                            current_idx = next_idx
                            next_idx += 1
                        r = await safe_do_one(current_idx)
                        record_result(r, now_mono=time.perf_counter())

                worker_count = min(concurrency, total_requests)
                await asyncio.gather(
                    *(total_worker() for _ in range(worker_count)), return_exceptions=True
                )
            else:
                assert duration_s is not None
                stop_at = time.perf_counter() + duration_s

                async def duration_worker(worker_id: int) -> None:
                    i = worker_id
                    while time.perf_counter() < stop_at and not stop_requested():
                        r = await safe_do_one(i)
                        i += concurrency
                        record_result(r, now_mono=time.perf_counter())

                await asyncio.gather(
                    *(duration_worker(w) for w in range(concurrency)),
                    return_exceptions=True,
                )

        finally:
            stop_sampler.set()
            if sampler_task is not None:
                await sampler_task

        summary.wall_seconds = time.perf_counter() - summary.wall_t0

    return summary


__all__ = [
    "run_benchmark",
    "one_chat_request",
    "probe_connectivity",
    "resolve_proxy",
    "prompt_request_distribution",
    "normalize_prompt_strategy",
    "normalize_prompt_weights",
    "limits_for_concurrency",
    "failure_result_from_exception",
]

