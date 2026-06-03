"""Helpers for resolving a box office movie to a TMDb/Radarr candidate."""

from __future__ import annotations

import re
import unicodedata
from inspect import Parameter, signature
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional

from .boxoffice import BoxOfficeMovie
from .identity_overrides import lookup_identity_override
from ..utils.config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text)).lower()
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _extract_year(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"\((\d{4})\)", str(text))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _candidate_year(movie_info: Dict[str, Any]) -> Optional[int]:
    year = movie_info.get("year")
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit():
        return int(year)
    for key in ("releaseDate", "inCinemas", "physicalRelease"):
        value = movie_info.get(key)
        if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
            return int(value[:4])
    return None


def _candidate_titles(movie_info: Dict[str, Any]) -> List[str]:
    titles: List[str] = []
    for key in ("title", "originalTitle", "sortTitle"):
        value = movie_info.get(key)
        if isinstance(value, str) and value.strip():
            titles.append(value.strip())

    alternate_titles = movie_info.get("alternateTitles")
    if isinstance(alternate_titles, list):
        for alt in alternate_titles:
            if isinstance(alt, dict):
                value = alt.get("title") or alt.get("name")
                if isinstance(value, str) and value.strip():
                    titles.append(value.strip())
            elif isinstance(alt, str) and alt.strip():
                titles.append(alt.strip())

    seen = set()
    deduped: List[str] = []
    for title in titles:
        key = _normalize_text(title)
        if key and key not in seen:
            seen.add(key)
            deduped.append(title)
    return deduped


def _candidate_directors(movie_info: Dict[str, Any]) -> List[str]:
    directors: List[str] = []
    for key in ("director", "directors", "directorName"):
        value = movie_info.get(key)
        if isinstance(value, str) and value.strip():
            directors.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    directors.append(item.strip())
                elif isinstance(item, dict):
                    candidate = item.get("name") or item.get("title")
                    if isinstance(candidate, str) and candidate.strip():
                        directors.append(candidate.strip())
    seen = set()
    deduped: List[str] = []
    for director in directors:
        key = _normalize_text(director)
        if key and key not in seen:
            seen.add(key)
            deduped.append(director)
    return deduped


def _movie_detail_titles(movie: BoxOfficeMovie) -> List[str]:
    """Return all title-like hints we know about for a box-office movie."""
    metadata = dict(getattr(movie, "identity_metadata", {}) or {})
    titles = [
        movie.title,
        movie.original_title,
        metadata.get("original_title"),
        metadata.get("international_title"),
        metadata.get("english_title"),
        metadata.get("detail_original_title"),
        metadata.get("detail_international_title"),
        metadata.get("detail_english_title"),
    ]
    seen: List[str] = []
    result: List[str] = []
    for title in titles:
        if not isinstance(title, str) or not title.strip():
            continue
        normalized = _normalize_text(title)
        if not normalized or normalized in seen:
            continue
        seen.append(normalized)
        result.append(title.strip())
    return result


def _movie_detail_year(movie: BoxOfficeMovie) -> Optional[int]:
    metadata = dict(getattr(movie, "identity_metadata", {}) or {})
    for key in (
        "year",
        "release_year",
        "production_year",
        "detail_year",
    ):
        value = metadata.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    for key in ("release_date_text", "release_date", "detail_release_date"):
        value = metadata.get(key)
        if isinstance(value, str):
            year = _extract_year(value)
            if year is not None:
                return year
    return None


def _best_title_similarity(movie: BoxOfficeMovie, movie_info: Dict[str, Any]) -> float:
    """Return the strongest similarity between box-office and candidate titles."""
    source_titles = _movie_detail_titles(movie)
    candidate_titles = _candidate_titles(movie_info)
    best = 0.0
    for source_title in source_titles:
        source_norm = _normalize_text(source_title)
        if not source_norm:
            continue
        for candidate_title in candidate_titles:
            candidate_norm = _normalize_text(candidate_title)
            if not candidate_norm:
                continue
            if source_norm == candidate_norm:
                return 1.0
            ratio = SequenceMatcher(None, source_norm, candidate_norm).ratio()
            if ratio > best:
                best = ratio
    return round(best, 3)


