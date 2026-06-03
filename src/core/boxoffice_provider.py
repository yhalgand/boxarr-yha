"""Box office provider abstractions and registry helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .exceptions import BoxOfficeError

SUPPORTED_MARKETS: Tuple[str, ...] = ("us", "fr")
SUPPORTED_PROVIDERS: Tuple[str, ...] = (
    "mojo",
    "jpboxoffice",
    "allocine",
    "france_boxoffice",
    "mojo_us",
    "jpboxoffice_fr",
    "allocine_fr",
)
DEFAULT_MARKET = "us"
DEFAULT_PROVIDER = "mojo"
JPBOXOFFICE_COUNTRY_SPECS: Dict[str, Dict[str, Any]] = {
    "fr": {
        "label": "France",
        "view": 2,
        "min_year": 1993,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "de": {
        "label": "Germany / Allemagne",
        "view": 4,
        "min_year": 1976,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "br": {
        "label": "Brazil / Brésil",
        "view": 36,
        "min_year": 1976,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "cn": {
        "label": "China / Chine",
        "view": 30,
        "min_year": 2002,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "kr": {
        "label": "South Korea / Corée du Sud",
        "view": 34,
        "min_year": 1976,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "es": {
        "label": "Spain / Espagne",
        "view": 33,
        "min_year": 1976,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "it": {
        "label": "Italy / Italie",
        "view": 32,
        "min_year": 1976,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
    "ru": {
        "label": "Russia / Russie",
        "view": 35,
        "min_year": 1997,
        "supports_historical_update": True,
        "supports_live_fetch": True,
    },
}
MARKET_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "us": {
        "label": "US Box Office",
        "provider": "mojo",
        "source": "boxofficemojo",
        "units": "usd",
    },
    "fr": {
        "label": "France Box Office",
        "provider": "france_boxoffice",
        "source": "allocine+jpboxoffice",
        "units": "admissions",
    },
}
MARKET_TO_PROVIDER: Dict[str, str] = {
    market: definition["provider"] for market, definition in MARKET_DEFINITIONS.items()
}
PROVIDER_TO_MARKET: Dict[str, str] = {
    provider: market for market, provider in MARKET_TO_PROVIDER.items()
}
PROVIDER_TO_MARKET.update(
    {
        "jpboxoffice": "fr",
        "allocine": "fr",
    }
)
PROVIDER_ALIAS_MAP: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "mojo_us": ("mojo", {"area": "us"}),
    "jpboxoffice_fr": ("jpboxoffice", {"country": "fr"}),
    "allocine_fr": ("allocine", {"country": "fr"}),
}
PROVIDER_FAMILY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "mojo": {"area": "us"},
    "jpboxoffice": {"country": "fr"},
    "allocine": {"country": "fr", "min_entries": 10},
    "france_boxoffice": {
        "country": "fr",
        "primary": "allocine",
        "fallback": "jpboxoffice",
        "min_entries": 10,
    },
}


def get_supported_jpboxoffice_countries() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the supported JPBoxOffice country registry."""
    return deepcopy(JPBOXOFFICE_COUNTRY_SPECS)


