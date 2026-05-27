"""Integration tests for web routes and setup page rendering."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.routes import web as web_routes
from src.utils.config import Settings


def _seed_config_without_markets(dir_path: Path) -> Path:
    cfg = {
        "radarr": {
            "url": "http://localhost:7878",
            "api_key": "test-key",
            "root_folder": "/movies",
            "quality_profile_default": "HD-1080p",
        },
        "boxarr": {
            "scheduler": {"enabled": False, "cron": "0 23 * * 1"},
            "features": {"auto_add": True, "quality_upgrade": False},
            "ui": {"theme": "light"},
        },
    }
    path = dir_path / "local.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return path


@pytest.fixture
def setup_client(tmp_path, monkeypatch):
    config_path = _seed_config_without_markets(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    yield client

    # Restore the repository default config so this test suite does not leak state.
    Settings.reload_from_file(Path("config/default.yaml").resolve())


def test_setup_redirects_to_default_market(setup_client):
    response = setup_client.get("/setup", allow_redirects=False)

    assert response.status_code in {302, 307}
    assert "market=us" in response.headers["location"]


def test_setup_page_renders_for_us_and_fr(setup_client):
    us = setup_client.get("/setup?market=us")
    fr = setup_client.get("/setup?market=fr")

    assert us.status_code == 200
    assert fr.status_code == 200
    assert "Market Settings Preview" in us.text
    assert "Market Settings Preview" in fr.text
    assert "Canonical:" in us.text
    assert "Legacy compat:" in fr.text


def test_setup_page_renders_when_preview_has_no_definition_key(setup_client, monkeypatch):
    def _raw_market_previews(_settings_obj):
        return {
            "us": {
                "effective": {
                    "box_office_fetch_limit": 10,
                    "maximum_movies_to_add": 3,
                    "auto_add_enabled": True,
                    "tags": ["boxarr", "boxarr-us"],
                    "cleanup_protect_tag": "boxarr-protected",
                },
                "sources": {
                    "box_office_fetch_limit": "global",
                    "maximum_movies_to_add": "market",
                    "auto_add_enabled": "global",
                    "tags": "market",
                    "cleanup_protect_tag": "global",
                },
                "tag_policy": {},
            },
            "fr": {
                "effective": {
                    "box_office_fetch_limit": 10,
                    "maximum_movies_to_add": 5,
                    "auto_add_enabled": True,
                    "tags": ["boxarr", "boxarr-fr"],
                    "cleanup_protect_tag": "boxarr-protected",
                },
                "sources": {},
                "tag_policy": {},
            },
        }

    monkeypatch.setattr(web_routes, "_build_market_previews", _raw_market_previews)

    response = setup_client.get("/setup?market=us")

    assert response.status_code == 200
    assert "US Box Office" in response.text
    assert "Canonical:" in response.text
    assert "boxarr-protected" in response.text

