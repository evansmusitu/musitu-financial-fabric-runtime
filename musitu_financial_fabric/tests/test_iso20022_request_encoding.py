from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import auth
from app.config import Settings


def _request(body: bytes) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/iso20022/pacs008",
        "raw_path": b"/iso20022/pacs008",
        "query_string": b"merchant_id=m-1&destination_account_id=a-1",
        "headers": [(b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 12345),
        "server": ("musitu.invalid", 443),
    }
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_sandbox_iso20022_invalid_utf8_fails_closed_before_endpoint(monkeypatch):
    monkeypatch.setattr(auth, "settings", Settings(environment="sandbox"))
    called = False

    async def call_next(_: Request):
        nonlocal called
        called = True
        return Response(status_code=204)

    response = await auth.production_auth_middleware(_request(b"\xff\xfe"), call_next)
    assert response.status_code == 400
    assert called is False


@pytest.mark.asyncio
async def test_production_iso20022_invalid_utf8_fails_closed_before_auth_and_endpoint(monkeypatch):
    monkeypatch.setattr(auth, "settings", Settings(environment="production", max_request_body_bytes=1024))
    called = False

    async def call_next(_: Request):
        nonlocal called
        called = True
        return Response(status_code=204)

    response = await auth.production_auth_middleware(_request(b"\xff\xfe"), call_next)
    assert response.status_code == 400
    assert called is False


@pytest.mark.asyncio
async def test_sandbox_iso20022_valid_utf8_continues(monkeypatch):
    monkeypatch.setattr(auth, "settings", Settings(environment="sandbox"))
    called = False

    async def call_next(_: Request):
        nonlocal called
        called = True
        return Response(status_code=204)

    response = await auth.production_auth_middleware(_request(b"<Document/>"), call_next)
    assert response.status_code == 204
    assert called is True
