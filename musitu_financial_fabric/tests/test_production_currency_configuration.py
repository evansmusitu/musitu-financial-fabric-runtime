from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_accept_uppercase_ascii_production_currencies():
    cfg = Settings(production_enabled_currencies=("USD", "ZWL"))
    assert cfg.production_enabled_currencies == ("USD", "ZWL")


def test_settings_reject_non_ascii_production_currency():
    with pytest.raises(ValueError, match="uppercase ASCII three-letter"):
        Settings(production_enabled_currencies=("ΑΒΓ",))


def test_settings_reject_lowercase_direct_production_currency():
    with pytest.raises(ValueError, match="uppercase ASCII three-letter"):
        Settings(production_enabled_currencies=("usd",))
