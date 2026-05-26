"""Unit tests for market admin helpers."""

import pytest

from src.core.market_admin import (
    build_market_definition,
    infer_provider_config,
    normalize_market_key,
)


def test_normalize_market_key_accepts_safe_values():
    assert normalize_market_key("DE") == "de"
    assert normalize_market_key("my-market_1") == "my-market_1"


@pytest.mark.parametrize("key", ["", " ", "bad/key", "bad.key", "..", ".", "bad key"])
def test_normalize_market_key_rejects_dangerous_values(key):
    with pytest.raises(ValueError):
        normalize_market_key(key)


def test_infer_provider_config_defaults_by_provider_family():
    assert infer_provider_config("de", "jpboxoffice", {}) == {"country": "de"}
    assert infer_provider_config("us", "mojo", {}) == {"area": "us"}


def test_build_market_definition_infers_defaults_for_new_market():
    definition = build_market_definition(
        "de",
        {
            "label": "Germany Box Office",
            "provider": "jpboxoffice",
            "enabled": True,
        },
        create=True,
    )

    assert definition["provider"] == "jpboxoffice"
    assert definition["provider_config"] == {"country": "de"}
    assert definition["auto_tag_text"] == "boxarr-de"
    assert definition["tags"] == ["boxarr", "boxarr-de"]
    assert definition["cleanup_protect_tag"] == "boxarr-keep"


def test_build_market_definition_preserves_existing_fields_on_partial_update():
    definition = build_market_definition(
        "de",
        {"enabled": False},
        existing={
            "label": "Germany Box Office",
            "provider": "jpboxoffice",
            "provider_config": {"country": "de"},
            "enabled": True,
            "box_office_fetch_limit": 10,
            "maximum_movies_to_add": 3,
            "auto_add_enabled": True,
            "tags": ["boxarr", "boxarr-de"],
            "auto_tag_text": "boxarr-de",
            "cleanup_protect_tag": "boxarr-keep",
        },
        create=False,
    )

    assert definition["enabled"] is False
    assert definition["label"] == "Germany Box Office"
    assert definition["provider"] == "jpboxoffice"
    assert definition["provider_config"] == {"country": "de"}
    assert definition["box_office_fetch_limit"] == 10
    assert definition["maximum_movies_to_add"] == 3
    assert definition["auto_add_enabled"] is True
    assert definition["tags"] == ["boxarr", "boxarr-de"]
    assert definition["auto_tag_text"] == "boxarr-de"
    assert definition["cleanup_protect_tag"] == "boxarr-keep"
