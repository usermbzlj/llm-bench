from __future__ import annotations

import copy
import json
import time
from typing import Any

import httpx

from llm_bench.runner import one_chat_request, prompt_request_distribution, resolve_proxy

try:
    import tiktoken
except ImportError:  # pragma: no cover - dependency might not be installed yet
    tiktoken = None  # type: ignore[assignment]


def _extract_default_prompt(body_template: dict[str, Any]) -> str:
    messages = body_template.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                return str(content) if content is not None else ""
    return ""


def _normalize_prompts(body_template: dict[str, Any], prompts: list[str] | None) -> list[str]:
    if prompts:
        items = [prompt.strip() for prompt in prompts if prompt.strip()]
        if items:
            return items
    return [_extract_default_prompt(body_template)]


def _apply_prompt_to_body(body_template: dict[str, Any], prompt: str) -> dict[str, Any]:
    body = copy.deepcopy(body_template)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        body["messages"] = [{"role": "user", "content": prompt}]
        return body
    copied = copy.deepcopy(messages)
    for idx, message in enumerate(copied):
        if isinstance(message, dict) and message.get("role") == "user":
            copied[idx] = {**message, "content": prompt}
            body["messages"] = copied
            return body
    copied.append({"role": "user", "content": prompt})
    body["messages"] = copied
    return body


def _encoding_for_model(model: str):
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model((model or "").strip())
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def _count_tokens_fallback(text: str) -> int:
    # Keep a rough estimate even when tiktoken is unavailable.
    return max(1, (len(text) + 3) // 4)


def _count_tokens_for_json(payload: dict[str, Any], *, model: str) -> int:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoder = _encoding_for_model(model)
    if encoder is None:
        return _count_tokens_fallback(normalized)
    return len(encoder.encode(normalized))


def estimate_tokens_local(
    *,
    body_template: dict[str, Any],
    prompts: list[str] | None,
    model: str,
    total_requests: int,
    max_tokens: int,
    prompt_strategy: str,
    prompt_weights: list[float] | None,
) -> dict[str, Any]:
    normalized_prompts = _normalize_prompts(body_template, prompts)
    prompt_token_counts: list[int] = []
    for prompt in normalized_prompts:
        prompt_body = _apply_prompt_to_body(body_template, prompt)
        prompt_token_counts.append(_count_tokens_for_json(prompt_body, model=model))
    distribution = prompt_request_distribution(
        total_requests,
        normalized_prompts,
        prompt_strategy=prompt_strategy,
        prompt_weights=prompt_weights,
    )
    per_prompt: list[dict[str, Any]] = []
    for idx, prompt in enumerate(normalized_prompts):
        expected_requests = distribution[idx] if idx < len(distribution) else 0.0
        input_tokens = prompt_token_counts[idx]
        per_prompt.append(
            {
                "index": idx + 1,
                "prompt": prompt,
                "input_tokens": input_tokens,
                "expected_requests": expected_requests,
                "expected_input_tokens": input_tokens * expected_requests,
            }
        )
    estimated_input = sum(item["expected_input_tokens"] for item in per_prompt)
    estimated_output = max(0, int(max_tokens)) * max(0, int(total_requests))
    return {
        "mode": "local",
        "tokenizer": "tiktoken" if tiktoken is not None else "fallback",
        "per_prompt": per_prompt,
        "estimated_input_tokens_total": estimated_input,
        "estimated_output_tokens_total": float(estimated_output),
        "estimated_tokens_total": estimated_input + float(estimated_output),
        "total_requests": max(0, int(total_requests)),
    }


def _resolve_proxy(proxy_mode: str, proxy_url: str | None) -> tuple[str | None, bool]:
    """保留的旧名；转调公共 :func:`llm_bench.runner.resolve_proxy`，``strict=False``。"""
    return resolve_proxy(proxy_mode, proxy_url, strict=False)


async def estimate_tokens_prerun(
    *,
    url: str,
    headers: dict[str, str],
    body_template: dict[str, Any],
    prompts: list[str] | None,
    stream: bool,
    timeout_s: float,
    http2: bool,
    proxy_mode: str,
    proxy_url: str | None,
    total_requests: int,
    prompt_strategy: str,
    prompt_weights: list[float] | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    normalized_prompts = _normalize_prompts(body_template, prompts)
    distribution = prompt_request_distribution(
        total_requests,
        normalized_prompts,
        prompt_strategy=prompt_strategy,
        prompt_weights=prompt_weights,
    )
    proxy, trust_env = _resolve_proxy(proxy_mode, proxy_url)
    started = time.perf_counter()
    per_prompt: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        http2=http2, proxy=proxy, trust_env=trust_env, transport=transport
    ) as client:
        for idx, prompt in enumerate(normalized_prompts):
            body = _apply_prompt_to_body(body_template, prompt)
            result = await one_chat_request(
                client,
                url,
                headers,
                body,
                stream=stream,
                timeout_s=timeout_s,
            )
            if not result.ok:
                raise ValueError(
                    f"第 {idx + 1} 条 Prompt 预跑失败: HTTP {result.status_code or '-'} {result.error or ''}".strip()
                )
            prompt_tokens = int(result.prompt_tokens or 0)
            completion_tokens = int(result.completion_tokens or 0)
            expected_requests = distribution[idx] if idx < len(distribution) else 0.0
            per_prompt.append(
                {
                    "index": idx + 1,
                    "prompt": prompt,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": int(result.total_tokens or (prompt_tokens + completion_tokens)),
                    "expected_requests": expected_requests,
                    "expected_prompt_tokens": prompt_tokens * expected_requests,
                    "expected_completion_tokens": completion_tokens * expected_requests,
                }
            )
    estimated_prompt = sum(item["expected_prompt_tokens"] for item in per_prompt)
    estimated_completion = sum(item["expected_completion_tokens"] for item in per_prompt)
    return {
        "mode": "prerun",
        "per_prompt": per_prompt,
        "estimated_prompt_tokens_total": estimated_prompt,
        "estimated_completion_tokens_total": estimated_completion,
        "estimated_tokens_total": estimated_prompt + estimated_completion,
        "total_requests": max(0, int(total_requests)),
        "wall_seconds": time.perf_counter() - started,
    }


__all__ = ["estimate_tokens_local", "estimate_tokens_prerun"]
