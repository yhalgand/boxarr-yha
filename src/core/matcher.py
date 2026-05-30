"""Movie matching algorithms for finding Radarr movies from box office titles."""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.logger import get_logger
from .boxoffice import BoxOfficeMovie
from .movie_identity import resolve_movie_identity
from .radarr import RadarrMovie

logger = get_logger(__name__)


@dataclass
class MatchResult:
    """Result of movie matching attempt."""

    box_office_movie: BoxOfficeMovie
    radarr_movie: Optional[RadarrMovie] = None
    confidence: float = 0.0
    match_method: str = "none"
    resolved_tmdb_id: Optional[int] = None
    resolved_movie_info: Optional[Dict[str, Any]] = None
    identity_status: str = "Unmatched / needs identity"
    debug: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_matched(self) -> bool:
        """Check if movie was successfully matched."""
        return self.radarr_movie is not None


class MovieMatcher:
    """Service for matching box office titles with Radarr movies."""

    # Common subtitle patterns to remove for matching
    SUBTITLE_PATTERNS = [
        r"\s*:\s*.*$",  # Remove everything after colon
        r"\s*-\s*.*$",  # Remove everything after dash
        r"\s*\(.*?\)",  # Remove parenthetical content
        r"\s*\[.*?\]",  # Remove bracketed content
    ]

    # Roman numerals for sequel detection
    ROMAN_NUMERALS = {
        "I": 1,
        "II": 2,
        "III": 3,
        "IV": 4,
        "V": 5,
        "VI": 6,
        "VII": 7,
        "VIII": 8,
        "IX": 9,
        "X": 10,
    }

    # Number to word mappings for common cases (only cardinal numbers, not ordinals)
    NUMBER_WORDS = {
        "1": "one",
        "2": "two",
        "3": "three",
        "4": "four",
        "5": "five",
        "6": "six",
        "7": "seven",
        "8": "eight",
        "9": "nine",
        "10": "ten",
        "11": "eleven",
        "12": "twelve",
    }

    # Reverse mapping: word to number (only cardinal numbers)
    WORD_TO_NUMBER = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
        "eleven": "11",
        "twelve": "12",
    }

    def __init__(self, min_confidence: float = 0.95):
        """
        Initialize movie matcher.

        Args:
            min_confidence: Minimum confidence threshold for matches
        """
        self.min_confidence = min_confidence
        self._movie_cache: Dict[str, RadarrMovie] = {}
        self._imdb_index: Dict[str, RadarrMovie] = {}
        self._tmdb_index: Dict[int, RadarrMovie] = {}
        self._index_built = False

    def build_movie_index(self, movies: List[RadarrMovie]) -> None:
        """
        Build search index from Radarr movies.

        Args:
            movies: List of Radarr movies
        """
        self._movie_cache.clear()
        self._imdb_index.clear()
        self._tmdb_index.clear()

        for movie in movies:
            if movie.imdbId:
                self._imdb_index[movie.imdbId] = movie
            if getattr(movie, "tmdbId", None):
                try:
                    self._tmdb_index[int(movie.tmdbId)] = movie
                except (TypeError, ValueError):
                    pass

        def _is_sequel(title: str) -> bool:
            # Has trailing number or roman numeral
            has_number = re.search(r"\s+\d+$", title) is not None
            if has_number:
                return True
            # Check for Roman numerals at the end
            words = title.strip().split()
            if words and words[-1].upper() in self.ROMAN_NUMERALS:
                return True
            return False

        for movie in movies:
            # Index by exact title
            self._movie_cache[movie.title.lower()] = movie

            # Index by normalized title
            normalized = self.normalize_title(movie.title)
            self._movie_cache[normalized] = movie

            # Index by title without articles
            no_articles = self.remove_articles(movie.title)
            self._movie_cache[no_articles.lower()] = movie

            # Index by title without subtitle
            base_title = self.get_base_title(movie.title)
            if base_title != movie.title:
                key = base_title.lower()
                existing = self._movie_cache.get(key)
                if existing is None:
                    self._movie_cache[key] = movie
                else:
                    # Prefer non-sequel for the base title mapping
                    if _is_sequel(existing.title) and not _is_sequel(movie.title):
                        self._movie_cache[key] = movie

        logger.info(f"Built movie index with {len(movies)} movies")
        self._index_built = True

    def _is_junk_title(self, title: Optional[str]) -> bool:
        normalized = self.normalize_title(title or "")
        if len(normalized) < 2:
            return True
        if normalized in {"n", "na", "n a", "unknown", "untitled"}:
            return True
        return False

    def _apply_detail_metadata(
        self,
        box_office_movie: BoxOfficeMovie,
        detail_fetcher: Optional[Callable[[Optional[str]], Dict[str, Any]]],
    ) -> None:
        if not detail_fetcher:
            return
        source_href = getattr(box_office_movie, "source_href", None) or getattr(
            box_office_movie, "release_url", None
        )
        if not source_href:
            return
        try:
            detail = detail_fetcher(source_href)
        except Exception as exc:
            logger.debug(
                "Could not enrich JPBoxOffice detail metadata for '%s': %s",
                box_office_movie.title,
                exc,
            )
            return
        if not isinstance(detail, dict) or not detail:
            return
        metadata = getattr(box_office_movie, "identity_metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            box_office_movie.identity_metadata = metadata
        metadata.update(detail)
        for field_name in ("original_title", "international_title", "english_title"):
            value = detail.get(field_name)
            if isinstance(value, str) and value.strip() and not getattr(
                box_office_movie, field_name, None
            ):
                setattr(box_office_movie, field_name, value.strip())
        detail_year = detail.get("year")
        if box_office_movie.year is None and isinstance(detail_year, int):
            box_office_movie.year = detail_year

    def _best_confirmed_radarr_match(
        self,
        box_office_movie: BoxOfficeMovie,
        radarr_movies: List[RadarrMovie],
        search_movie_tmdb: Optional[Callable[..., List[Dict[str, Any]]]],
        detail_fetcher: Optional[Callable[[Optional[str]], Dict[str, Any]]] = None,
    ) -> MatchResult:
        """Strict FR matcher that requires TMDB confirmation before Radarr linkage."""
        debug: Dict[str, Any] = {
            "source_title": box_office_movie.title,
            "cleaned_title": self.normalize_title(box_office_movie.title),
            "tmdb_query": None,
            "tmdb_language": "fr-FR",
            "tmdb_region": "FR",
            "candidates": [],
            "selected_candidate": None,
            "radarr_title": None,
            "rejection_reason": None,
        }

        if search_movie_tmdb is None:
            debug["rejection_reason"] = "missing tmdb search callable"
            return MatchResult(
                box_office_movie=box_office_movie,
                confidence=0.0,
                match_method="none",
                debug=debug,
            )

        self._apply_detail_metadata(box_office_movie, detail_fetcher)
        identity = resolve_movie_identity(
            box_office_movie,
            search_movie_tmdb,
            market="fr",
        )
        debug.update(identity.debug or {})
        debug["candidates"] = identity.debug.get("candidates", [])

        if not identity.matched or not identity.movie_info:
            debug["rejection_reason"] = identity.reason or "tmdb resolution rejected"
            return MatchResult(
                box_office_movie=box_office_movie,
                confidence=0.0,
                match_method="none",
                debug=debug,
            )

        movie_info = identity.movie_info
        try:
            tmdb_id = int(movie_info.get("tmdbId"))
        except (TypeError, ValueError):
            debug["rejection_reason"] = "resolved tmdb candidate missing tmdbId"
            return MatchResult(
                box_office_movie=box_office_movie,
                confidence=0.0,
                match_method="none",
                debug=debug,
            )

        resolved_identity_status = "TMDB confirmed / not in Radarr"
        resolved_match_method = "tmdb_confirmed"
        if identity.reason == "manual override":
            resolved_identity_status = "Manual confirmed / not in Radarr"
            resolved_match_method = "manual_confirmed"

        radarr_movie = self._tmdb_index.get(tmdb_id)
        if not radarr_movie:
            radarr_movie = next(
                (movie for movie in radarr_movies if getattr(movie, "tmdbId", None) == tmdb_id),
                None,
            )
        if not radarr_movie:
            debug["rejection_reason"] = f"tmdbId {tmdb_id} not present in Radarr"
            return MatchResult(
                box_office_movie=box_office_movie,
                confidence=float(identity.confidence or 0.0),
                match_method=resolved_match_method,
                resolved_tmdb_id=tmdb_id,
                resolved_movie_info=movie_info,
                identity_status=resolved_identity_status,
                debug=debug,
            )

        if self._is_junk_title(radarr_movie.title):
            debug["rejection_reason"] = f"junk radarr title '{radarr_movie.title}'"
            return MatchResult(
                box_office_movie=box_office_movie,
                confidence=0.0,
                match_method="none",
                debug=debug,
            )

        title_similarity = float(identity.debug.get("title_similarity") or 0.0)
        confidence = round((float(identity.confidence or 0.0) + title_similarity) / 2, 3)
        selected_candidate = dict(identity.debug.get("selected_candidate") or {})
        selected_candidate.update(
            {
                "radarr_title": radarr_movie.title,
                "radarr_id": radarr_movie.id,
                "confidence": confidence,
            }
        )
        debug["radarr_title"] = radarr_movie.title
        debug["selected_candidate"] = selected_candidate
        debug["rejection_reason"] = None
        return MatchResult(
            box_office_movie=box_office_movie,
            radarr_movie=radarr_movie,
            confidence=confidence,
            match_method=resolved_match_method,
            resolved_tmdb_id=tmdb_id,
            resolved_movie_info=movie_info,
            identity_status="Matched in Radarr",
            debug=debug,
        )

    def normalize_title(self, title: str) -> str:
        """
        Normalize title for matching.

        Args:
            title: Movie title

        Returns:
            Normalized title
        """
        decomposed = unicodedata.normalize("NFKD", title.lower())
        decomposed = "".join(
            char for char in decomposed if not unicodedata.combining(char)
        )
        # Remove non-alphanumeric characters
        normalized = re.sub(r"[^\w\s]", "", decomposed)
        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def remove_articles(self, title: str) -> str:
        """
        Remove leading articles from title.

        Args:
            title: Movie title

        Returns:
            Title without articles
        """
        articles = ["the", "a", "an", "le", "la", "les", "el", "los", "las"]
        words = title.lower().split()

        if words and words[0] in articles:
            return " ".join(words[1:])

        return title.lower()

    def get_base_title(self, title: str) -> str:
        """
        Get base title without subtitle or sequel indicators.

        Args:
            title: Movie title

        Returns:
            Base title
        """
        # Remove common subtitle patterns
        base = title
        for pattern in self.SUBTITLE_PATTERNS:
            base = re.sub(pattern, "", base, flags=re.IGNORECASE)

        # Remove sequel numbers
        base = re.sub(r"\s+\d+$", "", base)

        # Remove Roman numerals
        words = base.split()
        if words and words[-1].upper() in self.ROMAN_NUMERALS:
            base = " ".join(words[:-1])

        return base.strip()

    def extract_year(self, title: str) -> Optional[int]:
        """
        Extract year from title if present.

        Args:
            title: Movie title

        Returns:
            Year or None
        """
        match = re.search(r"\((\d{4})\)", title)
        return int(match.group(1)) if match else None

    def calculate_similarity(self, str1: str, str2: str) -> float:
        """
        Calculate similarity score between two strings.

        Args:
            str1: First string
            str2: Second string

        Returns:
            Similarity score between 0 and 1
        """
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

    def convert_numbers_to_words(self, title: str) -> str:
        """
        Convert numbers in title to word equivalents.

        Args:
            title: Movie title

        Returns:
            Title with numbers converted to words
        """
        import re

        result = title

        # Convert standalone numbers to words
        for num, word in self.NUMBER_WORDS.items():
            # Match number as a whole word (with word boundaries)
            pattern = r"\b" + re.escape(num) + r"\b"
            if re.search(pattern, result):
                result = re.sub(pattern, word, result, flags=re.IGNORECASE)

        return result

    def convert_words_to_numbers(self, title: str) -> str:
        """
        Convert number words in title to digit equivalents.

        Args:
            title: Movie title

        Returns:
            Title with words converted to numbers
        """
        import re

        result = title

        # Convert word numbers to digits
        for word, num in self.WORD_TO_NUMBER.items():
            # Match word as a whole word (with word boundaries)
            pattern = r"\b" + re.escape(word) + r"\b"
            if re.search(pattern, result, re.IGNORECASE):
                result = re.sub(pattern, num, result, flags=re.IGNORECASE)

        return result

    def match_single(
        self, box_office_title: str, radarr_movies: List[RadarrMovie]
    ) -> MatchResult:
        """
        Match a single box office title with Radarr movies.

        Args:
            box_office_title: Title from box office
            radarr_movies: List of Radarr movies

        Returns:
            MatchResult object
        """
        # Create box office movie object
        box_office_movie = BoxOfficeMovie(rank=0, title=box_office_title)

        # Build index if needed
        if not self._index_built:
            self.build_movie_index(radarr_movies)

        # Try exact match
        result = self._try_exact_match(box_office_title)
        if result:
            return MatchResult(
                box_office_movie=box_office_movie,
                radarr_movie=result,
                confidence=1.0,
                match_method="exact",
                resolved_tmdb_id=getattr(result, "tmdbId", None),
                identity_status="Matched in Radarr",
            )

        # Try special cases (sequels, remakes, etc.)
        result = self._try_special_cases(box_office_title, radarr_movies)
        if result:
            return MatchResult(
                box_office_movie=box_office_movie,
                radarr_movie=result,
                confidence=0.85,
                match_method="special",
                resolved_tmdb_id=getattr(result, "tmdbId", None),
                identity_status="Matched in Radarr",
            )

        # Try normalized match (including number conversions)
        result = self._try_normalized_match(box_office_title)
        if result:
            return MatchResult(
                box_office_movie=box_office_movie,
                radarr_movie=result,
                confidence=0.95,
                match_method="normalized",
                resolved_tmdb_id=getattr(result, "tmdbId", None),
                identity_status="Matched in Radarr",
            )

        # Try fuzzy matching
        result, confidence = self._try_fuzzy_match(box_office_title, radarr_movies)
        if result and confidence >= self.min_confidence:
            return MatchResult(
                box_office_movie=box_office_movie,
                radarr_movie=result,
                confidence=confidence,
                match_method="fuzzy",
                resolved_tmdb_id=getattr(result, "tmdbId", None),
                identity_status="Matched in Radarr",
            )

        # No match found
        return MatchResult(
            box_office_movie=box_office_movie,
            radarr_movie=None,
            confidence=0.0,
            match_method="none",
            identity_status="Unmatched / needs identity",
        )

    def _match_title_variants(
        self,
        box_office_movie: BoxOfficeMovie,
        radarr_movies: List[RadarrMovie],
        title_variants: List[str],
    ) -> MatchResult:
        """Try a set of title variants and keep the best match."""
        best_result: Optional[MatchResult] = None
        for title in title_variants:
            if not title:
                continue
            result = self.match_single(title, radarr_movies)
            if not best_result or result.confidence > best_result.confidence:
                best_result = result
        if not best_result:
            return MatchResult(
                box_office_movie=box_office_movie,
                radarr_movie=None,
                confidence=0.0,
                match_method="none",
            )
        best_result.box_office_movie = box_office_movie
        return best_result

    def _try_imdb_match(self, imdb_id: Optional[str]) -> Optional[RadarrMovie]:
        """Try matching by IMDb ID."""
        if not imdb_id:
            return None
        return self._imdb_index.get(imdb_id)

    def _try_exact_match(self, title: str) -> Optional[RadarrMovie]:
        """Try exact title match."""
        return self._movie_cache.get(title.lower())

    def _try_normalized_match(self, title: str) -> Optional[RadarrMovie]:
        """Try normalized title match."""
        normalized = self.normalize_title(title)

        # Try normalized title
        if normalized in self._movie_cache:
            return self._movie_cache[normalized]

        # Try without articles
        no_articles = self.remove_articles(title)
        if no_articles in self._movie_cache:
            return self._movie_cache[no_articles]

        # Try replacing trailing Roman numerals with numbers and re-check
        title_upper = title.upper()
        for numeral in sorted(self.ROMAN_NUMERALS.keys(), key=len, reverse=True):
            if title_upper.endswith(f" {numeral}"):
                replaced = re.sub(
                    rf"\b{numeral}\b",
                    str(self.ROMAN_NUMERALS[numeral]),
                    title_upper,
                    flags=re.IGNORECASE,
                )
                alt_norm = self.normalize_title(replaced)
                if alt_norm in self._movie_cache:
                    return self._movie_cache[alt_norm]

        # Try base title
        base_title = self.get_base_title(title)
        if base_title.lower() in self._movie_cache:
            return self._movie_cache[base_title.lower()]

        # Try converting numbers to words and vice versa
        # This handles cases like "The Fantastic Four" vs "The Fantastic 4"
        title_with_numbers = self.convert_words_to_numbers(title)
        if title_with_numbers != title:
            # Try exact match with converted title
            if title_with_numbers.lower() in self._movie_cache:
                return self._movie_cache[title_with_numbers.lower()]

            # Try normalized match with converted title
            normalized_numbers = self.normalize_title(title_with_numbers)
            if normalized_numbers in self._movie_cache:
                return self._movie_cache[normalized_numbers]

        title_with_words = self.convert_numbers_to_words(title)
        if title_with_words != title:
            # Try exact match with converted title
            if title_with_words.lower() in self._movie_cache:
                return self._movie_cache[title_with_words.lower()]

            # Try normalized match with converted title
            normalized_words = self.normalize_title(title_with_words)
            if normalized_words in self._movie_cache:
                return self._movie_cache[normalized_words]

        return None

    def _try_fuzzy_match(
        self, title: str, radarr_movies: List[RadarrMovie]
    ) -> Tuple[Optional[RadarrMovie], float]:
        """
        Try fuzzy string matching.

        Returns:
            Tuple of (matched movie, confidence score)
        """
        best_match = None
        best_score = 0.0

        normalized_title = self.normalize_title(title)

        for movie in radarr_movies:
            # Calculate various similarity scores
            exact_score = self.calculate_similarity(title, movie.title)
            normalized_score = self.calculate_similarity(
                normalized_title, self.normalize_title(movie.title)
            )
            base_score = self.calculate_similarity(
                self.get_base_title(title), self.get_base_title(movie.title)
            )

            # Take the highest score
            score = max(exact_score, normalized_score, base_score)

            # Bonus for year match
            box_year = self.extract_year(title)
            if box_year and movie.year == box_year:
                score += 0.1

            if score > best_score:
                best_score = score
                best_match = movie

        return best_match, best_score

    def _try_special_cases(
        self, title: str, radarr_movies: List[RadarrMovie]
    ) -> Optional[RadarrMovie]:
        """
        Handle special cases like sequels with different naming.

        Args:
            title: Box office title
            radarr_movies: List of Radarr movies

        Returns:
            Matched movie or None
        """
        # Handle "Movie: Subtitle" vs "Movie Subtitle"
        if ":" in title:
            no_colon = title.replace(":", "").replace("  ", " ")
            result = self._try_normalized_match(no_colon)
            if result:
                return result

        # Handle year in title
        year_match = re.search(r"\((\d{4})\)", title)
        if year_match:
            year = int(year_match.group(1))
            title_no_year = re.sub(r"\s*\(\d{4}\)", "", title)

            for movie in radarr_movies:
                if (
                    movie.year == year
                    and self.calculate_similarity(title_no_year, movie.title) > 0.8
                ):
                    return movie

        # Handle Roman numeral sequels
        for numeral, value in self.ROMAN_NUMERALS.items():
            if f" {numeral}" in title.upper() or title.upper().endswith(numeral):
                # Try replacing with number
                title_with_number = re.sub(
                    rf"\b{numeral}\b", str(value), title, flags=re.IGNORECASE
                )
                # Prefer exact/normalized equality to sequel title
                norm_target = self.normalize_title(title_with_number)
                for m in radarr_movies:
                    if self.normalize_title(m.title) == norm_target:
                        return m
                result = self._try_normalized_match(title_with_number)
                if result:
                    return result

        return None

    def match_batch(
        self, box_office_movies: List[BoxOfficeMovie], radarr_movies: List[RadarrMovie]
    ) -> List[MatchResult]:
        """
        Match multiple box office movies with Radarr library.

        Args:
            box_office_movies: List of box office movies
            radarr_movies: List of Radarr movies

        Returns:
            List of MatchResult objects
        """
        # Build index once for efficiency
        self.build_movie_index(radarr_movies)

        results = []
        for box_movie in box_office_movies:
            match_result = self.match_movie(box_movie, radarr_movies)
            results.append(match_result)

            if match_result.is_matched:
                logger.debug(
                    f"Matched '{box_movie.title}' to '{match_result.radarr_movie.title}' "
                    f"(confidence: {match_result.confidence:.2f}, method: {match_result.match_method})"
                )
            else:
                logger.debug(f"No match found for '{box_movie.title}'")

        matched_count = sum(1 for r in results if r.is_matched)
        logger.info(
            f"Matched {matched_count}/{len(box_office_movies)} box office movies"
        )

        return results

    def match_movie(
        self,
        box_office_movie: BoxOfficeMovie,
        radarr_movies: List[RadarrMovie],
        market: Optional[str] = None,
        search_movie_tmdb: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        detail_fetcher: Optional[Callable[[Optional[str]], Dict[str, Any]]] = None,
    ) -> MatchResult:
        """
        Alias for match_single to maintain compatibility with routes.

        Args:
            box_office_movie: Box office movie to match
            radarr_movies: List of Radarr movies

        Returns:
            MatchResult object
        """
        # Build index if needed
        if not self._index_built:
            self.build_movie_index(radarr_movies)

        if market == "fr":
            return self._best_confirmed_radarr_match(
                box_office_movie,
                radarr_movies,
                search_movie_tmdb,
                detail_fetcher=detail_fetcher,
            )

        # Try IMDb match first (language-agnostic)
        imdb_match = self._try_imdb_match(box_office_movie.imdb_id)
        if imdb_match:
            return MatchResult(
                box_office_movie=box_office_movie,
                radarr_movie=imdb_match,
                confidence=1.0,
                match_method="imdb_id",
                resolved_tmdb_id=getattr(imdb_match, "tmdbId", None),
                identity_status="Matched in Radarr",
            )

        # Fall back to title matching, preferring the original title when available.
        title_variants = [box_office_movie.title]
        if box_office_movie.original_title and box_office_movie.original_title not in title_variants:
            title_variants.append(box_office_movie.original_title)
        if box_office_movie.year:
            year_variants = [
                f"{box_office_movie.title} ({box_office_movie.year})",
            ]
            if box_office_movie.original_title:
                year_variants.append(
                    f"{box_office_movie.original_title} ({box_office_movie.year})"
                )
            for variant in year_variants:
                if variant not in title_variants:
                    title_variants.append(variant)

        result = self._match_title_variants(
            box_office_movie, radarr_movies, title_variants
        )
        return result

    def match_movies(
        self,
        box_office_movies: List[BoxOfficeMovie],
        radarr_movies: List[RadarrMovie],
        market: Optional[str] = None,
        search_movie_tmdb: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        detail_fetcher: Optional[Callable[[Optional[str]], Dict[str, Any]]] = None,
    ) -> List[MatchResult]:
        """
        Alias for match_batch to maintain compatibility with routes.

        Args:
            box_office_movies: List of box office movies
            radarr_movies: List of Radarr movies

        Returns:
            List of MatchResult objects
        """
        if market is None and search_movie_tmdb is None:
            return self.match_batch(box_office_movies, radarr_movies)

        self.build_movie_index(radarr_movies)
        results = []
        for box_movie in box_office_movies:
            match_result = self.match_movie(
                box_movie,
                radarr_movies,
                market=market,
                search_movie_tmdb=search_movie_tmdb,
                detail_fetcher=detail_fetcher,
            )
            results.append(match_result)

            if match_result.is_matched:
                logger.debug(
                    f"Matched '{box_movie.title}' to '{match_result.radarr_movie.title}' "
                    f"(confidence: {match_result.confidence:.2f}, method: {match_result.match_method})"
                )
            else:
                logger.debug(f"No match found for '{box_movie.title}'")

        matched_count = sum(1 for r in results if r.is_matched)
        logger.info(
            f"Matched {matched_count}/{len(box_office_movies)} box office movies"
        )
        return results