def _build_search_terms(movie: BoxOfficeMovie, market: str) -> List[str]:
    terms: List[str] = []

    preferred = []
    detail_titles = _movie_detail_titles(movie)
    preferred.extend(detail_titles)

    if market == "fr" and movie.title not in preferred:
        # Prefer the localized French title first for JPBoxOffice FR markets,
        # then fall back to the original/English/detail titles and normalized variants.
        preferred.insert(0, movie.title)
    elif movie.title not in preferred:
        preferred.append(movie.title)

    if movie.original_title and movie.original_title not in preferred:
        preferred.append(movie.original_title)

    detail_year = _movie_detail_year(movie)
    year = detail_year or movie.year
    if year:
        preferred.extend(
            [
                f"{movie.title} ({year})",
                f"{movie.original_title} ({year})" if movie.original_title else None,
            ]
        )

    for term in preferred:
        if isinstance(term, str) and term.strip():
            stripped = term.strip()
            if stripped not in terms:
                terms.append(stripped)
            normalized = _normalize_text(stripped)
            if normalized and normalized not in terms:
                terms.append(normalized)

    return terms


def _score_candidate(
    movie: BoxOfficeMovie, movie_info: Dict[str, Any], search_term: str
) -> float:
    query_texts = [movie.title, movie.original_title, search_term]
    candidate_texts = _candidate_titles(movie_info)
    if not candidate_texts:
        return 0.0

    query_norms = [_normalize_text(text) for text in query_texts if text]
    candidate_norms = [_normalize_text(text) for text in candidate_texts if text]
    query_years = {
        year
        for year in (
            movie.year,
            _extract_year(movie.title),
            _extract_year(movie.original_title),
            _extract_year(search_term),
        )
        if year is not None
    }
    candidate_year = _candidate_year(movie_info)
    source_director = _normalize_text(
        getattr(movie, "identity_metadata", {}).get("director")
    )
    candidate_directors = [
        _normalize_text(value) for value in _candidate_directors(movie_info)
    ]

    best = 0.0
    for query in query_norms:
        for candidate in candidate_norms:
            if not query or not candidate:
                continue
            if query == candidate:
                best = max(best, 1.0)
                continue
            ratio = SequenceMatcher(None, query, candidate).ratio()
            if ratio > best:
                best = ratio

    if candidate_year and query_years:
        if candidate_year in query_years:
            best += 0.08
        else:
            best -= 0.05

    if source_director and candidate_directors:
        if source_director in candidate_directors:
            best += 0.05
        elif any(
            source_director in director or director in source_director
            for director in candidate_directors
            if director
        ):
            best += 0.02

    return max(0.0, min(best, 1.0))


@dataclass
class MovieIdentityResolution:
    """Result of resolving a box office movie to a TMDb/Radarr candidate."""

    matched: bool
    confidence: float = 0.0
    movie_info: Optional[Dict[str, Any]] = None
    search_term: Optional[str] = None
    reason: Optional[str] = None
    searched_terms: List[str] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)


def _search_locale_for_market(market: str) -> Dict[str, Optional[str]]:
    market_key = str(market or "").strip().lower()
    if market_key == "fr":
        return {"language": "fr-FR", "region": "FR"}
    return {"language": None, "region": None}


