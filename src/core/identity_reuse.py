"""Helpers for stable cross-week source identity reuse."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .boxoffice_provider import normalize_market
from .history_sanitizer import normalize_title_key

_CONFIRMED_MATCH_METHODS = {"manual_confirmed", "tmdb_confirmed"}


def _record_get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _metadata_get(record: Any, key: str, default: Any = None) -> Any:
    metadata = _record_get(record, "identity_metadata")
    if isinstance(metadata, dict):
        return metadata.get(key, default)
    return default


def normalized_source_title_key(record: Any) -> str:
    title = (
        _record_get(record, "normalized_source_title")
        or _record_get(record, "source_title")
        or _record_get(record, "title")
    )
    return normalize_title_key(title)


def stable_identity_aliases(
    record: Any, market: Optional[str] = None
) -> List[str]:
    market_key = normalize_market(
        _record_get(record, "market") or market or "us"
    )

    aliases: List[str] = []
    jpboxoffice_id = _record_get(record, "jpboxoffice_id")
    if jpboxoffice_id is None:
        jpboxoffice_id = _metadata_get(record, "jpboxoffice_id")
    try:
        if jpboxoffice_id is not None:
            aliases.append(f"{market_key}:jpboxoffice_id:{int(jpboxoffice_id)}")
    except (TypeError, ValueError):
        pass
    allocine_movie_id = _record_get(record, "allocine_movie_id")
    if allocine_movie_id is None:
        allocine_movie_id = _metadata_get(record, "allocine_movie_id")
    try:
        if allocine_movie_id is not None:
            aliases.append(f"{market_key}:allocine_movie_id:{int(allocine_movie_id)}")
    except (TypeError, ValueError):
        pass

    source_href = _record_get(record, "source_href") or _record_get(record, "release_url")
    if isinstance(source_href, str) and source_href.strip():
        aliases.append(f"{market_key}:source_href:{source_href.strip()}")

    title_key = normalized_source_title_key(record)
    if title_key:
        aliases.append(f"{market_key}:source_title:{title_key}")

    seen = set()
    deduped: List[str] = []
    for alias in aliases:
        if alias and alias not in seen:
            seen.add(alias)
            deduped.append(alias)
    return deduped


def stable_identity_key(record: Any, market: Optional[str] = None) -> Optional[str]:
    aliases = stable_identity_aliases(record, market=market)
    return aliases[0] if aliases else None


def identity_priority(record: Any) -> Tuple[int, float, int, int]:
    """Sort identities from strongest to weakest."""
    match_method = str(_record_get(record, "match_method") or "").strip().lower()
    confidence = _record_get(record, "match_confidence", 0.0)
    try:
        confidence_value = float(confidence or 0.0)
    except (TypeError, ValueError):
        confidence_value = 0.0
    radarr_id = _record_get(record, "radarr_id")
    tmdb_id = _record_get(record, "tmdb_id")

    if match_method == "manual_confirmed" and radarr_id is not None:
        tier = 4
    elif match_method == "tmdb_confirmed" and radarr_id is not None:
        tier = 3
    elif match_method == "manual_confirmed":
        tier = 2
    elif match_method == "tmdb_confirmed":
        tier = 1
    else:
        tier = 0

    return (
        tier,
        confidence_value,
        1 if radarr_id is not None else 0,
        1 if tmdb_id is not None else 0,
    )


def is_confirmed_identity(record: Any) -> bool:
    return (
        identity_priority(record)[0] > 0
        and _record_get(record, "tmdb_id") is not None
        and float(_record_get(record, "match_confidence", 0.0) or 0.0) > 0
    )


def build_stable_identity_cache(
    records: Iterable[Any], market: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """Build a best-identity cache keyed by stable source identity."""
    cache: Dict[str, Dict[str, Any]] = {}
    priorities: Dict[str, Tuple[int, float, int, int]] = {}

    for record in records:
        if not is_confirmed_identity(record):
            continue
        aliases = stable_identity_aliases(record, market=market)
        if not aliases:
            continue
        priority = identity_priority(record)
        for key in aliases:
            if key not in cache or priority > priorities[key]:
                cache[key] = dict(record)
                priorities[key] = priority

    return cache


def apply_stable_identity_reuse(
    record: Dict[str, Any], cache: Dict[str, Dict[str, Any]], market: Optional[str] = None
) -> bool:
    """Apply a cached identity to a record when the source identity matches."""
    aliases = stable_identity_aliases(record, market=market)
    if not aliases:
        return False
    cached = None
    for key in aliases:
        cached = cache.get(key)
        if cached:
            break
    if not cached:
        return False

    current_priority = identity_priority(record)
    cached_priority = identity_priority(cached)
    if cached_priority <= current_priority and record.get("tmdb_id") is not None:
        return False

    changed = False
    for field in (
        "source_href",
        "source_url",
        "source_title",
        "normalized_source_title",
        "jpboxoffice_id",
        "allocine_movie_id",
        "market",
        "country",
        "tmdb_id",
        "match_confidence",
        "match_method",
        "identity_status",
        "year",
        "poster",
        "overview",
        "imdb_id",
        "genres",
        "original_language",
    ):
        value = cached.get(field)
        if value is not None and record.get(field) != value:
            record[field] = value
            changed = True

    return changed
