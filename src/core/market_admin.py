"""Admin helpers for creating and updating configured markets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .boxoffice_provider import DEFAULT_PROVIDER, canonicalize_provider_definition, normalize_provider
from .market_settings import get_configured_markets, market_config_to_dict
from ..utils.config import Settings, settings

MARKET_KEY_PATTERN = re.compile(r"^[a-z0-9_-]+$")

EDITABLE_MARKET_FIELDS = {
    "label",
    "provider",
    "provider_config",
    "enabled",
    "box_office_fetch_limit",
    "maximum_movies_to_add",
    "auto_add_enabled",
    "tags",
    "auto_tag_text",
    "cleanup_protect_tag",
    "root_folder",
    "quality_profile_default",
    "quality_profile_upgrade",
    "minimum_availability_enabled",
    "minimum_availability",
    "monitor_option",
    "search_on_add",
    "language_filter_enabled",
    "language_filter_mode",
    "language_whitelist",
    "language_blacklist",
    "ignore_rereleases",
}


def normalize_market_key(market_key: str) -> str:
    """Normalize and validate a market key."""
    normalized = str(market_key or "").strip().lower()
    if not normalized:
        raise ValueError("Market key is required")
    if normalized in {".", ".."}:
        raise ValueError("Invalid market key")
    if any(sep in normalized for sep in ("/", "\\", " ", ".")):
        raise ValueError(
            "Invalid market key. Use lowercase letters, digits, hyphen, or underscore."
        )
    if not MARKET_KEY_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Invalid market key. Use lowercase letters, digits, hyphen, or underscore."
        )
    return normalized


def load_yaml_config(config_path: Path) -> Dict[str, Any]:
    """Load the local YAML configuration as a mutable dictionary."""
    if not config_path.exists():
        return {}

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("local.yaml root must be a mapping")
    return data


def save_yaml_config(config_path: Path, data: Dict[str, Any]) -> None:
    """Persist the local YAML configuration."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def resolve_config_path(base_directory: Optional[Path] = None) -> Path:
    """Resolve the local YAML config path for the active data directory."""
    if base_directory is None:
        base_directory = Path(str(settings.boxarr_data_directory))
    return Path(base_directory) / "local.yaml"


