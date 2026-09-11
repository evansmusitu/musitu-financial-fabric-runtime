from __future__ import annotations

import pytest
from starlette.requests import Request

from app import auth
from app.config import Settings


def _request(chunks: list[bytes], *, content_length: str | None = None) -> Request:
    headers = []
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/payments/intents",
        "raw_path": b"/v1/payments/intents",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("musitu.invalid", 443),
    }
    queue = list(chunks)

    async def receive():
        if queue:
            body = queue.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(queue)}
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _settings(limit: int) -> Settings:
    return Settings(environment="production", max_request_body_bytes=limit)


@pytest.mark.asyncio
async def test_declared_oversized_body_rejected_before_read(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(8))
    request = _request([b"small"], content_length="9")
    with pytest.raises(auth.RequestBodyTooLarge):
        await auth._buffer_limited_body(request)


@pytest.mark.asyncio
async def test_chunked_body_cannot_bypass_size_limit(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(8))
    request = _request([b"1234", b"56789"])
    with pytest.raises(auth.RequestBodyTooLarge):
        await auth._buffer_limited_body(request)


@pytest.mark.asyncio
async def test_body_within_limit_is_buffered_for_downstream_reuse(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(8))
    request = _request([b"1234", b"5678"])
    body = await auth._buffer_limited_body(request)
    assert body == b"12345678"
    assert await request.body() == b"12345678"


@pytest.mark.asyncio
async def test_invalid_content_length_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(8))
    request = _request([b"1234"], content_length="not-a-number")
    with pytest.raises(ValueError, match="Content-Length"):
        await auth._buffer_limited_body(request)


@pytest.mark.asyncio
async def test_nonpositive_limit_fails_closed(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(0))
    request = _request([b""])
    with pytest.raises(RuntimeError, match="limit"):
        await auth._buffer_limited_body(request)
