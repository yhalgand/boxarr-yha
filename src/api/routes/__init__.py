"""API route modules for Boxarr."""

from .admin import router as admin_router
from .cleanup import router as cleanup_router
from .boxoffice import router as boxoffice_router
from .config import router as config_router
from .policy import router as policy_router
from .movies import router as movies_router
from .scheduler import router as scheduler_router
from .web import router as web_router

__all__ = [
    "admin_router",
    "cleanup_router",
    "boxoffice_router",
    "config_router",
    "policy_router",
    "movies_router",
    "scheduler_router",
    "web_router",
]