def infer_provider_config(
    market_key: str, provider: str, provider_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Infer a provider config for a market when the caller does not provide one."""
    market_key = normalize_market_key(market_key)
    provider_key = normalize_provider(provider)
    config: Dict[str, Any] = dict(provider_config or {})

    if provider_key == "mojo":
        config.setdefault("area", market_key)
    elif provider_key == "jpboxoffice":
        config.setdefault("country", market_key)

    return config


def _normalize_tags(tags: Any) -> Optional[list[str]]:
    if tags is None:
        return None
    if isinstance(tags, str):
        parts = [part.strip() for part in tags.split(",")]
        return [part for part in parts if part]
    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    return [str(tags).strip()] if str(tags).strip() else []


def _normalize_string_list(values: Any) -> Optional[list[str]]:
    if values is None:
        return None
    if isinstance(values, str):
        parts = [part.strip() for part in values.split(",")]
        return [part for part in parts if part]
    if isinstance(values, list):
        return [str(item).strip() for item in values if str(item).strip()]
    value = str(values).strip()
    return [value] if value else []


def build_market_definition(
    market_key: str,
    payload: Dict[str, Any],
    existing: Optional[Dict[str, Any]] = None,
    *,
    create: bool = False,
) -> Dict[str, Any]:
    """Build a canonical market definition from incoming payload data."""
    normalized_key = normalize_market_key(market_key)
    base = market_config_to_dict(existing)
    incoming = dict(payload or {})

    if "label" in incoming and incoming.get("label") is not None and not str(incoming.get("label")).strip():
        raise ValueError("Label is required")
    if "provider" in incoming and incoming.get("provider") is not None and not str(incoming.get("provider")).strip():
        raise ValueError("Provider is required")

    provider = incoming.get("provider", base.get("provider", DEFAULT_PROVIDER))
    provider_config = incoming.get("provider_config", base.get("provider_config"))
    provider_changed = False
    if "provider" in incoming and incoming.get("provider") is not None:
        provider_changed = normalize_provider(incoming.get("provider")) != normalize_provider(
            base.get("provider", DEFAULT_PROVIDER)
        )
    if provider_config is None or provider_config == {} or (provider_changed and "provider_config" not in incoming):
        provider_config = infer_provider_config(normalized_key, provider, provider_config)

    canonical = canonicalize_provider_definition(provider, provider_config)

    # Preserve the existing market definition on updates so partial payloads
    # (for example enable/disable toggles) do not wipe unrelated overrides.
    record: Dict[str, Any] = dict(base) if not create else {}

    record["label"] = incoming.get("label", base.get("label", normalized_key.upper()))
    record["provider"] = canonical["provider"]
    record["provider_config"] = canonical["provider_config"]
    record["enabled"] = incoming.get("enabled", base.get("enabled", True))

    if create and "enabled" not in incoming:
        record["enabled"] = True

    if "box_office_fetch_limit" in incoming:
        record["box_office_fetch_limit"] = incoming.get("box_office_fetch_limit")
    elif create and "box_office_fetch_limit" in base:
        record["box_office_fetch_limit"] = base.get("box_office_fetch_limit")

    if "maximum_movies_to_add" in incoming:
        record["maximum_movies_to_add"] = incoming.get("maximum_movies_to_add")
    elif create and "maximum_movies_to_add" in base:
        record["maximum_movies_to_add"] = base.get("maximum_movies_to_add")

    if "auto_add_enabled" in incoming:
        record["auto_add_enabled"] = incoming.get("auto_add_enabled")
    elif create and "auto_add_enabled" in base:
        record["auto_add_enabled"] = base.get("auto_add_enabled")

    auto_tag_text = incoming.get("auto_tag_text", base.get("auto_tag_text"))
    if auto_tag_text is None and create:
        auto_tag_text = f"boxarr-{normalized_key}"
    if auto_tag_text is not None:
        record["auto_tag_text"] = auto_tag_text

    tags = _normalize_tags(incoming["tags"]) if "tags" in incoming else None
    if tags is None and not create and "tags" in base:
        tags = _normalize_tags(base.get("tags"))
    if tags is None and create:
        default_auto_tag = auto_tag_text or f"boxarr-{normalized_key}"
        tags = ["boxarr", default_auto_tag]
    if tags is not None:
        record["tags"] = tags

    cleanup_tag = incoming.get("cleanup_protect_tag", base.get("cleanup_protect_tag"))
    if cleanup_tag is None and create:
        cleanup_tag = "boxarr-protected"
    if cleanup_tag is not None:
        record["cleanup_protect_tag"] = cleanup_tag

    simple_fields = [
        "root_folder",
        "quality_profile_default",
        "quality_profile_upgrade",
        "minimum_availability_enabled",
        "minimum_availability",
        "monitor_option",
        "search_on_add",
        "language_filter_enabled",
        "language_filter_mode",
        "ignore_rereleases",
    ]
    for field_name in simple_fields:
        if field_name in incoming:
            record[field_name] = incoming.get(field_name)
        elif create and field_name in base:
            record[field_name] = base.get(field_name)

    for field_name in ("language_whitelist", "language_blacklist"):
        if field_name in incoming:
            record[field_name] = _normalize_string_list(incoming.get(field_name))
        elif create and field_name in base:
            record[field_name] = _normalize_string_list(base.get(field_name))

    return record


def persist_market_definition(
    market_key: str,
    payload: Dict[str, Any],
    *,
    create: bool = False,
    base_directory: Optional[Path] = None,
) -> Dict[str, Any]:
    """Create or update a market definition in local.yaml and reload settings."""
    normalized_market = normalize_market_key(market_key)
    config_path = resolve_config_path(base_directory)
    config_payload = load_yaml_config(config_path)
    markets_section = config_payload.get("markets", {}) or {}
    if not isinstance(markets_section, dict):
        markets_section = {}

    current_markets = getattr(settings, "markets", {}) or {}
    if not isinstance(current_markets, dict):
        current_markets = {}
    registry_markets = get_configured_markets(settings)

    market_exists = (
        normalized_market in current_markets
        or normalized_market in markets_section
        or normalized_market in registry_markets
    )
    if create and market_exists:
        raise ValueError(f"Market '{normalized_market}' already exists")
    if not create and not market_exists:
        raise ValueError(f"Market '{normalized_market}' not found")

    existing_definition = (
        market_config_to_dict(markets_section.get(normalized_market))
        or market_config_to_dict(current_markets.get(normalized_market))
        or market_config_to_dict(registry_markets.get(normalized_market, {}))
    )
    updated_definition = build_market_definition(
        normalized_market,
        payload,
        existing=existing_definition,
        create=create,
    )
    markets_section[normalized_market] = updated_definition
    config_payload["markets"] = markets_section
    save_yaml_config(config_path, config_payload)
    Settings.reload_from_file(config_path)

    refreshed_markets = getattr(settings, "markets", {}) or {}
    definition = market_config_to_dict(
        refreshed_markets.get(normalized_market, updated_definition)
    )
    return {
        "market": normalized_market,
        "definition": definition,
        "enabled": definition.get("enabled", True),
    }
