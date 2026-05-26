"""Tests for dynamic market registry and effective market settings."""

from pathlib import Path

import pytest

from src.core.market_settings import (
    get_configured_markets,
    get_effective_market_settings,
    get_market_definition,
)
from src.core.boxoffice_provider import market_for_provider, normalize_market, provider_for_market
from src.utils.config import MarketConfig, Settings


def _make_settings(**overrides) -> Settings:
    return Settings(boxarr_data_directory=Path("/tmp/boxarr-test"), **overrides)


def test_default_markets_fallback_to_us_and_fr():
    settings = _make_settings()
    configured = get_configured_markets(settings)

    assert "us" in configured
    assert "fr" in configured
    assert configured["us"]["provider"] == "mojo_us"
    assert configured["fr"]["provider"] == "jpboxoffice_fr"

    effective_us = get_effective_market_settings(settings, "us")
    assert effective_us["effective"]["box_office_fetch_limit"] == settings.boxarr_features_box_office_limit
    assert effective_us["sources"]["box_office_fetch_limit"] == "global"
    assert effective_us["effective"]["cleanup_protect_tag"] == "boxarr-keep"


def test_market_overrides_take_precedence_and_sources_reflect_market():
    settings = _make_settings(
        markets={
            "us": MarketConfig(
                label="US Box Office",
                provider="mojo_us",
                provider_config={"area": "us"},
                enabled=True,
                maximum_movies_to_add=3,
                auto_tag_text="boxarr-us",
                cleanup_protect_tag="boxarr-keep",
            ),
            "fr": MarketConfig(
                label="France Box Office",
                provider="jpboxoffice_fr",
                provider_config={"country": "fr"},
                enabled=True,
                maximum_movies_to_add=7,
                auto_tag_text="boxarr-fr",
                cleanup_protect_tag="boxarr-keep",
            ),
        }
    )

    us_effective = get_effective_market_settings(settings, "us")
    fr_effective = get_effective_market_settings(settings, "fr")

    assert us_effective["effective"]["maximum_movies_to_add"] == 3
    assert fr_effective["effective"]["maximum_movies_to_add"] == 7
    assert us_effective["sources"]["maximum_movies_to_add"] == "market"
    assert fr_effective["sources"]["maximum_movies_to_add"] == "market"
    assert us_effective["effective"]["tags"] == ["boxarr", "boxarr-us"]
    assert fr_effective["effective"]["tags"] == ["boxarr", "boxarr-fr"]
    assert us_effective["effective"]["cleanup_protect_tag"] == "boxarr-keep"


def test_null_override_falls_back_to_global():
    settings = _make_settings(
        boxarr_features_auto_add_limit=12,
        markets={
            "us": MarketConfig(
                label="US Box Office",
                provider="mojo_us",
                provider_config={"area": "us"},
                enabled=True,
                maximum_movies_to_add=None,
            ),
        },
    )

    effective = get_effective_market_settings(settings, "us")
    assert effective["effective"]["maximum_movies_to_add"] == 12
    assert effective["sources"]["maximum_movies_to_add"] == "global"


def test_dynamic_market_registry_accepts_custom_market(monkeypatch):
    settings = _make_settings(
        markets={
            "de": MarketConfig(
                label="Germany Box Office",
                provider="jpboxoffice_fr",
                provider_config={"country": "de"},
                enabled=True,
            )
        }
    )

    configured = get_configured_markets(settings)
    assert "de" in configured
    assert get_market_definition(settings, "de")["provider_config"] == {"country": "de"}
    monkeypatch.setattr(
        "src.core.boxoffice_provider._runtime_market_registry", lambda: configured
    )
    assert normalize_market("de") == "de"
    assert provider_for_market("de") == "jpboxoffice_fr"
    assert market_for_provider("jpboxoffice_fr") == "fr"


def test_unknown_market_raises_without_configuration():
    settings = _make_settings()
    with pytest.raises(ValueError):
        get_market_definition(settings, "bogus")
