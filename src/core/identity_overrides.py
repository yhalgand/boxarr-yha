"""Persistent manual identity overrides for box office movies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.config import settings
from ..utils.logger import get_logger
from .history_sanitizer import normalize_title_key
from .boxoffice_provider import normalize_market

logger = get_logger(__name__)

IDENTITY_OVERRIDES_FILENAME = "identity_overrides.json"


def _overrides_path(base_directory: Optional[Path] = None) -> Path:
    base = Path(base_directory or settings.boxarr_data_directory)
    return base / IDENTITY_OVERRIDES_FILENAME


def load_identity_overrides(base_directory: Optional[Path] = None) -> Dict[str, Any]:
    path = _overrides_path(base_directory)
    if not path.exists():
        return {"markets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("markets", {})
            if isinstance(data["markets"], dict):
                return data
    except Exception as exc:
        logger.debug("Failed to load identity overrides from %s: %s", path, exc)
    return {"markets": {}}


def lookup_identity_override(
    market: str,
    *,
    jpboxoffice_id: Optional[int] = None,
    allocine_movie_id: Optional[int] = None,
    title: Optional[str] = None,
    year: Optional[int] = None,
    base_directory: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    data = load_identity_overrides(base_directory)
    market_key = normalize_market(market)
    market_bucket = data.get("markets", {}).get(market_key, {})
    if not isinstance(market_bucket, dict):
        return None

    if jpboxoffice_id is not None:
        by_id = market_bucket.get("jpboxoffice_ids", {})
        override = by_id.get(str(int(jpboxoffice_id))) if isinstance(by_id, dict) else None
        if isinstance(override, dict):
            return dict(override)

    if allocine_movie_id is not None:
        by_id = market_bucket.get("allocine_movie_ids", {})
        override = by_id.get(str(int(allocine_movie_id))) if isinstance(by_id, dict) else None
        if isinstance(override, dict):
            return dict(override)

    normalized_title = normalize_title_key(title)
    if normalized_title:
        title_key = normalized_title
        if year is not None:
            title_key = f"{title_key}|{int(year)}"
        by_title = market_bucket.get("titles", {})
        override = by_title.get(title_key) if isinstance(by_title, dict) else None
        if isinstance(override, dict):
            return dict(override)

    return None
