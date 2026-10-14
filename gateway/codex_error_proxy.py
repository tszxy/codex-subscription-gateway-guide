"""Translate known final CPA failures; keep successful responses streaming.

Account selection, OAuth and retry rounds remain the responsibility of CPA.
Bind this service to loopback: authentication is delegated to CPA.
"""
from contextlib import asynccontextmanager
import json
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

UPSTREAM_URL = os.environ.get("CPA_UPSTREAM_URL", "http://127.0.0.1:8317").rstrip("/")
TERMINAL_ERROR_STATUS = int(os.environ.get("TERMINAL_ERROR_STATUS", "400"))
if TERMINAL_ERROR_STATUS not in (400, 429, 503):
    raise ValueError("TERMINAL_ERROR_STATUS must be 400, 429 or 503")
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
}


def filtered_headers(headers, *, response=False):
    blocked = HOP_HEADERS | {x.strip().lower() for x in headers.get("connection", "").split(",")}
    blocked |= {"content-encoding"} if response else {"host"}
    return {k: v for k, v in headers.items() if k.lower() not in blocked}


def friendly_error(body):
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("error"), dict):
        return None
    error = data["error"]
    code = error.get("code") or error.get("type", "")
    if not isinstance(code, str):
        return None
    message = str(error.get("message", "")).lower()
    if code in ("usage_limit_reached", "quota_exceeded", "insufficient_quota"):
        message = "所有可用 Codex 账号在当前模型上的额度均已用尽，请等待额度重置后重试。"
        public_code = "codex_quota_exhausted"
    elif code in ("auth_unavailable", "no_available_auth", "model_cooldown") or \
            "all credentials" in message or "all auth" in message:
        message = "当前没有可用的 Codex 账号：可能额度已用尽、账号正在冷却或认证失效。请稍后重试或检查账号状态。"
        public_code = "codex_accounts_unavailable"
    else:
        return None
    return {"type": "error", "error": {
        "type": "invalid_request_error", "code": public_code,
        "upstream_code": code, "message": message,
    }}


def proxy_error(status, code, message):
    body = {"type": "error", "error": {
        "type": "api_error", "code": code, "message": message,
    }}
    return Response(json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    status_code=status, media_type="application/json")


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15), trust_env=False) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS"])
async def forward(path: str, request: Request):
    url = UPSTREAM_URL + "/" + path
    if request.url.query:
        url += "?" + request.url.query
    upstream_request = app.state.client.build_request(
        request.method, url, headers=filtered_headers(request.headers),
        content=await request.body(),
    )
    try:
        upstream = await app.state.client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        return proxy_error(504, "gateway_upstream_timeout", "网关等待 CPA 响应超时，请检查内部服务与上游连接。")
    except httpx.RequestError:
        return proxy_error(502, "gateway_upstream_unreachable", "网关无法连接 CPA，请检查内部服务状态。")
    headers = filtered_headers(upstream.headers, response=True)
    if upstream.status_code >= 400:
        try:
            body = await upstream.aread()
        except httpx.TimeoutException:
            return proxy_error(504, "gateway_upstream_timeout", "网关读取 CPA 错误响应超时。")
        except httpx.RequestError:
            return proxy_error(502, "gateway_upstream_unreachable", "网关读取 CPA 错误响应失败。")
        finally:
            await upstream.aclose()
        error = friendly_error(body)
        status = upstream.status_code
        if error:
            error["error"]["upstream_status"] = status
            status = TERMINAL_ERROR_STATUS
            headers = {k: v for k, v in headers.items()
                       if k.lower() not in ("retry-after", "retry-after-ms")}
            headers["content-type"] = "application/json; charset=utf-8"
            body = json.dumps(error, ensure_ascii=False).encode("utf-8")
        return Response(body, status_code=status, headers=headers)

    async def chunks():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=headers)

