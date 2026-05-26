"""Cleanup routes for Boxarr-added Radarr movies."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.boxoffice_provider import DEFAULT_MARKET, normalize_market
from ...core.cleanup import AddLimitCleanupService
from ...core.market_settings import get_effective_market_settings
from ...core.radarr import RadarrService
from ...utils.config import settings
from ...utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])
_DANGEROUS_ACTIONS_DISABLED_MESSAGE = (
    "Execute actions are disabled. Enable BOXARR_ENABLE_DANGEROUS_ACTIONS=true to allow this action."
)


class AddLimitCleanupRequest(BaseModel):
    """Request payload for add-limit cleanup."""

    market: str = DEFAULT_MARKET
    target_add_limit: int = Field(default=3, ge=1, le=30)
    year_from: Optional[int] = None
    week_from: Optional[int] = None
    year_to: Optional[int] = None
    week_to: Optional[int] = None
    delete_files: bool = True
    require_boxarr_tag: bool = True
    protect_tag: str = "boxarr-protected"


def _normalize_cleanup_market(market: str) -> str:
    value = str(market or "").strip().lower()
    if value == "all":
        return value
    return normalize_market(value)


def _run_cleanup(request: AddLimitCleanupRequest, execute: bool) -> dict:
    if not settings.radarr_api_key:
        raise HTTPException(status_code=400, detail="Radarr not configured")

    if execute and not settings.boxarr_enable_dangerous_actions:
        raise HTTPException(
            status_code=403,
            detail=_DANGEROUS_ACTIONS_DISABLED_MESSAGE,
        )

    if execute and not request.delete_files:
        raise HTTPException(
            status_code=400,
            detail="delete_files must be true when executing cleanup",
        )

    if not request.require_boxarr_tag:
        raise HTTPException(
            status_code=400,
            detail="require_boxarr_tag must be true for safe cleanup",
        )

    try:
        market = _normalize_cleanup_market(request.market)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if market != "all":
        try:
            effective = get_effective_market_settings(settings, market)
            if not request.protect_tag or request.protect_tag == "boxarr-keep":
                request.protect_tag = str(
                    effective.get("effective", {}).get("cleanup_protect_tag", request.protect_tag)
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if (
        request.year_from is not None
        and request.year_to is not None
        and (request.year_from, request.week_from or 1)
        > (request.year_to, request.week_to or 53)
    ):
        raise HTTPException(
            status_code=400,
            detail="year_from/week_from must not be after year_to/week_to",
        )

    try:
        radarr_service = RadarrService()
        cleanup_service = AddLimitCleanupService(radarr_service)
        return cleanup_service.run(
            market=market,
            target_add_limit=request.target_add_limit,
            year_from=request.year_from,
            week_from=request.week_from,
            year_to=request.year_to,
            week_to=request.week_to,
            delete_files=request.delete_files,
            require_boxarr_tag=request.require_boxarr_tag,
            protect_tag=request.protect_tag,
            execute=execute,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("Invalid cleanup request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Cleanup failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/add-limit/dry-run")
async def dry_run_add_limit_cleanup(request: AddLimitCleanupRequest):
    """Preview movies that would be deleted by an add-limit reduction."""
    return _run_cleanup(request, execute=False)


@router.post("/add-limit/execute")
async def execute_add_limit_cleanup(request: AddLimitCleanupRequest):
    """Delete movies from Radarr that are no longer eligible under the new limit."""
    return _run_cleanup(request, execute=True)
