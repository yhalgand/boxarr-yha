"""Shared pytest helpers for Boxarr integration tests."""

from __future__ import annotations

import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.boxoffice_provider import canonicalize_provider_definition
from src.core.boxoffice_storage import market_weekly_page_path
from src.core.market_policy import build_policy_snapshot, get_market_policy
from src.utils.config import settings


class FakeHealthRadarrService:
    """Minimal Radarr stand-in for health endpoint tests."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def test_connection(self) -> bool:
        return True


class FakeWeeklyDataGenerator:
    """Lightweight stand-in for WeeklyDataGenerator used in route tests.

    The real generator performs additional enrichment that is unnecessary for
    most route-level integration tests and can slow the suite down or hang on
    external calls. This helper writes a deterministic weekly JSON payload that
    preserves the fields the tests assert on.
    """

    def __init__(
        self,
        radarr_service: Optional[Any] = None,
        market: str = "us",
        provider: Optional[str] = None,
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        self.radarr_service = radarr_service
        self.market = market
        self.provider = provider or "mojo"
        if provider_config is None:
            provider_config = {}
        canonical = canonicalize_provider_definition(self.provider, provider_config)
        self.provider = canonical["provider"]
        self.provider_config = canonical["provider_config"]
        self.provider_aliases = canonical["aliases"]

    def generate_weekly_data(
        self,
        match_results: List[Any],
        year: int,
        week: int,
        radarr_movies: Optional[List] = None,
    ) -> Path:
        monday = date.fromisocalendar(year, week, 1)
        friday = datetime.combine(monday + timedelta(days=4), datetime.min.time())
        sunday = datetime.combine(monday + timedelta(days=6), datetime.min.time())

        movies_data = []
        for result in match_results:
            box_movie = result.box_office_movie
            movie_data = {
                "rank": box_movie.rank,
                "title": box_movie.title,
                "provider": self.provider,
                "provider_config": self.provider_config,
                "provider_aliases": self.provider_aliases,
                "weekend_gross": box_movie.weekend_gross,
                "total_gross": box_movie.total_gross,
                "weeks_released": box_movie.weeks_released,
                "weeks_in_release": box_movie.weeks_released,
                "theater_count": box_movie.theater_count,
                "original_title": box_movie.original_title,
                "source_year": box_movie.year,
                "radarr_id": None,
                "radarr_title": None,
                "status": "Not in Radarr",
                "status_color": "#718096",
                "status_icon": "➕",
                "quality_profile_id": None,
                "quality_profile_name": None,
                "has_file": False,
                "can_upgrade_quality": False,
                "poster": None,
                "year": None,
                "genres": None,
                "overview": None,
                "imdb_id": None,
                "tmdb_id": None,
                "original_language": None,
                "is_new_release": (
                    box_movie.weeks_released == 1
                    if box_movie.weeks_released is not None
                    else False
                ),
            }

            if result.is_matched and result.radarr_movie:
                movie = result.radarr_movie
                movie_data.update(
                    {
                        "radarr_id": movie.id,
                        "radarr_title": movie.title,
                        "quality_profile_id": movie.qualityProfileId,
                        "quality_profile_name": None,
                        "has_file": movie.hasFile,
                        "year": movie.year,
                        "genres": ", ".join(movie.genres[:2]) if movie.genres else None,
                        "overview": (
                            movie.overview[:150] + "..."
                            if movie.overview and len(movie.overview) > 150
                            else movie.overview
                        ),
                        "imdb_id": movie.imdbId,
                        "tmdb_id": movie.tmdbId,
                        "original_language": movie.original_language,
                        "poster": movie.poster_url,
                        "can_upgrade_quality": False,
                    }
                )
                if movie.hasFile:
                    movie_data["status"] = "Downloaded"
                    movie_data["status_color"] = "#48bb78"
                    movie_data["status_icon"] = "✅"
                else:
                    movie_data["status"] = "Missing"
                    movie_data["status_color"] = "#f56565"
                    movie_data["status_icon"] = "❌"

            movies_data.append(movie_data)

        market_policy = get_market_policy(settings, self.market)
        metadata = {
            "generated_at": datetime.now().isoformat(),
            "market": self.market,
            "provider": self.provider,
            "provider_config": self.provider_config,
            "provider_aliases": self.provider_aliases,
            "source": market_policy.get("provider", "boxofficemojo"),
            "units": "admissions" if self.provider == "jpboxoffice" else "usd",
            "policy_snapshot": build_policy_snapshot(market_policy, year, week),
            "year": year,
            "week": week,
            "friday": friday.isoformat(),
            "sunday": sunday.isoformat(),
            "total_movies": len(movies_data),
            "matched_movies": sum(1 for m in movies_data if m["radarr_id"]),
            "quality_profiles": {},
            "ultra_hd_id": None,
            "movies": movies_data,
        }

        metadata_path = market_weekly_page_path(
            settings.boxarr_data_directory, self.market, year, week
        )
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return metadata_path
