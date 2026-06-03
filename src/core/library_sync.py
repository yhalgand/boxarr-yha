"""Helpers for refreshing stored weekly movie data from Radarr."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.config import settings
from ..utils.logger import get_logger
from .boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    market_for_provider,
    normalize_market,
    normalize_provider,
    provider_for_market,
)
from .boxoffice_storage import (
    iter_weekly_page_paths,
    market_weekly_page_path,
    market_weekly_pages_dir,
)
from .identity_reuse import (
    apply_stable_identity_reuse,
    build_stable_identity_cache,
)
from .models import MovieStatus
from .radarr import (
    RadarrMovie,
    RadarrService,
    get_all_movies_with_optional_cache_bypass,
)

logger = get_logger(__name__)


def _truncate_overview(overview: Optional[str]) -> Optional[str]:
    """Truncate overview text to match stored JSON shape."""
    if not overview:
        return overview
    return overview[:150] + "..." if len(overview) > 150 else overview


def _build_movie_update(
    movie: RadarrMovie,
    profiles_by_id: Dict[int, str],
    upgrade_profile_id: Optional[int],
) -> Dict[str, Any]:
    """Build the persisted JSON fields for a Radarr-backed movie."""
    if movie.hasFile:
        display_status = "Downloaded"
        status_color = "#48bb78"
        status_icon = "✅"
    elif movie.status == MovieStatus.RELEASED and getattr(movie, "isAvailable", False):
        display_status = "Missing"
        status_color = "#f56565"
        status_icon = "❌"
    elif movie.status == MovieStatus.IN_CINEMAS:
        display_status = "In Cinemas"
        status_color = "#f6ad55"
        status_icon = "🎬"
    else:
        display_status = "Pending"
        status_color = "#ed8936"
        status_icon = "⏳"

    return {
        "radarr_id": movie.id,
        "radarr_title": movie.title,
        "status": display_status,
        "status_color": status_color,
        "status_icon": status_icon,
        "quality_profile_id": movie.qualityProfileId,
        "quality_profile_name": profiles_by_id.get(movie.qualityProfileId or -1, ""),
        "has_file": movie.hasFile,
        "can_upgrade_quality": bool(
            settings.boxarr_features_quality_upgrade
            and movie.qualityProfileId is not None
            and upgrade_profile_id is not None
            and movie.qualityProfileId != upgrade_profile_id
        ),
        "year": movie.year,
        "genres": ", ".join(movie.genres[:2]) if movie.genres else None,
        "overview": _truncate_overview(movie.overview),
        "imdb_id": movie.imdbId,
        "tmdb_id": movie.tmdbId,
        "original_language": movie.original_language,
        "poster": movie.poster_url,
    }


def _build_stale_movie_clear(movie: Optional[RadarrMovie] = None) -> Dict[str, Any]:
    """Build the persisted JSON fields that should be cleared when Radarr loses a movie."""
    return {
        "radarr_id": None,
        "radarr_title": None,
        "radarr_status": None,
        "status": "Not in Radarr",
        "status_color": "#718096",
        "status_icon": "➕",
        "quality_profile_id": None,
        "quality_profile_name": None,
        "has_file": False,
        "radarr_has_file": False,
        "movie_file": None,
        "movieFile": None,
        "size_on_disk": None,
        "path": None,
        "can_upgrade_quality": False,
    }


def refresh_weekly_data_from_radarr(
    radarr_service: Optional[RadarrService] = None,
    data_directory: Optional[Path] = None,
    ignore_cache: bool = False,
    market: str = DEFAULT_MARKET,
    provider: Optional[str] = None,
) -> Dict[str, int]:
    """Refresh stored weekly JSON files with current Radarr status/details."""
    base_directory = data_directory or settings.boxarr_data_directory
    if provider is not None and market == DEFAULT_MARKET:
        market = market_for_provider(provider)
    market = normalize_market(market)
    provider = normalize_provider(provider or provider_for_market(market))
    weekly_paths = iter_weekly_page_paths(base_directory, market)
    if not weekly_paths:
        return {
            "weeks_scanned": 0,
            "weeks_updated": 0,
            "movies_refreshed": 0,
            "movies_linked": 0,
        }

    service = radarr_service or RadarrService()
    radarr_movies = get_all_movies_with_optional_cache_bypass(service, ignore_cache)
    profiles = service.get_quality_profiles()
    profiles_by_id = {profile.id: profile.name for profile in profiles}
    upgrade_profile_id = next(
        (
            profile.id
            for profile in profiles
            if profile.name == settings.radarr_quality_profile_upgrade
        ),
        None,
    )

    movies_by_id = {movie.id: movie for movie in radarr_movies}
    movies_by_tmdb_id = {movie.tmdbId: movie for movie in radarr_movies if movie.tmdbId}

    loaded_weeks: list[tuple[Path, dict]] = []
    for json_file in weekly_paths:
        try:
            with open(json_file) as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning(f"Could not read weekly data file {json_file}: {exc}")
            continue
        loaded_weeks.append((json_file, data))

    identity_cache = build_stable_identity_cache(
        (
            movie
            for _, data in loaded_weeks
            for movie in data.get("movies", [])
        ),
        market=market,
    )

    weeks_scanned = 0
    weeks_updated = 0
    movies_refreshed = 0
    movies_linked = 0

    for json_file, data in loaded_weeks:
        weeks_scanned += 1

        file_updated = False
        for stored_movie in data.get("movies", []):
            radarr_movie = None
            existing_radarr_id = stored_movie.get("radarr_id")
            stored_tmdb_id = stored_movie.get("tmdb_id")

            if existing_radarr_id:
                radarr_movie = movies_by_id.get(existing_radarr_id)

            if not radarr_movie and stored_tmdb_id:
                radarr_movie = movies_by_tmdb_id.get(stored_tmdb_id)

            if not radarr_movie:
                reused_identity = apply_stable_identity_reuse(
                    stored_movie,
                    identity_cache,
                    market=market,
                )
                if reused_identity:
                    movies_refreshed += 1
                    file_updated = True

                stored_match_method = str(stored_movie.get("match_method") or "").lower()
                already_confirmed = (
                    stored_movie.get("tmdb_id") is not None
                    and stored_match_method in {"tmdb_confirmed", "manual_confirmed"}
                )
                if already_confirmed:
                    continue

                stale_fields_present = any(
                    stored_movie.get(field) is not None
                    for field in (
                        "radarr_id",
                        "radarr_title",
                        "quality_profile_id",
                        "quality_profile_name",
                        "movie_file",
                        "movieFile",
                        "size_on_disk",
                        "path",
                    )
                ) or bool(
                    stored_movie.get("has_file")
                    or stored_movie.get("radarr_has_file")
                    or stored_movie.get("status")
                    and stored_movie.get("status") != "Not in Radarr"
                )
                if not stale_fields_present and not reused_identity:
                    continue

                updates = _build_stale_movie_clear()
                changed = False
                for key, value in updates.items():
                    if stored_movie.get(key) != value:
                        stored_movie[key] = value
                        changed = True

                if changed:
                    movies_refreshed += 1
                    file_updated = True
                continue

            was_unmatched = not existing_radarr_id
            updates = _build_movie_update(
                radarr_movie, profiles_by_id, upgrade_profile_id
            )

            changed = False
            for key, value in updates.items():
                if stored_movie.get(key) != value:
                    stored_movie[key] = value
                    changed = True

            if changed:
                movies_refreshed += 1
                file_updated = True
                if was_unmatched and stored_movie.get("radarr_id"):
                    movies_linked += 1

        if file_updated:
            data["matched_movies"] = sum(
                1 for movie in data.get("movies", []) if movie.get("radarr_id")
            )
            data["status_refreshed_at"] = datetime.now().isoformat()
            data["market"] = normalize_market(data.get("market") or market)
            data["provider"] = normalize_provider(data.get("provider") or provider)
            target_file = json_file
            if market == DEFAULT_MARKET and json_file.parent == base_directory / "weekly_pages":
                target_file = market_weekly_page_path(
                    base_directory, market, data["year"], data["week"]
                )
            with open(target_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
            weeks_updated += 1

    return {
        "weeks_scanned": weeks_scanned,
        "weeks_updated": weeks_updated,
        "movies_refreshed": movies_refreshed,
        "movies_linked": movies_linked,
    }
