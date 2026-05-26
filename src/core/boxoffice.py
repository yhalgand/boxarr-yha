"""Box office providers and compatibility service facade."""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from ..utils.logger import get_logger
from .boxoffice_provider import (
    DEFAULT_MARKET,
    DEFAULT_PROVIDER,
    BoxOfficeProvider,
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


class JPBoxOfficeFRProvider(BoxOfficeProvider):
    """JPBoxOffice France provider.

    The logical model reuses ``weekend_gross`` and ``total_gross`` for
    compatibility with the rest of Boxarr, but for ``market=fr`` those values
    represent admissions/entries rather than USD revenue.
    """

    provider_key = "jpboxoffice"
    BASE_URL = "https://www.jpbox-office.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 Boxarr/1.7.0"
    )
    REQUEST_TIMEOUT = 30.0
    DEBUG_DUMP_ENABLED = str(
        __import__("os").environ.get("BOXARR_JPBOXOFFICE_DEBUG_DUMP", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    DEBUG_DUMP_DIR = Path(__import__("os").environ.get("BOXARR_JPBOXOFFICE_DEBUG_DIR", "/tmp"))

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
        if self.country != "fr":
            raise BoxOfficeError(
                f"JPBoxOffice country '{self.country}' is not implemented yet"
            )

    def close(self) -> None:
        if self.client:
            self.client.close()

    def _fetch_html(self, url: str) -> str:
        logger.info(f"Fetching JPBoxOffice data from: {url}")
        try:
            response = self.client.get(url)
            response.raise_for_status()
            html = response.text
            if self.DEBUG_DUMP_ENABLED:
                self._dump_debug_html(url, html)
            return html
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch JPBoxOffice data: {e}")
            raise BoxOfficeError(f"Failed to fetch JPBoxOffice data: {e}") from e
        except Exception as e:
            logger.error(f"Failed to fetch JPBoxOffice data: {e}")
            raise BoxOfficeError(f"Failed to fetch JPBoxOffice data: {e}") from e

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
        return f"{self.BASE_URL}/v9_hebdomadaire.php?view=2&year={year}"

    def _resolve_weekly_page_url(self, year: int, week: int) -> str:
        """Resolve the weekly page URL via the annual listing page."""
        listing_html = self._fetch_html(self._year_listing_url(year))
        soup = BeautifulSoup(listing_html, "html.parser")

        candidate_href = None
        week_text = str(week)

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", ""))
            if "v9_tophebdo.php" not in href:
                continue

            text = anchor.get_text(" ", strip=True)
            if text == week_text:
                candidate_href = href
                break

            row = anchor.find_parent("tr")
            if row:
                row_text = " ".join(row.stripped_strings)
                if re.search(rf"\bSemaine\s+{week}\b", row_text, re.IGNORECASE):
                    candidate_href = href
                    break
                if re.search(rf"\b{week}\b", row_text) and "Janvier" in row_text:
                    candidate_href = href

        if not candidate_href:
            raise BoxOfficeError(
                f"Could not resolve JPBoxOffice weekly page for {year}W{week:02d}"
            )

        if candidate_href.startswith("http"):
            return candidate_href
        return f"{self.BASE_URL}/{candidate_href.lstrip('/')}"

    def _normalize_space(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

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
        if line in {"Image", "Entrées Hebdomadaires 2026"}:
            return False
        if line.startswith("(") and line.endswith(")"):
            return False
        if re.fullmatch(r"[+-]?\d+", line):
            return False
        if "%" in line:
            return False
        return not re.search(r"\b(France|Etats-Unis|Royaume-Uni|Espagne|Allemagne|Italie|Brésil|Iran|Japon)\b", line)

    def _find_title(self, block_lines: List[str]) -> Optional[str]:
        for line in block_lines:
            if self._is_title_line(line) and re.search(r"[A-Za-zÀ-ÿ]", line):
                return self._normalize_space(line)
        return None

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

        is_new_release = metrics["weeks_released"] == 1
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
        )

    def _parse_weekly_page(self, html: str, limit: int = 10) -> List[BoxOfficeMovie]:
        soup = BeautifulSoup(html, "html.parser")
        release_urls: Dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", ""))
            if "fichfilm.php" not in href:
                continue
            title_text = self._normalize_space(anchor.get_text(" ", strip=True))
            if title_text:
                release_urls[self._title_key(title_text)] = href if href.startswith("/") else f"/{href.lstrip('/')}"
        tables = soup.find_all("table")
        logger.debug(
            "JPBoxOffice live parse: %s tables, %s release links",
            len(tables),
            len(release_urls),
        )

        target_table = None
        target_rows: List = []
        target_score = 0
        for table in tables:
            rows = table.find_all("tr")
            ranked_rows = []
            for row in rows:
                title_cell = row.find("td", class_=re.compile(r"col_poster_titre"))
                rank_cell = row.find("td", class_=re.compile(r"col_poster_compteur"))
                value_cells = row.find_all(
                    "td", class_=re.compile(r"col_poster_contenu_majeur")
                )
                if title_cell and rank_cell and len(value_cells) >= 6:
                    ranked_rows.append(row)

            if len(ranked_rows) > target_score:
                target_score = len(ranked_rows)
                target_table = table
                target_rows = ranked_rows

        if not target_table or not target_rows:
            # Fall back to the text-only parser only if the live table shape changes.
            raise BoxOfficeError("No JPBoxOffice rankings table found")

        logger.debug(
            "JPBoxOffice selected table: %s rows with ranking data", len(target_rows)
        )

        movies: List[BoxOfficeMovie] = []
        ignored_rows = []
        detected_ranks: List[int] = []
        for row in target_rows[:limit]:
            rank_cell = row.find("td", class_=re.compile(r"col_poster_compteur"))
            title_cell = row.find("td", class_=re.compile(r"col_poster_titre"))
            value_cells = row.find_all("td", class_=re.compile(r"col_poster_contenu_majeur"))

            if not rank_cell or not title_cell or len(value_cells) < 6:
                ignored_rows.append(("missing_cells", row.get_text(" ", strip=True)[:200]))
                continue

            rank_div = rank_cell.find("div", class_=re.compile(r"compteur"))
            rank_text = rank_div.get_text(" ", strip=True) if rank_div else rank_cell.get_text(" ", strip=True)
            rank = self._parse_int(rank_text, first_only=True)
            if rank is None:
                ignored_rows.append(("bad_rank", rank_cell.get_text(" ", strip=True)))
                continue

            title_link = title_cell.find("a", href=True)
            if not title_link:
                ignored_rows.append(("missing_title_link", title_cell.get_text(" ", strip=True)))
                continue

            title = self._normalize_space(title_link.get_text(" ", strip=True))
            release_url = str(title_link.get("href", ""))
            if release_url and not release_url.startswith("/"):
                release_url = f"/{release_url.lstrip('/')}"
            release_url = release_urls.get(self._title_key(title), release_url)
            original_title, year = self._extract_fr_title_metadata(title_cell, title)

            weeks_released = self._parse_int(value_cells[0].get_text(" ", strip=True), first_only=True)
            weekend_gross = self._parse_number(value_cells[1].get_text(" ", strip=True), first_only=True)
            theater_count = self._parse_int(value_cells[3].get_text(" ", strip=True), first_only=True)
            total_gross = self._parse_number(value_cells[5].get_text(" ", strip=True), first_only=True)

            if weekend_gross is None or total_gross is None:
                ignored_rows.append(
                    (
                        "missing_metrics",
                        f"rank={rank} title={title} cells={[cell.get_text(' ', strip=True) for cell in value_cells]}",
                    )
                )
                continue

            is_new_release = "N" in rank_cell.get_text(" ", strip=True) or weeks_released == 1
            if weeks_released is None and is_new_release:
                weeks_released = 1

            movie = BoxOfficeMovie(
                rank=rank,
                title=title,
                weekend_gross=weekend_gross,
                total_gross=total_gross,
                weeks_released=weeks_released,
                theater_count=theater_count,
                original_title=original_title,
                year=year,
                release_url=release_url,
            )
            movies.append(movie)
            detected_ranks.append(rank)
            logger.debug(
                "Parsed JPBoxOffice row: rank=%s title=%s original=%s year=%s weeks=%s weekly=%s total=%s copies=%s new=%s",
                rank,
                title,
                original_title,
                year,
                weeks_released,
                weekend_gross,
                total_gross,
                theater_count,
                is_new_release,
            )

        if not movies:
            raise BoxOfficeError("No movies found in JPBoxOffice data")

        logger.debug("JPBoxOffice detected ranks: %s", detected_ranks)
        if ignored_rows:
            logger.debug("JPBoxOffice ignored rows: %s", ignored_rows)

        movies.sort(key=lambda movie: movie.rank)
        logger.info("Successfully parsed %s movies from JPBoxOffice", len(movies))
        return movies

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        if year is None or week is None:
            _, _, year, week = self.get_weekend_dates()

        weekly_url = self._resolve_weekly_page_url(year, week)
        html = self._fetch_html(weekly_url)
        movies = self._parse_weekly_page(html, limit=limit)
        self.enrich_with_imdb_ids(movies)
        return movies


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
        return JPBoxOfficeFRProvider(
            http_client=http_client, provider_config=provider_config
        )

    raise BoxOfficeError(f"Unsupported provider '{provider}'")


def create_provider_for_market(
    market: Optional[str] = None, http_client=None
) -> BoxOfficeProvider:
    """Create a provider instance from a market id."""
    normalized_market = normalize_market(market)
    provider_config = None
    try:
        from ..utils.config import settings
        from .market_settings import get_market_definition

        provider_config = get_market_definition(settings, normalized_market).get(
            "provider_config", {}
        )
    except Exception:
        provider_config = None
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
        if provider_config is None:
            try:
                from ..utils.config import settings
                from .market_settings import get_market_definition

                provider_config = get_market_definition(settings, self.market_key).get(
                    "provider_config", {}
                )
            except Exception:
                provider_config = None
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
