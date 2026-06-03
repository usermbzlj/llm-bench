import httpx
import pytest

from llm_bench.tokens import estimate_tokens_local, estimate_tokens_prerun


def _body() -> dict[str, object]:
    return {
        "model": "demo-model",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 16,
    }


def test_estimate_tokens_local_returns_prompt_breakdown() -> None:
    result = estimate_tokens_local(
        body_template=_body(),
        prompts=["a", "b"],
        model="gpt-4o-mini",
        total_requests=10,
        max_tokens=16,
        prompt_strategy="weighted",
        prompt_weights=[1, 3],
    )

    assert result["mode"] == "local"
    assert len(result["per_prompt"]) == 2
    assert result["estimated_tokens_total"] >= result["estimated_output_tokens_total"]
    assert result["per_prompt"][0]["expected_requests"] == pytest.approx(2.5)
    assert result["per_prompt"][1]["expected_requests"] == pytest.approx(7.5)


@pytest.mark.asyncio
async def test_estimate_tokens_prerun_uses_usage_fields() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    result = await estimate_tokens_prerun(
        url="https://example.test/v1/chat/completions",
        headers={},
        body_template=_body(),
        prompts=["p1", "p2"],
        stream=False,
        timeout_s=5,
        http2=False,
        proxy_mode="direct",
        proxy_url=None,
        total_requests=4,
        prompt_strategy="sequential",
        prompt_weights=None,
        transport=httpx.MockTransport(handler),
    )

    assert result["mode"] == "prerun"
    assert len(result["per_prompt"]) == 2
    assert result["estimated_prompt_tokens_total"] == 40
    assert result["estimated_completion_tokens_total"] == 80
