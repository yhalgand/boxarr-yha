"""Helpers for market registry and effective market-specific settings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

from ..utils.config import MarketConfig, Settings
from ..utils.logger import get_logger
from .boxoffice_provider import (
    DEFAULT_MARKET,
    canonicalize_provider_definition,
    get_boxoffice_provider_capabilities,
    get_supported_jpboxoffice_countries,
)

logger = get_logger(__name__)

_DEFAULT_MARKET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "us": {
        "label": "US Box Office",
        "provider": "mojo",
        "provider_config": {"area": "us"},
        "enabled": True,
    },
    "fr": {
        "label": "France Box Office",
        "provider": "france_boxoffice",
        "provider_config": {
            "country": "fr",
            "primary": "allocine",
            "fallback": "jpboxoffice",
            "min_entries": 10,
        },
        "enabled": True,
    },
}

_EFFECTIVE_FIELD_MAP: Dict[str, str] = {
    "box_office_fetch_limit": "boxarr_features_box_office_limit",
    "maximum_movies_to_add": "boxarr_features_auto_add_limit",
    "auto_add_enabled": "boxarr_features_auto_add",
    "auto_tag_text": "boxarr_features_auto_tag_text",
    "root_folder": "radarr_root_folder",
    "quality_profile_default": "radarr_quality_profile_default",
    "quality_profile_upgrade": "radarr_quality_profile_upgrade",
    "minimum_availability_enabled": "radarr_minimum_availability_enabled",
    "minimum_availability": "radarr_minimum_availability",
    "monitor_option": "radarr_monitor_option",
    "search_on_add": "radarr_search_for_movie",
    "language_filter_enabled": "boxarr_features_auto_add_language_filter_enabled",
    "language_filter_mode": "boxarr_features_auto_add_language_filter_mode",
    "language_whitelist": "boxarr_features_auto_add_language_whitelist",
    "language_blacklist": "boxarr_features_auto_add_language_blacklist",
    "ignore_rereleases": "boxarr_features_auto_add_ignore_rereleases",
    "scheduler_enabled": "boxarr_scheduler_enabled",
    "scheduler_cron": "boxarr_scheduler_cron",
}

_LEGACY_ACTIVE_TAGS = {"boxarr", "boxarr-keep"}


def _normalize_key(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def market_config_to_dict(market_config: Any) -> Dict[str, Any]:
    """Normalize a market config object or mapping into a plain dict."""
    if market_config is None:
        return {}
    if isinstance(market_config, MarketConfig):
        return dict(market_config.model_dump(exclude_none=False))
    if isinstance(market_config, dict):
        return dict(market_config)
    if hasattr(market_config, "model_dump"):
        return dict(market_config.model_dump(exclude_none=False))
    try:
        return dict(market_config)
    except Exception:
        return {}


def _normalize_tag_list(values: Optional[Iterable[Any]]) -> List[str]:
    tags: List[str] = []
    for value in values or []:
        label = str(value).strip()
        if label:
            tags.append(label)
    return tags


def canonical_active_tags(
    market_key: str,
    *,
    auto_tag_text: Optional[str] = None,
    extra_tags: Optional[Iterable[Any]] = None,
    include_market_tag: bool = True,
) -> List[str]:
    """Return canonical active tags for a market, filtering legacy tags."""

    market_key = _normalize_key(market_key)
    base_tags = ["boxarr-added"]
    if include_market_tag:
        base_tags.append(f"boxarr-market-{market_key}")
    active_tags: List[str] = list(base_tags)
    seen = {tag.lower() for tag in active_tags}

    candidates: List[str] = []
    if auto_tag_text is not None:
        candidates.append(str(auto_tag_text))
    candidates.extend(_normalize_tag_list(extra_tags))

    for candidate in candidates:
        normalized = str(candidate).strip()
        if not normalized:
            continue
        normalized_lower = normalized.lower()
        if normalized_lower in _LEGACY_ACTIVE_TAGS:
            continue
        if normalized_lower in seen:
            continue
        seen.add(normalized_lower)
        active_tags.append(normalized)

    return active_tags


def canonical_auto_tag_text(value: Optional[Any]) -> str:
    """Return the canonical active auto-tag text, filtering legacy values."""
    normalized = str(value or "").strip()
    if not normalized or normalized.lower() in _LEGACY_ACTIVE_TAGS:
        return "boxarr-added"
    return normalized


def _canonicalize_provider_fields(
    provider: Any, provider_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    provider_value = str(provider or "").strip()
    if not provider_value:
        return canonicalize_provider_definition("mojo", {"area": "us"})
    return canonicalize_provider_definition(provider_value, provider_config)


def _market_capabilities(
    provider: Any, provider_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    capabilities = deepcopy(
        get_boxoffice_provider_capabilities(provider, provider_config)
    )
    return {
        "provider": capabilities.get("provider"),
        "country": capabilities.get("country"),
        "country_label": capabilities.get("country_label"),
        "jpboxoffice_view": capabilities.get("jpboxoffice_view"),
        "live": dict(capabilities.get("live", {})),
        "historical": dict(capabilities.get("historical", {})),
    }


def _configured_market_overrides(settings_obj: Settings) -> Dict[str, Dict[str, Any]]:
    overrides: Dict[str, Dict[str, Any]] = {}
    markets = getattr(settings_obj, "markets", {}) or {}
    if not isinstance(markets, dict):
        return overrides

    for market_key, market_config in markets.items():
        key = _normalize_key(market_key)
        if not key:
            continue

        try:
            overrides[key] = market_config_to_dict(market_config)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Ignoring malformed market config for %s: %s", key, exc)
            continue

    return overrides


def _merged_market_registry(settings_obj: Settings) -> Dict[str, Dict[str, Any]]:
    registry: Dict[str, Dict[str, Any]] = {
        key: {
            "market": key,
            "label": value["label"],
            "provider": _canonicalize_provider_fields(
                value.get("provider"), value.get("provider_config", {})
            )["provider"],
            "provider_config": deepcopy(
                _canonicalize_provider_fields(
                    value.get("provider"), value.get("provider_config", {})
                )["provider_config"]
            ),
            "aliases": list(
                _canonicalize_provider_fields(
                    value.get("provider"), value.get("provider_config", {})
                )["aliases"]
            ),
            "enabled": value.get("enabled", True),
            "configured": False,
            "overrides": {},
            "capabilities": _market_capabilities(
                value.get("provider"), value.get("provider_config", {})
            ),
        }
        for key, value in _DEFAULT_MARKET_CONFIGS.items()
    }

    for key, override in _configured_market_overrides(settings_obj).items():
        canonical = _canonicalize_provider_fields(
            override.get("provider"), override.get("provider_config", {})
        )
        base = registry.get(
            key,
            {
                "market": key,
                "label": key.upper(),
                "provider": canonical["provider"],
                "provider_config": {},
                "aliases": list(canonical.get("aliases", [])),
                "enabled": True,
                "configured": False,
                "overrides": {},
                "capabilities": _market_capabilities(
                    canonical["provider"], canonical.get("provider_config", {})
                ),
            },
        )
        merged = {
            **base,
            "market": key,
            "label": override.get("label", base.get("label") or key.upper()),
            "provider": canonical["provider"] or base.get("provider"),
            "provider_config": {
                **deepcopy(base.get("provider_config", {})),
                **deepcopy(canonical.get("provider_config", {})),
            },
            "aliases": list(canonical.get("aliases", base.get("aliases", []))),
            "enabled": override.get("enabled", base.get("enabled", True)),
            "configured": True,
            "overrides": override,
            "capabilities": _market_capabilities(
                canonical["provider"] or base.get("provider"),
                {
                    **deepcopy(base.get("provider_config", {})),
                    **deepcopy(canonical.get("provider_config", {})),
                },
            ),
        }
        registry[key] = merged

    return registry


def get_configured_markets(settings_obj: Settings) -> Dict[str, Dict[str, Any]]:
    """Return the configured markets merged with defaults.

    When ``settings.markets`` is missing or empty, this returns the default
    US/FR markets so the current app behaviour remains unchanged.
    """

    return _merged_market_registry(settings_obj)


def get_market_definition(settings_obj: Settings, market: str) -> Dict[str, Any]:
    """Return the merged definition for a single market or raise if missing."""

    market_key = _normalize_key(market)
    registry = get_configured_markets(settings_obj)
    if market_key not in registry:
        raise ValueError(
            f"Unsupported market '{market}'. Supported markets: {', '.join(sorted(registry.keys()))}"
        )
    return market_config_to_dict(registry[market_key])


def ensure_market_enabled(settings_obj: Settings, market: str) -> Dict[str, Any]:
    """Return the market definition or raise when the market is disabled."""
    definition = get_market_definition(settings_obj, market)
    if not bool(definition.get("enabled", True)):
        raise ValueError(f"Market '{definition['market']}' is disabled")
    return definition


def _global_value(settings_obj: Settings, field_name: str) -> Any:
    value = getattr(settings_obj, field_name)
    if hasattr(value, "value"):
        return getattr(value, "value")
    if isinstance(value, list):
        return list(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _resolve_with_source(
    settings_obj: Settings,
    overrides: Dict[str, Any],
    field_name: str,
    global_field: str,
) -> Dict[str, Any]:
    value = overrides.get(field_name)
    if value is not None:
        if hasattr(value, "value"):
            value = getattr(value, "value")
        return {"value": value, "source": "market"}

    return {"value": _global_value(settings_obj, global_field), "source": "global"}


def get_effective_market_settings(settings_obj: Settings, market: str) -> Dict[str, Any]:
    """Return the effective settings for a market with per-field provenance."""

    definition = market_config_to_dict(get_market_definition(settings_obj, market))
    overrides = dict(definition.get("overrides", {}) or {})

    effective: Dict[str, Any] = {}
    sources: Dict[str, str] = {}

    for field_name, global_field in _EFFECTIVE_FIELD_MAP.items():
        resolved = _resolve_with_source(settings_obj, overrides, field_name, global_field)
        effective[field_name] = resolved["value"]
        sources[field_name] = resolved["source"]

    auto_tag_text = canonical_auto_tag_text(effective.get("auto_tag_text"))
    effective["auto_tag_text"] = auto_tag_text
    tags = overrides.get("tags")
    if tags is not None:
        effective["tags"] = canonical_active_tags(
            definition["market"],
            auto_tag_text=auto_tag_text,
            extra_tags=tags,
        )
        sources["tags"] = "market"
    else:
        effective["tags"] = canonical_active_tags(
            definition["market"], auto_tag_text=auto_tag_text
        )
        sources["tags"] = sources.get("auto_tag_text", "global")

    cleanup_tag = overrides.get("cleanup_protect_tag")
    if cleanup_tag is not None:
        effective["cleanup_protect_tag"] = cleanup_tag
        sources["cleanup_protect_tag"] = "market"
    else:
        effective["cleanup_protect_tag"] = "boxarr-protected"
        sources["cleanup_protect_tag"] = "global"

    return {
        "market": definition["market"],
        "label": definition["label"],
        "provider": definition["provider"],
        "provider_config": deepcopy(definition.get("provider_config", {})),
        "aliases": list(definition.get("aliases", [])),
        "enabled": bool(definition.get("enabled", True)),
        "configured": bool(definition.get("configured", False)),
        "overrides": overrides,
        "capabilities": deepcopy(definition.get("capabilities", {})),
        "global": {
            field_name: _global_value(settings_obj, global_field)
            for field_name, global_field in _EFFECTIVE_FIELD_MAP.items()
        },
        "effective": effective,
        "sources": sources,
        "tag_policy": {
            "legacy_tags": ["boxarr", "boxarr-keep"],
            "added_tag": "boxarr-added",
            "market_tag": f"boxarr-market-{definition['market']}",
            "existing_tag": f"boxarr-existing-{definition['market']}",
            "protected_tag": effective["cleanup_protect_tag"],
            "auto_tag_text": effective.get("auto_tag_text") or "boxarr-added",
        },
    }


def get_market_capabilities(settings_obj: Settings, market: str) -> Dict[str, Any]:
    """Return provider capability metadata for a market."""
    definition = market_config_to_dict(get_market_definition(settings_obj, market))
    return deepcopy(
        definition.get("capabilities")
        or _market_capabilities(
            definition.get("provider"), definition.get("provider_config", {})
        )
    )


def get_supported_market_jpboxoffice_countries() -> Dict[str, Dict[str, Any]]:
    """Return the supported JPBoxOffice countries for UI selectors."""
    return get_supported_jpboxoffice_countries()
