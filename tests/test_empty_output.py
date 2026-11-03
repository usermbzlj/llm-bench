"""200 + empty answer must not count as success.

Defect + minimal repro reported by E'via Sales Agent (EigenFlux eigenflux#kPhwq):
``one_chat_request`` used to return ``ok=True`` for HTTP 200 with no answer text,
so ``TimelineBucket`` counted empty relay responses as successes
(success_rate_pct=100, goodput_fraction=1.0 on four empty responses).
"""

import httpx
import pytest

from llm_bench.models import ErrorKind, TimelineBucket
from llm_bench.runner import one_chat_request

URL = "https://example.test/v1/chat/completions"
BODY = {"model": "demo", "messages": [{"role": "user", "content": "hi"}]}
USAGE = {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1}

EMPTY_CASES = [
    # (id, stream, response factory)
    ("stream_empty_delta", True,
     lambda: httpx.Response(200, text='data: {"choices":[{"delta":{}}]}\n\ndata: [DONE]\n\n',
                            headers={"content-type": "text/event-stream"})),
    ("stream_blank_content", True,
     lambda: httpx.Response(200, text='data: {"choices":[{"delta":{"content":"   "}}]}\n\ndata: [DONE]\n\n',
                            headers={"content-type": "text/event-stream"})),
    ("stream_done_only", True,
     lambda: httpx.Response(200, text="data: [DONE]\n\n",
                            headers={"content-type": "text/event-stream"})),
    ("nonstream_empty_content", False,
     lambda: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})),
    ("nonstream_usage_only", False,
     lambda: httpx.Response(200, json={"usage": USAGE})),
    ("nonstream_empty_choices", False,
     lambda: httpx.Response(200, json={"choices": [], "usage": USAGE})),
    ("nonstream_null_content", False,
     lambda: httpx.Response(200, json={"choices": [{"message": {"content": None}}]})),
]

OK_CASES = [
    ("stream_has_text", True,
     lambda: httpx.Response(200, text='data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n',
                            headers={"content-type": "text/event-stream"})),
    ("nonstream_has_text", False,
     lambda: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": USAGE})),
    ("nonstream_output_text", False,
     lambda: httpx.Response(200, json={"output_text": "hi"})),
]


async def _run(stream: bool, factory):
    transport = httpx.MockTransport(lambda req: factory())
    async with httpx.AsyncClient(transport=transport) as client:
        return await one_chat_request(client, URL, {}, BODY, stream=stream, timeout_s=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,stream,factory", EMPTY_CASES, ids=[c[0] for c in EMPTY_CASES])
async def test_200_empty_answer_is_failure(case_id, stream, factory) -> None:
    r = await _run(stream, factory)
    assert r.status_code == 200
    assert r.ok is False, case_id
    assert r.error_kind == ErrorKind.EMPTY_OUTPUT
    assert r.error and r.error.startswith("empty_output")


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,stream,factory", OK_CASES, ids=[c[0] for c in OK_CASES])
async def test_200_with_answer_still_ok(case_id, stream, factory) -> None:
    r = await _run(stream, factory)
    assert r.ok is True, case_id
    assert r.error_kind == ErrorKind.NONE


@pytest.mark.asyncio
async def test_timeline_bucket_no_longer_counts_empty_as_success() -> None:
    """E'via's aggregate repro: four empty 200s used to give success=4, failed=0."""
    bucket = TimelineBucket()
    picks = [EMPTY_CASES[0], EMPTY_CASES[3], EMPTY_CASES[4], EMPTY_CASES[5]]
    for _, stream, factory in picks:
        bucket.add(await _run(stream, factory))
    assert bucket.success == 0
    assert bucket.failed == 4
