"""Market policy helpers for weekly-page policy awareness and policy actions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .boxoffice_provider import DEFAULT_MARKET, normalize_market
from .boxoffice_storage import iter_weekly_page_paths
from .market_admin import persist_market_definition
from .market_settings import get_effective_market_settings
from ..utils.config import settings
from ..utils.logger import get_logger

logger = get_logger(__name__)

POLICY_FIELDS = [
    "box_office_fetch_limit",
    "maximum_movies_to_add",
    "auto_add_enabled",
    "tags",
    "auto_tag_text",
    "cleanup_protect_tag",
]


def _normalize_market_or_default(market: str) -> str:
    return normalize_market(market or DEFAULT_MARKET)


def _policy_field_value(effective: Dict[str, Any], field: str) -> Any:
    return effective.get(field)


def _build_tag_policy(market: str, effective: Dict[str, Any]) -> Dict[str, Any]:
    market_key = _normalize_market_or_default(market)
    return {
        "legacy_tags": ["boxarr", "boxarr-keep"],
        "added_tag": "boxarr-added",
        "market_tag": f"boxarr-market-{market_key}",
        "existing_tag": f"boxarr-existing-{market_key}",
        "protected_tag": str(effective.get("cleanup_protect_tag") or "boxarr-protected"),
        "auto_tag_text": str(effective.get("auto_tag_text") or "boxarr-added"),
    }


def get_market_policy(settings_obj, market: str) -> Dict[str, Any]:
    """Return the effective policy for a market."""
    market_key = _normalize_market_or_default(market)
    effective = get_effective_market_settings(settings_obj, market_key)
    policy = {
        "market": market_key,
        "label": effective.get("label"),
        "provider": effective.get("provider"),
        "provider_config": effective.get("provider_config", {}),
        "enabled": effective.get("enabled", True),
        "configured": effective.get("configured", False),
        "policy_version": 1,
        "effective": {field: _policy_field_value(effective.get("effective", {}), field) for field in POLICY_FIELDS},
        "sources": {field: effective.get("sources", {}).get(field, "global") for field in POLICY_FIELDS},
        "global": {field: effective.get("global", {}).get(field) for field in POLICY_FIELDS},
        "overrides": effective.get("overrides", {}),
        "aliases": effective.get("aliases", []),
        "tag_policy": _build_tag_policy(market_key, effective.get("effective", {})),
    }
    return policy


def build_policy_snapshot(policy: Dict[str, Any], year: int, week: int) -> Dict[str, Any]:
    """Build a compact policy snapshot stored with weekly JSON files."""
    effective = dict(policy.get("effective", {}) or {})
    tag_policy = _build_tag_policy(str(policy.get("market") or DEFAULT_MARKET), effective)
    return {
        "market": policy.get("market"),
        "provider": policy.get("provider"),
        "provider_config": policy.get("provider_config", {}),
        "fetch_limit_used": effective.get("box_office_fetch_limit"),
        "add_limit_used": effective.get("maximum_movies_to_add"),
        "auto_add_enabled_used": effective.get("auto_add_enabled"),
        "tags_used": effective.get("tags", []),
        "auto_tag_text_used": effective.get("auto_tag_text"),
        "cleanup_protect_tag_used": effective.get("cleanup_protect_tag"),
        "tag_policy_used": tag_policy,
        "policy_applied_at": datetime.now().isoformat(),
        "policy_version": policy.get("policy_version", 1),
        "year": year,
        "week": week,
    }


def compare_policy_change(
    settings_obj,
    market: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare current policy to a proposed update and suggest next actions."""
    market_key = _normalize_market_or_default(market)
    current = get_market_policy(settings_obj, market_key)
    new_effective = dict(current.get("effective", {}))
    new_effective.update({k: v for k, v in updates.items() if k in POLICY_FIELDS and v is not None})

    changes = []
    recommendations: List[str] = []

    for field in POLICY_FIELDS:
        old = current.get("effective", {}).get(field)
        new = new_effective.get(field)
        if old != new:
            changes.append({"field": field, "old": old, "new": new})
            if field == "maximum_movies_to_add":
                if isinstance(old, int) and isinstance(new, int):
                    if new > old:
                        recommendations.append("backfill-add")
                    elif new < old:
                        recommendations.append("cleanup")
            elif field == "box_office_fetch_limit":
                if isinstance(old, int) and isinstance(new, int):
                    if new > old:
                        recommendations.append("refetch")
                    elif new < old:
                        recommendations.append("future-only")
            elif field == "auto_add_enabled":
                recommendations.append("future-only")
            elif field in {"tags", "auto_tag_text", "cleanup_protect_tag"}:
                recommendations.append("apply-policy")

    return {
        "market": market_key,
        "current": current,
        "proposed_effective": new_effective,
        "changes": changes,
        "recommendations": list(dict.fromkeys(recommendations)),
        "scope_options": ["future-only", "selected-range", "all-stored"],
    }


def _load_week_payload(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read weekly page %s: %s", path, exc)
        return None


def iter_policy_week_paths(
    market: str,
    year_from: Optional[int] = None,
    week_from: Optional[int] = None,
    year_to: Optional[int] = None,
    week_to: Optional[int] = None,
) -> List[Path]:
    """Return weekly pages for the given market and optional range."""
    market_key = _normalize_market_or_default(market)
    paths: List[Path] = []
    start = (year_from, week_from or 1) if year_from is not None else None
    end = (year_to, week_to or 53) if year_to is not None else None

    for path in iter_weekly_page_paths(settings.boxarr_data_directory, market_key):
        stem = path.stem
        if "W" not in stem:
            continue
        try:
            year_str, week_str = stem.split("W", 1)
            year = int(year_str)
            week = int(week_str[:2])
        except Exception:
            continue
        if start and (year, week) < start:
            continue
        if end and (year, week) > end:
            continue
        paths.append(path)
    return paths


def update_weekly_policy_snapshot(
    market: str,
    policy: Dict[str, Any],
    year_from: Optional[int] = None,
    week_from: Optional[int] = None,
    year_to: Optional[int] = None,
    week_to: Optional[int] = None,
) -> Dict[str, Any]:
    """Write policy_snapshot to stored weekly JSON files for the selected range."""
    market_key = _normalize_market_or_default(market)
    paths = iter_policy_week_paths(market_key, year_from, week_from, year_to, week_to)
    updated = 0
    skipped = 0
    for path in paths:
        payload = _load_week_payload(path)
        if not payload:
            skipped += 1
            continue
        year = int(payload.get("year") or 0)
        week = int(payload.get("week") or 0)
        payload["policy_snapshot"] = build_policy_snapshot(policy, year, week)
        try:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            updated += 1
        except Exception as exc:
            logger.warning("Failed to write policy snapshot to %s: %s", path, exc)
            skipped += 1
    return {"market": market_key, "updated": updated, "skipped": skipped, "paths": [str(p) for p in paths]}


def save_market_policy(
    market: str,
    updates: Dict[str, Any],
    *,
    base_directory: Optional[Path] = None,
) -> Dict[str, Any]:
    """Persist market policy overrides via the market registry."""
    # The market policy lives in the market configuration overrides.
    result = persist_market_definition(
        market,
        updates,
        create=False,
        base_directory=base_directory,
    )
    return result
