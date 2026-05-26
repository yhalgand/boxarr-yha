"""JSON data generator for weekly box office pages."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.config import settings
from ..utils.logger import get_logger
from .boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    MARKET_DEFINITIONS,
    canonicalize_provider_definition,
    market_for_provider,
    normalize_market,
    normalize_provider,
    provider_for_market,
)
from .movie_identity import resolve_movie_identity
from .boxoffice_storage import market_weekly_page_path, market_weekly_pages_dir
from .matcher import MatchResult
from .models import MovieStatus
from .radarr import RadarrService

logger = get_logger(__name__)


class WeeklyDataGenerator:
    """Generates JSON data files for weekly box office data."""

    def __init__(
        self,
        radarr_service: Optional[RadarrService] = None,
        market: str = DEFAULT_MARKET,
        provider: Optional[str] = None,
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize data generator.

        Args:
            radarr_service: Optional Radarr service instance
            provider: Provider identifier
        """
        self.radarr_service = radarr_service
        if provider is not None and market == DEFAULT_MARKET:
            market = market_for_provider(provider)
        self.market = normalize_market(market)
        self.provider = normalize_provider(provider or provider_for_market(self.market))
        if provider_config is None:
            try:
                from ..utils.config import settings as current_settings
                from .market_settings import get_market_definition

                provider_config = get_market_definition(current_settings, self.market).get(
                    "provider_config", {}
                )
            except Exception:
                provider_config = {}
        canonical = canonicalize_provider_definition(self.provider, provider_config)
        self.provider = canonical["provider"]
        self.provider_config = canonical["provider_config"]
        self.provider_aliases = canonical["aliases"]
        self.output_dir = market_weekly_pages_dir(
            settings.boxarr_data_directory, self.market, create=True
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_weekly_data(
        self,
        match_results: List[MatchResult],
        year: int,
        week: int,
        radarr_movies: Optional[List] = None,
    ) -> Path:
        """
        Generate JSON data file for a week's box office data.

        Args:
            match_results: Movie matching results
            year: Year
            week: Week number
            radarr_movies: Optional list of Radarr movies (for compatibility)

        Returns:
            Path to generated JSON file
        """
        # Calculate friday and sunday from year and week
        from datetime import date, timedelta

        # Get the first day of the week (Monday)
        monday = date.fromisocalendar(year, week, 1)
        # Calculate Friday (4 days after Monday) and Sunday (6 days after Monday)
        friday = datetime.combine(monday + timedelta(days=4), datetime.min.time())
        sunday = datetime.combine(monday + timedelta(days=6), datetime.min.time())

        # Get quality profiles if available
        quality_profiles = {}
        ultra_hd_id = None

        if self.radarr_service:
            try:
                profiles = self.radarr_service.get_quality_profiles()
                quality_profiles = {p.id: p.name for p in profiles}

                # Find Ultra-HD profile
                for p in profiles:
                    if (
                        "ultra" in p.name.lower()
                        or "uhd" in p.name.lower()
                        or "2160" in p.name
                    ):
                        ultra_hd_id = p.id
                        break

                if not ultra_hd_id and settings.radarr_quality_profile_upgrade:
                    upgrade_profile = next(
                        (
                            p
                            for p in profiles
                            if p.name == settings.radarr_quality_profile_upgrade
                        ),
                        None,
                    )
                    if upgrade_profile:
                        ultra_hd_id = upgrade_profile.id

            except Exception as e:
                logger.warning(f"Could not fetch quality profiles: {e}")

        # Prepare movie data
        movies_data = []
        for result in match_results:
            movie_data = {
                "rank": result.box_office_movie.rank,
                "title": result.box_office_movie.title,
                "provider": self.provider,
                "provider_config": self.provider_config,
                "provider_aliases": self.provider_aliases,
                "weekend_gross": result.box_office_movie.weekend_gross,
                "total_gross": result.box_office_movie.total_gross,
                # Internal field is weeks_released; API response uses weeks_in_release.
                # Keep both aliases in storage for compatibility while FR uses admissions.
                "weeks_released": result.box_office_movie.weeks_released,
                "weeks_in_release": result.box_office_movie.weeks_released,
                "theater_count": result.box_office_movie.theater_count,
                "original_title": result.box_office_movie.original_title,
                "source_year": result.box_office_movie.year,
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
                    result.box_office_movie.weeks_released == 1
                    if result.box_office_movie.weeks_released is not None
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
                        "quality_profile_name": quality_profiles.get(
                            movie.qualityProfileId, ""
                        ),
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
                        "can_upgrade_quality": bool(
                            movie.qualityProfileId
                            and ultra_hd_id
                            and movie.qualityProfileId != ultra_hd_id
                            and settings.boxarr_features_quality_upgrade
                        ),
                    }
                )

                # Initial status (will be updated dynamically when page loads)
                if movie.hasFile:
                    movie_data["status"] = "Downloaded"
                    movie_data["status_color"] = "#48bb78"
                    movie_data["status_icon"] = "✅"
                elif movie.status == MovieStatus.RELEASED and movie.isAvailable:
                    movie_data["status"] = "Missing"
                    movie_data["status_color"] = "#f56565"
                    movie_data["status_icon"] = "❌"
                elif movie.status == MovieStatus.IN_CINEMAS:
                    movie_data["status"] = "In Cinemas"
                    movie_data["status_color"] = "#f6ad55"
                    movie_data["status_icon"] = "🎬"
                else:
                    movie_data["status"] = "Pending"
                    movie_data["status_color"] = "#ed8936"
                    movie_data["status_icon"] = "⏳"
            else:
                # For unmatched movies, ALWAYS try to get data from TMDB
                # This ensures we have poster and description for dashboard display
                if self.radarr_service:
                    try:
                        identity = resolve_movie_identity(
                            result.box_office_movie,
                            self.radarr_service.search_movie,
                            market=self.market,
                        )
                        if identity.matched and identity.movie_info:
                            tmdb_movie = identity.movie_info
                            movie_data.update(
                                {
                                    "tmdb_id": tmdb_movie.get("tmdbId"),
                                    "year": tmdb_movie.get("year"),
                                    "overview": (
                                        tmdb_movie.get("overview", "")[:150] + "..."
                                        if tmdb_movie.get("overview")
                                        and len(tmdb_movie.get("overview", "")) > 150
                                        else tmdb_movie.get("overview")
                                    ),
                                    "poster": tmdb_movie.get("remotePoster"),
                                    "imdb_id": tmdb_movie.get("imdbId"),
                                    "genres": (
                                        ", ".join(tmdb_movie.get("genres", [])[:2])
                                        if tmdb_movie.get("genres")
                                        else None
                                    ),
                                    "original_language": (
                                        tmdb_movie.get("originalLanguage", {}).get(
                                            "name"
                                        )
                                        if isinstance(
                                            tmdb_movie.get("originalLanguage"),
                                            dict,
                                        )
                                        else None
                                    ),
                                }
                            )
                            logger.info(
                                "Enriched '%s' with TMDB data (term='%s', confidence=%.2f)",
                                result.box_office_movie.title,
                                identity.search_term,
                                identity.confidence,
                            )
                        else:
                            logger.debug(
                                "No TMDB enrichment for '%s': %s",
                                result.box_office_movie.title,
                                identity.reason,
                            )
                    except Exception as e:
                        logger.warning(
                            f"Could not fetch TMDB data for '{result.box_office_movie.title}': {e}"
                        )

            movies_data.append(movie_data)

        # Save metadata with full movie data
        metadata = {
            "generated_at": datetime.now().isoformat(),
            "market": self.market,
            "provider": self.provider,
            "source": MARKET_DEFINITIONS.get(self.market, {}).get("source", "boxofficemojo"),
            "units": MARKET_DEFINITIONS.get(self.market, {}).get("units", "usd"),
            "year": year,
            "week": week,
            "friday": friday.isoformat(),
            "sunday": sunday.isoformat(),
            "total_movies": len(movies_data),
            "matched_movies": sum(1 for m in movies_data if m["radarr_id"]),
            "quality_profiles": quality_profiles,
            "ultra_hd_id": ultra_hd_id,
            "movies": movies_data,  # Store full movie data for display
        }

        # Save JSON file
        metadata_path = market_weekly_page_path(
            settings.boxarr_data_directory, self.market, year, week
        )
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Generated weekly data: {metadata_path}")
        return metadata_path