def get_jpboxoffice_country_spec(country: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the configured JPBoxOffice country spec, if supported."""
    normalized = str(country or "").strip().lower()
    if not normalized:
        return None
    spec = JPBOXOFFICE_COUNTRY_SPECS.get(normalized)
    return deepcopy(spec) if spec else None


def get_boxoffice_provider_capabilities(
    provider: Optional[str], provider_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Return provider capability metadata without making any network calls."""
    normalized_provider = normalize_provider(provider)
    current_year = datetime.now().year

    if normalized_provider == "mojo":
        return {
            "provider": "mojo",
            "live": {"supports_live_fetch": True},
            "historical": {
                "supports_historical_update": True,
                "min_year": 1982,
                "max_year": current_year,
            },
        }

    if normalized_provider == "jpboxoffice":
        normalized_config = normalize_provider_config(normalized_provider, provider_config)
        country = str(normalized_config.get("country", "fr")).strip().lower()
        spec = JPBOXOFFICE_COUNTRY_SPECS.get(country)
        if not spec:
            return {
                "provider": "jpboxoffice",
                "country": country,
                "jpboxoffice_view": None,
                "live": {"supports_live_fetch": False},
                "historical": {
                    "supports_historical_update": False,
                    "min_year": None,
                    "max_year": current_year,
                },
            }

        return {
            "provider": "jpboxoffice",
            "country": country,
            "country_label": spec.get("label"),
            "jpboxoffice_view": spec.get("view"),
            "live": {
                "supports_live_fetch": bool(spec.get("supports_live_fetch", False))
            },
            "historical": {
                "supports_historical_update": bool(
                    spec.get("supports_historical_update", False)
                ),
                "min_year": spec.get("min_year"),
                "max_year": current_year,
            },
        }

    if normalized_provider == "allocine":
        normalized_config = normalize_provider_config(normalized_provider, provider_config)
        country = str(normalized_config.get("country", "fr")).strip().lower()
        supported = country == "fr"
        return {
            "provider": "allocine",
            "country": country,
            "country_label": "France" if supported else None,
            "live": {"supports_live_fetch": supported},
            "historical": {
                "supports_historical_update": supported,
                "min_year": 1998 if supported else None,
                "soft_min_year": 2001 if supported else None,
                "max_year": current_year,
                "min_entries": int(normalized_config.get("min_entries", 10) or 10),
            },
        }

    if normalized_provider == "france_boxoffice":
        normalized_config = normalize_provider_config(normalized_provider, provider_config)
        return {
            "provider": "france_boxoffice",
            "country": "fr",
            "country_label": "France",
            "primary_provider": normalized_config.get("primary", "allocine"),
            "fallback_provider": normalized_config.get("fallback", "jpboxoffice"),
            "live": {"supports_live_fetch": True},
            "historical": {
                "supports_historical_update": True,
                "min_year": 1998,
                "soft_min_year": 2001,
                "max_year": current_year,
                "min_entries": int(normalized_config.get("min_entries", 10) or 10),
            },
        }

    return {
        "provider": normalized_provider,
        "live": {"supports_live_fetch": False},
        "historical": {
            "supports_historical_update": False,
            "min_year": None,
            "max_year": current_year,
        },
    }


def normalize_provider_config(
    provider: Optional[str], provider_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Normalize provider-specific config and fill in family defaults."""
    provider_key = normalize_provider(provider)
    normalized_config: Dict[str, Any] = dict(provider_config or {})

    alias_default = PROVIDER_ALIAS_MAP.get(str(provider or "").strip().lower())
    if alias_default and provider_key == alias_default[0]:
        for key, value in alias_default[1].items():
            normalized_config.setdefault(key, value)

    for key, value in PROVIDER_FAMILY_DEFAULTS.get(provider_key, {}).items():
        normalized_config.setdefault(key, value)

    return normalized_config


def provider_aliases(
    provider: Optional[str], provider_config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Return legacy aliases for a canonical provider when possible."""
    normalized_provider = normalize_provider(provider)
    normalized_config = normalize_provider_config(normalized_provider, provider_config)

    aliases: List[str] = []
    if normalized_provider == "mojo" and normalized_config.get("area"):
        aliases.append(f"mojo_{str(normalized_config['area']).strip().lower()}")
    elif normalized_provider == "jpboxoffice" and normalized_config.get("country"):
        aliases.append(
            f"jpboxoffice_{str(normalized_config['country']).strip().lower()}"
        )
    elif normalized_provider == "allocine" and normalized_config.get("country"):
        aliases.append(
            f"allocine_{str(normalized_config['country']).strip().lower()}"
        )
    elif normalized_provider == "france_boxoffice":
        aliases.extend(["allocine_fr", "jpboxoffice_fr"])

    return aliases


def canonicalize_provider_definition(
    provider: Optional[str],
    provider_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return canonical provider metadata plus compatibility aliases."""
    canonical_provider = normalize_provider(provider)
    canonical_config = normalize_provider_config(canonical_provider, provider_config)
    return {
        "provider": canonical_provider,
        "provider_config": canonical_config,
        "aliases": provider_aliases(canonical_provider, canonical_config),
    }


def _runtime_market_registry() -> Dict[str, Dict[str, object]]:
    """Return the configured market registry when settings are available."""
    try:
        from ..utils.config import settings
        from .market_settings import get_configured_markets

        return get_configured_markets(settings)
    except Exception:
        return {}


def normalize_provider(provider: Optional[str]) -> str:
    """Normalize and validate a provider identifier."""
    if provider is None or str(provider).strip() == "":
        return DEFAULT_PROVIDER

    normalized = str(provider).strip().lower()
    if normalized in SUPPORTED_PROVIDERS:
        alias = PROVIDER_ALIAS_MAP.get(normalized)
        if alias:
            return alias[0]
        return normalized

    registry = _runtime_market_registry()
    for definition in registry.values():
        if str(definition.get("provider", "")).strip().lower() == normalized:
            return str(definition.get("provider", "")).strip().lower()

    raise ValueError(
        f"Unsupported provider '{provider}'. Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def normalize_market(market: Optional[str]) -> str:
    """Normalize and validate a market identifier."""
    if market is None or str(market).strip() == "":
        return DEFAULT_MARKET

    normalized = str(market).strip().lower()
    registry = _runtime_market_registry()
    if normalized in registry:
        return normalized
    if normalized in SUPPORTED_MARKETS:
        return normalized

    if normalized in SUPPORTED_PROVIDERS:
        return PROVIDER_TO_MARKET[normalize_provider(normalized)]

    for market_key, definition in registry.items():
        provider = str(definition.get("provider", "")).strip().lower()
        if provider and provider == normalized:
            return market_key

    supported_markets = sorted(set(SUPPORTED_MARKETS) | set(registry.keys()))
    raise ValueError(
        f"Unsupported market '{market}'. Supported markets: {', '.join(supported_markets)}"
    )


def provider_for_market(market: Optional[str]) -> str:
    """Map a market identifier to a provider identifier."""
    market_key = normalize_market(market)
    registry = _runtime_market_registry()
    if market_key in registry:
        provider = str(registry[market_key].get("provider", "")).strip().lower()
        if provider:
            return provider
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

    registry = _runtime_market_registry()
    for market_key, definition in registry.items():
        if str(definition.get("provider", "")).strip().lower() == normalized_candidate:
            return market_key

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
    registry = _runtime_market_registry()
    if market_key in registry and registry[market_key].get("label"):
        return str(registry[market_key]["label"])
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
