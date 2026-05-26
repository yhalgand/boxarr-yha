"""Integration test for market-aware current box office API."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.boxoffice import BoxOfficeMovie
from src.utils.config import Settings


def _seed_config(dir_path: Path) -> Path:
    cfg = {
        "radarr": {
            "url": "http://localhost:7878",
            "api_key": "",
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
    p = dir_path / "local.yaml"
    with open(p, "w") as f:
        yaml.safe_dump(cfg, f)
    return p


class _FakeBoxOfficeService:
    def __init__(self, *_, **__):
        pass

    def get_current_week_movies(self, limit: int = 10):
        return [
            BoxOfficeMovie(
                rank=1,
                title="La Femme de ménage",
                weekend_gross=541061,
                total_gross=3449941,
                weeks_released=4,
                theater_count=967,
            )
        ]


def test_current_boxoffice_route_uses_requested_market(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    import src.api.routes.boxoffice as boxoffice_routes

    monkeypatch.setattr(boxoffice_routes, "BoxOfficeService", _FakeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/current?market=fr")
    assert resp.status_code == 200

    data = resp.json()
    assert data[0]["title"] == "La Femme de ménage"
    assert data[0]["weekend_gross"] == 541061
    assert data[0]["total_gross"] == 3449941
    assert data[0]["weeks_in_release"] == 4
    assert data[0]["theater_count"] == 967


def test_current_boxoffice_route_rejects_unknown_market(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/current?market=bogus")
    assert resp.status_code == 400
    assert "Unsupported market" in resp.json()["detail"]
