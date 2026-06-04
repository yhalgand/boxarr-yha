"""Box office data routes."""

from datetime import datetime
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...core.boxoffice import BoxOfficeService
from ...core.boxoffice_provider import (
    DEFAULT_MARKET,
    market_for_provider,
    normalize_market,
    provider_for_market,
)
from ...core.boxoffice_storage import resolve_weekly_page_path
from ...core.history_sanitizer import sanitize_history_movies
from ...core.market_settings import get_effective_market_settings
from ...core.market_settings import get_market_capabilities
from ...core.exceptions import BoxOfficeError
from ...core.matcher import MovieMatcher
from ...core.radarr import RadarrService
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/boxoffice", tags=["boxoffice"])


def _is_parse_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "parse error" in message or "no ranking rows parsed" in message or "partial ranking parse" in message


class BoxOfficeMovieResponse(BaseModel):
    """Box office movie response model."""

    rank: int
    title: str
    weekend_gross: Optional[float] = None
    total_gross: Optional[float] = None
    weeks_in_release: Optional[int] = None
    theater_count: Optional[int] = None
    is_new_release: bool = False
    radarr_id: Optional[int] = None
    radarr_status: Optional[str] = None
    radarr_has_file: bool = False
    match_confidence: float = 0.0
    tmdb_id: Optional[int] = None
    source_href: Optional[str] = None
    source_title: Optional[str] = None
    normalized_source_title: Optional[str] = None
    source_url: Optional[str] = None
    jpboxoffice_id: Optional[int] = None
    allocine_movie_id: Optional[int] = None
    identity_status: Optional[str] = None
    match_method: Optional[str] = None
    year: Optional[int] = None
    poster: Optional[str] = None
    imdb_id: Optional[str] = None
    genres: Optional[str] = None


def _build_history_movie_response(
    stored_movie: dict,
    radarr_movies_by_id: Optional[dict] = None,
    radarr_movies_by_tmdb: Optional[dict] = None,
) -> dict:
    """Return a historical movie payload without dropping stored metadata."""
    result = dict(stored_movie)

    raw_confidence = result.get("match_confidence", None)
    try:
        match_confidence = float(raw_confidence) if raw_confidence is not None else None
    except (TypeError, ValueError):
        match_confidence = None

    if match_confidence is not None and match_confidence <= 0:
        result["tmdb_id"] = None
        result["radarr_id"] = None
        result["radarr_title"] = None
        result["radarr_status"] = None
        result["radarr_has_file"] = False
        result["has_file"] = False
        result["status"] = result.get("status") or "Not in Radarr"
        result["match_confidence"] = 0.0
        if "match_method" not in result:
            result["match_method"] = "unmatched"
        return result

    radarr_id = result.get("radarr_id")
    tmdb_id = result.get("tmdb_id")

    radarr_movie = None
    if radarr_id and radarr_movies_by_id:
        radarr_movie = radarr_movies_by_id.get(radarr_id)
    if not radarr_movie and tmdb_id and radarr_movies_by_tmdb:
        radarr_movie = radarr_movies_by_tmdb.get(tmdb_id)

    if radarr_movie:
        result["radarr_id"] = radarr_movie.id
        result["radarr_title"] = radarr_movie.title
        result["radarr_status"] = (
            radarr_movie.status.value if radarr_movie.status else result.get("radarr_status")
        )
        result["radarr_has_file"] = radarr_movie.hasFile
        result["radarr_has_file"] = bool(result["radarr_has_file"])
        result["match_confidence"] = result.get("match_confidence", 0.0)
        result["has_file"] = radarr_movie.hasFile
        result["status"] = (
            "Downloaded"
            if radarr_movie.hasFile
            else "Missing"
            if radarr_movie.status and radarr_movie.status.value == "released"
            else result.get("status")
        )
    else:
        # Preserve legacy JSON aliases when the file predates the radarr_* fields.
        if result.get("radarr_status") is None and result.get("status") is not None:
            result["radarr_status"] = result.get("status")
        if result.get("radarr_has_file") is None and result.get("has_file") is not None:
            result["radarr_has_file"] = bool(result.get("has_file"))
        if result.get("match_confidence") is None:
            result["match_confidence"] = 0.0
        if "radarr_has_file" in result:
            result["radarr_has_file"] = bool(result["radarr_has_file"])

    # Keep aliases in sync for consumers that expect either name.
    if "weeks_in_release" not in result and result.get("weeks_released") is not None:
        result["weeks_in_release"] = result.get("weeks_released")
    if "weeks_released" not in result and result.get("weeks_in_release") is not None:
        result["weeks_released"] = result.get("weeks_in_release")

    return result


