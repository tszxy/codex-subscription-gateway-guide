import json
import sys
from pathlib import Path
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
from codex_error_proxy import app, friendly_error


class ErrorClassificationTests(unittest.TestCase):
    def test_invalid_shapes_and_non_string_codes(self):
        for body in (b"null", b"[]", b"not-json", b'{"error":[]}',
                     b'{"error":{"code":[]}}', b"\xff"):
            with self.subTest(body=body):
                self.assertIsNone(friendly_error(body))

    def test_message_fallback_is_ambiguous(self):
        error = friendly_error(json.dumps({"error": {"message": "all credentials unavailable"}}))
        self.assertEqual(error["error"]["code"], "codex_accounts_unavailable")
        self.assertIn("可能", error["error"]["message"])


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def send_with(self, handler, *, path="/v1/messages", body=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
            app.state.client = upstream
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.post(path, headers={"Authorization": "Bearer fixture-key"}, json=body or {})

    async def test_terminal_errors_preserve_origin(self):
        cases = [(429, "usage_limit_reached", "codex_quota_exhausted"),
                 (429, "quota_exceeded", "codex_quota_exhausted"),
                 (429, "insufficient_quota", "codex_quota_exhausted"),
                 (503, "auth_unavailable", "codex_accounts_unavailable"),
                 (429, "model_cooldown", "codex_accounts_unavailable")]
        for status, code, expected in cases:
            with self.subTest(code=code):
                def mock(request):
                    self.assertEqual(request.headers["authorization"], "Bearer fixture-key")
                    return httpx.Response(status, json={"error": {"code": code}},
                                          headers={"retry-after": "3600", "retry-after-ms": "1000"})
                response = await self.send_with(mock)
                self.assertEqual(response.status_code, 400)
                error = response.json()["error"]
                self.assertEqual(error["code"], expected)
                self.assertEqual(error["upstream_status"], status)
                self.assertEqual(error["upstream_code"], code)
                self.assertNotIn("retry-after", response.headers)
                self.assertNotIn("retry-after-ms", response.headers)

    async def test_unknown_failures_are_not_quota(self):
        for status in (401, 429, 502):
            with self.subTest(status=status):
                body = {"error": {"message": "upstream busy or invalid key"}}
                response = await self.send_with(lambda request: httpx.Response(status, json=body))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), body)

    async def test_sse_and_query_passthrough(self):
        payload = b'event: message_start\ndata: {"type":"message_start"}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n'
        def mock(request):
            self.assertEqual(request.url.path, "/v1/messages")
            self.assertEqual(request.url.query, b"test=1")
            self.assertTrue(json.loads(request.content)["stream"])
            return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})
        response = await self.send_with(mock, path="/v1/messages?test=1", body={"stream": True})
        self.assertEqual(response.content, payload)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))

    async def test_local_network_failure_is_distinct(self):
        for exception, expected, code in (
            (httpx.ConnectError, 502, "gateway_upstream_unreachable"),
            (httpx.ReadTimeout, 504, "gateway_upstream_timeout"),
        ):
            with self.subTest(exception=exception):
                def mock(request):
                    raise exception("fixture", request=request)
                response = await self.send_with(mock)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.json()["error"]["code"], code)


if __name__ == "__main__":
    unittest.main()
