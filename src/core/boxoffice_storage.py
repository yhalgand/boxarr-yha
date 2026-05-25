"""Helpers for provider-aware weekly page and history storage."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

from .boxoffice_provider import DEFAULT_PROVIDER, normalize_provider


def week_key(year: int, week: int) -> str:
    return f"{year}W{week:02d}"


def weekly_pages_root(base_dir: Path) -> Path:
    return base_dir / "weekly_pages"


def history_root(base_dir: Path) -> Path:
    return base_dir / "history"


def provider_weekly_pages_dir(base_dir: Path, provider: str, create: bool = False) -> Path:
    provider = normalize_provider(provider)
    path = weekly_pages_root(base_dir) / provider
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def provider_history_dir(base_dir: Path, provider: str, create: bool = False) -> Path:
    provider = normalize_provider(provider)
    path = history_root(base_dir) / provider
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_weekly_page_path(base_dir: Path, year: int, week: int) -> Path:
    return weekly_pages_root(base_dir) / f"{week_key(year, week)}.json"


def legacy_history_latest_path(base_dir: Path, year: int, week: int) -> Path:
    return history_root(base_dir) / f"{week_key(year, week)}_latest.json"


def provider_weekly_page_path(
    base_dir: Path, provider: str, year: int, week: int, create_dir: bool = True
) -> Path:
    return provider_weekly_pages_dir(
        base_dir, provider, create=create_dir
    ) / f"{week_key(year, week)}.json"


def provider_history_file_path(
    base_dir: Path,
    provider: str,
    year: int,
    week: int,
    suffix: str,
    create_dir: bool = True,
) -> Path:
    directory = provider_history_dir(base_dir, provider, create=create_dir)
    return directory / f"{week_key(year, week)}_{suffix}.json"


def provider_history_latest_file_path(
    base_dir: Path, provider: str, year: int, week: int, create_dir: bool = True
) -> Path:
    return provider_history_file_path(
        base_dir, provider, year, week, "latest", create_dir=create_dir
    )


def resolve_weekly_page_path(base_dir: Path, provider: str, year: int, week: int) -> Path:
    provider = normalize_provider(provider)
    preferred = provider_weekly_page_path(
        base_dir, provider, year, week, create_dir=False
    )
    if preferred.exists():
        return preferred

    if provider == DEFAULT_PROVIDER:
        legacy = legacy_weekly_page_path(base_dir, year, week)
        if legacy.exists():
            return legacy

    return preferred


def resolve_history_latest_path(base_dir: Path, provider: str, year: int, week: int) -> Path:
    provider = normalize_provider(provider)
    preferred = provider_history_latest_file_path(
        base_dir, provider, year, week, create_dir=False
    )
    if preferred.exists():
        return preferred

    if provider == DEFAULT_PROVIDER:
        legacy = legacy_history_latest_path(base_dir, year, week)
        if legacy.exists():
            return legacy

    return preferred


def iter_weekly_page_paths(base_dir: Path, provider: str) -> List[Path]:
    """Return provider-aware weekly metadata paths, including legacy fallback for US."""
    provider = normalize_provider(provider)
    paths: List[Path] = []
    seen: Set[str] = set()

    provider_dir = provider_weekly_pages_dir(base_dir, provider)
    if provider_dir.exists():
        for json_file in sorted(provider_dir.glob("*.json")):
            if json_file.name == "current.json":
                continue
            paths.append(json_file)
            seen.add(json_file.stem)

    if provider == DEFAULT_PROVIDER:
        legacy_dir = weekly_pages_root(base_dir)
        if legacy_dir.exists():
            for json_file in sorted(legacy_dir.glob("*.json")):
                if json_file.name == "current.json":
                    continue
                if json_file.stem in seen:
                    continue
                paths.append(json_file)

    return sorted(paths, key=lambda path: path.name, reverse=True)


def iter_history_paths(base_dir: Path, provider: str) -> List[Path]:
    """Return provider-aware history paths, including legacy fallback for US."""
    provider = normalize_provider(provider)
    paths: List[Path] = []
    seen: Set[str] = set()

    provider_dir = provider_history_dir(base_dir, provider)
    if provider_dir.exists():
        for json_file in sorted(provider_dir.glob("*.json")):
            paths.append(json_file)
            seen.add(json_file.stem)

    if provider == DEFAULT_PROVIDER:
        legacy_dir = history_root(base_dir)
        if legacy_dir.exists():
            for json_file in sorted(legacy_dir.glob("*.json")):
                if json_file.stem in seen:
                    continue
                paths.append(json_file)

    return sorted(paths, key=lambda path: path.name, reverse=True)
