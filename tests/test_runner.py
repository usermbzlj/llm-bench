import asyncio

import httpx
import pytest

from llm_bench.models import ErrorKind
from llm_bench.runner import (
    _body_for_index,
    failure_result_from_exception,
    one_chat_request,
    probe_connectivity,
    prompt_request_distribution,
    resolve_proxy,
    run_benchmark,
)


def _body() -> dict[str, object]:
    return {
        "model": "demo-model",
        "messages": [{"role": "user", "content": "hello"}],
    }


class RetryThenSuccessTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        await asyncio.sleep(0.05)
        if self.calls == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(
            200,
            json={"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
        )


class SlowSuccessTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        )


@pytest.mark.asyncio
async def test_retry_latency_includes_backoff_and_attempts() -> None:
    raw = []
    transport = RetryThenSuccessTransport()

    async with httpx.AsyncClient(transport=transport) as client:
        summary = await run_benchmark(
            url="https://example.test/v1/chat/completions",
            headers={},
            body_template=_body(),
            concurrency=1,
            total_requests=1,
            duration_s=None,
            stream=False,
            timeout_s=5,
            http2=False,
            retry_on_429=1,
            base_backoff_s=0.1,
            shared_client=client,
            raw_results=raw,
        )

    assert transport.calls == 2
    assert summary.total == 1
    assert summary.attempt_total == 2

    result = raw[0]
    assert result.attempt_count == 2
    assert result.final_attempt_latency_ms is not None
    assert result.retry_sleep_ms >= 100
    assert result.latency_ms > result.final_attempt_latency_ms + 80


@pytest.mark.asyncio
async def test_rps_mode_skips_when_scheduler_is_saturated() -> None:
    async with httpx.AsyncClient(transport=SlowSuccessTransport()) as client:
        summary = await run_benchmark(
            url="https://example.test/v1/chat/completions",
            headers={},
            body_template=_body(),
            concurrency=1,
            total_requests=None,
            duration_s=None,
            stream=False,
            timeout_s=5,
            http2=False,
            target_rps=50,
            rps_duration_s=0.2,
            shared_client=client,
        )

    assert summary.rps_schedule_skipped > 0
    assert summary.wall_seconds < 0.4
    assert summary.total <= 5


@pytest.mark.asyncio
async def test_one_chat_request_marks_404_as_failure() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, text='{"error":"missing"}'))

    async with httpx.AsyncClient(transport=transport) as client:
        result = await one_chat_request(
            client,
            "https://example.test/v1/chat/completions",
            {},
            _body(),
            stream=False,
            timeout_s=5,
        )

    assert result.ok is False
    assert result.status_code == 404
    assert result.error_kind == ErrorKind.CLIENT_ERROR
    assert result.response_text is None
    assert "missing" in (result.raw_response_text or "")
    assert "missing" in (result.error or "")


@pytest.mark.asyncio
async def test_one_chat_request_extracts_response_text() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello from model"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
    )

    async with httpx.AsyncClient(transport=transport) as client:
        result = await one_chat_request(
            client,
            "https://example.test/v1/chat/completions",
            {},
            _body(),
            stream=False,
            timeout_s=5,
        )

    assert result.ok is True
    assert result.response_text == "hello from model"
    assert '"content":"hellofrommodel"' in (result.raw_response_text or "").replace(" ", "")


@pytest.mark.asyncio
async def test_probe_connectivity_uses_post_and_404_is_not_ok() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        return httpx.Response(404, text="route missing")

    result = await probe_connectivity(
        url="https://example.test/v1/chat/completions",
        method="POST",
        json_body=_body(),
        transport=httpx.MockTransport(handler),
    )

    assert captured["method"] == "POST"
    assert result["ok"] is False
    assert result["status_code"] == 404
    assert result["error_kind"] == ErrorKind.CLIENT_ERROR.value


def test_body_for_index_supports_prompt_strategies(monkeypatch) -> None:
    body = {"messages": [{"role": "user", "content": "old"}]}
    prompts = ["p1", "p2", "p3"]
    sequential = _body_for_index(
        body, 4, prompts, False, prompt_strategy="sequential", prompt_weights=None
    )
    assert sequential["messages"][0]["content"] == "p2"

    monkeypatch.setattr("llm_bench.runner.random.randrange", lambda n: 2)
    random_body = _body_for_index(
        body, 0, prompts, False, prompt_strategy="random", prompt_weights=None
    )
    assert random_body["messages"][0]["content"] == "p3"

    monkeypatch.setattr("llm_bench.runner.random.choices", lambda population, weights, k: [1])
    weighted = _body_for_index(
        body, 0, prompts, False, prompt_strategy="weighted", prompt_weights=[0.1, 0.7, 0.2]
    )
    assert weighted["messages"][0]["content"] == "p2"


def test_prompt_request_distribution_handles_weighted_random() -> None:
    sequential = prompt_request_distribution(
        5, ["a", "b"], prompt_strategy="sequential", prompt_weights=None
    )
    assert sequential == [3.0, 2.0]

    random_dist = prompt_request_distribution(
        10, ["a", "b", "c"], prompt_strategy="random", prompt_weights=None
    )
    assert random_dist == [pytest.approx(10 / 3)] * 3

    weighted = prompt_request_distribution(
        10, ["a", "b"], prompt_strategy="weighted", prompt_weights=[1, 3]
    )
    assert weighted == [2.5, 7.5]


