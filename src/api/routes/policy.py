"""Policy routes for market policy, backfill, cleanup, and tag migration."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anyio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.auto_add import auto_add_missing_movies
from ...core.boxoffice import BoxOfficeMovie
from ...core.boxoffice_provider import DEFAULT_MARKET, normalize_market
from ...core.boxoffice_storage import iter_weekly_page_paths
from ...core.cleanup import AddLimitCleanupService
from ...core.market_admin import persist_market_definition
from ...core.market_policy import (
    compare_policy_change,
    get_market_policy,
    update_weekly_policy_snapshot,
)
from .movies import refresh_stored_status_for_market
from ...core.market_settings import ensure_market_enabled, get_configured_markets
from ...core.matcher import MovieMatcher
from ...core.radarr import RadarrMovie, RadarrService, get_all_movies_with_optional_cache_bypass
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/policy", tags=["policy"])
_DANGEROUS_ACTIONS_DISABLED_MESSAGE = (
    "Execute actions are disabled. Enable BOXARR_ENABLE_DANGEROUS_ACTIONS=true to allow this action."
)


class PolicyUpdateRequest(BaseModel):
    box_office_fetch_limit: Optional[int] = None
    maximum_movies_to_add: Optional[int] = None
    auto_add_enabled: Optional[bool] = None
    tags: Optional[List[str]] = None
    auto_tag_text: Optional[str] = None
    cleanup_protect_tag: Optional[str] = None
    year_from: Optional[int] = None
    week_from: Optional[int] = None
    year_to: Optional[int] = None
    week_to: Optional[int] = None


class BackfillRequest(PolicyUpdateRequest):
    market: str = DEFAULT_MARKET
    all_stored: bool = False
    max_weeks: Optional[int] = None


class CleanupRequest(PolicyUpdateRequest):
    market: str = DEFAULT_MARKET


class TagMigrationRequest(BaseModel):
    market: str = "all"
    year_from: Optional[int] = None
    week_from: Optional[int] = None
    year_to: Optional[int] = None
    week_to: Optional[int] = None


def _market_scope(request_market: str) -> List[str]:
    market_value = str(request_market or DEFAULT_MARKET).strip().lower()
    configured = get_configured_markets(settings)
    if market_value == "all":
        return [key for key, definition in configured.items() if definition.get("enabled", True)]
    return [normalize_market(market_value)]


def _policy_updates(payload: PolicyUpdateRequest) -> Dict[str, Any]:
    updates = {
        "box_office_fetch_limit": payload.box_office_fetch_limit,
        "maximum_movies_to_add": payload.maximum_movies_to_add,
        "auto_add_enabled": payload.auto_add_enabled,
        "tags": payload.tags,
        "auto_tag_text": payload.auto_tag_text,
        "cleanup_protect_tag": payload.cleanup_protect_tag,
    }
    return {key: value for key, value in updates.items() if value is not None}


def _policy_scope(payload: PolicyUpdateRequest) -> Dict[str, Optional[int]]:
    return {
        "year_from": payload.year_from,
        "week_from": payload.week_from,
        "year_to": payload.year_to,
        "week_to": payload.week_to,
    }


def _backfill_scope_error() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail="Scope required for backfill dry-run. Provide year/week range or all_stored=true.",
    )


def _resolve_backfill_paths(market_key: str, payload: BackfillRequest) -> List[Path]:
    if payload.all_stored:
        paths = _week_paths_for_market(market_key)
        if payload.max_weeks is not None and payload.max_weeks > 0:
            return paths[: int(payload.max_weeks)]
        return paths

    scope_fields = [
        payload.year_from,
        payload.week_from,
        payload.year_to,
        payload.week_to,
    ]
    if all(value is None for value in scope_fields):
        raise _backfill_scope_error()

    if any(value is None for value in scope_fields):
        raise HTTPException(
            status_code=400,
            detail="Incomplete backfill scope. Provide year/week range or all_stored=true.",
        )

    paths = _week_paths_for_market(
        market_key,
        payload.year_from,
        payload.week_from,
        payload.year_to,
        payload.week_to,
    )

    max_weeks = int(payload.max_weeks) if payload.max_weeks is not None else 12
    if len(paths) > max_weeks:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Backfill scope too large ({len(paths)} weeks). "
                "Reduce the range or set all_stored=true."
            ),
        )
    return paths


def _ensure_market_active(market: str) -> str:
    market_key = normalize_market(market)
    ensure_market_enabled(settings, market_key)
    return market_key


def _load_week_payload(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_to_boxoffice_movies(payload: Dict[str, Any]) -> List[BoxOfficeMovie]:
    movies: List[BoxOfficeMovie] = []
    for movie in payload.get("movies", []):
        if not isinstance(movie, dict):
            continue
        movies.append(
            BoxOfficeMovie(
                rank=int(movie.get("rank") or len(movies) + 1),
                title=str(movie.get("title") or ""),
                weekend_gross=movie.get("weekend_gross"),
                total_gross=movie.get("total_gross"),
                weeks_released=movie.get("weeks_released") or movie.get("weeks_in_release"),
                theater_count=movie.get("theater_count"),
                original_title=movie.get("original_title"),
                year=movie.get("year") or movie.get("source_year"),
                imdb_id=movie.get("imdb_id"),
                release_url=movie.get("release_url"),
            )
        )
    return movies


def _week_paths_for_market(
    market: str,
    year_from: Optional[int] = None,
    week_from: Optional[int] = None,
    year_to: Optional[int] = None,
    week_to: Optional[int] = None,
) -> List[Path]:
    market_key = normalize_market(market)
    paths: List[Path] = []
    start = (year_from, week_from or 1) if year_from is not None else None
    end = (year_to, week_to or 53) if year_to is not None else None
    for path in iter_weekly_page_paths(settings.boxarr_data_directory, market_key):
        stem = path.stem
        if "W" not in stem:
            continue
        try:
            year_str, week_str = stem.split("W", 1)
            year = int(year_str)
            week = int(week_str[:2])
        except Exception:
            continue
        if start and (year, week) < start:
            continue
        if end and (year, week) > end:
            continue
        paths.append(path)
    return paths


def _radarr_tag_label_map(radarr_service: RadarrService) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    try:
        for tag in radarr_service.get_tags():
            if not isinstance(tag, dict):
                continue
            tag_id = tag.get("id")
            label = (
                tag.get("label")
                or tag.get("name")
                or tag.get("title")
                or tag.get("tag")
            )
            if isinstance(tag_id, int) and isinstance(label, str):
                labels[tag_id] = label
    except Exception as exc:
        logger.warning("Could not load Radarr tags: %s", exc)
    return labels


def _tag_ids_for_labels(radarr_service: RadarrService, labels: List[str]) -> List[int]:
    tag_ids: List[int] = []
    for label in labels:
        if not isinstance(label, str) or not label.strip():
            continue
        tag_id = radarr_service.ensure_tag(label.strip())
        if isinstance(tag_id, int) and tag_id not in tag_ids:
            tag_ids.append(tag_id)
    return tag_ids


def _movie_tag_ids(movie: RadarrMovie) -> List[int]:
    ids: List[int] = []
    for tag in getattr(movie, "tags", []) or []:
        if isinstance(tag, int) and tag not in ids:
            ids.append(tag)
        elif isinstance(tag, str) and tag.isdigit():
            tag_id = int(tag)
            if tag_id not in ids:
                ids.append(tag_id)
    raw = getattr(movie, "_raw_data", None) or {}
    for tag in raw.get("tags", []) if isinstance(raw, dict) else []:
        if isinstance(tag, int) and tag not in ids:
            ids.append(tag)
        elif isinstance(tag, str) and tag.isdigit():
            tag_id = int(tag)
            if tag_id not in ids:
                ids.append(tag_id)
    return ids


def _movie_has_tag(movie: RadarrMovie, label: str, tag_labels: Dict[int, str]) -> bool:
    normalized = label.lower()
    for tag_id in _movie_tag_ids(movie):
        if tag_labels.get(tag_id, "").lower() == normalized:
            return True
    return False


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _weekly_movie_markets(
    market: str,
    year_from: Optional[int] = None,
    week_from: Optional[int] = None,
    year_to: Optional[int] = None,
    week_to: Optional[int] = None,
) -> Dict[Tuple[str, int, int], Dict[str, Any]]:
    markets = _market_scope(market)
    index: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    for selected_market in markets:
        for path in _week_paths_for_market(selected_market, year_from, week_from, year_to, week_to):
            try:
                payload = _load_week_payload(path)
            except Exception as exc:
                logger.warning("Could not read %s: %s", path, exc)
                continue
            file_market = str(payload.get("market") or selected_market).lower()
            if file_market != selected_market and not (selected_market == DEFAULT_MARKET and file_market == "us"):
                continue
            year = int(payload.get("year") or 0)
            week = int(payload.get("week") or 0)
            for movie in payload.get("movies", []):
                if not isinstance(movie, dict):
                    continue
                key = (
                    selected_market,
                    int(movie.get("tmdb_id") or 0),
                    int(movie.get("radarr_id") or 0),
                )
                index[key] = {
                    "market": selected_market,
                    "year": year,
                    "week": week,
                    "movie": movie,
                    "title_key": _normalize_text(movie.get("title")),
                    "source_year": movie.get("source_year") or movie.get("year"),
                }
    return index


@router.get("/{market}")
async def get_policy(market: str):
    try:
        market_key = _ensure_market_active(market)
        return get_market_policy(settings, market_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{market}")
async def update_policy(market: str, payload: PolicyUpdateRequest):
    try:
        market_key = _ensure_market_active(market)
        updates = _policy_updates(payload)
        if not updates:
            return get_market_policy(settings, market_key)
        persist_market_definition(market_key, updates, create=False)
        return get_market_policy(settings, market_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{market}/impact")
async def policy_impact(market: str, payload: PolicyUpdateRequest):
    try:
        market_key = _ensure_market_active(market)
        return compare_policy_change(settings, market_key, _policy_updates(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{market}/apply")
async def apply_policy(market: str, payload: PolicyUpdateRequest):
    try:
        market_key = _ensure_market_active(market)
        updates = _policy_updates(payload)
        base_policy = get_market_policy(settings, market_key)
        applied_policy = dict(base_policy)
        applied_effective = dict(base_policy.get("effective", {}))
        applied_effective.update(updates)
        applied_sources = dict(base_policy.get("sources", {}))
        for field in updates:
            applied_sources[field] = "market"
        applied_policy["effective"] = applied_effective
        applied_policy["sources"] = applied_sources
        scope = _policy_scope(payload)
        snapshot_result = update_weekly_policy_snapshot(
            market_key,
            applied_policy,
            scope["year_from"],
            scope["week_from"],
            scope["year_to"],
            scope["week_to"],
        )
        return {
            "success": True,
            "market": market_key,
            "policy": applied_policy,
            "policy_snapshot": snapshot_result,
            "updated": bool(updates),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{market}/backfill-add/dry-run")
async def backfill_add_dry_run(market: str, payload: BackfillRequest):
    return await _backfill_add(market, payload, execute=False)


@router.post("/{market}/backfill-add/execute")
async def backfill_add_execute(market: str, payload: BackfillRequest):
    return await _backfill_add(market, payload, execute=True)


async def _backfill_add(
    market: str,
    payload: BackfillRequest,
    *,
    execute: bool,
):
    return _backfill_add_sync(market, payload, execute)


def _backfill_add_sync(
    market: str,
    payload: BackfillRequest,
    execute: bool,
):
    try:
        if execute and not settings.boxarr_enable_dangerous_actions:
            raise HTTPException(
                status_code=403,
                detail=_DANGEROUS_ACTIONS_DISABLED_MESSAGE,
            )
        market_key = _ensure_market_active(market)
        policy = get_market_policy(settings, market_key)
        target_add_limit = int(
            _policy_updates(payload).get(
                "maximum_movies_to_add",
                policy.get("effective", {}).get(
                    "maximum_movies_to_add", settings.boxarr_features_auto_add_limit
                ),
            )
        )
        radarr_service = RadarrService()
        matcher = MovieMatcher()
        radarr_movies = get_all_movies_with_optional_cache_bypass(
            radarr_service, ignore_cache=True
        )
        matcher.build_movie_index(radarr_movies)

        week_paths = _resolve_backfill_paths(market_key, payload)
        weeks_report = []
        total_added = 0
        total_would_add = 0
        total_skipped = 0
        refetch_required = []
        for path in week_paths:
            week_payload = _load_week_payload(path)
            if not week_payload:
                continue
            movies_payload = week_payload.get("movies", [])
            if len(movies_payload) < target_add_limit:
                refetch_required.append(str(path))
            box_office_movies = _payload_to_boxoffice_movies(week_payload)
            match_results = [
                matcher.match_movie(box_office_movie, radarr_movies)
                for box_office_movie in box_office_movies
            ]
            matched_count = sum(1 for result in match_results if result.is_matched)
            logger.info(
                "Matched %s/%s box office movies for %s",
                matched_count,
                len(box_office_movies),
                path.stem,
            )
            unmatched = [r for r in match_results if not r.is_matched]
            would_add = min(len(unmatched), target_add_limit)
            total_would_add += would_add
            total_skipped += len(match_results) - len(unmatched)
            week_result = {
                "week": f"{int(week_payload.get('year') or 0)}W{int(week_payload.get('week') or 0):02d}",
                "path": str(path),
                "stored_count": len(movies_payload),
                "target_add_limit": target_add_limit,
                "needs_refetch": len(movies_payload) < target_add_limit,
                "would_add_count": would_add,
                "skipped": len(match_results) - len(unmatched),
            }
            if execute and not week_result["needs_refetch"]:
                added_movies = auto_add_missing_movies(
                    match_results,
                    radarr_service,
                    int(week_payload.get("year") or 0),
                    market=market_key,
                )
                total_added += len(added_movies)
                week_result["added_count"] = len(added_movies)
                if added_movies:
                    new_movies = []
                    for movie in added_movies:
                        try:
                            new_movies.append(
                                RadarrMovie(
                                    id=int(movie.get("id") or 0),
                                    title=str(movie.get("title") or ""),
                                    tmdbId=int(movie.get("tmdbId") or 0),
                                )
                            )
                        except Exception:
                            continue
                    if new_movies:
                        radarr_movies.extend(new_movies)
                        matcher.build_movie_index(radarr_movies)
            weeks_report.append(week_result)

        result = {
            "success": True,
            "mode": "execute" if execute else "dry-run",
            "market": market_key,
            "policy": policy,
            "scope": {
                "all_stored": bool(payload.all_stored),
                "year_from": payload.year_from,
                "week_from": payload.week_from,
                "year_to": payload.year_to,
                "week_to": payload.week_to,
                "max_weeks": payload.max_weeks,
            },
            "target_add_limit": target_add_limit,
            "refetch_required": refetch_required,
            "weeks": weeks_report,
            "would_add_count_total": total_would_add,
            "skipped_count_total": total_skipped,
            "added_count": total_added,
            "dry_run": not execute,
        }
        if execute and total_added > 0:
            result["status_refresh"] = refresh_stored_status_for_market(market_key)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{market}/cleanup/dry-run")
async def cleanup_dry_run(market: str, payload: CleanupRequest):
    return await _cleanup(market, payload, execute=False)


@router.post("/{market}/cleanup/execute")
async def cleanup_execute(market: str, payload: CleanupRequest):
    return await _cleanup(market, payload, execute=True)


async def _cleanup(market: str, payload: CleanupRequest, *, execute: bool):
    try:
        if execute and not settings.boxarr_enable_dangerous_actions:
            raise HTTPException(
                status_code=403,
                detail=_DANGEROUS_ACTIONS_DISABLED_MESSAGE,
            )
        market_key = _ensure_market_active(market)
        policy = get_market_policy(settings, market_key)
        target_add_limit = int(
            _policy_updates(payload).get(
                "maximum_movies_to_add",
                policy.get("effective", {}).get(
                    "maximum_movies_to_add", settings.boxarr_features_auto_add_limit
                ),
            )
        )
        cleanup = AddLimitCleanupService(RadarrService(), settings.boxarr_data_directory)
        result = cleanup.run(
            market=market_key,
            target_add_limit=target_add_limit,
            year_from=payload.year_from,
            week_from=payload.week_from,
            year_to=payload.year_to,
            week_to=payload.week_to,
            delete_files=True,
            require_boxarr_tag=True,
            protect_tag=str(
                _policy_updates(payload).get(
                    "cleanup_protect_tag",
                    policy.get("effective", {}).get("cleanup_protect_tag", "boxarr-protected"),
                )
            ),
            required_market_tag=market_key,
            execute=execute,
        )
        result["policy"] = policy
        if execute and (
            result.get("deleted")
            or result.get("detached")
            or result.get("would_delete")
            or result.get("would_detach_market_tag_only")
        ):
            result["status_refresh"] = await anyio.to_thread.run_sync(
                refresh_stored_status_for_market,
                market_key,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _radarr_movie_tag_labels(movie: RadarrMovie, tag_labels: Dict[int, str]) -> List[str]:
    return [tag_labels.get(tag_id, f"tag:{tag_id}") for tag_id in _movie_tag_ids(movie)]


def _movie_market_matches(
    movie: RadarrMovie,
    weekly_index: Dict[Tuple[str, int, int], Dict[str, Any]],
    selected_markets: List[str],
) -> List[str]:
    markets: List[str] = []
    title_key = _normalize_text(movie.title)
    year = movie.year
    tmdb_id = movie.tmdbId
    radarr_id = movie.id
    for (market_key, movie_tmdb, movie_radarr), record in weekly_index.items():
        if selected_markets and market_key not in selected_markets:
            continue
        if movie_tmdb and tmdb_id and movie_tmdb == tmdb_id:
            markets.append(market_key)
            continue
        if movie_radarr and radarr_id and movie_radarr == radarr_id:
            markets.append(market_key)
            continue
        if record.get("title_key") == title_key and record.get("source_year") == year:
            markets.append(market_key)
    return sorted(set(markets))


@router.post("/tags/migrate/dry-run")
async def migrate_tags_dry_run(payload: TagMigrationRequest):
    return await _migrate_tags(payload, execute=False)


@router.post("/tags/migrate/execute")
async def migrate_tags_execute(payload: TagMigrationRequest):
    return await _migrate_tags(payload, execute=True)


async def _migrate_tags(payload: TagMigrationRequest, *, execute: bool):
    try:
        if execute and not settings.boxarr_enable_dangerous_actions:
            raise HTTPException(
                status_code=403,
                detail=_DANGEROUS_ACTIONS_DISABLED_MESSAGE,
            )
        market = str(payload.market or "all").strip().lower()
        selected_markets = _market_scope(market)
        radarr_service = RadarrService()
        tag_labels = _radarr_tag_label_map(radarr_service)
        weekly_index = _weekly_movie_markets(
            market,
            payload.year_from,
            payload.week_from,
            payload.year_to,
            payload.week_to,
        )
        movies = get_all_movies_with_optional_cache_bypass(radarr_service, ignore_cache=True)

        legacy_map = {
            "boxarr": "legacy_boxarr",
            "boxarr-keep": "legacy_keep",
            "boxarr-us": "legacy_boxarr_us",
            "boxarr-fr": "legacy_boxarr_fr",
        }
        counters = Counter(
            {
                "total_movies_scanned": len(movies),
                "total_tagged_legacy_boxarr": 0,
                "total_tagged_boxarr_keep": 0,
                "total_tagged_boxarr_us": 0,
                "total_tagged_boxarr_fr": 0,
            }
        )
        resolved_tags = [
            {"id": tag_id, "label": label}
            for tag_id, label in sorted(tag_labels.items(), key=lambda item: item[0])
        ]

        candidates: List[Dict[str, Any]] = []
        already_migrated: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        ambiguous: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        all_results: List[Dict[str, Any]] = []

        for movie in movies:
            try:
                current_labels = _radarr_movie_tag_labels(movie, tag_labels)
                current_label_set = {label.lower() for label in current_labels if isinstance(label, str)}
                legacy_hits = sorted(current_label_set & set(legacy_map))
                if "boxarr" in current_label_set:
                    counters["total_tagged_legacy_boxarr"] += 1
                if "boxarr-keep" in current_label_set:
                    counters["total_tagged_boxarr_keep"] += 1
                if "boxarr-us" in current_label_set:
                    counters["total_tagged_boxarr_us"] += 1
                if "boxarr-fr" in current_label_set:
                    counters["total_tagged_boxarr_fr"] += 1

                proposed_labels: List[str] = []
                reason = None
                safe = False
                matched_markets: List[str] = []
                required_labels: List[str] = []

                if not legacy_hits:
                    skipped.append(
                        {
                            "movie_id": movie.id,
                            "title": movie.title,
                            "current_tags": current_labels,
                            "proposed_tags": [],
                            "reason": "no legacy tags",
                            "safe": False,
                        }
                    )
                    all_results.append(skipped[-1])
                    continue

                if "boxarr-keep" in current_label_set and "boxarr-protected" not in current_label_set:
                    required_labels.append("boxarr-protected")
                    reason = "legacy keep tag"

                if "boxarr-us" in current_label_set and "boxarr-market-us" not in current_label_set:
                    required_labels.append("boxarr-market-us")
                    reason = "legacy market tag"
                if "boxarr-fr" in current_label_set and "boxarr-market-fr" not in current_label_set:
                    required_labels.append("boxarr-market-fr")
                    reason = "legacy market tag"

                if "boxarr" in current_label_set:
                    markets = _movie_market_matches(movie, weekly_index, selected_markets)
                    matched_markets = markets
                    if markets:
                        required_labels.append("boxarr-added")
                        for m in markets:
                            market_tag = f"boxarr-market-{m}"
                            if market_tag not in required_labels:
                                required_labels.append(market_tag)
                        reason = "legacy boxarr tag matched to weekly pages"
                    else:
                        reason = "ambiguous legacy boxarr tag"
                        ambiguous.append(
                            {
                                "movie_id": movie.id,
                                "title": movie.title,
                                "current_tags": current_labels,
                                "legacy_tags": legacy_hits,
                                "proposed_tags": [],
                                "matched_markets": matched_markets,
                                "reason": reason,
                                "safe": False,
                            }
                        )
                        all_results.append(ambiguous[-1])
                        continue

                required_labels = list(dict.fromkeys(required_labels))
                proposed_labels = [label for label in required_labels if label not in current_label_set]
                if legacy_hits and not proposed_labels:
                    already_row = {
                        "movie_id": movie.id,
                        "title": movie.title,
                        "current_tags": current_labels,
                        "legacy_tags": legacy_hits,
                        "proposed_tags": [],
                        "matched_markets": matched_markets,
                        "reason": "already has canonical tags",
                        "safe": False,
                        "already_migrated": True,
                    }
                    already_migrated.append(already_row)
                    all_results.append(already_row)
                    continue
                safe = bool(proposed_labels)

                result_row = {
                    "movie_id": movie.id,
                    "title": movie.title,
                    "current_tags": current_labels,
                    "legacy_tags": legacy_hits,
                    "proposed_tags": proposed_labels,
                    "matched_markets": matched_markets,
                    "reason": reason or "legacy tag migration",
                    "safe": safe,
                    "already_migrated": False,
                }
                candidates.append(result_row)
                all_results.append(result_row)
                if execute and proposed_labels:
                    new_labels = list(dict.fromkeys(current_labels + proposed_labels))
                    new_tag_ids = _tag_ids_for_labels(radarr_service, new_labels)
                    raw = dict(getattr(movie, "_raw_data", {}) or {})
                    raw["tags"] = new_tag_ids
                    movie._raw_data = raw
                    movie.tags = new_tag_ids
                    try:
                        radarr_service.update_movie(movie)
                    except Exception as exc:
                        logger.warning("Failed to migrate tags for %s: %s", movie.title, exc)
                        result_row["safe"] = False
                        result_row["reason"] = f"update failed: {exc}"
                        errors.append(
                            {
                                "movie_id": movie.id,
                                "title": movie.title,
                                "error": str(exc),
                            }
                        )
            except Exception as exc:
                logger.warning("Failed to inspect Radarr movie for migration: %s", exc)
                errors.append(
                    {
                        "movie_id": getattr(movie, "id", None),
                        "title": getattr(movie, "title", None),
                        "error": str(exc),
                    }
                )

        if counters["total_tagged_legacy_boxarr"] == 0:
            message = "No legacy boxarr tags were detected in Radarr movies."
        else:
            message = None

        result = {
            "success": True,
            "mode": "execute" if execute else "dry-run",
            "dry_run": not execute,
            "market": market,
            "total_movies_scanned": counters["total_movies_scanned"],
            "total_tagged_legacy_boxarr": counters["total_tagged_legacy_boxarr"],
            "total_tagged_boxarr_keep": counters["total_tagged_boxarr_keep"],
            "total_tagged_boxarr_us": counters["total_tagged_boxarr_us"],
            "total_tagged_boxarr_fr": counters["total_tagged_boxarr_fr"],
            "resolved_tags": resolved_tags,
            "message": message,
            "candidates": candidates,
            "already_migrated": already_migrated,
            "skipped": skipped,
            "ambiguous": ambiguous,
            "errors": errors,
            "results": all_results,
            "migrated": sum(1 for item in candidates if item.get("safe")),
            "already_migrated_count": len(already_migrated),
        }
        if execute and result["migrated"] > 0:
            result["status_refresh"] = refresh_stored_status_for_market(market)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
