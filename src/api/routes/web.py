"""Web UI routes."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ... import __version__
from ...core.boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    market_for_provider,
    market_from_provider,
    market_label,
    normalize_market,
    normalize_provider,
    provider_for_market,
)
from ...core.boxoffice_storage import (
    iter_weekly_page_paths,
    resolve_weekly_page_path,
)
from ...core.ignore_list import IgnoreList
from ...core.models import MovieStatus
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["web"])

# Template directory
templates = Jinja2Templates(directory="src/web/templates")


# Helper function for URL generation in templates
def url_for(request: Request, path: str) -> str:
    """Generate URL with proper base path handling."""
    root_path = str(request.scope.get("root_path", ""))
    if not path.startswith("/"):
        path = "/" + path
    return root_path + path


# Register the helper as a Jinja2 global
templates.env.globals["url_for"] = url_for


def get_template_context(request: Request, **kwargs) -> dict:
    """Get base template context with common values."""
    # Handle both string and enum values for theme
    theme_value = settings.boxarr_ui_theme
    if hasattr(theme_value, "value"):
        theme_str = getattr(theme_value, "value")
    else:
        theme_str = str(theme_value)

    context = {
        "request": request,
        "version": __version__,
        "theme": theme_str,
        "market": kwargs.get("market", DEFAULT_MARKET),
        "provider": kwargs.get("provider")
        or provider_for_market(kwargs.get("market", DEFAULT_MARKET)),
    }
    context.update(kwargs)
    return context


def _selected_market(request: Request) -> str:
    """Read the selected market from query params, defaulting to US."""
    market_or_provider = request.query_params.get("market") or request.query_params.get(
        "provider"
    )
    try:
        return normalize_market(market_or_provider)
    except ValueError:
        return DEFAULT_MARKET


def _selected_provider(request: Request) -> str:
    return provider_for_market(_selected_market(request))


def _redirect_with_market(request: Request, path: str, market: str) -> RedirectResponse:
    """Redirect to a canonical market URL while preserving other query params."""
    params = dict(request.query_params)
    params.pop("provider", None)
    params["market"] = market
    base = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{base}{path}?{urlencode(params)}")


class WeekInfo(BaseModel):
    """Week information model."""

    year: int
    week: int
    filename: str
    date_range: str
    movie_count: int
    matched_count: int = 0
    has_data: bool
    timestamp_str: str = ""


class WidgetData(BaseModel):
    """Widget data model."""

    current_week: int
    current_year: int
    movies: List[dict]


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Serve the home page (overview or setup)."""
    market = _selected_market(request)
    # Check if Radarr is configured
    if not settings.is_configured:
        base = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{base}/setup?market={market}")

    # Redirect to overview as the main landing page
    base = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{base}/overview?market={market}")


@router.get("/settings", response_class=HTMLResponse)
async def settings_redirect(request: Request):
    """Compatibility route: redirect /settings → /setup.

    Some users type /settings by habit; provide a friendly redirect.
    Honors the app's root_path for reverse proxy setups.
    """
    base = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{base}/setup?market={_selected_market(request)}")


async def aggregate_all_movies(market: str = DEFAULT_MARKET) -> List[dict]:
    """Aggregate all movies from all weekly JSON files, handling duplicates."""
    market = normalize_market(market)
    weekly_files = iter_weekly_page_paths(settings.boxarr_data_directory, market)
    if not weekly_files:
        return []

    # Dictionary to store unique movies with their appearance weeks
    movies_by_key: Dict[str, dict] = {}

    # Process all JSON files
    for json_file in weekly_files:
        try:
            with open(json_file) as f:
                metadata = json.load(f)

            year = metadata.get("year")
            week = metadata.get("week")
            week_str = f"{year}W{week:02d}"

            for movie in metadata.get("movies", []):
                # Use TMDB ID as primary key, fallback to title+year
                if movie.get("tmdb_id"):
                    key = f"tmdb_{movie['tmdb_id']}"
                else:
                    key = f"{movie.get('title', 'unknown')}_{movie.get('year', 0)}"

                if key in movies_by_key:
                    # Movie already exists, add this week to its appearances
                    movies_by_key[key]["weeks"].append(week_str)
                    # Update with better data if this week has higher rank
                    if movie.get("rank", 999) < movies_by_key[key]["best_rank"]:
                        movies_by_key[key]["best_rank"] = movie.get("rank", 999)
                        movies_by_key[key]["best_weekend_gross"] = movie.get(
                            "weekend_gross", 0
                        )
                else:
                    # New movie entry
                    movie_copy = dict(movie)
                    movie_copy["weeks"] = [week_str]
                    movie_copy["best_rank"] = movie.get("rank", 999)
                    movie_copy["best_weekend_gross"] = movie.get("weekend_gross", 0)
                    movies_by_key[key] = movie_copy

        except Exception as e:
            logger.warning(f"Error reading {json_file}: {e}")
            continue

    # Convert to list and sort by best weekend gross (highest first)
    movies_list = list(movies_by_key.values())
    movies_list.sort(key=lambda x: x.get("best_weekend_gross", 0), reverse=True)

    return movies_list


