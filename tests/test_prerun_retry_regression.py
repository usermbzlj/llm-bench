"""Prerun retries only transient failures and does not count attempts as prompts."""
import asyncio
import unittest
from unittest.mock import patch

import httpx

from llm_bench.tokens import estimate_tokens_prerun


class PrerunRetryTests(unittest.TestCase):
    def test_retries_429_and_counts_one_prompt(self):
        seen = []
        def handler(request):
            seen.append(request.content)
            if len(seen) == 1:
                return httpx.Response(429, json={"error":{"message":"slow down"}})
            return httpx.Response(200, json={
                "choices": [{"message": {"content":"ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            })
        async def run():
            return await estimate_tokens_prerun(
                url="https://example.test/v1/chat/completions",
                headers={}, body_template={"model":"test"}, prompts=["hello"],
                stream=False, timeout_s=5, http2=False,
                proxy_mode="direct", proxy_url=None,
                total_requests=7, prompt_strategy="sequential",
                prompt_weights=None, transport=httpx.MockTransport(handler),
            )
        with patch("llm_bench.tokens.asyncio.sleep", return_value=asyncio.sleep(0)):
            # No mock sleep needed in correctness assertion; requests remain identical.
            pass
        result = asyncio.run(run())
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(len(result["per_prompt"]), 1)
        self.assertEqual(result["estimated_prompt_tokens_total"], 35)

    def test_no_retry_on_auth_error(self):
        count = []
        def handler(request):
            count.append(1)
            return httpx.Response(401, json={"error":"no"})
        async def run():
            return await estimate_tokens_prerun(
                url="https://example.test/v1/chat/completions",
                headers={}, body_template={"model":"test"}, prompts=["hello"],
                stream=False, timeout_s=5, http2=False,
                proxy_mode="direct", proxy_url=None,
                total_requests=1, prompt_strategy="sequential",
                prompt_weights=None, transport=httpx.MockTransport(handler),
            )
        with self.assertRaisesRegex(ValueError, "尝试 1 次"):
            asyncio.run(run())
        self.assertEqual(len(count), 1)
