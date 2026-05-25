"""Tests for market normalization and market-aware storage helpers."""

import pytest

from src.core.boxoffice import JPBoxOfficeFRProvider, create_provider
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
    assert normalize_provider("mojo_us") == "mojo_us"
    assert normalize_provider("jpboxoffice_fr") == "jpboxoffice_fr"
    assert provider_from_market("us") == "mojo_us"
    assert provider_from_market("fr") == "jpboxoffice_fr"
    assert market_from_provider("mojo_us") == "us"
    assert market_from_provider("jpboxoffice_fr") == "fr"

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


def test_fr_provider_is_stubbed_cleanly():
    provider = create_provider("jpboxoffice_fr")
    assert isinstance(provider, JPBoxOfficeFRProvider)

    with pytest.raises(BoxOfficeError) as excinfo:
        provider.fetch_weekend_box_office(2024, 10)

    assert "not implemented yet" in str(excinfo.value)
