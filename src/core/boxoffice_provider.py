"""Box office provider abstractions and registry helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .exceptions import BoxOfficeError

SUPPORTED_MARKETS: Tuple[str, ...] = ("us", "fr")
SUPPORTED_PROVIDERS: Tuple[str, ...] = ("mojo_us", "jpboxoffice_fr")
DEFAULT_MARKET = "us"
DEFAULT_PROVIDER = "mojo_us"
MARKET_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "us": {
        "label": "US Box Office",
        "provider": "mojo_us",
        "source": "boxofficemojo",
        "units": "usd",
    },
    "fr": {
        "label": "France Box Office",
        "provider": "jpboxoffice_fr",
        "source": "jpboxoffice",
        "units": "admissions",
    },
}
MARKET_TO_PROVIDER: Dict[str, str] = {
    market: definition["provider"] for market, definition in MARKET_DEFINITIONS.items()
}
PROVIDER_TO_MARKET: Dict[str, str] = {
    provider: market for market, provider in MARKET_TO_PROVIDER.items()
}


def normalize_provider(provider: Optional[str]) -> str:
    """Normalize and validate a provider identifier."""
    if provider is None or str(provider).strip() == "":
        return DEFAULT_PROVIDER

    normalized = str(provider).strip().lower()
    if normalized in SUPPORTED_PROVIDERS:
        return normalized

    raise ValueError(
        f"Unsupported provider '{provider}'. Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def normalize_market(market: Optional[str]) -> str:
    """Normalize and validate a market identifier."""
    if market is None or str(market).strip() == "":
        return DEFAULT_MARKET

    normalized = str(market).strip().lower()
    if normalized in SUPPORTED_MARKETS:
        return normalized

    if normalized in SUPPORTED_PROVIDERS:
        return PROVIDER_TO_MARKET[normalize_provider(normalized)]

    raise ValueError(
        f"Unsupported market '{market}'. Supported markets: {', '.join(SUPPORTED_MARKETS)}"
    )


def provider_for_market(market: Optional[str]) -> str:
    """Map a market identifier to a provider identifier."""
    market_key = normalize_market(market)
    return MARKET_TO_PROVIDER[market_key]


def provider_from_market(market: Optional[str]) -> str:
    """Backward-compatible alias for provider_for_market."""
    return provider_for_market(market)


def market_for_provider(provider: Optional[str]) -> str:
    """Map a provider identifier to a market identifier."""
    if provider is None or str(provider).strip() == "":
        return DEFAULT_MARKET

    candidate = str(provider).strip()
    normalized_candidate = candidate.lower()
    if normalized_candidate in SUPPORTED_PROVIDERS:
        return PROVIDER_TO_MARKET[normalize_provider(normalized_candidate)]

    if normalized_candidate in SUPPORTED_MARKETS:
        return normalize_market(normalized_candidate)

    raise ValueError(
        f"Unsupported provider '{provider}'. Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def market_from_provider(provider: Optional[str]) -> str:
    """Backward-compatible alias for market_for_provider."""
    return market_for_provider(provider)


def market_label(market: Optional[str]) -> str:
    """Return the display label for a market."""
    market_key = normalize_market(market)
    return MARKET_DEFINITIONS[market_key]["label"]


class BoxOfficeProvider(ABC):
    """Base class for box office data providers."""

    provider_key = DEFAULT_PROVIDER

    def __init__(self, http_client=None):
        self.client = http_client

    def get_weekend_dates(
        self, date: Optional[datetime] = None
    ) -> Tuple[datetime, datetime, int, int]:
        """Calculate the most recent completed weekend (Friday-Sunday)."""
        if date is None:
            date = datetime.now()

        today = date.date()
        weekday = today.weekday()
        days_since_friday = (weekday - 4) % 7

        if weekday in (4, 5, 6):
            days_since_friday += 7

        friday = datetime.combine(
            today - timedelta(days=days_since_friday), datetime.min.time()
        )
        sunday = friday + timedelta(days=2)
        year, week, _ = friday.isocalendar()
        return friday, sunday, year, week

    def get_current_week_movies(self, limit: int = 10):
        """Fetch the current week's movies."""
        _, _, year, week = self.get_weekend_dates()
        return self.fetch_weekend_box_office(year, week, limit=limit)

    def get_historical_movies(self, weeks_back: int = 1):
        """Fetch a small history of weekly movie data."""
        history = {}

        for i in range(weeks_back):
            date = datetime.now() - timedelta(weeks=i)
            _, _, year, week = self.get_weekend_dates(date)
            week_key = f"{year}W{week:02d}"

            try:
                history[week_key] = self.fetch_weekend_box_office(year, week)
            except BoxOfficeError:
                continue

        return history

    def extract_imdb_id(self, release_url: str) -> Optional[str]:
        """Fetch a release page and extract an IMDb ID when possible."""
        base_url = getattr(self, "BASE_URL", "")
        client = getattr(self, "client", None)
        if not base_url or not client or not release_url:
            return None

        try:
            url = f"{base_url}{release_url}"
            response = client.get(url)
            response.raise_for_status()
        except Exception:
            return None

        import re

        imdb_match = re.search(r"pro\.imdb\.com/title/(tt\d+)/", response.text)
        return imdb_match.group(1) if imdb_match else None

    def enrich_with_imdb_ids(self, movies) -> None:
        """Enrich movies in-place with IMDb IDs when the provider exposes release URLs."""
        count = 0
        for movie in movies:
            release_url = getattr(movie, "release_url", None)
            if not release_url:
                continue

            imdb_id = self.extract_imdb_id(release_url)
            if imdb_id:
                movie.imdb_id = imdb_id
                count += 1

        if movies:
            from ..utils.logger import get_logger

            get_logger(__name__).info(f"Enriched {count}/{len(movies)} movies with IMDb IDs")

    @abstractmethod
    def fetch_weekend_box_office(self, year=None, week=None, limit: int = 10):
        """Fetch movie rankings for a specific weekend."""
