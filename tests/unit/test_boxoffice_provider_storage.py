"""Tests for market normalization and market-aware storage helpers."""

import pytest

from src.core.boxoffice import JPBoxOfficeFRProvider, MojoUSProvider, create_provider
from src.core.boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    market_from_provider,
    normalize_market,
    normalize_provider,
    provider_from_market,
)
from src.core.boxoffice_storage import (
    iter_history_paths,
    iter_weekly_page_paths,
    market_history_latest_file_path,
    market_weekly_page_path,
    resolve_history_latest_path,
    resolve_weekly_page_path,
)
from src.core.exceptions import BoxOfficeError


def test_market_and_provider_mapping():
    assert normalize_market(None) == DEFAULT_MARKET
    assert normalize_market("US") == "us"
    assert normalize_market("fr") == "fr"
    assert normalize_provider(None) == DEFAULT_PROVIDER
    assert normalize_provider("mojo_us") == "mojo"
    assert normalize_provider("jpboxoffice_fr") == "jpboxoffice"
    assert provider_from_market("us") == "mojo"
    assert provider_from_market("fr") == "jpboxoffice"
    assert market_from_provider("mojo_us") == "us"
    assert market_from_provider("jpboxoffice_fr") == "fr"
    assert market_from_provider("mojo") == "us"
    assert market_from_provider("jpboxoffice") == "fr"

    with pytest.raises(ValueError):
        normalize_market("de")

    with pytest.raises(ValueError):
        normalize_provider("bogus")

    with pytest.raises(ValueError):
        provider_from_market("DE")


def test_market_paths_and_legacy_fallback(tmp_path):
    legacy_week = tmp_path / "weekly_pages" / "2024W10.json"
    legacy_week.parent.mkdir(parents=True)
    legacy_week.write_text("{}")

    legacy_history = tmp_path / "history" / "2024W10_latest.json"
    legacy_history.parent.mkdir(parents=True)
    legacy_history.write_text("{}")

    assert resolve_weekly_page_path(tmp_path, "us", 2024, 10) == legacy_week
    assert resolve_history_latest_path(tmp_path, "us", 2024, 10) == legacy_history

    provider_week = market_weekly_page_path(tmp_path, "us", 2024, 10)
    provider_history = market_history_latest_file_path(tmp_path, "us", 2024, 10)
    assert provider_week == tmp_path / "weekly_pages" / "us" / "2024W10.json"
    assert provider_history == tmp_path / "history" / "us" / "2024W10_latest.json"

    fr_week = resolve_weekly_page_path(tmp_path, "fr", 2024, 10)
    fr_history = resolve_history_latest_path(tmp_path, "fr", 2024, 10)
    assert fr_week == tmp_path / "weekly_pages" / "fr" / "2024W10.json"
    assert fr_history == tmp_path / "history" / "fr" / "2024W10_latest.json"


def test_iterators_prefer_market_files_and_keep_legacy_us(tmp_path):
    provider_week = tmp_path / "weekly_pages" / "us" / "2024W10.json"
    provider_week.parent.mkdir(parents=True)
    provider_week.write_text("{}")

    legacy_week = tmp_path / "weekly_pages" / "2024W11.json"
    legacy_week.write_text("{}")

    provider_history = tmp_path / "history" / "us" / "2024W10_latest.json"
    provider_history.parent.mkdir(parents=True)
    provider_history.write_text("{}")

    legacy_history = tmp_path / "history" / "2024W10_latest.json"
    legacy_history.write_text("{}")

    weekly_paths = iter_weekly_page_paths(tmp_path, "us")
    history_paths = iter_history_paths(tmp_path, "us")

    assert provider_week in weekly_paths
    assert legacy_week in weekly_paths
    assert len([p for p in weekly_paths if p.stem == "2024W10"]) == 1

    assert provider_history in history_paths
    assert legacy_history not in history_paths
    assert len([p for p in history_paths if p.stem == "2024W10_latest"]) == 1


def test_iterators_do_not_fall_back_to_legacy_for_fr(tmp_path):
    legacy_week = tmp_path / "weekly_pages" / "2024W10.json"
    legacy_week.parent.mkdir(parents=True)
    legacy_week.write_text("{}")

    legacy_history = tmp_path / "history" / "2024W10_latest.json"
    legacy_history.parent.mkdir(parents=True)
    legacy_history.write_text("{}")

    weekly_paths = iter_weekly_page_paths(tmp_path, "fr")
    history_paths = iter_history_paths(tmp_path, "fr")

    assert legacy_week not in weekly_paths
    assert legacy_history not in history_paths


def test_fr_provider_is_real_provider_class():
    provider = create_provider("jpboxoffice_fr")
    assert isinstance(provider, JPBoxOfficeFRProvider)


def test_generic_providers_accept_canonical_config():
    mojo = create_provider("mojo", provider_config={"area": "us"})
    assert isinstance(mojo, MojoUSProvider)

    fr = create_provider("jpboxoffice", provider_config={"country": "fr"})
    assert isinstance(fr, JPBoxOfficeFRProvider)

    supported = {
        "fr": 2,
        "de": 4,
        "br": 36,
        "cn": 30,
        "kr": 34,
        "es": 33,
        "it": 32,
        "ru": 35,
    }
    for country, expected_view in supported.items():
        provider = create_provider("jpboxoffice", provider_config={"country": country})
        assert provider.country == country
        assert provider.view == expected_view

    with pytest.raises(BoxOfficeError) as exc:
        create_provider("jpboxoffice", provider_config={"country": "world"})
    assert "not implemented yet" in str(exc.value)
