"""Configuration management routes."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import __version__
from ...core.boxoffice_provider import DEFAULT_MARKET
from ...core.market_admin import (
    build_market_definition,
    load_yaml_config,
    normalize_market_key,
    persist_market_definition,
    save_yaml_config,
)
from ...core.market_settings import get_configured_markets, get_effective_market_settings
from ...core.radarr import RadarrService
from ...utils.config import RootFolderConfig, RootFolderMapping, Settings, settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/config", tags=["configuration"])


class ConfigResponse(BaseModel):
    """Configuration response model."""

    radarr_url: str
    radarr_api_key: str
    radarr_configured: bool
    scheduler_enabled: bool
    auto_add: bool
    default_market: str = DEFAULT_MARKET
    markets: Dict[str, Any] = Field(default_factory=dict)


class TestConfigRequest(BaseModel):
    """Test configuration request model."""

    url: str
    api_key: str


class SaveConfigRequest(BaseModel):
    """Save configuration request model."""

    radarr_url: str
    radarr_api_key: str
    radarr_root_folder: str = "/movies"
    radarr_quality_profile_default: str = "HD-1080p"
    radarr_quality_profile_upgrade: str = ""  # Optional, empty string means no upgrade
    # Minimum availability controls
    radarr_minimum_availability_enabled: bool = False
    radarr_minimum_availability: str = "announced"
    # Root folder mapping configuration
    radarr_root_folder_config: Optional[RootFolderConfig] = None
    boxarr_scheduler_enabled: bool = True
    boxarr_scheduler_cron: str = "0 23 * * 2"
    boxarr_features_auto_add: bool = True
    boxarr_features_quality_upgrade: bool = True
    # Box office fetch limit
    boxarr_features_box_office_limit: int = 10
    # New auto-add advanced options
    boxarr_features_auto_add_limit: int = 10
    boxarr_features_auto_add_genre_filter_enabled: bool = False
    boxarr_features_auto_add_genre_filter_mode: str = "blacklist"
    boxarr_features_auto_add_genre_whitelist: List[str] = Field(default_factory=list)
    boxarr_features_auto_add_genre_blacklist: List[str] = Field(default_factory=list)
    boxarr_features_auto_add_rating_filter_enabled: bool = False
    boxarr_features_auto_add_rating_whitelist: List[str] = Field(default_factory=list)
    boxarr_features_auto_add_ignore_rereleases: bool = False
    # Language filter settings
    boxarr_features_auto_add_language_filter_enabled: bool = False
    boxarr_features_auto_add_language_filter_mode: str = "whitelist"
    boxarr_features_auto_add_language_whitelist: List[str] = Field(
        default_factory=lambda: ["English"]
    )
    boxarr_features_auto_add_language_blacklist: List[str] = Field(default_factory=list)
    # Auto-tagging settings
    boxarr_features_auto_tag_enabled: bool = True
    boxarr_features_auto_tag_text: str = "boxarr"
    # UI theme setting
    boxarr_ui_theme: str = "light"


class MarketCreateRequest(BaseModel):
    """Create market request model."""

    market: str
    label: str
    provider: str
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    box_office_fetch_limit: Optional[int] = None
    maximum_movies_to_add: Optional[int] = None
    auto_add_enabled: Optional[bool] = None
    tags: Optional[List[str]] = None
    auto_tag_text: Optional[str] = None
    cleanup_protect_tag: Optional[str] = None


class MarketUpdateRequest(BaseModel):
    """Update market request model."""

    label: Optional[str] = None
    provider: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    box_office_fetch_limit: Optional[int] = None
    maximum_movies_to_add: Optional[int] = None
    auto_add_enabled: Optional[bool] = None
    tags: Optional[List[str]] = None
    auto_tag_text: Optional[str] = None
    cleanup_protect_tag: Optional[str] = None


@router.get("/root-folders")
async def get_root_folder_configuration():
    """Get current root folder configuration."""
    current_settings = settings

    return {
        "default_root_folder": str(current_settings.radarr_root_folder),
        "config": {
            "enabled": current_settings.radarr_root_folder_config.enabled,
            "mappings": [
                {
                    "genres": mapping.genres,
                    "root_folder": mapping.root_folder,
                    "priority": mapping.priority,
                }
                for mapping in current_settings.radarr_root_folder_config.mappings
            ],
        },
    }


@router.get("", response_model=ConfigResponse)
async def get_configuration():
    """Get current configuration."""
    current_settings = settings
    configured_markets = get_configured_markets(current_settings)
    return ConfigResponse(
        radarr_url=str(current_settings.radarr_url),
        radarr_api_key="***" if current_settings.radarr_api_key else "",
        radarr_configured=bool(current_settings.radarr_api_key),
        scheduler_enabled=current_settings.boxarr_scheduler_enabled,
        auto_add=current_settings.boxarr_features_auto_add,
        markets={
            market: {
                "label": definition["label"],
                "provider": definition["provider"],
                "provider_config": definition.get("provider_config", {}),
                "aliases": definition.get("aliases", []),
                "enabled": definition.get("enabled", True),
            }
            for market, definition in configured_markets.items()
        },
    )


@router.get("/markets")
async def get_market_configuration():
    """Return configured markets, raw overrides, and effective settings."""
    current_settings = settings
    configured_markets = get_configured_markets(current_settings)
    markets: Dict[str, Any] = {}
    for market_key, definition in configured_markets.items():
        effective = get_effective_market_settings(current_settings, market_key)
        markets[market_key] = {
            "definition": definition,
            "overrides": effective.get("overrides", {}),
            "effective": effective.get("effective", {}),
            "sources": effective.get("sources", {}),
            "global": effective.get("global", {}),
            "configured": effective.get("configured", False),
            "tag_policy": effective.get("tag_policy", {}),
        }

    return {
        "global": {
            "box_office_fetch_limit": current_settings.boxarr_features_box_office_limit,
            "maximum_movies_to_add": current_settings.boxarr_features_auto_add_limit,
            "auto_add_enabled": current_settings.boxarr_features_auto_add,
            "auto_tag_text": current_settings.boxarr_features_auto_tag_text,
            "tags": ["boxarr", current_settings.boxarr_features_auto_tag_text],
            "root_folder": str(current_settings.radarr_root_folder),
            "quality_profile_default": current_settings.radarr_quality_profile_default,
            "quality_profile_upgrade": current_settings.radarr_quality_profile_upgrade,
            "minimum_availability_enabled": current_settings.radarr_minimum_availability_enabled,
            "minimum_availability": current_settings.radarr_minimum_availability.value,
            "monitor_option": current_settings.radarr_monitor_option.value,
            "search_on_add": current_settings.radarr_search_for_movie,
            "language_filter_enabled": current_settings.boxarr_features_auto_add_language_filter_enabled,
            "language_filter_mode": current_settings.boxarr_features_auto_add_language_filter_mode,
            "language_whitelist": current_settings.boxarr_features_auto_add_language_whitelist,
            "language_blacklist": current_settings.boxarr_features_auto_add_language_blacklist,
        "ignore_rereleases": current_settings.boxarr_features_auto_add_ignore_rereleases,
        "cleanup_protect_tag": "boxarr-protected",
    },
        "markets": markets,
    }


def _resolve_config_path() -> Path:
    data_directory = Path(
        os.getenv("BOXARR_DATA_DIRECTORY", str(settings.boxarr_data_directory))
    )
    return data_directory / "local.yaml"


def _load_config_payload(config_path: Path) -> Dict[str, Any]:
    return load_yaml_config(config_path)


def _save_config_payload(config_path: Path, payload: Dict[str, Any]) -> None:
    save_yaml_config(config_path, payload)


def _get_market_section(payload: Dict[str, Any]) -> Dict[str, Any]:
    markets = payload.get("markets", {}) or {}
    if not isinstance(markets, dict):
        markets = {}
    return markets


def _persist_market_definition(
    market_key: str,
    request_payload: Dict[str, Any],
    *,
    create: bool = False,
) -> Dict[str, Any]:
    normalized_market = normalize_market_key(market_key)
    existing_markets = get_configured_markets(settings)
    market_exists = normalized_market in existing_markets
    if create and market_exists:
        raise HTTPException(
            status_code=400, detail=f"Market '{normalized_market}' already exists"
        )
    if not create and not market_exists:
        raise HTTPException(status_code=404, detail=f"Market '{normalized_market}' not found")

    try:
        result = persist_market_definition(
            normalized_market,
            request_payload,
            create=create,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    refreshed_markets = get_configured_markets(settings)
    refreshed_effective = get_effective_market_settings(settings, normalized_market)
    return {
        "market": normalized_market,
        "definition": refreshed_markets[normalized_market],
        "effective": refreshed_effective.get("effective", {}),
        "sources": refreshed_effective.get("sources", {}),
        "aliases": refreshed_markets[normalized_market].get("aliases", []),
        "enabled": result.get("enabled", refreshed_markets[normalized_market].get("enabled", True)),
        "configured": refreshed_markets[normalized_market].get("configured", False),
    }


@router.post("/markets")
async def create_market(config: MarketCreateRequest):
    """Create a new market in local.yaml."""
    try:
        payload = config.model_dump(exclude_none=False)
        market_key = payload.pop("market")
        if "provider_config" not in payload or payload.get("provider_config") is None:
            payload["provider_config"] = {}
        return _persist_market_definition(str(market_key), payload, create=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error creating market: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/markets/{market}")
async def update_market(market: str, config: MarketUpdateRequest):
    """Update an existing market in local.yaml."""
    try:
        payload = config.model_dump(exclude_none=False, exclude_unset=True)
        return _persist_market_definition(market, payload, create=False)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error updating market %s: %s", market, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/markets/{market}/disable")
async def disable_market(market: str):
    """Disable a configured market."""
    try:
        return _persist_market_definition(market, {"enabled": False}, create=False)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error disabling market %s: %s", market, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/markets/{market}/enable")
async def enable_market(market: str):
    """Enable a configured market."""
    try:
        return _persist_market_definition(market, {"enabled": True}, create=False)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error enabling market %s: %s", market, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test")
async def test_configuration(config: TestConfigRequest):
    """Test Radarr connection and return profiles/folders."""
    try:
        test_service = RadarrService(url=config.url, api_key=config.api_key)

        if not test_service.test_connection():
            return {
                "success": False,
                "message": "Could not connect to Radarr. Check URL and API key.",
            }

        # Get profiles and folders
        profiles = test_service.get_quality_profiles()
        folders = test_service.get_root_folders()

        # Get Radarr version
        try:
            status = test_service.get_system_status()
            version = status.get("version", "Unknown")
        except Exception:
            version = "Unknown"

        return {
            "success": True,
            "message": "Connected successfully!",
            "version": version,
            "profiles": [{"id": p.id, "name": p.name} for p in profiles],
            "root_folders": [
                {"path": f.get("path", ""), "freeSpace": f.get("freeSpace", 0)}
                for f in folders
            ],
        }
    except Exception as e:
        logger.error(f"Error testing configuration: {e}")
        return {"success": False, "message": str(e)}


@router.post("/save")
async def save_configuration(config: SaveConfigRequest):
    """Save configuration to file."""
    try:
        data_directory = Path(
            os.getenv("BOXARR_DATA_DIRECTORY", str(settings.boxarr_data_directory))
        )
        config_path = data_directory / "local.yaml"
        current_file_settings = Settings(boxarr_data_directory=data_directory)
        if config_path.exists():
            current_file_settings.load_from_yaml(config_path)

        # Validate cron expression first
        if config.boxarr_scheduler_enabled:
            try:
                from apscheduler.triggers.cron import CronTrigger

                # Test if cron expression is valid
                CronTrigger.from_crontab(config.boxarr_scheduler_cron)
            except (ValueError, TypeError) as e:
                return {
                    "success": False,
                    "message": f"Invalid cron expression: {str(e)}",
                }

        # Test connection first
        test_service = RadarrService(
            url=config.radarr_url, api_key=config.radarr_api_key
        )

        if not test_service.test_connection():
            return {
                "success": False,
                "message": "Cannot save: Radarr connection failed",
            }

        # Build config dict
        radarr_config: Dict[str, Any] = {
            "url": config.radarr_url,
            "api_key": config.radarr_api_key,
            "root_folder": config.radarr_root_folder,
            "quality_profile_default": config.radarr_quality_profile_default,
        }

        # Include minimum availability settings (UI-driven)
        radarr_config["minimum_availability_enabled"] = bool(
            config.radarr_minimum_availability_enabled
        )
        if config.radarr_minimum_availability:
            radarr_config["minimum_availability"] = config.radarr_minimum_availability

        # Only include upgrade profile if specified
        if config.radarr_quality_profile_upgrade:
            radarr_config["quality_profile_upgrade"] = (
                config.radarr_quality_profile_upgrade
            )

        # Add root folder config if provided
        # Semantics (order-first):
        # - If field present: respect posted 'enabled'. For mappings:
        #   - if posted list is empty and existing has rules, preserve existing rules but apply posted 'enabled'
        #   - else, save exactly what was posted
        #   - Regardless, normalize each mapping's priority to its list index (0..N-1)
        # - If field absent: preserve existing config untouched
        if config.radarr_root_folder_config is not None:
            posted = config.radarr_root_folder_config
            current = current_file_settings.radarr_root_folder_config

            if len(posted.mappings) == 0 and len(current.mappings) > 0:
                # Keep rules, apply posted enabled flag (allows disabling without losing rules)
                preserved = [
                    {
                        "genres": m.genres,
                        "root_folder": m.root_folder,
                        "priority": idx,
                    }
                    for idx, m in enumerate(current.mappings)
                ]
                radarr_config["root_folder_config"] = {
                    "enabled": posted.enabled,
                    "mappings": preserved,
                }
            else:
                normalized = [
                    {
                        "genres": m.genres,
                        "root_folder": m.root_folder,
                        "priority": idx,
                    }
                    for idx, m in enumerate(posted.mappings)
                ]
                radarr_config["root_folder_config"] = {
                    "enabled": posted.enabled,
                    "mappings": normalized,
                }
        else:
            # No root folder config provided at all - preserve existing if any
            current_settings = current_file_settings
            if (
                current_settings.radarr_root_folder_config.enabled
                or current_settings.radarr_root_folder_config.mappings
            ):
                # Normalize existing mapping priorities to sequential indices
                normalized_existing = [
                    {
                        "genres": mapping.genres,
                        "root_folder": mapping.root_folder,
                        "priority": idx,
                    }
                    for idx, mapping in enumerate(
                        current_settings.radarr_root_folder_config.mappings
                    )
                ]
                radarr_config["root_folder_config"] = {
                    "enabled": current_settings.radarr_root_folder_config.enabled,
                    "mappings": normalized_existing,
                }

        config_data = {
            "radarr": radarr_config,
            "boxarr": {
                "scheduler": {
                    "enabled": config.boxarr_scheduler_enabled,
                    "cron": config.boxarr_scheduler_cron,
                },
                "features": {
                    "auto_add": config.boxarr_features_auto_add,
                    "quality_upgrade": config.boxarr_features_quality_upgrade,
                    "box_office_limit": config.boxarr_features_box_office_limit,
                    "auto_tag_enabled": config.boxarr_features_auto_tag_enabled,
                    "auto_tag_text": config.boxarr_features_auto_tag_text,
                    "auto_add_options": {
                        "limit": config.boxarr_features_auto_add_limit,
                        "genre_filter_enabled": config.boxarr_features_auto_add_genre_filter_enabled,
                        "genre_filter_mode": config.boxarr_features_auto_add_genre_filter_mode,
                        "genre_whitelist": config.boxarr_features_auto_add_genre_whitelist,
                        "genre_blacklist": config.boxarr_features_auto_add_genre_blacklist,
                        "rating_filter_enabled": config.boxarr_features_auto_add_rating_filter_enabled,
                        "rating_whitelist": config.boxarr_features_auto_add_rating_whitelist,
                        "ignore_rereleases": config.boxarr_features_auto_add_ignore_rereleases,
                        "language_filter_enabled": config.boxarr_features_auto_add_language_filter_enabled,
                        "language_filter_mode": config.boxarr_features_auto_add_language_filter_mode,
                        "language_whitelist": config.boxarr_features_auto_add_language_whitelist,
                        "language_blacklist": config.boxarr_features_auto_add_language_blacklist,
                    },
                },
                "ui": {
                    "theme": config.boxarr_ui_theme,
                },
            },
        }

        existing_markets = getattr(current_file_settings, "markets", {}) or {}
        if existing_markets:
            config_data["markets"] = {
                market_key: (
                    market_value.model_dump(exclude_none=True)
                    if hasattr(market_value, "model_dump")
                    else dict(market_value)
                )
                for market_key, market_value in existing_markets.items()
            }

        # Save to local.yaml
        import yaml

        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        logger.info("Configuration saved successfully")

        # Save old scheduler settings BEFORE reloading
        old_scheduler_enabled = settings.boxarr_scheduler_enabled
        old_cron = settings.boxarr_scheduler_cron

        # Reload settings
        Settings.reload_from_file(config_path)

        # Reload scheduler if it's running and schedule changed
        try:
            # Get new settings values (define these early to avoid NameError)
            new_cron = config.boxarr_scheduler_cron
            new_enabled = config.boxarr_scheduler_enabled

            # Try to get scheduler from app state or module
            scheduler = None
            try:
                # Try getting from the scheduler routes module
                from .scheduler import get_scheduler

                scheduler = get_scheduler()
            except Exception as e:
                logger.debug(f"Could not get scheduler instance: {e}")

            # If scheduler exists and is running, check if we need to reload
            if scheduler and hasattr(scheduler, "_running") and scheduler._running:
                # Check if scheduler settings changed
                schedule_changed = old_cron != new_cron
                enabled_changed = old_scheduler_enabled != new_enabled

                if schedule_changed or enabled_changed:
                    if new_enabled:
                        # Reload with new cron
                        if scheduler.reload_schedule(new_cron):
                            logger.info(
                                f"✅ Scheduler reloaded: {old_cron} → {new_cron}"
                            )
                        else:
                            logger.error(
                                f"Failed to reload scheduler with new cron: {new_cron}"
                            )
                    else:
                        # Disable scheduler by removing job
                        job = scheduler.scheduler.get_job("box_office_update")
                        if job:
                            scheduler.scheduler.remove_job("box_office_update")
                            logger.info("✅ Scheduler disabled (job removed)")
                else:
                    logger.debug("Scheduler settings unchanged, no reload needed")
            elif new_enabled and not scheduler:
                logger.warning(
                    "⚠️ Scheduler should be enabled but instance not found - restart required"
                )
        except Exception as e:
            logger.warning(f"Could not reload scheduler: {e}")
            # Don't fail the whole config save just because scheduler reload failed

        return {
            "success": True,
            "message": "Configuration saved successfully!",
        }
    except Exception as e:
        logger.error(f"Error saving configuration: {e}")
        return {"success": False, "message": str(e)}


@router.get("/check-update")
async def check_for_update():
    """Check if a newer version is available on GitHub."""
    try:
        # Clean up current version for comparison
        current_version = __version__.replace("-dev", "").replace("-dirty", "")
        if "-" in current_version:
            # Handle versions like "1.0.5-2-g1234567"
            current_version = current_version.split("-")[0]

        # Fetch latest release from GitHub
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/repos/iongpt/boxarr/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=5.0,
            )

            if response.status_code != 200:
                logger.warning(f"GitHub API returned status {response.status_code}")
                return {
                    "update_available": False,
                    "error": "Could not check for updates",
                }

            release_data = response.json()
            latest_version = release_data.get("tag_name", "").lstrip("v")

            # Compare versions
            def parse_version(v):
                """Parse semantic version string to tuple for comparison."""
                try:
                    parts = v.split(".")
                    return tuple(int(p) for p in parts[:3])  # Major, minor, patch
                except (ValueError, AttributeError):
                    return (0, 0, 0)

            current_tuple = parse_version(current_version)
            latest_tuple = parse_version(latest_version)

            update_available = latest_tuple > current_tuple

            # Always link to releases page if update available
            changelog_url = None
            if update_available:
                changelog_url = "https://github.com/iongpt/boxarr/releases"

            return {
                "update_available": update_available,
                "current_version": __version__,
                "latest_version": latest_version,
                "changelog_url": changelog_url,
                "release_url": release_data.get("html_url"),
                "release_name": release_data.get("name"),
                "published_at": release_data.get("published_at"),
            }

    except httpx.TimeoutException:
        logger.warning("Timeout checking for updates")
        return {
            "update_available": False,
            "error": "Timeout checking for updates",
        }
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return {
            "update_available": False,
            "error": str(e),
        }