@router.get("/current", response_model=List[BoxOfficeMovieResponse])
async def get_current_box_office(
    market: str = Query(DEFAULT_MARKET, description="Box office market"),
    provider: Optional[str] = Query(None, description="Compat provider fallback"),
):
    """Get current week's box office with Radarr matching."""
    try:
        if provider and market == DEFAULT_MARKET:
            market = market_for_provider(provider)
        market = normalize_market(market)
        provider = provider_for_market(market)
        market_effective = get_effective_market_settings(settings, market)
        # Get current week's box office
        boxoffice_service = BoxOfficeService(market=market)
        movies = boxoffice_service.get_current_week_movies(
            limit=int(
                market_effective.get("effective", {}).get(
                    "box_office_fetch_limit", settings.boxarr_features_box_office_limit
                )
            )
        )

        # Match with Radarr if configured
        results = []
        if settings.radarr_api_key:
            radarr_service = RadarrService()
            matcher = MovieMatcher()
            search_movie_tmdb = getattr(radarr_service, "search_movie_tmdb", None)
            if search_movie_tmdb is None:
                search_movie_tmdb = getattr(radarr_service, "search_movie", None)
            detail_fetcher = getattr(boxoffice_service, "extract_detail_metadata", None)

            # Get all Radarr movies and build index
            radarr_movies = radarr_service.get_all_movies()
            matcher.build_movie_index(radarr_movies)

            # Match each movie
            for movie in movies:
                match_result = matcher.match_movie(
                    movie,
                    radarr_movies,
                    market=market,
                    search_movie_tmdb=search_movie_tmdb,
                    detail_fetcher=detail_fetcher,
                )
                resolved_movie_info = getattr(match_result, "resolved_movie_info", None) or {}
                matched_movie = match_result.radarr_movie if match_result.is_matched else None
                results.append(
                    BoxOfficeMovieResponse(
                        rank=movie.rank,
                        title=movie.title,
                        weekend_gross=movie.weekend_gross,
                        total_gross=movie.total_gross,
                        weeks_in_release=movie.weeks_released,
                        theater_count=movie.theater_count,
                        is_new_release=(
                            movie.weeks_released == 1 if movie.weeks_released else False
                        ),
                        radarr_id=(
                            match_result.radarr_movie.id
                            if match_result.is_matched and match_result.confidence > 0
                            else None
                        ),
                        radarr_status=(
                            match_result.radarr_movie.status.value
                            if match_result.is_matched and match_result.confidence > 0
                            else None
                        ),
                        radarr_has_file=(
                            match_result.radarr_movie.hasFile
                            if match_result.is_matched and match_result.confidence > 0
                            else False
                        ),
                        match_confidence=match_result.confidence if match_result.confidence > 0 else 0.0,
                        tmdb_id=(
                            match_result.resolved_tmdb_id
                            if getattr(match_result, "resolved_tmdb_id", None) is not None
                            else None
                        ),
                        source_href=movie.source_href,
                        source_title=movie.source_title,
                        normalized_source_title=movie.normalized_source_title,
                        source_url=movie.source_url,
                        jpboxoffice_id=movie.jpboxoffice_id,
                        allocine_movie_id=movie.allocine_movie_id,
                        identity_status=getattr(match_result, "identity_status", None),
                        match_method=getattr(match_result, "match_method", None),
                        year=(
                            getattr(matched_movie, "year", None)
                            or resolved_movie_info.get("year")
                            or movie.year
                        ),
                        poster=(
                            getattr(matched_movie, "poster_url", None)
                            or resolved_movie_info.get("remotePoster")
                        ),
                        imdb_id=(
                            getattr(matched_movie, "imdbId", None)
                            or resolved_movie_info.get("imdbId")
                        ),
                        genres=(
                            ", ".join(resolved_movie_info.get("genres", [])[:2])
                            if resolved_movie_info.get("genres")
                            else None
                        ),
                    )
                )
        else:
            # No Radarr configured, just return box office data
            results = [
                BoxOfficeMovieResponse(
                    rank=movie.rank,
                    title=movie.title,
                    weekend_gross=movie.weekend_gross,
                    total_gross=movie.total_gross,
                    weeks_in_release=movie.weeks_released,
                    theater_count=movie.theater_count,
                    is_new_release=(
                        movie.weeks_released == 1 if movie.weeks_released else False
                    ),
                    source_href=movie.source_href,
                    source_title=movie.source_title,
                    normalized_source_title=movie.normalized_source_title,
                    source_url=movie.source_url,
                    jpboxoffice_id=movie.jpboxoffice_id,
                    allocine_movie_id=movie.allocine_movie_id,
                    identity_status="Unmatched / needs identity",
                )
                for movie in movies
            ]

        return results
    except ValueError as e:
        logger.error(f"Invalid market/provider for box office current: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except BoxOfficeError as e:
        if "skipped_incomplete_week" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        if _is_parse_error(e):
            raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting box office: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{year}/W{week}")
async def get_historical_box_office(
    year: int,
    week: int,
    market: str = Query(DEFAULT_MARKET, description="Box office market"),
    provider: Optional[str] = Query(None, description="Compat provider fallback"),
):
    """Get historical box office data for a specific week."""
    try:
        if provider and market == DEFAULT_MARKET:
            market = market_for_provider(provider)
        market = normalize_market(market)
        market_effective = get_effective_market_settings(settings, market)
        market_capabilities = get_market_capabilities(settings, market)
        # Validate year and week
        if week < 1 or week > 53:
            raise HTTPException(status_code=400, detail="Invalid week number")
        historical = dict(market_capabilities.get("historical", {}) or {})
        min_year = historical.get("min_year")
        max_year = historical.get("max_year", datetime.now().year)
        if not historical.get("supports_historical_update", False) or min_year is None:
            raise HTTPException(
                status_code=400,
                detail=f"Market {market} does not support historical updates",
            )
        if year < int(min_year) or year > int(max_year):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Market {market} supports historical updates from "
                    f"{int(min_year)} to {int(max_year)}"
                ),
            )

        stored_path = resolve_weekly_page_path(settings.boxarr_data_directory, market, year, week)
        if stored_path.exists():
            with open(stored_path) as f:
                stored_payload = json.load(f) or {}
            stored_movies = stored_payload.get("movies", []) or []

            radarr_movies_by_id = {}
            radarr_movies_by_tmdb = {}
            if settings.radarr_api_key:
                try:
                    radarr_service = RadarrService()
                    radarr_movies = radarr_service.get_all_movies()
                    radarr_movies_by_id = {
                        movie.id: movie for movie in radarr_movies if movie.id is not None
                    }
                    radarr_movies_by_tmdb = {
                        movie.tmdbId: movie
                        for movie in radarr_movies
                        if movie.tmdbId is not None
                    }
                except Exception as exc:
                    logger.warning(
                        "Could not refresh historical box office status from Radarr: %s",
                        exc,
                    )

            movies = [
                _build_history_movie_response(
                    movie,
                    radarr_movies_by_id=radarr_movies_by_id,
                    radarr_movies_by_tmdb=radarr_movies_by_tmdb,
                )
                for movie in stored_movies
            ]
            return sanitize_history_movies(movies, market=market)

        # Fallback to live provider only if no stored file exists.
        boxoffice_service = BoxOfficeService(market=market)
        try:
            movies = boxoffice_service.fetch_weekend_box_office(
                year,
                week,
                limit=int(
                    market_effective.get("effective", {}).get(
                        "box_office_fetch_limit",
                        settings.boxarr_features_box_office_limit,
                    )
                ),
            )
        except BoxOfficeError as exc:
            logger.warning(
                "Historical live fetch failed for market=%s year=%s week=%s: %s",
                market,
                year,
                week,
                exc,
            )
            if _is_parse_error(exc):
                raise HTTPException(status_code=500, detail=str(exc))
            return []
        return sanitize_history_movies([
            {
                "rank": movie.rank,
                "title": movie.title,
                "weekend_gross": movie.weekend_gross,
                "total_gross": movie.total_gross,
                "weeks_in_release": movie.weeks_released,
                "weeks_released": movie.weeks_released,
                "theater_count": movie.theater_count,
                "radarr_id": None,
                "radarr_status": None,
                "radarr_has_file": False,
                "match_confidence": 0.0,
                "identity_status": "Unmatched / needs identity",
                "source_href": movie.source_href,
                "source_title": movie.source_title,
                "source_url": movie.source_url,
                "jpboxoffice_id": movie.jpboxoffice_id,
                "allocine_movie_id": movie.allocine_movie_id,
                "is_new_release": (
                    movie.weeks_released == 1 if movie.weeks_released else False
                ),
            }
            for movie in movies
        ], market=market)
    except ValueError as e:
        logger.error(f"Invalid market/provider for historical box office: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except BoxOfficeError as e:
        if _is_parse_error(e):
            raise HTTPException(status_code=500, detail=str(e))
        logger.warning(f"Historical box office fetch returned no data: {e}")
        return []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting historical box office: {e}")
        raise HTTPException(status_code=500, detail=str(e))
