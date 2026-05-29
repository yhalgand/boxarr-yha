"""Helpers for sanitizing historical weekly box office payloads."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional


def normalize_title_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_header_like_title(value: object) -> bool:
    normalized = normalize_title_key(value)
    return normalized in {"titre", "title", "image"}


def _confidence(record: dict) -> float:
    try:
        value = record.get("match_confidence")
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _dedupe_key(record: dict, field: str) -> Optional[int]:
    value = record.get(field)
    if isinstance(value, bool):
        return None
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clear_record(record: dict) -> None:
    record["tmdb_id"] = None
    record["radarr_id"] = None
    record["radarr_title"] = None
    record["radarr_status"] = None
    record["radarr_has_file"] = False
    record["has_file"] = False
    record["match_confidence"] = 0.0
    record["match_method"] = "duplicate_rejected"


def sanitize_history_movies(movies: List[dict]) -> List[dict]:
    """Sanitize historical weekly payloads.

    - Drop obvious header rows
    - Clear IDs/status when confidence is non-positive
    - Deduplicate tmdb/radarr IDs across different titles
    - Renumber sequentially by remaining order
    """

    sanitized: List[dict] = []
    for movie in movies:
        title = movie.get("title") or movie.get("radarr_title") or movie.get("original_title")
        if is_header_like_title(title):
            continue
        sanitized.append(movie)

    for record in sanitized:
        if _confidence(record) <= 0:
            _clear_record(record)

    for field in ("tmdb_id", "radarr_id"):
        by_id: Dict[int, List[int]] = {}
        by_title: Dict[int, str] = {}
        for idx, movie in enumerate(sanitized):
            movie_id = _dedupe_key(movie, field)
            if movie_id is None:
                continue
            by_id.setdefault(movie_id, []).append(idx)
            by_title[idx] = normalize_title_key(movie.get("title") or movie.get("original_title"))

        for _, indexes in by_id.items():
            if len(indexes) < 2:
                continue
            title_keys = {by_title[i] for i in indexes}
            if len(title_keys) <= 1:
                continue
            ranked = sorted(indexes, key=lambda i: (_confidence(sanitized[i]), -i), reverse=True)
            winner = ranked[0]
            if _confidence(sanitized[winner]) <= 0:
                for idx in indexes:
                    _clear_record(sanitized[idx])
                continue
            for idx in indexes:
                if idx == winner:
                    continue
                _clear_record(sanitized[idx])

    for index, record in enumerate(sanitized, start=1):
        record["rank"] = index

    return sanitized
