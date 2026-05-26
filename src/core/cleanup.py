"""Safe cleanup helpers for removing Boxarr-added movies from Radarr."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .boxoffice_provider import DEFAULT_MARKET, normalize_market
from .boxoffice_storage import iter_weekly_page_paths
from .market_settings import get_configured_markets, get_effective_market_settings
from .ignore_list import IgnoreList
from .radarr import RadarrMovie, RadarrService, get_all_movies_with_optional_cache_bypass
from ..utils.config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_market_selection(market: str) -> str:
    value = str(market or "").strip().lower()
    if value == "all":
        return value
    return normalize_market(value)


def _parse_week_file_key(path: Path) -> Optional[Tuple[int, int]]:
    stem = path.stem
    if len(stem) < 7 or "W" not in stem:
        return None

    try:
        year_str, week_str = stem.split("W", 1)
        if not year_str.isdigit() or not week_str[:2].isdigit():
            return None
        return int(year_str), int(week_str[:2])
    except Exception:
        return None


def _week_key_tuple(year: Optional[int], week: Optional[int]) -> Optional[Tuple[int, int]]:
    if year is None:
        return None
    return year, week if week is not None else 1


def _within_bounds(
    year: int,
    week: int,
    year_from: Optional[int],
    week_from: Optional[int],
    year_to: Optional[int],
    week_to: Optional[int],
) -> bool:
    current = (year, week)
    start = _week_key_tuple(year_from, week_from)
    end = _week_key_tuple(year_to, week_to)
    if start and current < start:
        return False
    if end and current > end:
        return False
    return True


def _movie_tag_ids(movie: RadarrMovie) -> Set[int]:
    if movie.tags:
        return {
            int(tag)
            for tag in movie.tags
            if isinstance(tag, (int, str)) and str(tag).isdigit()
        }

    raw = getattr(movie, "_raw_data", None) or {}
    tags = raw.get("tags", []) if isinstance(raw, dict) else []
    return {
        int(tag)
        for tag in tags
        if isinstance(tag, (int, str)) and str(tag).isdigit()
    }


def _normalize_tag_label(label: Optional[str]) -> str:
    return str(label or "").strip().lower()


def _market_tag_aliases(market: str) -> Set[str]:
    market_key = _normalize_market_selection(market)
    if market_key == "all":
        return set()
    aliases = {f"boxarr-market-{market_key}"}
    if market_key in {"us", "fr"}:
        aliases.add(f"boxarr-{market_key}")
    return aliases


def _all_market_tag_aliases() -> Set[str]:
    configured_markets = get_configured_markets(settings)
    aliases: Set[str] = set()
    for market_key in configured_markets.keys():
        aliases.add(f"boxarr-market-{market_key}")
        if market_key in {"us", "fr"}:
            aliases.add(f"boxarr-{market_key}")
    return aliases


def _movie_original_language(movie_info: Dict[str, Any]) -> Optional[str]:
    value = movie_info.get("originalLanguage")
    if isinstance(value, dict):
        language = value.get("name")
        return language if isinstance(language, str) else None
    if isinstance(value, str):
        return value
    value = movie_info.get("original_language")
    return value if isinstance(value, str) else None


def _movie_genres(movie_info: Dict[str, Any]) -> List[str]:
    genres = movie_info.get("genres", [])
    if isinstance(genres, list):
        return [genre for genre in genres if isinstance(genre, str)]
    if isinstance(genres, str):
        return [part.strip() for part in genres.split(",") if part.strip()]
    return []


def _movie_year(movie_info: Dict[str, Any]) -> Optional[int]:
    year = movie_info.get("year")
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit():
        return int(year)

    release_date = movie_info.get("releaseDate") or movie_info.get("inCinemas")
    if isinstance(release_date, str) and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


@dataclass
class CleanupDecision:
    """Single cleanup report row."""

    title: str
    market: str
    year: int
    week: int
    rank: int
    action: str
    reason: str
    tmdb_id: Optional[int] = None
    radarr_id: Optional[int] = None
    eligible_key: Optional[str] = None
    radarr_key: Optional[str] = None
    identity_source: Optional[str] = None
    why_not_eligible: Optional[str] = None
    radarr_title: Optional[str] = None
    path: Optional[str] = None
    size_on_disk: Optional[int] = None
    has_file: Optional[bool] = None
    monitored: Optional[bool] = None
    quality_profile_id: Optional[int] = None
    tags: List[int] = field(default_factory=list)
    tag_names: List[str] = field(default_factory=list)
    weeks_found: List[Dict[str, Any]] = field(default_factory=list)
    ranks_by_week: List[Dict[str, Any]] = field(default_factory=list)
    best_rank: Optional[int] = None
    eligible_under_target_limit: bool = False
    safe_to_delete: bool = False
    safe_to_detach: bool = False
    unsafe_to_delete: bool = False
    unsafe_reason: Optional[str] = None
    estimated_size_bytes: int = 0
    actual_size_bytes: int = 0
    radarr_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "market": self.market,
            "year": self.year,
            "week": self.week,
            "rank": self.rank,
            "action": self.action,
            "reason": self.reason,
            "tmdb_id": self.tmdb_id,
            "radarr_id": self.radarr_id,
            "eligible_key": self.eligible_key,
            "radarr_key": self.radarr_key,
            "identity_source": self.identity_source,
            "why_not_eligible": self.why_not_eligible,
            "radarr_title": self.radarr_title,
            "path": self.path,
            "size_on_disk": self.size_on_disk,
            "has_file": self.has_file,
            "monitored": self.monitored,
            "quality_profile_id": self.quality_profile_id,
            "tags": self.tags,
            "tag_names": self.tag_names,
            "weeks_found": self.weeks_found,
            "ranks_by_week": self.ranks_by_week,
            "best_rank": self.best_rank,
            "eligible_under_target_limit": self.eligible_under_target_limit,
            "safe_to_delete": self.safe_to_delete,
            "safe_to_detach": self.safe_to_detach,
            "unsafe_to_delete": self.unsafe_to_delete,
            "unsafe_reason": self.unsafe_reason,
            "estimated_size_bytes": self.estimated_size_bytes,
            "actual_size_bytes": self.actual_size_bytes,
            "radarr_result": self.radarr_result,
        }


@dataclass
class CleanupReport:
    """Overall cleanup report."""

    market: str
    target_add_limit: int
    dry_run: bool
    delete_files: bool
    require_boxarr_tag: bool
    protect_tag: str
    markets_scanned: List[str] = field(default_factory=list)
    weeks_scanned: int = 0
    movies_scanned: int = 0
    considered_total: int = 0
    eligible_count: int = 0
    associated_count: int = 0
    candidates: List[CleanupDecision] = field(default_factory=list)
    would_delete: List[CleanupDecision] = field(default_factory=list)
    would_detach_market_tag_only: List[CleanupDecision] = field(default_factory=list)
    protected: List[CleanupDecision] = field(default_factory=list)
    unsafe: List[CleanupDecision] = field(default_factory=list)
    deleted: List[CleanupDecision] = field(default_factory=list)
    detached: List[CleanupDecision] = field(default_factory=list)
    skipped: List[CleanupDecision] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    estimated_size_deleted: int = 0
    actual_size_deleted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        if self.dry_run:
            return {
                "success": True,
                "mode": "dry-run",
                "dry_run": True,
                "market": self.market,
                "markets_scanned": self.markets_scanned,
                "target_add_limit": self.target_add_limit,
                "delete_files": self.delete_files,
                "require_boxarr_tag": self.require_boxarr_tag,
                "protect_tag": self.protect_tag,
                "weeks_scanned": self.weeks_scanned,
                "movies_scanned": self.movies_scanned,
                "considered_total": self.considered_total,
                "eligible_count": self.eligible_count,
                "associated_count": self.associated_count,
                "candidates": [item.to_dict() for item in self.would_delete],
                "would_delete": [item.to_dict() for item in self.would_delete],
                "would_detach_market_tag_only": [
                    item.to_dict() for item in self.would_detach_market_tag_only
                ],
                "protected": [item.to_dict() for item in self.protected],
                "unsafe": [item.to_dict() for item in self.unsafe],
                "skipped": [item.to_dict() for item in self.skipped],
                "estimated_size_to_delete": self.estimated_size_deleted,
            }
        return {
            "success": True,
            "mode": "execute",
            "dry_run": False,
            "market": self.market,
            "markets_scanned": self.markets_scanned,
            "target_add_limit": self.target_add_limit,
            "delete_files": self.delete_files,
            "require_boxarr_tag": self.require_boxarr_tag,
            "protect_tag": self.protect_tag,
            "weeks_scanned": self.weeks_scanned,
            "movies_scanned": self.movies_scanned,
            "considered_total": self.considered_total,
            "eligible_count": self.eligible_count,
            "associated_count": self.associated_count,
            "would_delete": [item.to_dict() for item in self.would_delete],
            "would_detach_market_tag_only": [
                item.to_dict() for item in self.would_detach_market_tag_only
            ],
            "deleted": [item.to_dict() for item in self.deleted],
            "detached": [item.to_dict() for item in self.detached],
            "protected": [item.to_dict() for item in self.protected],
            "unsafe": [item.to_dict() for item in self.unsafe],
            "skipped": [item.to_dict() for item in self.skipped],
            "errors": self.errors,
            "estimated_size_deleted": self.estimated_size_deleted,
            "actual_size_deleted": self.actual_size_deleted,
        }


class AddLimitCleanupService:
    """Implements the safe add-limit cleanup workflow."""

    def __init__(
        self,
        radarr_service: RadarrService,
        data_directory: Optional[Path] = None,
    ):
        self.radarr_service = radarr_service
        self.data_directory = Path(data_directory or settings.boxarr_data_directory)
        self._movies_by_id: Dict[int, RadarrMovie] = {}
        self._movies_by_tmdb: Dict[int, RadarrMovie] = {}
        self._tag_ids_by_label: Dict[str, int] = {}
        self._tag_labels_by_id: Dict[int, str] = {}
        self._tmdb_search_cache: Dict[int, Optional[Dict[str, Any]]] = {}

    def run(
        self,
        market: str,
        target_add_limit: int,
        year_from: Optional[int] = None,
        week_from: Optional[int] = None,
        year_to: Optional[int] = None,
        week_to: Optional[int] = None,
        delete_files: bool = True,
        require_boxarr_tag: bool = True,
        protect_tag: str = "boxarr-protected",
        required_market_tag: Optional[str] = None,
        execute: bool = False,
    ) -> Dict[str, Any]:
        market_value = _normalize_market_selection(market)
        configured_markets = get_configured_markets(settings)
        selected_markets = (
            [key for key, definition in configured_markets.items() if definition.get("enabled", True)]
            if market_value == "all"
            else [normalize_market(market_value)]
        )
        if execute and not delete_files:
            raise ValueError("delete_files must be true when executing cleanup")

        self._load_radarr_context()
        ignore_ids = IgnoreList(self.data_directory).get_ignored_tmdb_ids()
        report = CleanupReport(
            market=market_value,
            target_add_limit=target_add_limit,
            dry_run=not execute,
            delete_files=delete_files,
            require_boxarr_tag=require_boxarr_tag,
            protect_tag=protect_tag,
            markets_scanned=selected_markets,
        )

        eligible_ids: Set[int] = set()
        eligible_keys: Set[Tuple[str, int]] = set()
        known_associated_ids: Set[int] = set()
        known_associated_keys: Set[Tuple[str, int]] = set()
        weekly_records = self._collect_weekly_records(
            selected_markets,
            year_from,
            week_from,
            year_to,
            week_to,
        )
        report.weeks_scanned = len({(item["market"], item["year"], item["week"]) for item in weekly_records})
        report.movies_scanned = len(weekly_records)
        report.considered_total = len(self._all_radarr_movies())
        weekly_index = self._build_weekly_appearance_index(weekly_records)

        for record in weekly_records:
            stored_movie = record["movie"]
            rank = int(stored_movie.get("rank", 0) or 0)

            tmdb_id = self._safe_int(stored_movie.get("tmdb_id"))
            radarr_id = self._safe_int(stored_movie.get("radarr_id"))
            if tmdb_id is not None:
                known_associated_ids.add(tmdb_id)
            if radarr_id is not None:
                known_associated_ids.add(radarr_id)
            for key in self._movie_keys_from_stored_movie(stored_movie):
                known_associated_keys.add(key)

            if rank <= 0 or rank > target_add_limit:
                continue

            movie_info = self._resolve_movie_info(stored_movie)
            if not movie_info:
                continue

            if self._passes_auto_add_filters(
                movie_info,
                top_year=record["year"],
                ignore_ids=ignore_ids,
            ):
                if tmdb_id is not None:
                    eligible_ids.add(tmdb_id)
                if radarr_id is not None:
                    eligible_ids.add(radarr_id)
                for key in self._movie_keys_from_stored_movie(stored_movie):
                    eligible_keys.add(key)

        report.eligible_count = len(eligible_keys)
        report.associated_count = len(known_associated_keys)
        all_market_tag_labels = _all_market_tag_aliases()
        current_market_tag_labels = _market_tag_aliases(market_value)

        decisions: List[CleanupDecision] = []
        for movie in sorted(self._all_radarr_movies(), key=lambda item: item.id):
            decision = self._evaluate_radarr_movie_for_cleanup(
                movie,
                market=market_value,
                eligible_ids=eligible_ids,
                eligible_keys=eligible_keys,
                known_associated_ids=known_associated_ids,
                known_associated_keys=known_associated_keys,
                weekly_index=weekly_index,
                target_add_limit=target_add_limit,
                require_boxarr_tag=require_boxarr_tag,
                protect_tag=protect_tag,
                required_market_tag=required_market_tag,
                current_market_tag_labels=current_market_tag_labels,
                all_market_tag_labels=all_market_tag_labels,
            )
            if decision is None:
                continue
            decisions.append(decision)

        report.candidates = [decision for decision in decisions if decision.action == "delete"]
        report.would_delete = [decision for decision in decisions if decision.action == "delete"]
        report.would_detach_market_tag_only = [
            decision for decision in decisions if decision.action == "detach"
        ]
        report.protected = [decision for decision in decisions if decision.action == "protected"]
        report.unsafe = [decision for decision in decisions if decision.action == "unsafe"]
        report.estimated_size_deleted = sum(
            item.estimated_size_bytes for item in report.would_delete
        )

        for decision in report.would_delete:
            if execute:
                try:
                    response = self.radarr_service.delete_movie(
                        decision.radarr_id,
                        delete_files=True,
                    )
                    decision.action = "deleted"
                    decision.actual_size_bytes = decision.estimated_size_bytes
                    decision.radarr_result = {
                        "status_code": getattr(response, "status_code", 200),
                        "delete_files": True,
                        "movie_id": decision.radarr_id,
                    }
                    report.deleted.append(decision)
                    report.actual_size_deleted += decision.actual_size_bytes
                except Exception as exc:
                    decision.action = "error"
                    decision.reason = f"Radarr delete failed: {exc}"
                    report.errors.append(
                        {
                            "title": decision.title,
                            "radarr_id": decision.radarr_id,
                            "tmdb_id": decision.tmdb_id,
                            "error": str(exc),
                        }
                    )

        for decision in report.would_detach_market_tag_only:
            if execute:
                try:
                    self._detach_market_tag(decision, market_value)
                    decision.action = "detached"
                    report.detached.append(decision)
                except Exception as exc:
                    decision.action = "error"
                    decision.reason = f"Radarr tag update failed: {exc}"
                    report.errors.append(
                        {
                            "title": decision.title,
                            "radarr_id": decision.radarr_id,
                            "tmdb_id": decision.tmdb_id,
                            "error": str(exc),
                        }
                    )

        for decision in decisions:
            if decision.action in {"delete", "detach", "protected", "unsafe", "error"}:
                continue
            report.skipped.append(decision)
        if execute:
            # In execute mode, report.deleted contains the successful deletions.
            # Skipped items are already captured, and errors are recorded separately.
            pass

        logger.info(
            "Cleanup report generated for market=%s limit=%s: %s deletions, %s skips, %s errors",
            market_value,
            target_add_limit,
            len(report.deleted),
            len(report.skipped),
            len(report.errors),
        )
        return report.to_dict()

    def _load_radarr_context(self) -> None:
        movies = get_all_movies_with_optional_cache_bypass(
            self.radarr_service, ignore_cache=True
        )
        self._movies_by_id = {movie.id: movie for movie in movies}
        self._movies_by_tmdb = {
            movie.tmdbId: movie for movie in movies if getattr(movie, "tmdbId", 0)
        }

        try:
            tags = self.radarr_service.get_tags()
        except Exception as exc:
            logger.warning("Unable to load Radarr tags for cleanup: %s", exc)
            tags = []

        self._tag_ids_by_label = {}
        self._tag_labels_by_id = {}
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            label = tag.get("label")
            tag_id = tag.get("id")
            if isinstance(label, str) and isinstance(tag_id, int):
                self._tag_ids_by_label[label.lower()] = tag_id
                self._tag_labels_by_id[tag_id] = label

    def _all_radarr_movies(self) -> List[RadarrMovie]:
        return list(self._movies_by_id.values())

    def _collect_weekly_records(
        self,
        markets: Sequence[str],
        year_from: Optional[int],
        week_from: Optional[int],
        year_to: Optional[int],
        week_to: Optional[int],
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        seen_paths: Set[str] = set()

        for market in markets:
            for path in iter_weekly_page_paths(self.data_directory, market):
                if path.as_posix() in seen_paths:
                    continue
                seen_paths.add(path.as_posix())

                parsed_week = _parse_week_file_key(path)
                if not parsed_week:
                    continue
                year, week = parsed_week
                if not _within_bounds(year, week, year_from, week_from, year_to, week_to):
                    continue

                try:
                    import json

                    payload = json.loads(path.read_text())
                except Exception as exc:
                    logger.warning("Failed to read cleanup source file %s: %s", path, exc)
                    continue

                file_market = str(payload.get("market") or market).lower()
                if file_market != market and not (market == DEFAULT_MARKET and file_market == "us"):
                    continue

                movies = payload.get("movies", [])
                if not isinstance(movies, list):
                    continue

                for movie in movies:
                    if not isinstance(movie, dict):
                        continue
                    records.append(
                        {
                "market": market,
                "year": int(payload.get("year") or year),
                "week": int(payload.get("week") or week),
                "movie": movie,
            }
                    )

        return records

    def _build_weekly_appearance_index(
        self, weekly_records: Sequence[Dict[str, Any]]
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        index: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for record in weekly_records:
            stored_movie = record.get("movie")
            if not isinstance(stored_movie, dict):
                continue

            market = str(record.get("market") or "").lower()
            year = self._safe_int(record.get("year"))
            week = self._safe_int(record.get("week"))
            rank = self._safe_int(stored_movie.get("rank"))
            if not market or year is None or week is None or rank is None:
                continue

            week_key = (market, year, week)
            rank_key = (market, year, week, rank)
            for key in self._movie_keys_from_stored_movie(stored_movie):
                entry = index.setdefault(
                    key,
                    {
                        "weeks_set": set(),
                        "ranks_set": set(),
                        "best_rank": None,
                    },
                )
                entry["weeks_set"].add(week_key)
                entry["ranks_set"].add(rank_key)
                best_rank = entry.get("best_rank")
                entry["best_rank"] = rank if best_rank is None else min(best_rank, rank)
        return index

    def _movie_keys_from_stored_movie(self, stored_movie: Dict[str, Any]) -> List[Tuple[str, int]]:
        keys: List[Tuple[str, int]] = []
        tmdb_id = self._safe_int(stored_movie.get("tmdb_id"))
        radarr_id = self._safe_int(stored_movie.get("radarr_id"))
        if tmdb_id is not None:
            keys.append(("tmdb", tmdb_id))
        if radarr_id is not None:
            keys.append(("radarr", radarr_id))
        return keys

    def _collect_appearance_stats(
        self,
        movie: RadarrMovie,
        weekly_index: Dict[Tuple[str, int], Dict[str, Any]],
    ) -> Dict[str, Any]:
        keys = self._movie_identity_keys(movie)

        weeks: Set[Tuple[str, int, int]] = set()
        ranks: Set[Tuple[str, int, int, int]] = set()
        best_rank: Optional[int] = None

        for key in keys:
            entry = weekly_index.get(key)
            if not entry:
                continue
            weeks.update(entry.get("weeks_set", set()))
            ranks.update(entry.get("ranks_set", set()))
            entry_best_rank = entry.get("best_rank")
            if isinstance(entry_best_rank, int):
                best_rank = entry_best_rank if best_rank is None else min(best_rank, entry_best_rank)

        weeks_found = [
            {"market": market, "year": year, "week": week}
            for market, year, week in sorted(weeks)
        ]
        ranks_by_week = [
            {"market": market, "year": year, "week": week, "rank": rank}
            for market, year, week, rank in sorted(ranks)
        ]
        return {
            "weeks_found": weeks_found,
            "ranks_by_week": ranks_by_week,
            "best_rank": best_rank,
        }

    def _movie_identity_keys(self, movie: RadarrMovie) -> List[Tuple[str, int]]:
        keys: List[Tuple[str, int]] = []
        if movie.tmdbId:
            keys.append(("tmdb", movie.tmdbId))
        if movie.id:
            keys.append(("radarr", movie.id))
        return keys

    def _format_identity_key(self, key: Optional[Tuple[str, int]]) -> Optional[str]:
        if not key:
            return None
        kind, value = key
        return f"{kind}:{value}"

    def _first_matching_key(
        self,
        candidates: List[Tuple[str, int]],
        available_keys: Iterable[Tuple[str, int]],
    ) -> Optional[Tuple[str, int]]:
        available = set(available_keys)
        for key in candidates:
            if key in available:
                return key
        return None

    def _resolve_movie_info(self, stored_movie: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tmdb_id = self._safe_int(stored_movie.get("tmdb_id"))
        radarr_id = self._safe_int(stored_movie.get("radarr_id"))

        if radarr_id is not None and radarr_id in self._movies_by_id:
            movie = self._movies_by_id[radarr_id]
            return movie._raw_data or {}

        if tmdb_id is not None and tmdb_id in self._movies_by_tmdb:
            movie = self._movies_by_tmdb[tmdb_id]
            return movie._raw_data or {}

        if tmdb_id is not None:
            if tmdb_id not in self._tmdb_search_cache:
                try:
                    results = self.radarr_service.search_movie(f"tmdb:{tmdb_id}")
                    self._tmdb_search_cache[tmdb_id] = (
                        results[0] if isinstance(results, list) and results else None
                    )
                except Exception as exc:
                    logger.debug("Radarr TMDB lookup failed for %s: %s", tmdb_id, exc)
                    self._tmdb_search_cache[tmdb_id] = None
            return self._tmdb_search_cache.get(tmdb_id)

        if radarr_id is not None:
            try:
                movie = self.radarr_service.get_movie(radarr_id)
                return movie._raw_data or {}
            except Exception as exc:
                logger.debug("Radarr movie lookup failed for %s: %s", radarr_id, exc)

        return None

    def _movie_size_on_disk(self, movie: RadarrMovie) -> Optional[int]:
        if isinstance(movie.size_on_disk, int) and movie.size_on_disk > 0:
            return movie.size_on_disk
        if movie.movieFile:
            size_bytes = movie.movieFile.get("size")
            if isinstance(size_bytes, (int, float)) and size_bytes > 0:
                return int(size_bytes)
        return None

    def _passes_auto_add_filters(
        self,
        movie_info: Dict[str, Any],
        top_year: int,
        ignore_ids: Set[int],
    ) -> bool:
        movie_tmdb_id = self._safe_int(movie_info.get("tmdbId"))
        if movie_tmdb_id is not None and movie_tmdb_id in ignore_ids:
            return False

        if settings.boxarr_features_auto_add_ignore_rereleases:
            movie_year = _movie_year(movie_info)
            if movie_year and int(movie_year) < (top_year - 1):
                return False

        if settings.boxarr_features_auto_add_genre_filter_enabled:
            movie_genres = _movie_genres(movie_info)
            if settings.boxarr_features_auto_add_genre_filter_mode == "whitelist":
                whitelist = settings.boxarr_features_auto_add_genre_whitelist
                if whitelist and not any(genre in whitelist for genre in movie_genres):
                    return False
            else:
                blacklist = settings.boxarr_features_auto_add_genre_blacklist
                if blacklist and any(genre in blacklist for genre in movie_genres):
                    return False

        if settings.boxarr_features_auto_add_rating_filter_enabled:
            movie_rating = movie_info.get("certification")
            rating_whitelist = settings.boxarr_features_auto_add_rating_whitelist
            if rating_whitelist and movie_rating and movie_rating not in rating_whitelist:
                return False

        if settings.boxarr_features_auto_add_language_filter_enabled:
            original_language = _movie_original_language(movie_info)
            if settings.boxarr_features_auto_add_language_filter_mode == "whitelist":
                whitelist = settings.boxarr_features_auto_add_language_whitelist
                if whitelist and (
                    not original_language or original_language not in whitelist
                ):
                    return False
            else:
                blacklist = settings.boxarr_features_auto_add_language_blacklist
                if blacklist and original_language and original_language in blacklist:
                    return False

        return True

    def _evaluate_radarr_movie_for_cleanup(
        self,
        movie: RadarrMovie,
        market: str,
        eligible_ids: Set[int],
        eligible_keys: Set[Tuple[str, int]],
        known_associated_ids: Set[int],
        known_associated_keys: Set[Tuple[str, int]],
        weekly_index: Dict[Tuple[str, int], Dict[str, Any]],
        target_add_limit: int,
        require_boxarr_tag: bool,
        protect_tag: str,
        required_market_tag: Optional[str] = None,
        current_market_tag_labels: Optional[Set[str]] = None,
        all_market_tag_labels: Optional[Set[str]] = None,
    ) -> Optional[CleanupDecision]:
        tag_ids = _movie_tag_ids(movie)
        tag_labels = {
            self._tag_labels_by_id.get(tag_id, "")
            for tag_id in tag_ids
            if tag_id in self._tag_labels_by_id
        }
        tag_labels.discard("")
        tag_labels = {_normalize_tag_label(label) for label in tag_labels if label}

        protect_label = str(protect_tag or "").strip().lower()
        if not protect_label:
            effective = get_effective_market_settings(settings, market)
            protect_label = str(
                effective.get("effective", {}).get("cleanup_protect_tag", "boxarr-protected")
            ).strip().lower()
        required_boxarr_labels = {"boxarr-added"}
        legacy_boxarr_labels = {"boxarr"}
        required_market_label = str(required_market_tag or "").strip().lower()
        movie_keys = self._movie_identity_keys(movie)
        radarr_key = self._format_identity_key(("radarr", movie.id)) if movie.id else None
        identity_source = movie_keys[0][0] if movie_keys else None
        size_on_disk = self._movie_size_on_disk(movie)
        appearance_stats = self._collect_appearance_stats(movie, weekly_index)
        best_rank = appearance_stats.get("best_rank")
        eligible_under_target_limit = best_rank is not None and best_rank <= target_add_limit
        matched_eligible_key = self._first_matching_key(movie_keys, eligible_keys)
        matched_week_key = self._first_matching_key(movie_keys, weekly_index.keys())
        matched_associated_key = self._first_matching_key(movie_keys, known_associated_keys)
        weeks_found = appearance_stats.get("weeks_found", [])
        ranks_by_week = appearance_stats.get("ranks_by_week", [])
        eligible_key_str = self._format_identity_key(matched_eligible_key)

        def _base_decision(
            *,
            action: str,
            reason: str,
            eligible_key: Optional[str] = eligible_key_str,
            why_not_eligible: Optional[str] = None,
            safe_to_delete: bool = False,
            unsafe_reason: Optional[str] = None,
        ) -> CleanupDecision:
            return CleanupDecision(
                title=movie.title,
                market=market,
                year=movie.year or 0,
                week=0,
                rank=best_rank or 0,
                action=action,
                reason=reason,
                tmdb_id=movie.tmdbId or None,
                radarr_id=movie.id,
                eligible_key=eligible_key,
                radarr_key=radarr_key,
                identity_source=identity_source,
                why_not_eligible=why_not_eligible,
                radarr_title=movie.title,
                path=movie.path,
                size_on_disk=size_on_disk,
                has_file=movie.hasFile,
                monitored=movie.monitored,
                quality_profile_id=movie.qualityProfileId,
                tags=sorted(tag_ids),
                tag_names=sorted(tag_labels),
                weeks_found=weeks_found,
                ranks_by_week=ranks_by_week,
                best_rank=best_rank,
                eligible_under_target_limit=eligible_under_target_limit,
                safe_to_delete=safe_to_delete,
                safe_to_detach=False,
                unsafe_to_delete=not safe_to_delete,
                unsafe_reason=unsafe_reason,
                estimated_size_bytes=size_on_disk or 0,
            )

        protected_labels = {"boxarr-protected", "boxarr-keep"}
        if protect_label:
            protected_labels.add(protect_label)
        if protected_labels & tag_labels:
            return _base_decision(
                action="protected",
                reason=f"protected by tag '{protect_tag}'",
                eligible_key=None,
                why_not_eligible="protected by tag",
            )

        has_boxarr_added = "boxarr-added" in tag_labels
        has_legacy_boxarr = bool(legacy_boxarr_labels & tag_labels)
        if require_boxarr_tag and not has_boxarr_added:
            return _base_decision(
                action="skip",
                reason=(
                    "legacy boxarr tag requires migration"
                    if has_legacy_boxarr
                    else "missing required boxarr-added tag"
                ),
                eligible_key=None,
                why_not_eligible=(
                    "legacy boxarr tag requires migration"
                    if has_legacy_boxarr
                    else "missing required boxarr-added tag"
                ),
            )

        if required_market_label and required_market_label != "all":
            market_labels = _market_tag_aliases(required_market_label)
            if not (market_labels & tag_labels):
                return _base_decision(
                    action="skip",
                    reason=f"missing required market tag for {required_market_label}",
                    eligible_key=None,
                    why_not_eligible="missing required market tag",
                )

        associated = bool(matched_associated_key)
        if not associated:
            return _base_decision(
                action="skip",
                reason="no reliable Boxarr association",
                eligible_key=None,
                why_not_eligible="no reliable Boxarr association",
            )

        if eligible_under_target_limit:
            return _base_decision(
                action="skip",
                reason="present in eligible range by best_rank",
                why_not_eligible="present in eligible range by best_rank",
                unsafe_reason="present in eligible range by best_rank",
            )

        if matched_eligible_key is not None:
            return _base_decision(
                action="skip",
                reason="present in eligible set",
                why_not_eligible="present in eligible set",
                eligible_key=self._format_identity_key(matched_eligible_key),
            )

        current_market_labels = current_market_tag_labels or _market_tag_aliases(market)
        all_market_labels = all_market_tag_labels or _all_market_tag_aliases()
        current_tags_present = sorted(current_market_labels & tag_labels)
        other_market_tags = sorted((all_market_labels & tag_labels) - current_market_labels)

        if current_tags_present and other_market_tags:
            return _base_decision(
                action="detach",
                reason=(
                    "tagged for multiple markets; detach current market tag only"
                ),
                why_not_eligible="tagged for multiple markets",
                safe_to_delete=False,
                safe_to_detach=True,
            )

        if not current_tags_present:
            if has_legacy_boxarr:
                return _base_decision(
                    action="skip",
                    reason="legacy boxarr tag requires migration",
                    why_not_eligible="legacy boxarr tag requires migration",
                )
            if other_market_tags:
                return _base_decision(
                    action="skip",
                    reason="tagged for another market",
                    why_not_eligible="tagged for another market",
                )
            return _base_decision(
                action="skip",
                reason="missing current market tag",
                why_not_eligible="missing current market tag",
            )

        safe_to_delete = size_on_disk is not None and size_on_disk > 0
        if not safe_to_delete:
            return _base_decision(
                action="unsafe",
                reason="unsafe to delete: size_on_disk unknown",
                why_not_eligible="absent from eligible set",
                safe_to_delete=False,
                unsafe_reason="size_on_disk unknown",
            )

        reason_parts = ["tagged boxarr and absent from eligible set"]
        if best_rank is not None:
            reason_parts.append(f"best_rank={best_rank}")
        if weeks_found:
            reason_parts.append(f"weeks_found={len(weeks_found)}")
        if matched_week_key is not None:
            reason_parts.append(
                f"why_not_eligible=not in eligible set for {self._format_identity_key(matched_week_key)}"
            )
        else:
            reason_parts.append("why_not_eligible=absent from eligible set")

        return _base_decision(
            action="delete",
            reason="; ".join(reason_parts),
            why_not_eligible="absent from eligible set",
            eligible_key=None,
            safe_to_delete=True,
            unsafe_reason=None,
        )

    def _detach_market_tag(self, decision: CleanupDecision, market: str) -> None:
        if not decision.radarr_id:
            raise ValueError("Cannot detach tags without a Radarr movie id")

        movie = self._movies_by_id.get(decision.radarr_id)
        if movie is None:
            movie = self.radarr_service.get_movie(decision.radarr_id)

        current_market_labels = _market_tag_aliases(market)
        current_tag_ids = {
            tag_id
            for tag_id in _movie_tag_ids(movie)
            if self._tag_labels_by_id.get(tag_id, "").lower() in current_market_labels
        }
        if not current_tag_ids:
            return

        current_tags = [tag_id for tag_id in _movie_tag_ids(movie) if tag_id not in current_tag_ids]
        raw = dict(getattr(movie, "_raw_data", {}) or {})
        raw["tags"] = current_tags
        movie._raw_data = raw
        movie.tags = current_tags
        self.radarr_service.update_movie(movie)

    def _estimate_movie_size(self, movie: RadarrMovie) -> int:
        size_on_disk = self._movie_size_on_disk(movie)
        return size_on_disk or 0

    def _safe_int(self, value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None