@router.get("/overview", response_class=HTMLResponse)
async def movie_overview_page(request: Request):
    """Serve the movie overview page consolidating all movies from all weeks."""
    # Check if configured - if not, redirect to setup
    if not settings.is_configured:
        base = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{base}/setup?market={_selected_market(request)}")

    if "market" not in request.query_params:
        return _redirect_with_market(request, "/overview", _selected_market(request))

    # Get query parameters for filtering
    market = _selected_market(request)
    provider = provider_for_market(market)

    page = int(request.query_params.get("page", 1))
    per_page = int(request.query_params.get("per_page", 50))
    status_filter = request.query_params.get("status", "all")
    year_filter_str = request.query_params.get("year", None)
    search_query = request.query_params.get("search", "").strip().lower()

    # Validate per_page
    if per_page not in [20, 50, 100, 200]:
        per_page = 50

    # Aggregate movies from all weeks
    all_movies = await aggregate_all_movies(market)

    # Avoid synchronous full Radarr fetch here; hydrate via AJAX on the client

    # Load ignore list (needed for filtering and stats)
    ignore_list = IgnoreList()
    ignored_tmdb_ids_set = ignore_list.get_ignored_tmdb_ids()
    ignored_tmdb_ids = list(ignored_tmdb_ids_set)

    # Apply filters
    filtered_movies = all_movies

    # Status filter — ignored movies are excluded from all other status views
    if status_filter == "downloaded":
        filtered_movies = [
            m
            for m in filtered_movies
            if m.get("status") == "Downloaded"
            and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ]
    elif status_filter == "missing":
        filtered_movies = [
            m
            for m in filtered_movies
            if m.get("status") == "Missing"
            and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ]
    elif status_filter == "not_in_radarr":
        filtered_movies = [
            m
            for m in filtered_movies
            if not m.get("radarr_id") and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ]
    elif status_filter == "ignored":
        filtered_movies = [
            m for m in filtered_movies if m.get("tmdb_id") in ignored_tmdb_ids_set
        ]

    # Year filter
    if year_filter_str and year_filter_str.isdigit():
        year_filter = int(year_filter_str)
        filtered_movies = [m for m in filtered_movies if m.get("year") == year_filter]
    else:
        year_filter = None

    # Search filter
    if search_query:
        filtered_movies = [
            m for m in filtered_movies if search_query in m.get("title", "").lower()
        ]

    # Get unique years for filter buttons
    all_years = sorted(
        list(set(m.get("year") for m in all_movies if m.get("year"))), reverse=True
    )

    # Calculate pagination
    total_movies = len(filtered_movies)
    total_pages = max(1, (total_movies + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_movies = filtered_movies[start_idx:end_idx]

    # Avoid per-request full-library status refresh; client will update via AJAX

    # Count statistics — ignored movies are excluded from all other buckets
    stats = {
        "total": len(all_movies),
        "in_radarr": sum(
            1
            for m in all_movies
            if m.get("radarr_id") and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ),
        "downloaded": sum(
            1
            for m in all_movies
            if m.get("status") == "Downloaded"
            and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ),
        "missing": sum(
            1
            for m in all_movies
            if m.get("status") == "Missing"
            and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ),
        "not_in_radarr": sum(
            1
            for m in all_movies
            if not m.get("radarr_id") and m.get("tmdb_id") not in ignored_tmdb_ids_set
        ),
        "ignored": sum(
            1 for m in all_movies if m.get("tmdb_id") in ignored_tmdb_ids_set
        ),
    }

    # Get recent weeks for quick navigation
    recent_weeks = await get_available_weeks(market)
    recent_weeks = recent_weeks[:5]  # Show last 5 weeks

    return templates.TemplateResponse(
        request,
        "overview.html",
        get_template_context(
            request,
            movies=paginated_movies,
            total_movies=total_movies,
            stats=stats,
            recent_weeks=recent_weeks,
            # Pagination
            current_page=page,
            total_pages=total_pages,
            per_page=per_page,
            # Filters
            status_filter=status_filter,
            year_filter=year_filter,
            available_years=all_years,
            search_query=search_query,
            market=market,
            provider=provider,
            # Features
            auto_add=settings.boxarr_features_auto_add,
            quality_upgrade=settings.boxarr_features_quality_upgrade,
            # Ignore list
            ignored_tmdb_ids=ignored_tmdb_ids,
        ),
    )


@router.get("/dashboard", response_class=HTMLResponse)
@router.get("/weeks", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Serve the weekly view page (legacy dashboard)."""
    # Check if configured - if not, redirect to setup
    if not settings.is_configured:
        base = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{base}/setup?market={_selected_market(request)}")

    if "market" not in request.query_params:
        return _redirect_with_market(request, "/weeks", _selected_market(request))

    # Get query parameters for pagination and filtering
    market = _selected_market(request)
    provider = provider_for_market(market)

    page = int(request.query_params.get("page", 1))
    per_page = int(request.query_params.get("per_page", 10))
    year_filter_str = request.query_params.get("year", None)

    # Validate per_page
    if per_page not in [10, 20, 50, 100]:
        per_page = 10

    # Get all available weeks
    all_weeks = await get_available_weeks(market)

    # Apply year filter if specified
    year_filter: Optional[int] = None
    if year_filter_str and year_filter_str.isdigit():
        year_filter = int(year_filter_str)
        weeks = [w for w in all_weeks if w.year == year_filter]
    else:
        weeks = all_weeks

    # Get unique years for filter buttons
    available_years = sorted(list(set(w.year for w in all_weeks)), reverse=True)

    # Calculate pagination
    total_weeks = len(weeks)
    total_pages = (total_weeks + per_page - 1) // per_page  # Ceiling division
    page = max(1, min(page, total_pages))  # Ensure page is within bounds

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_weeks = weeks[start_idx:end_idx]

    # For backward compatibility, keep these but empty
    recent_weeks = paginated_weeks
    older_weeks: List[WeekInfo] = []

    # Calculate next scheduled update
    from datetime import datetime

    next_update = "Not scheduled"
    if settings.boxarr_scheduler_enabled:
        # Parse cron to get next run time (simplified display)
        import re

        cron_match = re.match(
            r"(\d+) (\d+) \* \* (\d+)", settings.boxarr_scheduler_cron
        )
        if cron_match:
            hour = int(cron_match.group(2))
            apscheduler_day = int(cron_match.group(3))

            # Convert APScheduler day to day name
            # APScheduler: Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
            apscheduler_days = {
                0: "Monday",
                1: "Tuesday",
                2: "Wednesday",
                3: "Thursday",
                4: "Friday",
                5: "Saturday",
                6: "Sunday",
            }
            day_name = apscheduler_days.get(apscheduler_day, "Unknown")
            next_update = f"{day_name} at {hour}:00"

    # Check if any auto-add filters are active
    auto_add_filters_active = settings.boxarr_features_auto_add and (
        settings.boxarr_features_auto_add_limit < 10
        or settings.boxarr_features_auto_add_genre_filter_enabled
        or settings.boxarr_features_auto_add_rating_filter_enabled
        or settings.boxarr_features_auto_add_language_filter_enabled
        or settings.boxarr_features_auto_add_ignore_rereleases
    )

    # Build filter description
    filter_descriptions = []
    if (
        settings.boxarr_features_auto_add
        and settings.boxarr_features_auto_add_limit < 10
    ):
        filter_descriptions.append(
            f"Top {settings.boxarr_features_auto_add_limit} movies"
        )
    if settings.boxarr_features_auto_add_genre_filter_enabled:
        mode = settings.boxarr_features_auto_add_genre_filter_mode
        if mode == "whitelist" and settings.boxarr_features_auto_add_genre_whitelist:
            filter_descriptions.append(
                f"Genre whitelist ({len(settings.boxarr_features_auto_add_genre_whitelist)} genres)"
            )
        elif mode == "blacklist" and settings.boxarr_features_auto_add_genre_blacklist:
            filter_descriptions.append(
                f"Genre blacklist ({len(settings.boxarr_features_auto_add_genre_blacklist)} genres)"
            )
    if (
        settings.boxarr_features_auto_add_rating_filter_enabled
        and settings.boxarr_features_auto_add_rating_whitelist
    ):
        filter_descriptions.append(
            f"Rating filter ({len(settings.boxarr_features_auto_add_rating_whitelist)} ratings)"
        )
    if settings.boxarr_features_auto_add_language_filter_enabled:
        lang_mode = settings.boxarr_features_auto_add_language_filter_mode
        if (
            lang_mode == "whitelist"
            and settings.boxarr_features_auto_add_language_whitelist
        ):
            filter_descriptions.append(
                f"Language whitelist ({len(settings.boxarr_features_auto_add_language_whitelist)} languages)"
            )
        elif (
            lang_mode == "blacklist"
            and settings.boxarr_features_auto_add_language_blacklist
        ):
            filter_descriptions.append(
                f"Language blacklist ({len(settings.boxarr_features_auto_add_language_blacklist)} languages)"
            )
    if settings.boxarr_features_auto_add_ignore_rereleases:
        filter_descriptions.append("Ignore re-releases")

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        get_template_context(
            request,
            weeks=weeks,
            recent_weeks=recent_weeks,
            older_weeks=older_weeks,
            total_weeks=total_weeks,
            market=market,
            provider=provider,
            radarr_configured=bool(settings.radarr_api_key),
            scheduler_enabled=settings.boxarr_scheduler_enabled,
            auto_add=settings.boxarr_features_auto_add,
            quality_upgrade=settings.boxarr_features_quality_upgrade,
            next_update=next_update,
            auto_add_filters_active=auto_add_filters_active,
            filter_descriptions=filter_descriptions,
            # Pagination data
            current_page=page,
            total_pages=total_pages,
            per_page=per_page,
            paginated_weeks=paginated_weeks,
            available_years=available_years,
            year_filter=year_filter,
            total_all_weeks=len(all_weeks),
            # Year information
            current_year=datetime.now().year,
        ),
    )


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Serve the setup page."""
    if "market" not in request.query_params:
        return _redirect_with_market(request, "/setup", _selected_market(request))

    market = _selected_market(request)
    provider = provider_for_market(market)
    # Parse current cron for display
    cron = settings.boxarr_scheduler_cron
    import re

    cron_match = re.match(r"(\d+) (\d+) \* \* (\d+)", cron)

    # Extract current cron settings
    apscheduler_day = (
        int(cron_match.group(3)) if cron_match else 1
    )  # Default Tuesday (APScheduler format)
    current_time = int(cron_match.group(2)) if cron_match else 23

    # Convert APScheduler day numbering to HTML form values
    # APScheduler: Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
    # HTML form: Sunday=0, Monday=1, ..., Saturday=6
    apscheduler_to_html = {
        0: 1,  # Monday: 0 -> 1
        1: 2,  # Tuesday: 1 -> 2
        2: 3,  # Wednesday: 2 -> 3
        3: 4,  # Thursday: 3 -> 4
        4: 5,  # Friday: 4 -> 5
        5: 6,  # Saturday: 5 -> 6
        6: 0,  # Sunday: 6 -> 0
    }
    current_day = apscheduler_to_html.get(
        apscheduler_day, 2
    )  # Default to Tuesday if unknown

    return templates.TemplateResponse(
        request,
        "setup.html",
        get_template_context(
            request,
            market=market,
            provider=provider,
            radarr_configured=bool(settings.radarr_api_key),
            is_configured=bool(settings.radarr_api_key),
            # Current settings for prefilling
            radarr_url=str(settings.radarr_url),
            radarr_api_key=settings.radarr_api_key,  # Show actual API key for editing
            root_folder=str(settings.radarr_root_folder),
            quality_profile_default=settings.radarr_quality_profile_default,
            quality_profile_upgrade=settings.radarr_quality_profile_upgrade,
            # Minimum availability controls
            radarr_minimum_availability_enabled=settings.radarr_minimum_availability_enabled,
            radarr_minimum_availability=settings.radarr_minimum_availability.value,
            # Root folder mapping configuration
            root_folder_mapping_enabled=settings.radarr_root_folder_config.enabled,
            root_folder_mappings=[
                {
                    "genres": mapping.genres,
                    "root_folder": mapping.root_folder,
                    "priority": mapping.priority,
                }
                for mapping in settings.radarr_root_folder_config.mappings
            ],
            scheduler_enabled=settings.boxarr_scheduler_enabled,
            scheduler_cron=settings.boxarr_scheduler_cron,
            scheduler_day=current_day,
            scheduler_time=current_time,
            auto_add=settings.boxarr_features_auto_add,
            quality_upgrade=settings.boxarr_features_quality_upgrade,
            # Box office fetch limit
            box_office_limit=settings.boxarr_features_box_office_limit,
            # Auto tagging
            auto_tag_enabled=settings.boxarr_features_auto_tag_enabled,
            auto_tag_text=settings.boxarr_features_auto_tag_text,
            # New auto-add advanced options
            auto_add_limit=settings.boxarr_features_auto_add_limit,
            genre_filter_enabled=settings.boxarr_features_auto_add_genre_filter_enabled,
            genre_filter_mode=settings.boxarr_features_auto_add_genre_filter_mode,
            genre_whitelist=settings.boxarr_features_auto_add_genre_whitelist,
            genre_blacklist=settings.boxarr_features_auto_add_genre_blacklist,
            rating_filter_enabled=settings.boxarr_features_auto_add_rating_filter_enabled,
            rating_whitelist=settings.boxarr_features_auto_add_rating_whitelist,
            ignore_rereleases=settings.boxarr_features_auto_add_ignore_rereleases,
            # Language filter settings
            language_filter_enabled=settings.boxarr_features_auto_add_language_filter_enabled,
            language_filter_mode=settings.boxarr_features_auto_add_language_filter_mode,
            language_whitelist=settings.boxarr_features_auto_add_language_whitelist,
            language_blacklist=settings.boxarr_features_auto_add_language_blacklist,
            # URL base for reverse proxy support
            url_base=settings.boxarr_url_base,
        ),
    )


@router.get("/{year}W{week}", response_class=HTMLResponse)
async def serve_weekly_page(request: Request, year: int, week: int):
    """Serve a specific week's page using template with dynamic data."""
    from datetime import date, datetime, timedelta

    if "market" not in request.query_params:
        return _redirect_with_market(request, f"/{year}W{week}", _selected_market(request))

    market = _selected_market(request)
    provider = provider_for_market(market)

    # Check for JSON data file
    json_file = resolve_weekly_page_path(
        settings.boxarr_data_directory, provider, year, week
    )

    if not json_file.exists():
        raise HTTPException(status_code=404, detail="Week not found")

    # Load week data
    with open(json_file) as f:
        metadata = json.load(f)

    movies = metadata.get("movies", [])

    # Avoid synchronous full Radarr fetch; client will refresh statuses via AJAX

    # Calculate counts (for future use/debugging)
    # matched_count = sum(1 for m in movies if m.get("radarr_id"))
    # downloaded_count = sum(1 for m in movies if m.get("status") == "Downloaded")
    # missing_count = sum(1 for m in movies if m.get("status") == "Missing")

    # Calculate week dates
    monday = date.fromisocalendar(year, week, 1)
    friday = monday + timedelta(days=4)
    sunday = monday + timedelta(days=6)

    available_weeks = await get_available_weeks(market)
    current_idx = next(
        (
            idx
            for idx, item in enumerate(available_weeks)
            if item.year == year and item.week == week
        ),
        None,
    )
    prev_week = None
    next_week = None
    if current_idx is not None:
        if current_idx + 1 < len(available_weeks):
            prev_candidate = available_weeks[current_idx + 1]
            prev_week = {"year": prev_candidate.year, "week": prev_candidate.week}
        if current_idx - 1 >= 0:
            next_candidate = available_weeks[current_idx - 1]
            next_week = {"year": next_candidate.year, "week": next_candidate.week}

    # Convert generated_at string to datetime if present
    generated_at = None
    if metadata.get("generated_at"):
        try:
            generated_at = datetime.fromisoformat(metadata.get("generated_at"))
        except (ValueError, TypeError):
            # If parsing fails, leave as None
            pass

    # Load ignore list
    ignore_list = IgnoreList()
    ignored_tmdb_ids = list(ignore_list.get_ignored_tmdb_ids())

    return templates.TemplateResponse(
        request,
        "weekly.html",
        get_template_context(
            request,
            week_data={
                "year": year,
                "week": week,
                "friday": friday,
                "sunday": sunday,
                "movies": movies,
                "generated_at": generated_at,
            },
            market=market,
            provider=provider,
            auto_add=settings.boxarr_features_auto_add,
            scheduler_enabled=settings.boxarr_scheduler_enabled,
            previous_week=f"{prev_week['year']}W{prev_week['week']:02d}" if prev_week else None,
            next_week=f"{next_week['year']}W{next_week['week']:02d}" if next_week else None,
            ignored_tmdb_ids=ignored_tmdb_ids,
        ),
    )


@router.get("/api/weeks")
async def get_weeks(request: Request):
    """Get list of all available weeks with metadata."""
    return await get_available_weeks(_selected_market(request))


@router.delete("/api/weeks/{year}/W{week}/delete")
async def delete_week(request: Request, year: int, week: int):
    """Delete a specific week's data files."""
    try:
        market = _selected_market(request)
        json_file = resolve_weekly_page_path(
            settings.boxarr_data_directory, market, year, week
        )
        html_file = None

        deleted_files = []
        if json_file.exists():
            if json_file.parent.name != market:
                return {"success": False, "message": "Legacy flat files are read-only"}
            json_file.unlink()
            deleted_files.append("JSON")
        if html_file and html_file.exists():
            html_file.unlink()
            deleted_files.append("HTML")

        if deleted_files:
            logger.info(
                f"Deleted week {year}W{week:02d} files: {', '.join(deleted_files)}"
            )
            return {"success": True, "message": f"Deleted week {year}W{week:02d}"}
        else:
            return {"success": False, "message": "Week not found"}
    except Exception as e:
        logger.error(f"Error deleting week: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/widget", response_class=HTMLResponse)
async def get_widget(request: Request):
    """Get embeddable widget HTML."""
    try:
        # Get current week data
        widget_data = await get_widget_data(_selected_market(request))

        # Build the base URL with correct scheme, host, and base path
        # request.base_url already includes the root_path from FastAPI
        full_url = str(request.base_url).rstrip("/") + "/"

        # Simple widget HTML
        html = f"""
        <div class="boxarr-widget">
            <h3>Box Office Week {widget_data.current_week}, {widget_data.current_year}</h3>
            <ol>
                {"".join(f'<li>{m["title"]}</li>' for m in widget_data.movies[:5])}
            </ol>
            <a href="{full_url}">View Full List</a>
        </div>
        """
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Error generating widget: {e}")
        return HTMLResponse(content="<div>Error loading widget</div>")


@router.get("/api/widget/json", response_model=WidgetData)
async def get_widget_json(request: Request):
    """Get widget data as JSON."""
    return await get_widget_data(_selected_market(request))


async def get_available_weeks(market: str = DEFAULT_MARKET) -> List[WeekInfo]:
    """Get all available weeks with metadata."""
    market = normalize_market(market)
    weekly_files = iter_weekly_page_paths(settings.boxarr_data_directory, market)
    if not weekly_files:
        return []

    weeks = []
    for json_file in weekly_files:
        try:
            with open(json_file) as f:
                metadata = json.load(f)

            # Calculate date range
            from datetime import datetime, timedelta

            year = metadata["year"]
            week = metadata["week"]

            # Get first day of week (Monday)
            jan1 = datetime(year, 1, 1)
            week_start = jan1 + timedelta(weeks=week - 1)
            week_start -= timedelta(days=week_start.weekday())
            week_end = week_start + timedelta(days=6)

            date_range = (
                f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}"
            )

            # Count matched movies
            movies = metadata.get("movies", [])
            matched_count = sum(1 for m in movies if m.get("radarr_id"))

            # Get timestamp
            timestamp_str = metadata.get("generated_at", "Unknown")
            if timestamp_str != "Unknown":
                try:
                    # Parse and format the timestamp
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    timestamp_str = ts.strftime("%Y-%m-%d %H:%M")
                except (ValueError, AttributeError):
                    pass

            weeks.append(
                WeekInfo(
                    year=year,
                    week=week,
                    filename=f"{year}W{week:02d}.html",
                    date_range=date_range,
                    movie_count=len(movies),
                    matched_count=matched_count,
                    has_data=True,
                    timestamp_str=timestamp_str,
                )
            )
        except Exception as e:
            logger.warning(f"Error reading {json_file}: {e}")
            continue

    return weeks


async def get_widget_data(market: str = DEFAULT_MARKET) -> WidgetData:
    """Get current week widget data."""
    market = normalize_market(market)
    json_files = iter_weekly_page_paths(settings.boxarr_data_directory, market)
    if not json_files:
        return WidgetData(
            current_week=0,
            current_year=datetime.now().year,
            movies=[],
        )

    with open(json_files[0]) as f:
        metadata = json.load(f)

    return WidgetData(
        current_week=metadata["week"],
        current_year=metadata["year"],
        movies=[
            {
                "rank": m.get("rank"),
                "title": m.get("title"),
                "gross": m.get("weekend_gross"),
            }
            for m in metadata.get("movies", [])[:10]
        ],
    )
