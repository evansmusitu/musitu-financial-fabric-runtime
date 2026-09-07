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
