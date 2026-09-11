from __future__ import annotations

import pytest

from app import auth
from app.config import Settings


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return _Response(self.payload)


def _settings(**overrides):
    values = dict(
        environment="production",
        auth_introspection_url="https://identity.invalid/introspect",
        auth_client_id="musitu-api",
        auth_client_secret="secret",
        auth_required_scope="musitu.payments",
    )
    values.update(overrides)
    return Settings(**values)


def _payload(aud):
    return {
        "active": True,
        "scope": "openid musitu.payments",
        "sub": "user-1",
        "aud": aud,
    }


@pytest.mark.asyncio
async def test_active_right_scope_wrong_audience_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings())
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: _Client(_payload("other-api")))
    with pytest.raises(ValueError, match="audience"):
        await auth._introspect("token")


@pytest.mark.asyncio
async def test_blank_required_scope_cannot_disable_scope_enforcement(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(auth_required_scope=""))
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: _Client(_payload("musitu-api")))
    with pytest.raises(ValueError, match="scope"):
        await auth._introspect("token")


@pytest.mark.asyncio
async def test_client_id_is_default_expected_audience(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings())
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: _Client(_payload(["account", "musitu-api"])))
    result = await auth._introspect("token")
    assert result["sub"] == "user-1"


@pytest.mark.asyncio
async def test_explicit_resource_audience_override_is_enforced(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(auth_expected_audience="musitu-resource"))
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: _Client(_payload("musitu-resource")))
    result = await auth._introspect("token")
    assert result["aud"] == "musitu-resource"