import pytest

from app.component_registry import Component, probe_components


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _Client:
    def __init__(self, status_code):
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return _Response(self.status_code)


@pytest.mark.asyncio
async def test_required_runtime_404_is_not_healthy(monkeypatch):
    monkeypatch.setenv("MUSITU_TEST_HEALTH_URL", "https://runtime.invalid/health")
    monkeypatch.setattr(
        "app.component_registry.httpx.AsyncClient",
        lambda *args, **kwargs: _Client(404),
    )
    component = Component(
        "test-runtime",
        "Test Runtime",
        "test",
        "runtime",
        health_env="MUSITU_TEST_HEALTH_URL",
    )

    result = await probe_components([component])

    assert result["all_required_runtime_healthy"] is False
    assert result["components"][0]["state"] == "unhealthy"


@pytest.mark.asyncio
async def test_required_runtime_redirect_is_not_followed_or_counted_healthy(monkeypatch):
    monkeypatch.setenv("MUSITU_TEST_HEALTH_URL", "https://runtime.invalid/health")
    options = {}

    def client_factory(*args, **kwargs):
        options.update(kwargs)
        return _Client(302)

    monkeypatch.setattr("app.component_registry.httpx.AsyncClient", client_factory)
    component = Component(
        "test-runtime",
        "Test Runtime",
        "test",
        "runtime",
        health_env="MUSITU_TEST_HEALTH_URL",
    )

    result = await probe_components([component])

    assert options["follow_redirects"] is False
    assert result["all_required_runtime_healthy"] is False
    assert result["components"][0]["state"] == "unhealthy"
    assert result["components"][0]["status_code"] == 302
