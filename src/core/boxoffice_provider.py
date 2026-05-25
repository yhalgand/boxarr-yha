"""Box office provider abstractions and registry helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .exceptions import BoxOfficeError

SUPPORTED_PROVIDERS: Tuple[str, ...] = ("mojo_us", "jpboxoffice_fr")
DEFAULT_PROVIDER = "mojo_us"
MARKET_TO_PROVIDER: Dict[str, str] = {
    "US": "mojo_us",
    "FR": "jpboxoffice_fr",
}
PROVIDER_TO_MARKET: Dict[str, str] = {value: key for key, value in MARKET_TO_PROVIDER.items()}


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


def provider_from_market(market: Optional[str]) -> str:
    """Map a simple market selector to a provider identifier."""
    if market is None or str(market).strip() == "":
        return DEFAULT_PROVIDER

    candidate = str(market).strip()
    normalized_candidate = candidate.lower()
    if normalized_candidate in SUPPORTED_PROVIDERS:
        return normalize_provider(normalized_candidate)

    market_code = candidate.upper()
    if market_code in MARKET_TO_PROVIDER:
        return MARKET_TO_PROVIDER[market_code]

    raise ValueError(
        f"Unsupported market '{market}'. Supported markets: {', '.join(sorted(MARKET_TO_PROVIDER))}"
    )


def market_from_provider(provider: Optional[str]) -> str:
    """Map a provider identifier back to the UI market selector."""
    normalized = normalize_provider(provider)
    return PROVIDER_TO_MARKET.get(normalized, "US")


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

    @abstractmethod
    def fetch_weekend_box_office(self, year=None, week=None, limit: int = 10):
        """Fetch movie rankings for a specific weekend."""

