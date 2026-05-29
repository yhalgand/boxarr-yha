"""Helpers for resolving a box office movie to a TMDb/Radarr candidate."""

from __future__ import annotations

import re
import unicodedata
from inspect import Parameter, signature
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional

from .boxoffice import BoxOfficeMovie
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


def _build_search_terms(movie: BoxOfficeMovie, market: str) -> List[str]:
    terms: List[str] = []

    preferred = []
    if market == "fr":
        # Prefer the localized French title first for JPBoxOffice FR markets,
        # then fall back to the original/English title and normalized variants.
        preferred.extend([movie.title, movie.original_title])
    else:
        preferred.extend([movie.title, movie.original_title])

    if movie.year:
        preferred.extend(
            [
                f"{movie.title} ({movie.year})",
                f"{movie.original_title} ({movie.year})" if movie.original_title else None,
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

    terms = _build_search_terms(movie, market)
    locale = _search_locale_for_market(market)
    source_title = movie.title
    cleaned_title = _normalize_text(movie.title)
    if not terms:
        return MovieIdentityResolution(
            matched=False,
            reason="no search terms available",
            debug={
                "source_title": source_title,
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
            candidate_title = movie_info.get("title") or movie_info.get("originalTitle")
            candidate_log.append(
                {
                    "term": term,
                    "candidate": candidate_title,
                    "tmdbId": movie_info.get("tmdbId"),
                    "year": movie_info.get("year"),
                    "score": round(score, 3),
                }
            )
            if score > best_score:
                best_score = score
                best_movie_info = movie_info
                best_term = term

    if best_movie_info and best_score >= min_confidence:
        selected_candidate = {
            "tmdbId": best_movie_info.get("tmdbId"),
            "title": best_movie_info.get("title") or best_movie_info.get("originalTitle"),
            "year": best_movie_info.get("year"),
            "score": round(best_score, 3),
            "search_term": best_term,
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
                "cleaned_title": cleaned_title,
                "tmdb_query": best_term,
                "tmdb_language": locale["language"],
                "tmdb_region": locale["region"],
                "candidates": candidate_log,
                "selected_candidate": selected_candidate,
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
            "cleaned_title": cleaned_title,
            "tmdb_query": best_term,
            "tmdb_language": locale["language"],
            "tmdb_region": locale["region"],
            "candidates": candidate_log,
            "selected_candidate": (
                {
                    "tmdbId": best_movie_info.get("tmdbId"),
                    "title": best_movie_info.get("title") or best_movie_info.get("originalTitle"),
                    "year": best_movie_info.get("year"),
                    "score": round(best_score, 3),
                    "search_term": best_term,
                }
                if best_movie_info
                else None
            ),
            "rejection_reason": reason,
        },
    )
