"""Pytest configuration file for Boxarr tests."""

import sys
from pathlib import Path

import anyio
import httpx

# Add src directory to Python path
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(src_path))


class BoxarrTestClient:
    """Minimal sync test client backed by httpx ASGITransport.

    Starlette's bundled TestClient hangs in this environment, so tests use this
    deterministic shim instead. It preserves the subset of the API the suite
    relies on: request helpers, context manager support, and redirect control.
    """

    def __init__(
        self,
        app,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        follow_redirects: bool = True,
        headers: dict | None = None,
        **kwargs,
    ):
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.root_path = root_path or getattr(app, "root_path", "") or ""
        self.follow_redirects = follow_redirects
        self.headers = headers or {}
        self._kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(self, method: str, url: str, **kwargs):
        async def _do_request():
            transport = httpx.ASGITransport(
                app=self.app,
                raise_app_exceptions=self.raise_server_exceptions,
                root_path=self.root_path,
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                follow_redirects=self.follow_redirects,
                headers=self.headers,
                **self._kwargs,
            ) as client:
                return await client.request(method, url, **kwargs)

        return anyio.run(_do_request)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def options(self, url: str, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url: str, **kwargs):
        return self.request("HEAD", url, **kwargs)


import fastapi.testclient as fastapi_testclient
import starlette.testclient as starlette_testclient

fastapi_testclient.TestClient = BoxarrTestClient
starlette_testclient.TestClient = BoxarrTestClient