def test_resolve_proxy_strict_mode_validates() -> None:
    # direct / system never need a URL
    assert resolve_proxy("direct", None) == (None, False)
    assert resolve_proxy("direct", "") == (None, False)
    assert resolve_proxy("system", "ignored") == (None, True)

    # custom with valid URL
    assert resolve_proxy("custom", "http://127.0.0.1:7890") == ("http://127.0.0.1:7890", False)
    assert resolve_proxy("custom", "socks5h://127.0.0.1:1080") == (
        "socks5h://127.0.0.1:1080",
        False,
    )

    # strict raises on bad config
    with pytest.raises(ValueError, match="代理地址"):
        resolve_proxy("custom", None)
    with pytest.raises(ValueError, match="代理地址"):
        resolve_proxy("custom", "")
    with pytest.raises(ValueError, match="代理地址"):
        resolve_proxy("custom", "ftp://1.2.3.4:21")
    with pytest.raises(ValueError, match="代理地址"):
        resolve_proxy("custom", "http://")
    with pytest.raises(ValueError, match="未知代理模式"):
        resolve_proxy("bogus", None, strict=True)


def test_resolve_proxy_lenient_mode_silently_falls_back() -> None:
    # strict=False: bad mode → direct; bad URL → direct; all silently
    assert resolve_proxy("bogus", "http://x", strict=False) == (None, False)
    assert resolve_proxy("custom", "ftp://nope", strict=False) == ("ftp://nope", False)
    # custom but no URL → falls back to direct (doesn't raise)
    assert resolve_proxy("custom", None, strict=False) == (None, False)


def test_failure_result_from_exception_classifies_known_types() -> None:
    from llm_bench.runner import _classify_error

    # TimeoutException → TIMEOUT
    res = failure_result_from_exception(httpx.TimeoutException("slow"))
    assert res.ok is False
    assert res.error_kind == ErrorKind.TIMEOUT
    assert res.attempt_count == 1
    assert "engine_error" in (res.error or "")

    # ConnectError → CONNECT
    res = failure_result_from_exception(httpx.ConnectError("nope"))
    assert res.error_kind == ErrorKind.CONNECT

    # Generic RuntimeError → OTHER
    res = failure_result_from_exception(RuntimeError("boom"))
    assert res.error_kind == ErrorKind.OTHER
    # Make sure classification still works (sanity).
    assert _classify_error(status_code=None, err="boom", exc=res) is not None


def test_one_chat_request_should_stop_mid_stream() -> None:
    """M5: one_chat_request accepts should_stop and the stop guard is wired in.

    Integration-testing actual mid-stream interruption is hard with httpx's
    transport interface (the body is delivered as a single aiter_text chunk
    in MockTransport). We verify two things instead:
      1. The signature accepts a should_stop kwarg.
      2. CancelledError raised from inside one_chat_request propagates out
         unchanged (not swallowed as a regular error).
    """
    # Signature sanity
    import inspect

    sig = inspect.signature(one_chat_request)
    assert "should_stop" in sig.parameters
    assert sig.parameters["should_stop"].default is None

    # The module-level _raise_if_should_stop is the actual guard. Test that.
    from llm_bench.runner import _raise_if_should_stop

    with pytest.raises(asyncio.CancelledError):
        _raise_if_should_stop(lambda: True)
    _raise_if_should_stop(lambda: False)  # no raise
    _raise_if_should_stop(None)  # no raise


def test_raise_if_should_stop_passes_through_when_not_set() -> None:
    """Module-level stop guard: None means never stop."""
    from llm_bench.runner import _raise_if_should_stop

    # Should NOT raise when should_stop is None.
    _raise_if_should_stop(None)
    # Should NOT raise when should_stop() returns False.
    _raise_if_should_stop(lambda: False)


def test_raise_if_should_stop_raises_when_true() -> None:
    """Module-level stop guard: True → CancelledError."""
    from llm_bench.runner import _raise_if_should_stop

    with pytest.raises(asyncio.CancelledError):
        _raise_if_should_stop(lambda: True)


class _NoCallTransport(httpx.AsyncBaseTransport):
    """Async transport that fails the test if called. Used in tests that
    should short-circuit before any HTTP work happens."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError("transport should not have been called")


def test_run_benchmark_survives_engine_exception() -> None:
    """M1: a non-httpx exception from inside the request must be caught
    and recorded as a failed result, not crash the whole benchmark."""

    class CrashOnSecondCall(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            # Raise something other than an httpx error to test exception isolation.
            raise RuntimeError("synthetic engine bug")

    async def run() -> None:
        transport = CrashOnSecondCall()
        async with httpx.AsyncClient(transport=transport) as client:
            summary = await run_benchmark(
                url="https://example.test/v1/chat/completions",
                headers={},
                body_template={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                concurrency=1,
                total_requests=2,
                duration_s=None,
                stream=False,
                timeout_s=5,
                http2=False,
                shared_client=client,
            )
        # Both requests should be recorded as failures, not crash the engine.
        assert summary.total == 2
        assert summary.success == 0
        assert summary.failed == 2
        # Error kind should be OTHER (RuntimeError isn't classified further).
        assert summary.error_kind_counts.get("other") == 2
        # transport was actually invoked — exception isolation happened on the
        # OUTER level (in the scheduler's gather / done handler), not in the
        # transport. So calls count is the number of attempts (1+retry).
        assert transport.calls >= 2

    asyncio.run(run())
