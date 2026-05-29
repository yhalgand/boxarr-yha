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
        self.country_spec = get_jpboxoffice_country_spec(self.country)
        if not self.country_spec:
            raise BoxOfficeError(
                f"JPBoxOffice country '{self.country}' is not implemented yet"
            )
        self.view = int(self.country_spec.get("view", 2))
        self.min_year = int(self.country_spec.get("min_year", 1982))

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
        return f"{self.BASE_URL}/v9_hebdomadaire.php?view={self.view}&year={year}"

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
            best_score, _, _, best_nodes = container_candidates[0]
            logger.debug(
                "JPBoxOffice selected ranking container score=%s candidates=%s",
                best_score,
                len(container_candidates),
            )
            return list(best_nodes)

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
            if title and title.strip().lower() == "image":
                title = None
            href = str(anchor.get("href", ""))
            if href:
                release_url = href if href.startswith("/") else f"/{href.lstrip('/')}"
        if not title:
            title = self._find_title(lines)
        if not title:
            return None, "missing_title", {"extracted_rank": None, "rank_source": "missing"}
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
        parsed_rows = []
        for index, node in enumerate(candidate_nodes[:limit], start=1):
            movie, reason, parsed_meta = self._parse_candidate_node(
                node, fallback_rank=index, release_urls=release_urls
            )
            if movie is None:
                skipped_rows.append(
                    {
                        "reason": reason or "unknown",
                        "text": self._normalize_space(node.get_text(" ", strip=True))[:240],
                        **parsed_meta,
                    }
                )
                continue
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

        rows_seen = min(len(candidate_nodes), limit)
        rows_parsed = len(movies)
        rows_skipped = len(skipped_rows)

        self.last_parse_diagnostics = {
            "source_url": source_url,
            "country": self.country,
            "view": self.view,
            "rows_seen": rows_seen,
            "rows_parsed": rows_parsed,
            "rows_skipped": rows_skipped,
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
        if rows_seen and rows_parsed < rows_seen:
            raise BoxOfficeError(
                "JPBoxOffice parse error: partial ranking parse "
                f"(source_url={source_url}, country={self.country}, view={self.view}, "
                f"rows_seen={rows_seen}, rows_parsed={rows_parsed}, rows_skipped={rows_skipped}, "
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

        weekly_url = self._resolve_weekly_page_url(year, week)
        html = self._fetch_html(weekly_url)
        movies = self._parse_weekly_page(html, limit=limit, source_url=weekly_url)
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
        return JPBoxOfficeProvider(
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
