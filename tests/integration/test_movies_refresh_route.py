from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.routes import movies as movies_routes
from src.utils.config import Settings


def _seed_config(dir_path: Path) -> Path:
    cfg = {
        "radarr": {
            "url": "http://localhost:7878",
            "api_key": "test-key",
            "root_folder": "/movies",
            "quality_profile_default": "HD-1080p",
        },
        "boxarr": {
            "scheduler": {"enabled": False, "cron": "0 23 * * 1"},
            "features": {
                "auto_add": False,
                "quality_upgrade": False,
                "auto_add_options": {
                    "limit": 10,
                    "genre_filter_enabled": False,
                    "rating_filter_enabled": False,
                },
            },
            "ui": {"theme": "light"},
        },
    }
    path = dir_path / "local.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return path


def test_refresh_stored_status_route_returns_counts(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    captured = {}

    def _fake_refresh_weekly_data_from_radarr(*, ignore_cache=False, market="us", provider=None):
        captured["ignore_cache"] = ignore_cache
        captured["market"] = market
        captured["provider"] = provider
        return {
            "weeks_scanned": 7,
            "weeks_updated": 2,
            "movies_refreshed": 3,
            "movies_linked": 1,
        }

    monkeypatch.setattr(
        movies_routes,
        "refresh_weekly_data_from_radarr",
        _fake_refresh_weekly_data_from_radarr,
    )

    app = create_app()
    client = TestClient(app)

    response = client.post("/api/movies/refresh-stored-status?market=us")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Weekly movie data refreshed from Radarr",
        "weeks_scanned": 7,
        "weeks_updated": 2,
        "movies_refreshed": 3,
        "movies_linked": 1,
    }
    assert captured == {
        "ignore_cache": True,
        "market": "us",
        "provider": "mojo",
    }
