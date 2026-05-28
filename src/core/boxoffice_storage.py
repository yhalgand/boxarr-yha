"""Helpers for market-aware weekly page and history storage."""

from __future__ import annotations

from pathlib import Path
from typing import List, Set

from .boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    market_for_provider,
    normalize_market,
    provider_for_market,
)


def week_key(year: int, week: int) -> str:
    return f"{year}W{week:02d}"


def weekly_pages_root(base_dir: Path) -> Path:
    base_dir = Path(base_dir)
    return base_dir / "weekly_pages"


def history_root(base_dir: Path) -> Path:
    base_dir = Path(base_dir)
    return base_dir / "history"


def market_weekly_pages_dir(base_dir: Path, market: str, create: bool = False) -> Path:
    base_dir = Path(base_dir)
    market = normalize_market(market)
    path = weekly_pages_root(base_dir) / market
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def market_history_dir(base_dir: Path, market: str, create: bool = False) -> Path:
    base_dir = Path(base_dir)
    market = normalize_market(market)
    path = history_root(base_dir) / market
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_weekly_page_path(base_dir: Path, year: int, week: int) -> Path:
    base_dir = Path(base_dir)
    return weekly_pages_root(base_dir) / f"{week_key(year, week)}.json"


def legacy_history_latest_path(base_dir: Path, year: int, week: int) -> Path:
    base_dir = Path(base_dir)
    return history_root(base_dir) / f"{week_key(year, week)}_latest.json"


def market_weekly_page_path(
    base_dir: Path, market: str, year: int, week: int, create_dir: bool = True
) -> Path:
    base_dir = Path(base_dir)
    return market_weekly_pages_dir(base_dir, market, create=create_dir) / f"{week_key(year, week)}.json"


def market_history_file_path(
    base_dir: Path,
    market: str,
    year: int,
    week: int,
    suffix: str,
    create_dir: bool = True,
) -> Path:
    base_dir = Path(base_dir)
    directory = market_history_dir(base_dir, market, create=create_dir)
    return directory / f"{week_key(year, week)}_{suffix}.json"


def market_history_latest_file_path(
    base_dir: Path, market: str, year: int, week: int, create_dir: bool = True
) -> Path:
    base_dir = Path(base_dir)
    return market_history_file_path(
        base_dir, market, year, week, "latest", create_dir=create_dir
    )


def resolve_weekly_page_path(base_dir: Path, market: str, year: int, week: int) -> Path:
    base_dir = Path(base_dir)
    market = normalize_market(market)
    preferred = market_weekly_page_path(base_dir, market, year, week, create_dir=False)
    if preferred.exists():
        return preferred

    if market == DEFAULT_MARKET:
        legacy = legacy_weekly_page_path(base_dir, year, week)
        if legacy.exists():
            return legacy

    return preferred


def resolve_history_latest_path(base_dir: Path, market: str, year: int, week: int) -> Path:
    base_dir = Path(base_dir)
    market = normalize_market(market)
    preferred = market_history_latest_file_path(
        base_dir, market, year, week, create_dir=False
    )
    if preferred.exists():
        return preferred

    if market == DEFAULT_MARKET:
        legacy = legacy_history_latest_path(base_dir, year, week)
        if legacy.exists():
            return legacy

    return preferred


def iter_weekly_page_paths(base_dir: Path, market: str) -> List[Path]:
    """Return market-aware weekly metadata paths, including legacy fallback for US."""
    base_dir = Path(base_dir)
    market = normalize_market(market)
    paths: List[Path] = []
    seen: Set[str] = set()

    market_dir = market_weekly_pages_dir(base_dir, market)
    if market_dir.exists():
        for json_file in sorted(market_dir.glob("*.json")):
            if json_file.name == "current.json":
                continue
            paths.append(json_file)
            seen.add(json_file.stem)

    if market == DEFAULT_MARKET:
        legacy_dir = weekly_pages_root(base_dir)
        if legacy_dir.exists():
            for json_file in sorted(legacy_dir.glob("*.json")):
                if json_file.name == "current.json":
                    continue
                if json_file.stem in seen:
                    continue
                paths.append(json_file)

    return sorted(paths, key=lambda path: path.name, reverse=True)


def iter_history_paths(base_dir: Path, market: str) -> List[Path]:
    """Return market-aware history paths, including legacy fallback for US."""
    base_dir = Path(base_dir)
    market = normalize_market(market)
    paths: List[Path] = []
    seen: Set[str] = set()

    market_dir = market_history_dir(base_dir, market)
    if market_dir.exists():
        for json_file in sorted(market_dir.glob("*.json")):
            paths.append(json_file)
            seen.add(json_file.stem)

    if market == DEFAULT_MARKET:
        legacy_dir = history_root(base_dir)
        if legacy_dir.exists():
            for json_file in sorted(legacy_dir.glob("*.json")):
                if json_file.stem in seen:
                    continue
                paths.append(json_file)

    return sorted(paths, key=lambda path: path.name, reverse=True)


def market_from_path_alias(market_or_provider: str) -> str:
    """Helper for compat code paths that still pass providers."""
    try:
        return normalize_market(market_or_provider)
    except ValueError:
        return market_for_provider(market_or_provider)


def provider_alias_for_market(market: str) -> str:
    """Return the provider tied to a market."""
    return provider_for_market(market)


def market_from_provider_alias(provider: str) -> str:
    """Return the market tied to a provider."""
    return market_for_provider(provider)


# Backward-compatible aliases for older imports.
provider_weekly_pages_dir = market_weekly_pages_dir
provider_history_dir = market_history_dir
provider_weekly_page_path = market_weekly_page_path
provider_history_file_path = market_history_file_path
provider_history_latest_file_path = market_history_latest_file_path