def _search_with_optional_locale(
    search_movie: Callable[..., List[Dict[str, Any]]],
    term: str,
    *,
    language: Optional[str] = None,
    region: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Call a search function, passing locale kwargs only when supported."""
    try:
        params = signature(search_movie).parameters
    except Exception:
        params = {}

    kwargs: Dict[str, Any] = {}
    if language is not None and (
        "language" in params or any(p.kind == Parameter.VAR_KEYWORD for p in params.values())
    ):
        kwargs["language"] = language
    if region is not None and (
        "region" in params or any(p.kind == Parameter.VAR_KEYWORD for p in params.values())
    ):
        kwargs["region"] = region

    try:
        if kwargs:
            return search_movie(term, **kwargs) or []
    except TypeError:
        # Fall back to the plain call when the callable is stricter than its signature.
        pass
    return search_movie(term) or []


def resolve_movie_identity(
    movie: BoxOfficeMovie,
    search_movie: Callable[[str], List[Dict[str, Any]]],
    market: str = "us",
    min_confidence: float = 0.84,
) -> MovieIdentityResolution:
    """Resolve a box office movie to the most likely TMDb/Radarr candidate.

    The caller provides the Radarr lookup function so this helper can stay pure
    and easy to test. For France, the resolver prefers the original title when
    JPBoxOffice exposes it, then falls back to the localized title and normalized
    variants.
    """

    override = lookup_identity_override(
        market,
        jpboxoffice_id=getattr(movie, "jpboxoffice_id", None),
        title=movie.title,
        year=movie.year or _movie_detail_year(movie),
        base_directory=getattr(settings, "boxarr_data_directory", None),
    )
    if override:
        tmdb_id = override.get("tmdb_id")
        if isinstance(tmdb_id, str) and tmdb_id.isdigit():
            tmdb_id = int(tmdb_id)
        if isinstance(tmdb_id, int):
            resolved_info = {
                "tmdbId": tmdb_id,
                "title": override.get("title") or movie.title,
                "originalTitle": override.get("original_title") or movie.original_title,
                "year": override.get("year") or movie.year or _movie_detail_year(movie),
                "source": "manual_override",
                "notes": override.get("notes"),
            }
            debug = {
                "source_title": movie.title,
                "normalized_source_title": getattr(movie, "normalized_source_title", None)
                or _normalize_text(movie.title),
                "cleaned_title": _normalize_text(movie.title),
                "tmdb_query": None,
                "tmdb_language": _search_locale_for_market(market)["language"],
                "tmdb_region": _search_locale_for_market(market)["region"],
                "candidates": [],
                "selected_candidate": {
                    "tmdbId": tmdb_id,
                    "title": resolved_info["title"],
                    "candidate_localized_title": resolved_info["title"],
                    "candidate_original_title": resolved_info["originalTitle"],
                    "candidate_english_title": resolved_info["title"],
                    "year": resolved_info["year"],
                    "score": 1.0,
                    "search_term": movie.title,
                    "title_similarity": 1.0,
                    "source": "manual_override",
                },
                "title_similarity": 1.0,
                "rejection_reason": None,
                "override": override,
            }
            return MovieIdentityResolution(
                matched=True,
                confidence=1.0,
                movie_info=resolved_info,
                search_term=movie.title,
                reason="manual override",
                searched_terms=[movie.title],
                candidates=[],
                debug=debug,
            )

    terms = _build_search_terms(movie, market)
    locale = _search_locale_for_market(market)
    source_title = movie.title
    cleaned_title = _normalize_text(movie.title)
    normalized_source_title = getattr(movie, "normalized_source_title", None) or cleaned_title
    if not terms:
        return MovieIdentityResolution(
            matched=False,
            reason="no search terms available",
            debug={
                "source_title": source_title,
                "normalized_source_title": normalized_source_title,
                "cleaned_title": cleaned_title,
                "tmdb_language": locale["language"],
                "tmdb_region": locale["region"],
                "tmdb_query": None,
                "candidates": [],
                "selected_candidate": None,
                "rejection_reason": "no search terms available",
            },
        )

    best_movie_info: Optional[Dict[str, Any]] = None
    best_term: Optional[str] = None
    best_score = 0.0
    candidate_log: List[Dict[str, Any]] = []

    logger.debug(
        "Resolving movie identity for '%s' (original='%s', market=%s) with terms=%s",
        movie.title,
        movie.original_title,
        market,
        terms,
    )

    for term in terms:
        try:
            results = _search_with_optional_locale(
                search_movie,
                term,
                language=locale["language"],
                region=locale["region"],
            )
        except Exception as exc:
            logger.debug("TMDb search failed for term '%s': %s", term, exc)
            continue

        if not results:
            logger.debug("TMDb search term '%s' returned no results", term)
            continue

        for movie_info in results:
            if not isinstance(movie_info, dict):
                continue
            score = _score_candidate(movie, movie_info, term)
            movie_director = _normalize_text(
                movie_info.get("director")
                or movie_info.get("directors")
                or movie_info.get("directorName")
            )
            source_director = _normalize_text(
                getattr(movie, "identity_metadata", {}).get("director")
            )
            if movie_director and source_director and movie_director == source_director:
                score = min(1.0, score + 0.05)
            candidate_title = movie_info.get("title") or movie_info.get("originalTitle")
            localized_title = movie_info.get("title")
            original_title = movie_info.get("originalTitle")
            english_title = movie_info.get("englishTitle") or movie_info.get("english_title")
            candidate_log.append(
                {
                    "term": term,
                    "candidate": candidate_title,
                    "candidate_localized_title": localized_title,
                    "candidate_original_title": original_title,
                    "candidate_english_title": english_title,
                    "tmdbId": movie_info.get("tmdbId"),
                    "year": movie_info.get("year"),
                    "director": movie_info.get("director")
                    or movie_info.get("directors")
                    or movie_info.get("directorName"),
                    "score": round(score, 3),
                }
            )
            if score > best_score:
                best_score = score
                best_movie_info = movie_info
                best_term = term

    best_title_similarity = (
        _best_title_similarity(movie, best_movie_info) if best_movie_info else 0.0
    )
    if best_movie_info and best_score >= min_confidence:
        if market_key := str(market or "").strip().lower():
            if market_key == "fr" and best_title_similarity < 0.55:
                reason = "no localized/original title confirmation"
                logger.debug(
                    "Rejecting FR identity for '%s': score=%.3f title_similarity=%.3f",
                    movie.title,
                    best_score,
                    best_title_similarity,
                )
                logger.debug("Movie identity candidate log: %s", candidate_log[:20])
                return MovieIdentityResolution(
                    matched=False,
                    confidence=best_score,
                    movie_info=best_movie_info,
                    search_term=best_term,
                    reason=reason,
                    searched_terms=terms,
                    candidates=candidate_log,
                    debug={
                        "source_title": source_title,
                        "normalized_source_title": normalized_source_title,
                        "cleaned_title": cleaned_title,
                        "tmdb_query": best_term,
                        "tmdb_language": locale["language"],
                        "tmdb_region": locale["region"],
                        "candidates": candidate_log,
                        "selected_candidate": {
                        "tmdbId": best_movie_info.get("tmdbId"),
                        "title": best_movie_info.get("title")
                        or best_movie_info.get("originalTitle"),
                        "candidate_localized_title": best_movie_info.get("title"),
                        "candidate_original_title": best_movie_info.get("originalTitle"),
                        "candidate_english_title": best_movie_info.get("englishTitle")
                        or best_movie_info.get("english_title"),
                        "year": best_movie_info.get("year"),
                        "director": best_movie_info.get("director")
                        or best_movie_info.get("directors")
                        or best_movie_info.get("directorName"),
                            "score": round(best_score, 3),
                            "search_term": best_term,
                            "title_similarity": best_title_similarity,
                        },
                        "title_similarity": best_title_similarity,
                        "rejection_reason": reason,
                    },
                )

        selected_candidate = {
            "tmdbId": best_movie_info.get("tmdbId"),
            "title": best_movie_info.get("title") or best_movie_info.get("originalTitle"),
            "year": best_movie_info.get("year"),
            "director": best_movie_info.get("director")
            or best_movie_info.get("directors")
            or best_movie_info.get("directorName"),
            "score": round(best_score, 3),
            "search_term": best_term,
            "title_similarity": best_title_similarity,
        }
        logger.info(
            "Resolved movie identity '%s' -> tmdbId=%s via term '%s' (confidence=%.2f)",
            movie.title,
            best_movie_info.get("tmdbId"),
            best_term,
            best_score,
        )
        logger.debug("Movie identity candidate log: %s", candidate_log[:20])
        return MovieIdentityResolution(
            matched=True,
            confidence=best_score,
            movie_info=best_movie_info,
            search_term=best_term,
            reason="matched",
            searched_terms=terms,
            candidates=candidate_log,
            debug={
                "source_title": source_title,
                "normalized_source_title": normalized_source_title,
                "cleaned_title": cleaned_title,
                "tmdb_query": best_term,
                "tmdb_language": locale["language"],
                "tmdb_region": locale["region"],
                "candidates": candidate_log,
                "selected_candidate": selected_candidate,
                "title_similarity": best_title_similarity,
                "rejection_reason": None,
            },
        )

    reason = "no candidate above confidence threshold" if best_movie_info else "no candidates found"
    logger.debug(
        "Failed to resolve movie identity '%s' (original='%s'): %s; best_score=%.3f",
        movie.title,
        movie.original_title,
        reason,
        best_score,
    )
    logger.debug("Movie identity candidate log: %s", candidate_log[:20])
    return MovieIdentityResolution(
        matched=False,
        confidence=best_score,
        movie_info=best_movie_info,
        search_term=best_term,
        reason=reason,
        searched_terms=terms,
        candidates=candidate_log,
        debug={
            "source_title": source_title,
            "normalized_source_title": normalized_source_title,
            "cleaned_title": cleaned_title,
            "tmdb_query": best_term,
            "tmdb_language": locale["language"],
            "tmdb_region": locale["region"],
            "candidates": candidate_log,
            "selected_candidate": (
                {
                    "tmdbId": best_movie_info.get("tmdbId"),
                    "title": best_movie_info.get("title") or best_movie_info.get("originalTitle"),
                    "candidate_localized_title": best_movie_info.get("title"),
                    "candidate_original_title": best_movie_info.get("originalTitle"),
                    "candidate_english_title": best_movie_info.get("englishTitle")
                    or best_movie_info.get("english_title"),
                    "year": best_movie_info.get("year"),
                    "score": round(best_score, 3),
                    "search_term": best_term,
                    "title_similarity": best_title_similarity,
                }
                if best_movie_info
                else None
            ),
            "title_similarity": best_title_similarity,
            "rejection_reason": reason,
        },
    )
