"""Box office providers and compatibility service facade."""

from __future__ import annotations

import re
import random
import time
from pathlib import Path
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from ..utils.logger import get_logger
from .history_sanitizer import normalize_title_key
from .boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    BoxOfficeProvider,
    get_jpboxoffice_country_spec,
    market_for_provider,
    normalize_market,
    normalize_provider,
    normalize_provider_config,
    provider_for_market,
)
from .exceptions import BoxOfficeError

logger = get_logger(__name__)


@dataclass
class BoxOfficeMovie:
    """Represents a movie in the box office rankings."""

    rank: int
    title: str
    # For mojo_us this is weekend gross in USD.
    # For jpboxoffice_fr this is weekend admissions/entries.
    weekend_gross: Optional[float] = None
    # For mojo_us this is cumulative USD gross.
    # For jpboxoffice_fr this is cumulative admissions/entries.
    total_gross: Optional[float] = None
    weeks_released: Optional[int] = None
    theater_count: Optional[int] = None
    original_title: Optional[str] = None
    year: Optional[int] = None
    imdb_id: Optional[str] = None
    release_url: Optional[str] = None
    source_href: Optional[str] = None
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    normalized_source_title: Optional[str] = None
    market: Optional[str] = None
    country: Optional[str] = None
    jpboxoffice_id: Optional[int] = None
    allocine_movie_id: Optional[int] = None
    identity_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class MojoUSProvider(BoxOfficeProvider):
    """Box Office Mojo provider family.

    ``market=us`` currently uses ``provider=mojo`` with ``area=us``.
    ``mojo_us`` remains a compatibility alias and resolves to the same
    implementation.
    """

    provider_key = "mojo"
    BASE_URL = "https://www.boxofficemojo.com"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        provider_config: Optional[Dict[str, object]] = None,
    ):
        super().__init__(
            http_client
            or httpx.Client(
                headers={"User-Agent": self.USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
        )
        self.provider_config = normalize_provider_config("mojo", provider_config)
        self.area = str(self.provider_config.get("area", "us")).strip().lower()
        if self.area != "us":
            raise BoxOfficeError(
                f"BoxOffice Mojo area '{self.area}' is not implemented yet"
            )

    def close(self) -> None:
        if self.client:
            self.client.close()

    def parse_money_value(self, text: str) -> Optional[float]:
        """Parse a monetary value from a string."""
        if not text or not isinstance(text, str):
            return None

        try:
            clean_text = re.sub(r"[$,\s]", "", text)
            parts = clean_text.split(".")
            if len(parts) > 2:
                clean_text = parts[0] + "." + "".join(parts[1:])
            return float(clean_text) if clean_text and clean_text != "." else None
        except ValueError:
            return None

    def parse_integer_value(self, text: str) -> Optional[int]:
        """Parse an integer value from a string."""
        if not text:
            return None

        try:
            clean_text = re.sub(r"[^\d-]", "", text)
            return int(clean_text) if clean_text else None
        except (ValueError, AttributeError):
            return None

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        """Fetch box office data from Box Office Mojo US."""
        if year is None or week is None:
            _, _, year, week = self.get_weekend_dates()

        url = f"{self.BASE_URL}/weekend/{year}W{week:02d}/"
        logger.info(f"Fetching box office data from: {url}")

        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch box office data: {e}")
            raise BoxOfficeError(f"Failed to fetch box office data: {e}") from e
        except Exception as e:
            logger.error(f"Failed to fetch box office data: {e}")
            raise BoxOfficeError(f"Failed to fetch box office data: {e}") from e

        movies = self.parse_box_office_html(response.text, limit=limit)
        self.enrich_with_imdb_ids(movies)
        return movies

    def parse_box_office_html(
        self, html: str, limit: int = 10
    ) -> List[BoxOfficeMovie]:  # noqa: C901
        """Parse a Box Office Mojo HTML page."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            movies: List[BoxOfficeMovie] = []

            table = soup.find("table", class_="a-bordered")
            if not table:
                return self._parse_alternative_format(html, limit=limit)

            rows = table.find_all("tr")[1:] if hasattr(table, "find_all") else []

            for idx, row in enumerate(rows[:limit], start=1):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue

                title_cell = cells[2] if len(cells) > 2 else None
                if not title_cell:
                    continue
                title_link = title_cell.find("a")
                if not title_link:
                    continue

                title = title_link.get_text(strip=True)
                href = str(title_link.get("href", ""))
                release_url = href if href.startswith("/release/") else None

                if self._is_studio_name(title):
                    continue

                weekend_gross = None
                total_gross = None
                weeks_released = None
                theater_count = None

                if len(cells) >= 4:
                    weekend_gross = self.parse_money_value(cells[3].get_text(strip=True))
                if len(cells) >= 7:
                    theater_count = self.parse_integer_value(cells[6].get_text(strip=True))
                if len(cells) >= 8:
                    total_gross = self.parse_money_value(cells[7].get_text(strip=True))
                if len(cells) >= 10:
                    weeks_released = self.parse_integer_value(
                        cells[9].get_text(strip=True)
                    )

                movie = BoxOfficeMovie(
                    rank=len(movies) + 1,
                    title=title,
                    weekend_gross=weekend_gross,
                    total_gross=total_gross,
                    weeks_released=weeks_released,
                    theater_count=theater_count,
                    release_url=release_url,
                    normalized_source_title=normalize_title_key(title),
                )
                movies.append(movie)
                logger.debug(f"Parsed movie: {movie}")

            if not movies:
                raise BoxOfficeError("No movies found in box office data")

            logger.info(f"Successfully parsed {len(movies)} movies from box office")
            return movies
        except Exception as e:
            logger.error(f"Failed to parse box office HTML: {e}")
            raise BoxOfficeError(f"Failed to parse box office data: {e}") from e

    def _parse_alternative_format(
        self, html: str, limit: int = 10
    ) -> List[BoxOfficeMovie]:
        """Fallback parser for alternate Box Office Mojo page layouts."""
        pattern = r'(/release/rl\d+/)[^"]*">([^<]+)</a>'
        matches = re.findall(pattern, html)

        movies = []
        rank = 1

        for release_url, title in matches:
            if self._is_studio_name(title):
                continue

            movie = BoxOfficeMovie(rank=rank, title=title, release_url=release_url)
            movie.normalized_source_title = normalize_title_key(title)
            movies.append(movie)
            rank += 1

            if rank > limit:
                break

        if not movies:
            raise BoxOfficeError("No movies found using alternative parsing")

        logger.info(f"Parsed {len(movies)} movies using alternative method")
        return movies

    def extract_imdb_id(self, release_url: str) -> Optional[str]:
        """Fetch a release page and extract the IMDb ID."""
        try:
            url = f"{self.BASE_URL}{release_url}"
            response = self.client.get(url)
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Failed to fetch release page {release_url}: {e}")
            return None

        imdb_match = re.search(r"pro\.imdb\.com/title/(tt\d+)/", response.text)
        result = imdb_match.group(1) if imdb_match else None
        if not result:
            logger.debug(f"No IMDb ID found on {release_url}")
        return result

    def enrich_with_imdb_ids(self, movies: List["BoxOfficeMovie"]) -> None:
        """Enrich movies in-place with IMDb IDs."""
        count = 0
        for movie in movies:
            if not movie.release_url:
                continue
            imdb_id = self.extract_imdb_id(movie.release_url)
            if imdb_id:
                movie.imdb_id = imdb_id
                count += 1
        logger.info(f"Enriched {count}/{len(movies)} movies with IMDb IDs")

    def _is_studio_name(self, text: str) -> bool:
        """Check whether a title looks like a studio name."""
        studio_keywords = [
            "Pictures",
            "Studios",
            "Films",
            "Entertainment",
            "Releasing",
            "Distribution",
            "Productions",
            "Company",
        ]
        return any(keyword.lower() in text.lower() for keyword in studio_keywords)


class AllocineFRProvider(BoxOfficeProvider):
    """AlloCiné France weekly box-office provider."""

    provider_key = "allocine"
    BASE_URL = "https://www.allocine.fr"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 Boxarr/1.7.0"
    )
    REQUEST_TIMEOUT = 20.0
    DETAIL_REQUEST_TIMEOUT = 8.0

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        provider_config: Optional[Dict[str, object]] = None,
    ):
        super().__init__(
            http_client
            or httpx.Client(
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.REQUEST_TIMEOUT,
                follow_redirects=True,
            )
        )
        self.provider_config = normalize_provider_config("allocine", provider_config)
        self.country = str(self.provider_config.get("country", "fr")).strip().lower()
        if self.country != "fr":
            raise BoxOfficeError(
                f"AlloCiné country '{self.country}' is not implemented yet"
            )
        self.min_entries = int(self.provider_config.get("min_entries", 10) or 10)
        self.last_parse_diagnostics: Dict[str, Any] = {}
        self.last_resolution_diagnostics: Dict[str, Any] = {}
        self._detail_metadata_cache: Dict[str, Dict[str, Any]] = {}

    def close(self) -> None:
        if self.client:
            self.client.close()

    def _week_start_for_iso_week(self, year: int, week: int) -> datetime:
        try:
            return datetime.fromisocalendar(year, week, 3)
        except ValueError as exc:
            raise BoxOfficeError(f"Invalid AlloCiné week {year}W{week:02d}") from exc

    def _week_url_for_start(self, week_start: datetime) -> str:
        return f"{self.BASE_URL}/boxoffice/france/sem-{week_start:%Y-%m-%d}/"

    def _fetch_html(self, url: str) -> str:
        logger.info(f"Fetching AlloCiné data from: {url}")
        try:
            response = self.client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            raise BoxOfficeError(f"Failed to fetch AlloCiné data: {exc}") from exc
        except Exception as exc:
            raise BoxOfficeError(f"Failed to fetch AlloCiné data: {exc}") from exc

    def _normalize_space(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

    def _parse_int(self, text: str, *, first_only: bool = False) -> Optional[int]:
        if not text:
            return None
        matches = re.findall(r"\d[\d\s.]*", text)
        if not matches:
            return None
        raw = matches[0] if first_only else matches[-1]
        digits = re.sub(r"\D", "", raw)
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    def _extract_allocine_id(self, href: Optional[str]) -> Optional[int]:
        if not href:
            return None
        match = re.search(r"(?:film|video)-(\d+)|cfilm=(\d+)", href)
        if not match:
            return None
        try:
            return int(match.group(1) or match.group(2))
        except ValueError:
            return None

    def _detail_url(self, release_url: Optional[str]) -> Optional[str]:
        if not release_url:
            return None
        if release_url.startswith("http"):
            return release_url
        return f"{self.BASE_URL}/{release_url.lstrip('/')}"

    def _clean_detail_title(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        text = self._normalize_space(value)
        text = re.sub(r"\s*-\s*(?:film|AlloCiné).*$", "", text, flags=re.IGNORECASE)
        return text.strip() or None

    def extract_detail_metadata(self, release_url: Optional[str]) -> Dict[str, Any]:
        """Extract title/year hints from an AlloCiné movie detail page.

        AlloCiné weekly rows are localized. The detail page often exposes the
        original title, release year, director, and occasionally external IDs;
        those fields materially improve strict TMDB confirmation for FR.
        """
        detail_url = self._detail_url(release_url)
        if not detail_url:
            return {}
        if detail_url in self._detail_metadata_cache:
            return dict(self._detail_metadata_cache[detail_url])

        try:
            try:
                response = self.client.get(detail_url, timeout=self.DETAIL_REQUEST_TIMEOUT)
            except TypeError:
                response = self.client.get(detail_url)
            response.raise_for_status()
        except Exception as exc:
            logger.debug("Failed to fetch AlloCiné detail page %s: %s", detail_url, exc)
            self._detail_metadata_cache[detail_url] = {}
            return {}

        html = response.text or ""
        soup = BeautifulSoup(html, "html.parser")
        page_text = self._normalize_space(" ".join(soup.stripped_strings))
        metadata: Dict[str, Any] = {
            "source_provider": "allocine",
            "source_href": release_url,
            "source_url": detail_url,
            "allocine_movie_id": self._extract_allocine_id(release_url),
        }

        title = None
        for selector in ("meta[property='og:title']", "h1", "title"):
            node = soup.select_one(selector)
            if not node:
                continue
            value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
            title = self._clean_detail_title(value)
            if title:
                metadata["detail_title"] = title
                break

        # JSON-LD is the most stable source when present.
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text("", strip=True)
            if not raw:
                continue
            try:
                import json as _json

                parsed = _json.loads(raw)
            except Exception:
                continue
            candidates = parsed if isinstance(parsed, list) else [parsed]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                name = self._clean_detail_title(item.get("name"))
                if name and "detail_title" not in metadata:
                    metadata["detail_title"] = name
                original = self._clean_detail_title(
                    item.get("alternateName") or item.get("originalTitle")
                )
                if original:
                    metadata["original_title"] = original
                date_published = item.get("datePublished") or item.get("releasedEvent")
                if isinstance(date_published, str):
                    year_match = re.search(r"(19|20)\d{2}", date_published)
                    if year_match:
                        metadata["year"] = int(year_match.group(0))
                director = item.get("director")
                if isinstance(director, dict):
                    name = director.get("name")
                    if isinstance(name, str) and name.strip():
                        metadata["director"] = self._normalize_space(name)
                elif isinstance(director, list):
                    names = [
                        self._normalize_space(entry.get("name"))
                        for entry in director
                        if isinstance(entry, dict) and entry.get("name")
                    ]
                    if names:
                        metadata["director"] = names[0]

        label_patterns = [
            (r"Titre\s+original\s+([A-Za-z0-9À-ÿ][^|]+?)(?:\s+Date de sortie|\s+Réalisé par|\s+De\s+|\s+Avec\s+|\s+Nationalité|\s+Presse|\s+Spectateurs|$)", "original_title"),
            (r"Titre\s+anglais\s+([A-Za-z0-9À-ÿ][^|]+?)(?:\s+Date de sortie|\s+Réalisé par|\s+De\s+|\s+Avec\s+|\s+Nationalité|\s+Presse|\s+Spectateurs|$)", "english_title"),
            (r"Date\s+de\s+sortie\s+([^|]+?)(?:\s+en salle|\s+Réalisé par|\s+De\s+|\s+Avec\s+|\s+Nationalité|$)", "release_date_text"),
            (r"(?:Réalisé par|De)\s+([^|]+?)(?:\s+Avec\s+|\s+Nationalité|\s+Presse|\s+Spectateurs|$)", "director"),
            (r"Nationalité\s+([^|]+?)(?:\s+Presse|\s+Spectateurs|\s+Voir sur|$)", "country_name"),
        ]
        for pattern, key in label_patterns:
            if key in metadata:
                continue
            match = re.search(pattern, page_text, flags=re.IGNORECASE)
            if match:
                value = self._normalize_space(match.group(1))
                if value:
                    metadata[key] = value

        for key, pattern in {
            "imdb_id": r"imdb\.com/title/(tt\d+)",
            "tmdb_id": r"themoviedb\.org/movie/(\d+)",
        }.items():
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                metadata[key] = int(match.group(1)) if key == "tmdb_id" else match.group(1)

        year_source = (
            metadata.get("release_date_text")
            or metadata.get("detail_title")
            or page_text[:500]
        )
        if isinstance(year_source, str) and "year" not in metadata:
            year_match = re.search(r"(19|20)\d{2}", year_source)
            if year_match:
                metadata["year"] = int(year_match.group(0))

        for title_key in ("original_title", "english_title", "detail_title"):
            value = metadata.get(title_key)
            if isinstance(value, str):
                cleaned = self._clean_detail_title(value)
                if cleaned:
                    metadata[title_key] = cleaned
                else:
                    metadata.pop(title_key, None)

        self._detail_metadata_cache[detail_url] = dict(metadata)
        return metadata

    def _extract_weekly_admissions(self, node, anchor) -> Optional[int]:
        cells = node.find_all(["td", "th"], recursive=False)
        if cells:
            title_index = None
            for index, cell in enumerate(cells):
                if anchor in cell.find_all("a", href=True) or cell.find("a", href=True) is anchor:
                    title_index = index
                    break
            search_cells = cells[(title_index + 1) :] if title_index is not None else cells
            for cell in search_cells:
                value = self._parse_int(cell.get_text(" ", strip=True), first_only=True)
                if value is not None:
                    return value

        text = self._normalize_space(node.get_text(" ", strip=True))
        numbers = re.findall(r"\d[\d\s.]*", text)
        parsed = []
        for number in numbers:
            value = self._parse_int(number, first_only=True)
            if value is not None:
                parsed.append(value)
        # Skip likely rank/year values and keep the first admissions-like value.
        for value in parsed:
            if value >= 100:
                return value
        return parsed[0] if parsed else None

    def _extract_page_week_start(self, html: str) -> Optional[datetime]:
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for selector in ("title", "h1", "h2"):
            node = soup.find(selector)
            if node:
                candidates.append(self._normalize_space(node.get_text(" ", strip=True)))
        candidates.append(self._normalize_space(soup.get_text(" ", strip=True)[:1200]))
        month_map = {
            "janvier": 1,
            "février": 2,
            "fevrier": 2,
            "mars": 3,
            "avril": 4,
            "mai": 5,
            "juin": 6,
            "juillet": 7,
            "août": 8,
            "aout": 8,
            "septembre": 9,
            "octobre": 10,
            "novembre": 11,
            "décembre": 12,
            "decembre": 12,
        }
        pattern = re.compile(
            r"Semaine\s+du\s+(?:(?:[A-Za-zÀ-ÿ]+)\s+)?(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})",
            re.IGNORECASE,
        )
        for candidate in candidates:
            match = pattern.search(candidate)
            if not match:
                continue
            month = month_map.get(match.group(2).strip().lower())
            if not month:
                continue
            try:
                return datetime(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                continue
        return None

    def _row_candidates(self, soup: BeautifulSoup) -> List:
        rows = []
        for row in soup.find_all("tr"):
            if row.find("a", href=re.compile(r"/film/|film-")):
                rows.append(row)
        if rows:
            return rows

        candidates = []
        for node in soup.find_all(["li", "div", "article"]):
            text = self._normalize_space(node.get_text(" ", strip=True))
            if not text:
                continue
            if node.find("a", href=re.compile(r"/film/|film-")) and re.search(
                r"\b\d[\d\s.]*\b", text
            ):
                candidates.append(node)
        return candidates

    def _parse_row(self, node, rank: int, source_url: str, week_start: datetime) -> Optional[BoxOfficeMovie]:
        anchor = node.find("a", href=re.compile(r"/film/|film-"))
        if anchor is None:
            return None
        title = self._normalize_space(anchor.get_text(" ", strip=True))
        if not title or title.lower() in {"film", "titre"}:
            return None
        href = str(anchor.get("href", ""))
        source_href = href if href.startswith("/") else f"/{href.lstrip('/')}"
        admissions = self._extract_weekly_admissions(node, anchor)
        allocine_movie_id = self._extract_allocine_id(source_href)
        return BoxOfficeMovie(
            rank=rank,
            title=title,
            weekend_gross=admissions,
            release_url=source_href,
            source_href=source_href,
            source_url=source_url,
            source_title=title,
            normalized_source_title=normalize_title_key(title),
            market="fr",
            country="fr",
            allocine_movie_id=allocine_movie_id,
            identity_metadata={
                "source_provider": "allocine",
                "allocine_movie_id": allocine_movie_id,
                "source_week_start_date": week_start.date().isoformat(),
                "source_week_end_date": (week_start + timedelta(days=6)).date().isoformat(),
                "metric": "admissions",
            },
        )

    def _parse_weekly_page(
        self, html: str, *, source_url: str, week_start: datetime, limit: int
    ) -> List[BoxOfficeMovie]:
        soup = BeautifulSoup(html, "html.parser")
        rows = self._row_candidates(soup)
        movies: List[BoxOfficeMovie] = []
        skipped = []
        seen_titles = set()
        for node in rows:
            if len(movies) >= limit:
                break
            movie = self._parse_row(node, len(movies) + 1, source_url, week_start)
            if movie is None:
                skipped.append(self._normalize_space(node.get_text(" ", strip=True))[:200])
                continue
            key = normalize_title_key(movie.title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
            movies.append(movie)

        self.last_parse_diagnostics = {
            "source_url": source_url,
            "provider": "allocine",
            "country": "fr",
            "requested_limit": limit,
            "rows_seen": len(rows),
            "rows_parsed": len(movies),
            "rows_skipped": len(skipped),
            "skipped_rows": skipped,
        }
        if len(movies) < min(limit, self.min_entries):
            raise BoxOfficeError(
                "AlloCiné parse error: insufficient ranking rows "
                f"(source_url={source_url}, rows_seen={len(rows)}, "
                f"rows_parsed={len(movies)}, requested_limit={limit}, "
                f"min_entries={self.min_entries})"
            )
        return movies

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        if year is None or week is None:
            _, _, year, week = self.get_weekend_dates()
        week_start = self._week_start_for_iso_week(year, week)
        if week_start.weekday() != 2:
            raise BoxOfficeError("AlloCiné box-office weeks must start on Wednesday")
        url = self._week_url_for_start(week_start)
        html = self._fetch_html(url)
        actual_start = self._extract_page_week_start(html)
        self.last_resolution_diagnostics = {
            "source_url": url,
            "requested_year": year,
            "requested_week": week,
            "expected_start_date": week_start.date().isoformat(),
            "actual_start_date": actual_start.date().isoformat() if actual_start else None,
        }
        if actual_start and actual_start.date() != week_start.date():
            raise BoxOfficeError(
                "AlloCiné explicit week mismatch: "
                f"source_url={url} requested={year}W{week:02d} "
                f"expected_start={week_start.date().isoformat()} "
                f"actual_start={actual_start.date().isoformat()}"
            )
        return self._parse_weekly_page(
            html,
            source_url=url,
            week_start=week_start,
            limit=limit,
        )


class FranceBoxOfficeProvider(BoxOfficeProvider):
    """France provider wrapper: AlloCiné primary, JPBoxOffice fallback."""

    provider_key = "france_boxoffice"

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        provider_config: Optional[Dict[str, object]] = None,
    ):
        super().__init__(
            http_client
            or httpx.Client(
                headers={"User-Agent": AllocineFRProvider.USER_AGENT},
                timeout=AllocineFRProvider.REQUEST_TIMEOUT,
                follow_redirects=True,
            )
        )
        self.provider_config = normalize_provider_config("france_boxoffice", provider_config)
        if str(self.provider_config.get("country", "fr")).strip().lower() != "fr":
            raise BoxOfficeError("france_boxoffice only supports country 'fr'")
        self.primary = AllocineFRProvider(
            http_client=self.client,
            provider_config={"country": "fr", "min_entries": self.provider_config.get("min_entries", 10)},
        )
        self.fallback = JPBoxOfficeProvider(
            http_client=self.client,
            provider_config={"country": "fr"},
        )
        self.last_provider_used: Optional[str] = None
        self.last_provider_errors: List[Dict[str, str]] = []
        self.last_parse_diagnostics: Dict[str, Any] = {}
        self.last_resolution_diagnostics: Dict[str, Any] = {}

    def close(self) -> None:
        if self.client:
            self.client.close()

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        errors: List[Dict[str, str]] = []
        for provider in (self.primary, self.fallback):
            try:
                movies = provider.fetch_weekend_box_office(year, week, limit=limit)
                self.last_provider_used = provider.provider_key
                self.last_provider_errors = errors
                self.last_parse_diagnostics = dict(
                    getattr(provider, "last_parse_diagnostics", {}) or {}
                )
                self.last_resolution_diagnostics = dict(
                    getattr(provider, "last_resolution_diagnostics", {}) or {}
                )
                return movies
            except BoxOfficeError as exc:
                errors.append({"provider": provider.provider_key, "error": str(exc)})
                logger.warning(
                    "France provider %s failed for %sW%s: %s",
                    provider.provider_key,
                    year,
                    week,
                    exc,
                )
                continue
        self.last_provider_errors = errors
        detail = "; ".join(f"{item['provider']}: {item['error']}" for item in errors)
        raise BoxOfficeError(f"France box office providers failed: {detail}")

    def get_current_week_movies(self, limit: int = 10) -> List[BoxOfficeMovie]:
        latest_info = self.fallback._latest_completed_week_info(datetime.now())
        year = int(latest_info["latest_completed_year"])
        week = int(latest_info["latest_completed_week_number"])
        return self.fetch_weekend_box_office(year, week, limit=limit)

    def get_historical_movies(self, weeks_back: int = 1):
        history = self.fallback.get_historical_movies(weeks_back=weeks_back)
        self.last_provider_used = self.fallback.provider_key
        self.last_parse_diagnostics = dict(
            getattr(self.fallback, "last_parse_diagnostics", {}) or {}
        )
        self.last_resolution_diagnostics = dict(
            getattr(self.fallback, "last_resolution_diagnostics", {}) or {}
        )
        return history

    def extract_detail_metadata(self, release_url: Optional[str]) -> Dict[str, Any]:
        if isinstance(release_url, str) and (
            "allocine.fr" in release_url or "fichefilm_gen_cfilm" in release_url
        ):
            return self.primary.extract_detail_metadata(release_url)
        return self.fallback.extract_detail_metadata(release_url)


class JPBoxOfficeProvider(BoxOfficeProvider):
    """JPBoxOffice provider supporting multiple country-specific views.

    The logical model reuses ``weekend_gross`` and ``total_gross`` for
    compatibility with the rest of Boxarr, but for JPBoxOffice markets those
    values represent admissions/entries rather than USD revenue.
    """

    provider_key = "jpboxoffice"
    BASE_URL = "https://www.jpbox-office.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 Boxarr/1.7.0"
    )
    REQUEST_TIMEOUT = 30.0
    DETAIL_REQUEST_TIMEOUT = 5.0
    DEBUG_DUMP_ENABLED = str(
        __import__("os").environ.get("BOXARR_JPBOXOFFICE_DEBUG_DUMP", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    DEBUG_DUMP_DIR = Path(__import__("os").environ.get("BOXARR_JPBOXOFFICE_DEBUG_DIR", "/tmp"))
    # JPBoxOffice France weekly series that Boxarr treats as the calendar anchor.
    # idsem 2943 is the completed Wednesday-Tuesday period 2026-05-20..2026-05-26.
    # The Boxarr week label for JPBoxOffice is the ISO week containing the
    # Wednesday start date, so that period is 2026W21.
    CALENDAR_ANCHOR_WEEK_START = datetime(2026, 5, 20)
    CALENDAR_ANCHOR_WEEK_END = datetime(2026, 5, 26)
    CALENDAR_ANCHOR_IDSEM = 2943
    CALENDAR_BUFFER_DAYS = 2

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        provider_config: Optional[Dict[str, object]] = None,
    ):
        super().__init__(
            http_client
            or httpx.Client(
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.REQUEST_TIMEOUT,
                follow_redirects=True,
            )
        )
        self.provider_config = normalize_provider_config(
            "jpboxoffice", provider_config
        )
        self.country = str(self.provider_config.get("country", "fr")).strip().lower()
        self.country_spec = get_jpboxoffice_country_spec(self.country)
        if not self.country_spec:
            raise BoxOfficeError(
                f"JPBoxOffice country '{self.country}' is not implemented yet"
            )
        self.view = int(self.country_spec.get("view", 2))
        self.min_year = int(self.country_spec.get("min_year", 1982))
        self.last_resolution_diagnostics: Dict[str, Any] = {}
        self._html_cache: Dict[str, str] = {}
        self._detail_metadata_cache: Dict[str, Dict[str, Any]] = {}
        self._resolved_weekly_page_cache: Dict[Tuple[int, int], str] = {}

    def close(self) -> None:
        if self.client:
            self.client.close()

    def _fetch_html(self, url: str) -> str:
        if url in self._html_cache:
            return self._html_cache[url]
        logger.info(f"Fetching JPBoxOffice data from: {url}")
        delays = [5, 15, 30]
        last_error: Optional[Exception] = None
        for attempt in range(1, len(delays) + 1):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                html = response.text
                if self.DEBUG_DUMP_ENABLED:
                    self._dump_debug_html(url, html)
                self._html_cache[url] = html
                return html
            except httpx.TimeoutException as e:
                last_error = e
            except httpx.HTTPStatusError as e:
                status = getattr(e.response, "status_code", None)
                if status not in {500, 502, 503, 504}:
                    logger.error(f"Failed to fetch JPBoxOffice data: {e}")
                    raise BoxOfficeError(f"Failed to fetch JPBoxOffice data: {e}") from e
                last_error = e
            except httpx.HTTPError as e:
                last_error = e
                logger.error(f"Failed to fetch JPBoxOffice data: {e}")
                raise BoxOfficeError(f"Failed to fetch JPBoxOffice data: {e}") from e
            except Exception as e:
                last_error = e
                logger.error(f"Failed to fetch JPBoxOffice data: {e}")
                raise BoxOfficeError(f"Failed to fetch JPBoxOffice data: {e}") from e

            if attempt < len(delays):
                delay = delays[attempt - 1] * (1.0 + random.uniform(0.0, 0.2))
                logger.warning(
                    "JPBoxOffice fetch failed for %s (attempt %s/%s), retrying in %.1fs: %s",
                    url,
                    attempt,
                    len(delays),
                    delay,
                    last_error,
                )
                time.sleep(delay)
                continue

            break
        logger.error(f"Failed to fetch JPBoxOffice data after retries: {last_error}")
        raise BoxOfficeError(f"Failed to fetch JPBoxOffice data after retries: {last_error}") from last_error

    def _dump_debug_html(self, url: str, html: str) -> None:
        try:
            self.DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", url)
            path = self.DEBUG_DUMP_DIR / f"jpboxoffice_{safe_name}.html"
            path.write_text(html, encoding="utf-8", errors="ignore")
            logger.debug(f"Dumped JPBoxOffice HTML to {path}")
        except Exception as e:
            logger.debug(f"Failed to dump JPBoxOffice HTML for debug: {e}")

    def _year_listing_url(self, year: int) -> str:
        return f"{self.BASE_URL}/v9_hebdomadaire.php?view={self.view}&year={year}"

    def _week_page_url_for_idsem(self, idsem: int) -> str:
        return f"{self.BASE_URL}/v9_tophebdo.php?idsem={idsem}&view={self.view}"

    def _latest_completed_week_end_date(
        self, reference_date: Optional[datetime] = None
    ) -> datetime:
        """Return the latest Tuesday that is safely eligible for parsing.

        JPBoxOffice France weeks run Wednesday -> Tuesday. Pages are not
        considered usable until Thursday, so we apply a one-day safety buffer
        after Tuesday and only consider Tuesdays that are at least two days old.
        """
        reference = reference_date or datetime.now()
        cutoff = reference.date() - timedelta(days=self.CALENDAR_BUFFER_DAYS)
        days_since_tuesday = (cutoff.weekday() - 1) % 7
        latest_end_date = cutoff - timedelta(days=days_since_tuesday)
        return datetime.combine(latest_end_date, datetime.min.time())

    def _latest_completed_week_info(
        self, reference_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        latest_end = self._latest_completed_week_end_date(reference_date)
        latest_start = latest_end - timedelta(days=6)
        iso_year, iso_week, _ = latest_start.isocalendar()
        reference = reference_date or datetime.now()
        weeks_delta = (latest_end.date() - self.CALENDAR_ANCHOR_WEEK_END.date()).days // 7
        latest_idsem = self.CALENDAR_ANCHOR_IDSEM + weeks_delta
        next_end_date = latest_end.date() + timedelta(days=7)
        next_start_date = next_end_date - timedelta(days=6)
        next_iso_year, next_iso_week, _ = next_start_date.isocalendar()
        next_eligible_date = next_end_date + timedelta(days=self.CALENDAR_BUFFER_DAYS)
        skipped_incomplete_week = reference.date() < next_eligible_date
        skipped_idsem = latest_idsem + 1 if skipped_incomplete_week else None
        return {
            "reference_date": reference.date().isoformat(),
            "latest_completed_start_date": latest_start.date().isoformat(),
            "latest_completed_end_date": latest_end.date().isoformat(),
            "latest_completed_year": iso_year,
            "latest_completed_week_number": iso_week,
            "latest_completed_idsem": latest_idsem,
            "latest_completed_url": self._week_page_url_for_idsem(latest_idsem),
            "skipped_incomplete_week": skipped_incomplete_week,
            "skipped_year": next_iso_year if skipped_incomplete_week else None,
            "skipped_week_number": next_iso_week if skipped_incomplete_week else None,
            "skipped_idsem": skipped_idsem,
            "skipped_week_end_date": next_end_date.isoformat(),
            "skipped_week_range": (
                f"DU {next_end_date - timedelta(days=6):%d %B %Y} "
                f"AU {next_end_date:%d %B %Y}"
            ),
        }

    def _explicit_week_info(self, year: int, week: int) -> Optional[Dict[str, Any]]:
        """Return direct JPBoxOffice mapping for explicit historical weeks.

        Boxarr's week label is ISO year/week. JPBoxOffice France weeks run
        Wednesday -> Tuesday, so we map an explicit request to the period whose
        Wednesday falls inside the requested ISO week.
        """
        if self.country != "fr" or year != 2026:
            return None
        if week < 1:
            return None
        try:
            start_date = datetime.fromisocalendar(year, week, 3)
        except ValueError:
            return None
        end_date = start_date + timedelta(days=6)
        weeks_delta = (start_date.date() - self.CALENDAR_ANCHOR_WEEK_START.date()).days // 7
        idsem = self.CALENDAR_ANCHOR_IDSEM + weeks_delta
        return {
            "year": year,
            "week": week,
            "idsem": idsem,
            "source_url": self._week_page_url_for_idsem(idsem),
            "expected_start_date": start_date,
            "expected_end_date": end_date,
        }

    def _validate_explicit_week_page(
        self,
        html: str,
        explicit_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        range_info = self._parse_week_page_date_range(html)
        start_date = range_info.get("start_date")
        end_date = range_info.get("end_date")
        expected_start = explicit_info["expected_start_date"]
        expected_end = explicit_info["expected_end_date"]
        diagnostics = {
            "source_url": explicit_info["source_url"],
            "requested_year": explicit_info["year"],
            "requested_week": explicit_info["week"],
            "idsem": explicit_info["idsem"],
            "expected_start_date": expected_start.date().isoformat(),
            "expected_end_date": expected_end.date().isoformat(),
            "actual_title": range_info.get("title"),
            "actual_start_date": start_date.date().isoformat() if start_date else None,
            "actual_end_date": end_date.date().isoformat() if end_date else None,
        }
        if start_date and end_date:
            if start_date.date() != expected_start.date() or end_date.date() != expected_end.date():
                self.last_resolution_diagnostics = diagnostics
                raise BoxOfficeError(
                    "JPBoxOffice explicit week mismatch: "
                    f"source_url={explicit_info['source_url']} "
                    f"requested={explicit_info['year']}W{explicit_info['week']:02d} "
                    f"expected_range={expected_start.date().isoformat()}..{expected_end.date().isoformat()} "
                    f"actual_range={start_date.date().isoformat()}..{end_date.date().isoformat()}"
                )
            is_complete, complete_diagnostics = self._is_week_page_complete(html)
            diagnostics.update(complete_diagnostics)
            if not is_complete:
                latest_info = self._latest_completed_week_info(datetime.now())
                latest_completed_idsem = latest_info.get("latest_completed_idsem")
                self.last_resolution_diagnostics = {
                    **diagnostics,
                    "skipped_incomplete_week": True,
                    "latest_completed_idsem": latest_completed_idsem,
                }
                raise BoxOfficeError(
                    "skipped_incomplete_week: "
                    f"source_url={explicit_info['source_url']} "
                    f"country={self.country} view={self.view} "
                    f"latest_completed_idsem={latest_completed_idsem} "
                    f"date_range={range_info.get('title')}"
                )
        self.last_resolution_diagnostics = diagnostics
        return diagnostics

    def _fetch_completed_week_movies(
        self, reference_date: Optional[datetime] = None, limit: int = 10
    ) -> List[BoxOfficeMovie]:
        week_info = self._latest_completed_week_info(reference_date)
        weekly_url = week_info["latest_completed_url"]
        html = self._fetch_html(weekly_url)
        movies = self._parse_weekly_page(html, limit=limit, source_url=weekly_url)
        self.enrich_with_imdb_ids(movies)
        self.last_resolution_diagnostics = {
            **week_info,
            "source_url": weekly_url,
            "selected_href": weekly_url,
        }
        return movies

    def _extract_week_listing_candidates(self, listing_html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(listing_html, "html.parser")
        candidates: List[Dict[str, Any]] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", ""))
            if "v9_tophebdo.php" not in href:
                continue
            text = self._normalize_space(anchor.get_text(" ", strip=True))
            row = anchor.find_parent("tr")
            row_text = self._normalize_space(row.get_text(" ", strip=True)) if row else text
            week_number = None
            for source_text in (text, row_text):
                match = re.search(r"\bSemaine\s+(\d{1,2})\b", source_text, re.IGNORECASE)
                if not match:
                    match = re.search(r"\b(\d{1,2})\b", source_text)
                if match:
                    try:
                        week_number = int(match.group(1))
                        break
                    except ValueError:
                        continue
            candidates.append(
                {
                    "href": href if href.startswith("http") else f"{self.BASE_URL}/{href.lstrip('/')}",
                    "text": text,
                    "row_text": row_text,
                    "week_number": week_number,
                }
            )
        return candidates

    def _parse_week_page_date_range(self, html: str) -> Dict[str, Optional[datetime]]:
        soup = BeautifulSoup(html, "html.parser")
        title_candidates = []
        for selector in ("title", "h1", "h2", "h3"):
            node = soup.find(selector)
            if node:
                title_candidates.append(self._normalize_space(node.get_text(" ", strip=True)))
        title_candidates.append(self._normalize_space(soup.get_text(" ", strip=True)[:1000]))

        month_map = {
            "janvier": 1,
            "février": 2,
            "fevrier": 2,
            "mars": 3,
            "avril": 4,
            "mai": 5,
            "juin": 6,
            "juillet": 7,
            "août": 8,
            "aout": 8,
            "septembre": 9,
            "octobre": 10,
            "novembre": 11,
            "décembre": 12,
            "decembre": 12,
        }
        pattern = re.compile(
            r"DU\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+AU\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})",
            re.IGNORECASE,
        )
        for candidate in title_candidates:
            match = pattern.search(candidate)
            if not match:
                continue
            start_day = int(match.group(1))
            start_month = month_map.get(match.group(2).strip().lower())
            end_day = int(match.group(3))
            end_month = month_map.get(match.group(4).strip().lower())
            year = int(match.group(5))
            if not start_month or not end_month:
                continue
            try:
                start_date = datetime(year, start_month, start_day)
                end_date = datetime(year, end_month, end_day)
            except ValueError:
                continue
            return {
                "title": candidate,
                "start_date": start_date,
                "end_date": end_date,
            }
        return {"title": None, "start_date": None, "end_date": None}

    def _is_week_page_complete(
        self, html: str, reference_date: Optional[datetime] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        reference = reference_date or datetime.now()
        range_info = self._parse_week_page_date_range(html)
        end_date = range_info.get("end_date")
        start_date = range_info.get("start_date")
        complete = True
        if end_date is not None:
            complete = end_date.date() < reference.date()
        return complete, {
            "title": range_info.get("title"),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "reference_date": reference.date().isoformat(),
            "complete": complete,
        }

    def _resolve_weekly_page_url(
        self,
        year: int,
        week: int,
        *,
        allow_backtrack: bool = False,
        reference_date: Optional[datetime] = None,
    ) -> str:
        """Resolve the weekly page URL via the annual listing page."""
        listing_html = self._fetch_html(self._year_listing_url(year))
        candidates = self._extract_week_listing_candidates(listing_html)
        candidate_index = None
        for index, candidate in enumerate(candidates):
            text = candidate.get("text") or ""
            row_text = candidate.get("row_text") or ""
            if text == str(week):
                candidate_index = index
                break
            if re.search(rf"\bSemaine\s+{week}\b", row_text, re.IGNORECASE):
                candidate_index = index
                break
            if re.search(rf"\b{week}\b", row_text) and "Janvier" in row_text:
                candidate_index = index
                break

        if candidate_index is None:
            raise BoxOfficeError(
                f"Could not resolve JPBoxOffice weekly page for {year}W{week:02d}"
            )

        cached_url = self._resolved_weekly_page_cache.get((year, week))
        if cached_url and cached_url in self._html_cache:
            cached_html = self._html_cache[cached_url]
            is_complete, diagnostics = self._is_week_page_complete(
                cached_html, reference_date=reference_date
            )
            if is_complete:
                self.last_resolution_diagnostics = {
                    **diagnostics,
                    "candidate_href": cached_url,
                    "candidate_week": week,
                    "candidate_text": str(week),
                    "requested_year": year,
                    "requested_week": week,
                    "allow_backtrack": allow_backtrack,
                    "cache_hit": True,
                }
                return cached_url

        first_incomplete_diagnostics: Optional[Dict[str, Any]] = None
        for index in range(candidate_index, -1, -1):
            candidate = candidates[index]
            weekly_url = candidate["href"]
            html = self._fetch_html(weekly_url)
            is_complete, diagnostics = self._is_week_page_complete(
                html, reference_date=reference_date
            )
            diagnostics.update(
                {
                    "candidate_href": weekly_url,
                    "candidate_week": candidate.get("week_number"),
                    "candidate_text": candidate.get("text"),
                    "requested_year": year,
                    "requested_week": week,
                    "allow_backtrack": allow_backtrack,
                }
            )
            self.last_resolution_diagnostics = diagnostics
            if is_complete:
                self._resolved_weekly_page_cache[(year, week)] = weekly_url
                if first_incomplete_diagnostics:
                    match = re.search(r"[?&]idsem=(\d+)", weekly_url)
                    self.last_resolution_diagnostics = {
                        **first_incomplete_diagnostics,
                        "skipped_incomplete_week": True,
                        "latest_completed_idsem": int(match.group(1)) if match else None,
                        "selected_href": weekly_url,
                    }
                return weekly_url
            if first_incomplete_diagnostics is None:
                first_incomplete_diagnostics = diagnostics
            if not allow_backtrack:
                break

        latest_completed_idsem = None
        if first_incomplete_diagnostics:
            for index in range(candidate_index - 1, -1, -1):
                candidate = candidates[index]
                html = self._fetch_html(candidate["href"])
                is_complete, _ = self._is_week_page_complete(
                    html, reference_date=reference_date
                )
                if is_complete:
                    match = re.search(r"[?&]idsem=(\d+)", candidate["href"])
                    if match:
                        latest_completed_idsem = int(match.group(1))
                    self._resolved_weekly_page_cache[(year, week)] = candidate["href"]
                    break

            self.last_resolution_diagnostics = {
                **first_incomplete_diagnostics,
                "skipped_incomplete_week": True,
                "latest_completed_idsem": latest_completed_idsem,
            }
            raise BoxOfficeError(
                "skipped_incomplete_week: "
                f"source_url={first_incomplete_diagnostics.get('candidate_href')} "
                f"country={self.country} view={self.view} "
                f"latest_completed_idsem={latest_completed_idsem} "
                f"date_range={first_incomplete_diagnostics.get('title')}"
            )

        raise BoxOfficeError(
            f"Could not resolve completed JPBoxOffice weekly page for {year}W{week:02d}"
        )

    def _normalize_space(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

    def _collect_candidate_nodes(self, soup: BeautifulSoup) -> List:
        """Return ranking row candidates in the most specific shape available."""
        def container_score(container) -> Tuple[int, int]:
            class_names = " ".join(container.get("class", [])) if hasattr(container, "get") else ""
            text = self._normalize_space(container.get_text(" ", strip=True))
            score = 0
            if re.search(r"\bTitre\b.*\bSem\.\b", text, re.IGNORECASE) or re.search(
                r"\bEntr[ée]es\b", text, re.IGNORECASE
            ):
                score += 100
            if re.search(r"\bEvol\.", text, re.IGNORECASE) or re.search(
                r"\bCopies\b", text, re.IGNORECASE
            ):
                score += 25
            if re.search(r"\bPDM\b", text, re.IGNORECASE):
                score += 10
            if "weekly" in class_names.lower() or "hebdo" in class_names.lower():
                score += 20
            if container.name in {"main", "section", "article"}:
                score += 5

            direct_movie_blocks = container.find_all("div", class_="movie-block", recursive=False)
            direct_rows = container.find_all("tr", recursive=False)
            score += len(direct_movie_blocks) * 10
            score += len(direct_rows) * 6
            return score, len(direct_movie_blocks) + len(direct_rows)

        container_candidates = []
        seen_ids = set()
        for candidate in soup.find_all(True):
            try:
                node_id = id(candidate)
                if node_id in seen_ids:
                    continue
                seen_ids.add(node_id)
            except Exception:
                pass

            direct_movie_blocks = candidate.find_all(
                "div", class_="movie-block", recursive=False
            )
            direct_rows = candidate.find_all("tr", recursive=False)
            nodes = list(direct_movie_blocks) + list(direct_rows)
            if not nodes:
                continue
            score, count = container_score(candidate)
            if count:
                container_candidates.append((score, count, candidate, nodes))

        if container_candidates:
            container_candidates.sort(
                key=lambda item: (item[0], item[1]), reverse=True
            )
            selected_nodes = []
            seen_ids = set()
            for score, _, container, _ in container_candidates:
                container_nodes = container.find_all("div", class_="movie-block")
                if not container_nodes:
                    container_nodes = container.find_all("tr")
                for node in container_nodes:
                    try:
                        node_id = id(node)
                        if node_id in seen_ids:
                            continue
                        seen_ids.add(node_id)
                    except Exception:
                        pass
                    selected_nodes.append(node)
            best_score = container_candidates[0][0]
            logger.debug(
                "JPBoxOffice selected ranking container score=%s candidates=%s selected_nodes=%s",
                best_score,
                len(container_candidates),
                len(selected_nodes),
            )
            return selected_nodes

        candidate_rows = []
        for row in soup.find_all("tr"):
            text = row.get_text(" ", strip=True)
            if not text:
                continue
            if row.find("a", href=re.compile(r"fichfilm\.php")):
                candidate_rows.append(row)
                continue
            if row.find("td", class_=re.compile(r"col_poster_(titre|compteur|contenu_majeur)")):
                candidate_rows.append(row)
                continue
            if re.match(r"^\s*(?:N\s*)?\d+\b", text):
                candidate_rows.append(row)

        if candidate_rows:
            return candidate_rows

        candidate_divs = []
        for div in soup.find_all(["div", "li"]):
            text = div.get_text(" ", strip=True)
            if not text:
                continue
            if div.find("a", href=re.compile(r"fichfilm\.php")):
                candidate_divs.append(div)
                continue
            if re.match(r"^\s*(?:N\s*)?\d+\b", text):
                candidate_divs.append(div)

        return candidate_divs

    def _collect_fallback_candidate_nodes(self, soup: BeautifulSoup, seen_nodes: set) -> List:
        """Collect additional row-like nodes when the primary pass had header rows or gaps."""
        fallback_nodes = []
        seen_texts = set()
        for node in soup.find_all(["tr", "div", "li"]):
            try:
                node_id = id(node)
                if node_id in seen_nodes:
                    continue
            except Exception:
                pass

            text = self._normalize_space(node.get_text(" ", strip=True))
            if not text:
                continue
            if self._is_header_label_line(text):
                continue
            if node.find("a", href=re.compile(r"fichfilm\.php")):
                key = self._title_key(text)
                if key and key not in seen_texts:
                    fallback_nodes.append(node)
                    seen_texts.add(key)
                continue
            if node.find("td", class_=re.compile(r"col_poster_(titre|compteur|contenu_majeur)")):
                key = self._title_key(text)
                if key and key not in seen_texts:
                    fallback_nodes.append(node)
                    seen_texts.add(key)
                continue
            if re.match(r"^\s*(?:N\s*)?\d+\b", text):
                key = self._title_key(text)
                if key and key not in seen_texts:
                    fallback_nodes.append(node)
                    seen_texts.add(key)
        return fallback_nodes

    def _extract_rank_from_node(self, node, lines: List[str]) -> Optional[int]:
        """Extract a ranking number from a candidate node."""
        rank_cell = node.find("td", class_=re.compile(r"col_poster_compteur"))
        if rank_cell:
            rank_div = rank_cell.find("div", class_=re.compile(r"compteur"))
            rank_text = (
                rank_div.get_text(" ", strip=True) if rank_div else rank_cell.get_text(" ", strip=True)
            )
            rank = self._parse_int(rank_text, first_only=True)
            if rank is not None:
                return rank

        for line in lines[:4]:
            normalized = self._normalize_space(line)
            if not normalized:
                continue
            match = re.match(r"^(?:N\s*)?(\d{1,3})\b", normalized)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue

        text = self._normalize_space(node.get_text(" ", strip=True))
        match = re.match(r"^(?:N\s*)?(\d{1,3})\b", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def _parse_candidate_node(
        self,
        node,
        fallback_rank: int,
        source_url: Optional[str] = None,
        release_urls: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[BoxOfficeMovie], Optional[str], Dict[str, Any]]:
        """Parse a single ranking candidate into a movie, or return a skip reason."""
        lines = [
            self._normalize_space(part)
            for part in node.stripped_strings
            if self._normalize_space(part)
        ]

        anchor = None
        for candidate in node.find_all("a", href=True):
            href = str(candidate.get("href", ""))
            if "fichfilm.php" in href:
                anchor = candidate
                break
        if anchor is None:
            anchor = node.find("a", href=True)

        title = None
        release_url = None
        if anchor is not None:
            title = self._normalize_space(anchor.get_text(" ", strip=True))
        if title and (title.strip().lower() == "image" or self._is_header_label_line(title)):
            title = None
            href = str(anchor.get("href", ""))
            if href:
                release_url = href if href.startswith("/") else f"/{href.lstrip('/')}"
        if not title:
            title = self._find_title(lines)
        if not title:
            return None, "missing_title", {"extracted_rank": None, "rank_source": "missing"}
        if self._is_header_label_line(title):
            return None, "header_title", {"extracted_rank": None, "rank_source": "header"}
        if re.match(r"^N\s*°?\s*1\b", title, re.IGNORECASE):
            fallback_title = next(
                (
                    self._normalize_space(line)
                    for line in lines
                    if line
                    and line != title
                    and not re.match(r"^N\s*°?\s*1\b", line, re.IGNORECASE)
                    and self._is_title_line(line)
                ),
                None,
            )
            if fallback_title:
                title = fallback_title
            else:
                return None, "artifact_title", {"extracted_rank": None, "rank_source": "artifact"}

        extracted_rank = self._extract_rank_from_node(node, lines)
        rank = fallback_rank
        rank_source = "row_order"

        if release_urls:
            release_url = release_urls.get(self._title_key(title), release_url)

        original_title, year = self._extract_fr_title_metadata(node, title)
        metrics = self._parse_metrics_from_block(lines) or {}

        movie = BoxOfficeMovie(
            rank=rank,
            title=title,
            weekend_gross=metrics.get("weekend_gross"),
            total_gross=metrics.get("total_gross"),
            weeks_released=metrics.get("weeks_released"),
            theater_count=metrics.get("theater_count"),
            original_title=original_title,
            year=year,
            release_url=release_url,
            source_href=release_url,
            source_title=title,
            normalized_source_title=normalize_title_key(title),
            source_url=source_url,
            market=self.provider_key,
            country=self.country,
            jpboxoffice_id=self._extract_jpboxoffice_id(release_url),
        )

        return movie, None, {
            "extracted_rank": extracted_rank,
            "final_rank": rank,
            "rank_source": rank_source,
        }

    def _extract_numeric_tokens(self, text: str) -> List[str]:
        text = text.replace("\xa0", " ")
        return re.findall(
            r"\([+-]?\d+\)|[+-]?\d+(?:[.,]\d+)?%|\d{1,3}(?:[ .]\d{3})+|\d+|N",
            text,
        )

    def _parse_int(self, token: Optional[str], first_only: bool = False) -> Optional[int]:
        if not token:
            return None
        source = token
        if first_only:
            match = re.search(r"-?\d[\d\s.,]*", token)
            if not match:
                return None
            source = match.group(0)
        cleaned = re.sub(r"[^\d-]", "", source)
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None

    def _parse_number(self, token: Optional[str], first_only: bool = False) -> Optional[float]:
        value = self._parse_int(token, first_only=first_only)
        if value is not None:
            return float(value)
        if not token:
            return None
        if first_only:
            match = re.search(r"-?\d[\d\s.,]*", token)
            if not match:
                return None
            token = match.group(0)
        cleaned = token.replace("%", "").replace(" ", "").replace("\xa0", "")
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _is_title_line(self, line: str) -> bool:
        if not line:
            return False
        normalized = self._normalize_space(line)
        lowered = normalized.lower()
        header_labels = {
            "titre",
            "title",
            "image",
            "sem.",
            "semaine",
            "entrées",
            "entrees",
            "evol.",
            "copies",
            "moyenne",
            "cumul",
            "pdm",
        }
        if lowered in header_labels:
            return False
        if re.search(
            r"\b(titre|title)\b.*\b(sem\.?|semaine|entr[ée]es|evol\.?|copies|moyenne|cumul|pdm)\b",
            lowered,
        ):
            return False
        if normalized in {"Image", "Entrées Hebdomadaires 2026"}:
            return False
        if normalized.startswith("(") and normalized.endswith(")"):
            return False
        if re.fullmatch(r"[+-]?\d+", normalized):
            return False
        if "%" in normalized:
            return False
        return not re.search(
            r"\b(France|Etats-Unis|Royaume-Uni|Espagne|Allemagne|Italie|Brésil|Iran|Japon)\b",
            normalized,
        )

    def _find_title(self, block_lines: List[str]) -> Optional[str]:
        for line in block_lines:
            if self._is_header_label_line(line):
                continue
            if self._is_title_line(line) and re.search(r"[A-Za-zÀ-ÿ]", line):
                return self._normalize_space(line)
        return None

    def _is_header_label_line(self, line: str) -> bool:
        normalized = self._normalize_space(line)
        lowered = normalized.lower()
        if lowered in {"titre", "title", "image"}:
            return True
        if re.search(r"\b(titre|title)\b.*\b(sem\.?|semaine|entr[ée]es|evol\.?|copies|moyenne|cumul|pdm)\b", lowered):
            return True
        return False

    def _title_key(self, title: str) -> str:
        return re.sub(r"[^\w\s]", "", title.lower()).strip()

    def _extract_year_from_text(self, text: Optional[str]) -> Optional[int]:
        if not text:
            return None
        match = re.search(r"\((\d{4})\)", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def _extract_jpboxoffice_id(self, href: Optional[str]) -> Optional[int]:
        if not href:
            return None
        match = re.search(r"[?&]id=(\d+)", href)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def extract_detail_metadata(self, release_url: Optional[str]) -> Dict[str, Any]:
        """Extract extra JPBoxOffice identity metadata from a detail page."""
        if not release_url:
            return {}
        detail_url = release_url if release_url.startswith("http") else f"{self.BASE_URL}{release_url}"
        if detail_url in self._detail_metadata_cache:
            return dict(self._detail_metadata_cache[detail_url])
        try:
            try:
                response = self.client.get(detail_url, timeout=self.DETAIL_REQUEST_TIMEOUT)
            except TypeError:
                # Some tests inject a minimal mock client that only accepts the URL.
                response = self.client.get(detail_url)
            response.raise_for_status()
        except Exception as exc:
            logger.debug("Failed to fetch JPBoxOffice detail page %s: %s", detail_url, exc)
            self._detail_metadata_cache[detail_url] = {}
            return {}

        html = response.text or ""
        soup = BeautifulSoup(html, "html.parser")
        metadata: Dict[str, Any] = {
            "source_href": release_url,
            "source_url": detail_url,
            "jpboxoffice_id": self._extract_jpboxoffice_id(release_url),
        }

        def _first_text(*selectors: str) -> Optional[str]:
            for selector in selectors:
                node = soup.select_one(selector)
                if node:
                    text = self._normalize_space(node.get_text(" ", strip=True))
                    if text:
                        return text
            return None

        title = _first_text("meta[property='og:title']", "h1", "title")
        if title and ":" in title:
            metadata["english_title"] = title

        link_patterns = {
            "imdb_id": r"pro\.imdb\.com/title/(tt\d+)/",
            "tmdb_id": r"themoviedb\.org/movie/(\d+)",
        }
        for key, pattern in link_patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                try:
                    metadata[key] = int(match.group(1)) if key == "tmdb_id" else match.group(1)
                except ValueError:
                    continue

        text = self._normalize_space(" ".join(soup.stripped_strings))
        for label, key in [
            (r"(?:Titre original|Original title)\s*[:\-]?\s*([^\n\r|]+)", "original_title"),
            (r"(?:Titre international|International title)\s*[:\-]?\s*([^\n\r|]+)", "international_title"),
            (r"(?:Titre anglais|English title)\s*[:\-]?\s*([^\n\r|]+)", "english_title"),
            (r"(?:Réalisateur|Director)\s*[:\-]?\s*([^\n\r|]+)", "director"),
            (r"(?:Pays|Country)\s*[:\-]?\s*([^\n\r|]+)", "country_name"),
            (r"(?:Distributeur|Distributor)\s*[:\-]?\s*([^\n\r|]+)", "distributor"),
            (r"(?:Durée|Runtime)\s*[:\-]?\s*([^\n\r|]+)", "runtime_text"),
            (r"(?:Sortie|Release date)\s*[:\-]?\s*([^\n\r|]+)", "release_date_text"),
        ]:
            match = re.search(label, text, re.IGNORECASE)
            if match:
                metadata[key] = self._normalize_space(match.group(1))

        for key in ("original_title", "international_title", "english_title"):
            if key in metadata and metadata[key] == "":
                metadata.pop(key, None)

        year_text = metadata.get("release_date_text") or metadata.get("runtime_text")
        if isinstance(year_text, str):
            year_match = re.search(r"(19|20)\d{2}", year_text)
            if year_match:
                metadata["year"] = int(year_match.group(0))

        self._detail_metadata_cache[detail_url] = dict(metadata)
        return metadata

    def enrich_with_imdb_ids(self, movies: List["BoxOfficeMovie"]) -> None:
        """Avoid eager per-row detail requests while fetching JPBoxOffice charts."""
        logger.debug(
            "Skipping eager JPBoxOffice IMDb enrichment for %s chart rows",
            len(movies),
        )

    def _extract_fr_title_metadata(
        self, title_cell, title: str
    ) -> Tuple[Optional[str], Optional[int]]:
        """Extract original title and year from a JPBoxOffice title cell."""
        original_title = None
        year = self._extract_year_from_text(title)

        stripped_strings = [
            self._normalize_space(part)
            for part in title_cell.stripped_strings
            if self._normalize_space(part)
        ]

        for extra in stripped_strings[1:]:
            if not extra or extra == title:
                continue
            if extra.strip().lower() == "image":
                continue
            if extra.startswith("(") and extra.endswith(")"):
                continue
            if "/" in extra:
                continue
            extra_year = self._extract_year_from_text(extra)
            if extra_year and year is None:
                year = extra_year
            candidate = re.sub(r"\s*\(\d{4}\)\s*$", "", extra).strip()
            if candidate and candidate != title:
                original_title = candidate
                if year is None:
                    year = extra_year
                break

        return original_title, year

    def _parse_metrics_from_block(self, block_lines: List[str]) -> Optional[Dict[str, Optional[float]]]:
        metric_start = None
        for idx, line in enumerate(block_lines):
            if "/" in line and re.search(r"\d", line):
                metric_start = idx
                break
        if metric_start is None:
            return None

        metric_text = self._normalize_space(" ".join(block_lines[metric_start:]))
        runtime_match = re.search(r"\b\d+h\d+\b", metric_text)
        if not runtime_match:
            return None

        tail = metric_text[runtime_match.end() :].strip()
        tokens = self._extract_numeric_tokens(tail)
        if len(tokens) < 3:
            return None

        stats: Dict[str, Optional[float]] = {
            "weeks_released": None,
            "weekend_gross": None,
            "theater_count": None,
            "total_gross": None,
        }

        index = 0
        weeks_token = tokens[index]
        index += 1
        if weeks_token == "N":
            stats["weeks_released"] = 1
        else:
            weeks = self._parse_int(weeks_token)
            stats["weeks_released"] = weeks

        if index < len(tokens):
            stats["weekend_gross"] = self._parse_number(tokens[index])
            index += 1

        if index < len(tokens) and tokens[index].endswith("%"):
            index += 1

        if index < len(tokens) and re.fullmatch(r"\d+", tokens[index]):
            stats["theater_count"] = self._parse_int(tokens[index])
            index += 1

        if index < len(tokens) and tokens[index].startswith("("):
            index += 1

        if index < len(tokens) and re.fullmatch(r"\d+", tokens[index]):
            # Average per copy, not currently stored but consumed to reach total.
            index += 1

        if index < len(tokens):
            stats["total_gross"] = self._parse_number(tokens[index])

        return stats

    def _parse_block(
        self,
        rank: int,
        block_lines: List[str],
        limit: int,
        source_url: Optional[str] = None,
        release_urls: Optional[Dict[str, str]] = None,
    ) -> Optional[BoxOfficeMovie]:
        if rank > limit:
            return None

        title = self._find_title(block_lines)
        if not title:
            return None

        metrics = self._parse_metrics_from_block(block_lines)
        if not metrics or metrics["weekend_gross"] is None or metrics["total_gross"] is None:
            logger.debug(f"Skipping row without parseable metrics for title={title}: {block_lines}")
            return None

        release_url = None
        if release_urls:
            release_url = release_urls.get(self._title_key(title))

        return BoxOfficeMovie(
            rank=rank,
            title=title,
            weekend_gross=metrics["weekend_gross"],
            total_gross=metrics["total_gross"],
            weeks_released=metrics["weeks_released"],
            theater_count=metrics["theater_count"],
            release_url=release_url,
            source_href=release_url,
            source_title=title,
            normalized_source_title=normalize_title_key(title),
            source_url=source_url,
            market=self.provider_key,
            country=self.country,
            jpboxoffice_id=self._extract_jpboxoffice_id(release_url),
        )

    def _parse_weekly_page(
        self, html: str, limit: int = 10, source_url: Optional[str] = None
    ) -> List[BoxOfficeMovie]:
        soup = BeautifulSoup(html, "html.parser")
        release_urls: Dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", ""))
            if "fichfilm.php" not in href:
                continue
            title_text = self._normalize_space(anchor.get_text(" ", strip=True))
            if title_text:
                release_urls[self._title_key(title_text)] = href if href.startswith("/") else f"/{href.lstrip('/')}"
        candidate_nodes = self._collect_candidate_nodes(soup)
        seen_nodes = set()
        for node in candidate_nodes:
            try:
                seen_nodes.add(id(node))
            except Exception:
                continue
        candidate_nodes.extend(self._collect_fallback_candidate_nodes(soup, seen_nodes))
        logger.debug(
            "JPBoxOffice live parse: source_url=%s country=%s view=%s candidates=%s release_links=%s",
            source_url,
            self.country,
            self.view,
            len(candidate_nodes),
            len(release_urls),
        )

        movies: List[BoxOfficeMovie] = []
        skipped_rows = []
        skipped_header_rows = 0
        parsed_rows = []
        rows_seen = 0
        candidate_rows = []
        for node in candidate_nodes:
            rows_seen += 1
            if len(movies) >= limit:
                break
            fallback_rank = len(movies) + 1
            movie, reason, parsed_meta = self._parse_candidate_node(
                node,
                fallback_rank=fallback_rank,
                source_url=source_url,
                release_urls=release_urls,
            )
            if movie is None:
                if reason == "header_title":
                    skipped_header_rows += 1
                skipped_rows.append(
                    {
                        "reason": reason or "unknown",
                        "text": self._normalize_space(node.get_text(" ", strip=True))[:240],
                        **parsed_meta,
                    }
                )
                continue
            candidate_rows.append(
                {
                    "title": movie.title,
                    "original_title": movie.original_title,
                    "source_text": self._normalize_space(node.get_text(" ", strip=True))[:240],
                    "rank": movie.rank,
                    "source_href": movie.release_url,
                }
            )
            movies.append(movie)
            parsed_rows.append(
                {
                    "rank": movie.rank,
                    "extracted_rank": parsed_meta.get("extracted_rank"),
                    "final_rank": parsed_meta.get("final_rank"),
                    "rank_source": parsed_meta.get("rank_source"),
                    "title": movie.title,
                    "original_title": movie.original_title,
                    "source_text": self._normalize_space(node.get_text(" ", strip=True))[:240],
                    "source_href": movie.release_url,
                }
            )
            logger.debug(
                "Parsed JPBoxOffice row: country=%s view=%s rank=%s title=%s original=%s year=%s weeks=%s weekly=%s total=%s copies=%s",
                self.country,
                self.view,
                movie.rank,
                movie.title,
                movie.original_title,
                movie.year,
                movie.weeks_released,
                movie.weekend_gross,
                movie.total_gross,
                movie.theater_count,
                )

        rows_parsed = len(movies)
        rows_skipped = len(skipped_rows)

        self.last_parse_diagnostics = {
            "source_url": source_url,
            "country": self.country,
            "view": self.view,
            "requested_limit": limit,
            "rows_seen": rows_seen,
            "valid_rows": rows_parsed,
            "skipped_header_rows": skipped_header_rows,
            "rows_parsed": rows_parsed,
            "rows_skipped": rows_skipped,
            "candidate_rows": candidate_rows,
            "parsed_rows": parsed_rows,
            "skipped_rows": skipped_rows,
        }
        logger.debug(
            "JPBoxOffice parse diagnostics: %s",
            self.last_parse_diagnostics,
        )

        expected_ranks = list(range(1, min(limit, rows_parsed) + 1))
        actual_ranks = [movie.rank for movie in movies]
        if rows_parsed and actual_ranks != expected_ranks:
            raise BoxOfficeError(
                "JPBoxOffice parse error: invalid ranking sequence "
                f"(source_url={source_url}, country={self.country}, view={self.view}, "
                f"expected_ranks={expected_ranks}, actual_ranks={actual_ranks}, "
                f"rows_seen={rows_seen}, rows_parsed={rows_parsed}, rows_skipped={rows_skipped}, "
                f"skipped_rows={skipped_rows})"
            )

        if rows_seen and rows_parsed == 0:
            raise BoxOfficeError(
                "JPBoxOffice parse error: no ranking rows parsed "
                f"(source_url={source_url}, country={self.country}, view={self.view}, "
                f"rows_seen={rows_seen}, rows_skipped={rows_skipped})"
            )
        if limit >= 10 and rows_parsed < limit:
            raise BoxOfficeError(
                "JPBoxOffice parse error: partial ranking parse "
                f"(source_url={source_url}, country={self.country}, view={self.view}, "
                f"rows_seen={rows_seen}, valid_rows={rows_parsed}, skipped_header_rows={skipped_header_rows}, "
                f"requested_limit={limit}, rows_skipped={rows_skipped}, "
                f"skipped_rows={skipped_rows})"
            )

        if not movies:
            raise BoxOfficeError("No movies found in JPBoxOffice data")

        movies.sort(key=lambda movie: movie.rank)
        logger.info(
            "Successfully parsed %s movies from JPBoxOffice (country=%s view=%s)",
            len(movies),
            self.country,
            self.view,
        )
        return movies

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        if year is None or week is None:
            _, _, year, week = self.get_weekend_dates()

        explicit_info = self._explicit_week_info(year, week)
        weekly_url = (
            explicit_info["source_url"]
            if explicit_info
            else self._resolve_weekly_page_url(year, week, allow_backtrack=False)
        )
        html = self._fetch_html(weekly_url)
        if explicit_info:
            self._validate_explicit_week_page(html, explicit_info)
        movies = self._parse_weekly_page(html, limit=limit, source_url=weekly_url)
        self.enrich_with_imdb_ids(movies)
        return movies

    def get_current_week_movies(self, limit: int = 10) -> List[BoxOfficeMovie]:
        return self._fetch_completed_week_movies(reference_date=datetime.now(), limit=limit)

    def get_historical_movies(
        self, weeks_back: int = 1
    ) -> Dict[str, List[BoxOfficeMovie]]:
        if weeks_back <= 0:
            return {}
        latest_info = self._latest_completed_week_info(datetime.now())
        latest_idsem = int(latest_info["latest_completed_idsem"])
        latest_end_date = datetime.fromisoformat(latest_info["latest_completed_end_date"])

        history: Dict[str, List[BoxOfficeMovie]] = {}
        failures: List[Dict[str, Any]] = []
        for offset in range(weeks_back):
            week_start = latest_end_date - timedelta(days=6 + (offset * 7))
            iso_year, week_number, _ = week_start.isocalendar()
            idsem = latest_idsem - offset
            weekly_url = self._week_page_url_for_idsem(idsem)
            week_key = f"{iso_year}W{week_number:02d}"
            try:
                html = self._fetch_html(weekly_url)
                movies = self._parse_weekly_page(html, limit=10, source_url=weekly_url)
                self.enrich_with_imdb_ids(movies)
                history[week_key] = movies
            except BoxOfficeError as exc:
                failures.append(
                    {
                        "week_key": week_key,
                        "idsem": idsem,
                        "source_url": weekly_url,
                        "error": str(exc),
                    }
                )
                logger.warning(
                    "JPBoxOffice historical fetch failed for %s (idsem=%s): %s",
                    week_key,
                    idsem,
                    exc,
                )
                continue

        if failures:
            self.last_resolution_diagnostics = {
                **latest_info,
                "historical_failures": failures,
            }

        return history


def create_provider(
    provider: Optional[str] = None,
    http_client=None,
    provider_config: Optional[Dict[str, object]] = None,
) -> BoxOfficeProvider:
    """Create a concrete provider instance from a provider id."""
    normalized = normalize_provider(provider)
    if normalized == "mojo":
        return MojoUSProvider(http_client=http_client, provider_config=provider_config)
    if normalized == "jpboxoffice":
        return JPBoxOfficeProvider(
            http_client=http_client, provider_config=provider_config
        )
    if normalized == "allocine":
        return AllocineFRProvider(
            http_client=http_client, provider_config=provider_config
        )
    if normalized == "france_boxoffice":
        return FranceBoxOfficeProvider(
            http_client=http_client, provider_config=provider_config
        )

    raise BoxOfficeError(f"Unsupported provider '{provider}'")


def create_provider_for_market(
    market: Optional[str] = None, http_client=None
) -> BoxOfficeProvider:
    """Create a provider instance from a market id."""
    normalized_market = normalize_market(market)
    from ..utils.config import settings
    from .market_settings import ensure_market_enabled

    provider_config = ensure_market_enabled(settings, normalized_market).get(
        "provider_config", {}
    )
    return create_provider(
        provider_for_market(normalized_market),
        http_client=http_client,
        provider_config=provider_config,
    )


class BoxOfficeService(BoxOfficeProvider):
    """Compatibility facade that delegates to a concrete provider."""

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        market: str = DEFAULT_MARKET,
        provider: Optional[str] = None,
        provider_config: Optional[Dict[str, object]] = None,
    ):
        if isinstance(http_client, str) and provider is None and market == DEFAULT_MARKET:
            provider = http_client
            http_client = None

        if provider is not None and market == DEFAULT_MARKET:
            market = market_for_provider(provider)

        self.market_key = normalize_market(market)
        self.provider_key = normalize_provider(provider or provider_for_market(self.market_key))
        try:
            from ..utils.config import settings
            from .market_settings import ensure_market_enabled

            market_definition = ensure_market_enabled(settings, self.market_key)
            if provider_config is None:
                provider_config = market_definition.get("provider_config", {})
        except Exception:
            if provider_config is None:
                provider_config = None
            raise
        self._provider = create_provider(
            self.provider_key,
            http_client=http_client,
            provider_config=provider_config,
        )
        super().__init__(getattr(self._provider, "client", None))

    def close(self) -> None:
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()

    def __getattr__(self, item):
        """Delegate provider-specific helpers to the concrete provider."""
        return getattr(self._provider, item)

    def get_weekend_dates(self, date: Optional[datetime] = None):
        return self._provider.get_weekend_dates(date)

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        return self._provider.fetch_weekend_box_office(year, week, limit=limit)

    def get_current_week_movies(self, limit: int = 10) -> List[BoxOfficeMovie]:
        return self._provider.get_current_week_movies(limit=limit)

    def get_historical_movies(
        self, weeks_back: int = 1
    ) -> Dict[str, List[BoxOfficeMovie]]:
        return self._provider.get_historical_movies(weeks_back=weeks_back)


# Backward-compatible alias for the historical FR-only class name.
JPBoxOfficeFRProvider = JPBoxOfficeProvider
