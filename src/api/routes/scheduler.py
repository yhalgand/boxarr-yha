"""Scheduler management routes."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...core.scheduler import BoxarrScheduler
from ...core.boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    market_for_provider,
    normalize_market,
    normalize_provider,
    provider_for_market,
)
from ...core.boxoffice_storage import (
    iter_history_paths,
)
from ...core.exceptions import BoxOfficeError
from ...core.market_settings import get_market_capabilities
from .movies import refresh_stored_status_for_market
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# Module-level scheduler instance
_scheduler: Optional[BoxarrScheduler] = None


def get_scheduler() -> BoxarrScheduler:
    """Get the scheduler instance."""
    global _scheduler
    if not _scheduler:
        from ...core.boxoffice import BoxOfficeService
        from ...core.radarr import RadarrService

        _scheduler = BoxarrScheduler(
            boxoffice_service=BoxOfficeService(),
            radarr_service=RadarrService() if settings.radarr_api_key else None,
        )
    return _scheduler


class TriggerResponse(BaseModel):
    """Trigger response model."""

    success: bool
    message: str
    movies_found: Optional[int] = None
    movies_added: Optional[int] = None


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_update(
    market: str = DEFAULT_MARKET, provider: Optional[str] = None
):
    """Manually trigger box office update."""
    try:
        if provider and market == DEFAULT_MARKET:
            market = market_for_provider(provider)
        market = normalize_market(market)
        provider = provider_for_market(market)
        scheduler = get_scheduler()
        result = await scheduler.update_box_office(market=market, provider=provider)

        # Handle added_movies which is a list
        added_movies = result.get("added_movies", [])
        movies_added_count = len(added_movies) if isinstance(added_movies, list) else 0

        return TriggerResponse(
            success=True,
            message="Box office update completed",
            movies_found=result.get(
                "total_count"
            ),  # Fixed: was "total_movies" but scheduler returns "total_count"
            movies_added=movies_added_count,
        )
    except ValueError as e:
        logger.error(f"Invalid provider for trigger update: {e}")
        return TriggerResponse(success=False, message=str(e))
    except Exception as e:
        logger.error(f"Error triggering update: {e}")
        return TriggerResponse(
            success=False,
            message=str(e),
        )


@router.post("/reload")
async def reload_scheduler():
    """Manually reload the scheduler with current settings."""
    try:
        scheduler = get_scheduler()

        if not scheduler._running:
            return {
                "success": False,
                "message": "Scheduler is not running",
            }

        # Reload with current settings
        if scheduler.reload_schedule():
            next_run = scheduler.get_next_run_time()
            return {
                "success": True,
                "message": f"Scheduler reloaded with cron: {settings.boxarr_scheduler_cron}",
                "next_run": next_run.isoformat() if next_run else None,
                "cron": settings.boxarr_scheduler_cron,
            }
        else:
            return {
                "success": False,
                "message": "Failed to reload scheduler",
            }
    except Exception as e:
        logger.error(f"Error reloading scheduler: {e}")
        return {
            "success": False,
            "message": str(e),
        }


@router.get("/status")
async def get_scheduler_status(
    market: str = DEFAULT_MARKET, provider: Optional[str] = None
):
    """Get current scheduler status and configuration."""
    try:
        if provider and market == DEFAULT_MARKET:
            market = market_for_provider(provider)
        market = normalize_market(market)
        provider = provider_for_market(market)
        scheduler = get_scheduler()

        # Get job information
        jobs = scheduler.scheduler.get_jobs() if scheduler.scheduler else []
        job_info = []

        for job in jobs:
            job_info.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                    "pending": job.pending,
                }
            )

        # Get next run time
        next_run = scheduler.get_next_run_time() if scheduler._running else None

        # Calculate time until next run
        time_until_next = None
        if next_run:
            from datetime import datetime

            import pytz

            now = datetime.now(pytz.timezone(settings.boxarr_scheduler_timezone))
            delta = next_run - now
            time_until_next = {
                "days": delta.days,
                "hours": delta.seconds // 3600,
                "minutes": (delta.seconds % 3600) // 60,
                "total_hours": delta.total_seconds() / 3600,
            }

        # Get last run info from history
        last_run_info = None
        try:
            history_files = [
                path
                for path in iter_history_paths(settings.boxarr_data_directory, market)
                if path.name.endswith("_latest.json")
            ]
            if history_files:
                history_files = sorted(history_files, reverse=True)
                if history_files:
                    with open(history_files[0]) as f:
                        data = json.load(f)
                        timestamp = data.get("timestamp")
                        if timestamp:
                            from datetime import datetime

                            last_run_time = datetime.fromisoformat(
                                timestamp.replace("Z", "+00:00")
                            )
                            last_run_info = {
                                "timestamp": last_run_time.isoformat(),
                                "success": True,
                                "matched_count": data.get("matched_count", 0),
                                "total_count": data.get("total_count", 0),
                            }
        except Exception as e:
            logger.debug(f"Could not get last run info: {e}")

        return {
            "enabled": settings.boxarr_scheduler_enabled,
            "running": scheduler._running if scheduler else False,
            "cron_expression": settings.boxarr_scheduler_cron,
            "timezone": settings.boxarr_scheduler_timezone,
            "next_run_time": next_run.isoformat() if next_run else None,
            "time_until_next": time_until_next,
            "last_run": last_run_info,
            "jobs": job_info,
            "auto_add_enabled": settings.boxarr_features_auto_add,
            "market": market,
            "provider": provider,
        }
    except ValueError as e:
        logger.error(f"Invalid provider for scheduler status: {e}")
        return {
            "enabled": settings.boxarr_scheduler_enabled,
            "running": False,
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        return {
            "enabled": settings.boxarr_scheduler_enabled,
            "running": False,
            "error": str(e),
        }


@router.get("/history")
async def get_scheduler_history(
    market: str = DEFAULT_MARKET, provider: Optional[str] = None
):
    """Get scheduler run history."""
    try:
        if provider and market == DEFAULT_MARKET:
            market = market_for_provider(provider)
        market = normalize_market(market)
        history_files = [
            path
            for path in iter_history_paths(settings.boxarr_data_directory, market)
        ]
        if not history_files:
            return {"runs": []}

        # Get all history files
        history_files = sorted(history_files, reverse=True)[:20]

        runs = []
        for file_path in history_files:
            # Parse filename for timestamp
            # Format: YYYYWW_YYYYMMDD_HHMMSS.json
            parts = file_path.stem.split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]

                try:
                    run_time = datetime.strptime(
                        f"{date_str}_{time_str}", "%Y%m%d_%H%M%S"
                    )

                    # Read result
                    import json

                    with open(file_path) as f:
                        result = json.load(f)

                    # Handle added_movies which could be a list or count
                    added_movies = result.get("added_movies", [])
                    added_count = (
                        len(added_movies)
                        if isinstance(added_movies, list)
                        else added_movies
                    )

                    runs.append(
                        {
                            "timestamp": run_time.isoformat(),
                            "week": parts[0],
                            "success": result.get("success", False),
                            "movies_found": result.get(
                                "total_count", result.get("total_movies")
                            ),
                            "movies_added": added_count,
                            "error": result.get("error"),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error parsing history file {file_path}: {e}")
                    continue

        return {"runs": runs}
    except Exception as e:
        logger.error(f"Error getting scheduler history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateWeekRequest(BaseModel):
    """Request model for updating a specific week."""

    year: int
    week: int
    market: str = DEFAULT_MARKET
    provider: Optional[str] = None


@router.post("/update-week")
async def update_specific_week(
    request: UpdateWeekRequest,
    market: Optional[str] = Query(None, description="Box office market override"),
):  # noqa: C901
    """Update box office for a specific historical week."""
    year = request.year
    week = request.week
    try:
        effective_market = market if market is not None else request.market
        if request.provider and effective_market == DEFAULT_MARKET:
            market = market_for_provider(request.provider)
        else:
            market = effective_market
        market = normalize_market(market)
        provider = provider_for_market(market)
        # Validate inputs
        if week < 1 or week > 53:
            raise HTTPException(status_code=400, detail="Invalid week number")

        capabilities = get_market_capabilities(settings, market)
        historical = dict(capabilities.get("historical", {}) or {})
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

        from ...core.boxoffice import BoxOfficeService
        from ...core.json_generator import WeeklyDataGenerator
        from ...core.matcher import MovieMatcher
        from ...core.radarr import (
            RadarrService,
            get_all_movies_with_optional_cache_bypass,
        )

        # Get box office data
        boxoffice_service = BoxOfficeService(market=market)
        detail_fetcher = getattr(boxoffice_service, "extract_detail_metadata", None)
        limit = settings.boxarr_features_box_office_limit
        box_office_movies = boxoffice_service.fetch_weekend_box_office(
            year, week, limit=limit
        )

        if not box_office_movies:
            return {
                "success": False,
                "message": f"No data found for week {year}W{week:02d}",
            }

        # Match with Radarr
        match_results = []
        added_count = 0
        radarr_movies = []

        if settings.radarr_api_key:
            radarr_service = RadarrService()
            matcher = MovieMatcher()
            search_movie_tmdb = getattr(radarr_service, "search_movie_tmdb", None)
            if search_movie_tmdb is None:
                search_movie_tmdb = getattr(radarr_service, "search_movie", None)

            radarr_movies = get_all_movies_with_optional_cache_bypass(
                radarr_service, ignore_cache=True
            )
            matcher.build_movie_index(radarr_movies)
            match_results = matcher.match_movies(
                box_office_movies,
                radarr_movies,
                market=market,
                search_movie_tmdb=search_movie_tmdb,
                detail_fetcher=detail_fetcher,
            )

            # Auto-add if enabled
            if settings.boxarr_features_auto_add:
                from ...core.auto_add import auto_add_missing_movies

                added_titles = auto_add_missing_movies(
                    match_results, radarr_service, year, market=market
                )
                added_count = len(added_titles)

                # Re-fetch and re-match after adding (fixes stale status bug)
                if added_count > 0:
                    logger.info(f"Added {added_count} movies to Radarr, re-matching...")
                    radarr_movies = get_all_movies_with_optional_cache_bypass(
                        radarr_service, ignore_cache=True
                    )
                    matcher.build_movie_index(radarr_movies)
                    match_results = matcher.match_movies(
                        box_office_movies,
                        radarr_movies,
                        market=market,
                        search_movie_tmdb=search_movie_tmdb,
                        detail_fetcher=detail_fetcher,
                    )
        else:
            # No Radarr, create unmatched results
            from ...core.matcher import MatchResult

            match_results = [
                MatchResult(box_office_movie=movie) for movie in box_office_movies
            ]

        # Generate data file
        generator = WeeklyDataGenerator(
            radarr_service=radarr_service if settings.radarr_api_key else None,
            market=market,
            provider=provider,
        )
        generator.generate_weekly_data(
            match_results,
            year,
            week,
            radarr_movies if settings.radarr_api_key else [],
        )

        if added_count > 0:
            refresh_stored_status_for_market(market)

        return {
            "success": True,
            "message": f"Updated week {year}W{week:02d}",
            "movies_found": len(box_office_movies),
            "movies_added": added_count,
            "market": market,
            "provider": provider,
        }
    except ValueError as e:
        logger.error(f"Invalid market/provider for update-week: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except BoxOfficeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating week: {e}")
        raise HTTPException(status_code=500, detail=str(e))
