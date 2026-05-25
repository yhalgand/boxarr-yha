"""Box office providers and compatibility service facade."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional

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
    provider_for_market,
)
from .exceptions import BoxOfficeError

logger = get_logger(__name__)


@dataclass
class BoxOfficeMovie:
    """Represents a movie in the box office rankings."""

    rank: int
    title: str
    weekend_gross: Optional[float] = None
    total_gross: Optional[float] = None
    weeks_released: Optional[int] = None
    theater_count: Optional[int] = None
    imdb_id: Optional[str] = None
    release_url: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class MojoUSProvider(BoxOfficeProvider):
    """Box Office Mojo US provider."""

    provider_key = "mojo_us"
    BASE_URL = "https://www.boxofficemojo.com"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    def __init__(self, http_client: Optional[httpx.Client] = None):
        super().__init__(
            http_client
            or httpx.Client(
                headers={"User-Agent": self.USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
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
    """Stub provider for a future French box office source."""

    provider_key = "jpboxoffice_fr"

    def fetch_weekend_box_office(
        self,
        year: Optional[int] = None,
        week: Optional[int] = None,
        limit: int = 10,
    ) -> List[BoxOfficeMovie]:
        raise BoxOfficeError(
            "Provider 'jpboxoffice_fr' is not implemented yet"
        )


def create_provider(provider: Optional[str] = None, http_client=None) -> BoxOfficeProvider:
    """Create a concrete provider instance from a provider id."""
    normalized = normalize_provider(provider)
    if normalized == "mojo_us":
        return MojoUSProvider(http_client=http_client)
    if normalized == "jpboxoffice_fr":
        return JPBoxOfficeFRProvider(http_client=http_client)

    raise BoxOfficeError(f"Unsupported provider '{provider}'")


def create_provider_for_market(
    market: Optional[str] = None, http_client=None
) -> BoxOfficeProvider:
    """Create a provider instance from a market id."""
    normalized_market = normalize_market(market)
    return create_provider(provider_for_market(normalized_market), http_client=http_client)


class BoxOfficeService(BoxOfficeProvider):
    """Compatibility facade that delegates to a concrete provider."""

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        market: str = DEFAULT_MARKET,
        provider: Optional[str] = None,
    ):
        if isinstance(http_client, str) and provider is None and market == DEFAULT_MARKET:
            provider = http_client
            http_client = None

        if provider is not None and market == DEFAULT_MARKET:
            market = market_for_provider(provider)

        self.market_key = normalize_market(market)
        self.provider_key = normalize_provider(provider or provider_for_market(self.market_key))
        self._provider = create_provider(
            self.provider_key, http_client=http_client
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
