"""Regression tests: HTTP 200 is not sufficient evidence of a valid completion."""
import asyncio
import json
import unittest

import httpx

from llm_bench.runner import one_chat_request


class SuccessfulResponseValidationTests(unittest.TestCase):
    def request(self, payload, *, stream=False, content_type="application/json"):
        def handler(request):
            return httpx.Response(200, headers={"content-type": content_type}, content=payload)
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await one_chat_request(
                    client, "https://example.test/v1/chat/completions",
                    {}, {"model": "test", "messages": []}, stream=stream, timeout_s=5,
                )
        return asyncio.run(run())

    def test_stream_without_sse_data_is_not_success(self):
        response = self.request(b'{"choices":[{"message":{"content":"hello"}}]}', stream=True)
        self.assertFalse(response.ok)
        self.assertIn("no valid SSE", response.error)

    def test_nonstream_error_body_is_not_success(self):
        response = self.request(b'{"error":{"message":"quota"}}')
        self.assertFalse(response.ok)

    def test_nonstream_empty_choices_is_not_success(self):
        response = self.request(b'{"choices":[]}')
        self.assertFalse(response.ok)

    def test_nonstream_array_is_not_success(self):
        response = self.request(b'[]')
        self.assertFalse(response.ok)

    def test_nonstream_valid_output_is_success(self):
        response = self.request(json.dumps({"choices":[{"message":{"content":"ok"}}]}).encode())
        self.assertTrue(response.ok)
