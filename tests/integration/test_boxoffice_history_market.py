"""Integration tests for market-aware historical box office API."""

from pathlib import Path
import json

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
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


def test_history_boxoffice_route_reads_market_file_and_keeps_radarr_fields(
    tmp_path, monkeypatch
):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    fr_dir = tmp_path / "weekly_pages" / "fr"
    fr_dir.mkdir(parents=True)
    with open(fr_dir / "2026W21.json", "w") as f:
        json.dump(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice_fr",
                "source": "jpboxoffice",
                "units": "admissions",
                "year": 2026,
                "week": 21,
                "movies": [
                    {
                        "rank": 1,
                        "title": "La Femme de ménage",
                        "original_title": "The Housemaid",
                        "source_year": 2026,
                        "weekend_gross": 373410,
                        "total_gross": 3823351,
                        "weeks_released": 5,
                        "weeks_in_release": 5,
                        "theater_count": 967,
                        "radarr_id": 12582,
                        "radarr_title": "La Femme de ménage",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "match_confidence": 0.98,
                        "tmdb_id": 27047903,
                        "status": "Downloaded",
                        "has_file": True,
                    },
                    {
                        "rank": 2,
                        "title": "Avatar : de feu et de cendres",
                        "original_title": "Avatar: Fire and Ash",
                        "source_year": 2026,
                        "weekend_gross": 336843,
                        "total_gross": 8242711,
                        "weeks_released": 6,
                        "weeks_in_release": 6,
                        "theater_count": 866,
                        "radarr_id": 12510,
                        "radarr_title": "Avatar: Fire and Ash",
                        "radarr_status": "released",
                        "radarr_has_file": False,
                        "match_confidence": 0.97,
                        "tmdb_id": 12345678,
                        "status": "Missing",
                        "has_file": False,
                    },
                ],
            },
            f,
            indent=2,
        )

    # Legacy US file should not be used for market=fr.
    legacy_dir = tmp_path / "weekly_pages"
    legacy_dir.mkdir(exist_ok=True)
    with open(legacy_dir / "2026W21.json", "w") as f:
        json.dump(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "us",
                "provider": "mojo_us",
                "year": 2026,
                "week": 21,
                "movies": [
                    {
                        "rank": 1,
                        "title": "US Legacy Should Not Appear",
                        "radarr_id": None,
                    }
                ],
            },
            f,
            indent=2,
        )

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/history/2026/W21?market=fr")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 2
    assert data[0]["title"] == "La Femme de ménage"
    assert data[0]["radarr_id"] == 12582
    assert data[0]["radarr_status"] == "released"
    assert data[0]["radarr_has_file"] is True
    assert data[0]["match_confidence"] == 0.98
    assert data[0]["tmdb_id"] == 27047903
    assert data[0]["original_title"] == "The Housemaid"
    assert data[0]["source_year"] == 2026
    assert data[0]["weeks_in_release"] == 5
    assert data[0]["weeks_released"] == 5
    assert data[0]["theater_count"] == 967

    assert data[1]["title"] == "Avatar : de feu et de cendres"
    assert data[1]["radarr_id"] == 12510
    assert data[1]["radarr_status"] == "released"
    assert data[1]["radarr_has_file"] is False
    assert data[1]["match_confidence"] == 0.97
    assert data[1]["original_title"] == "Avatar: Fire and Ash"
    assert data[1]["source_year"] == 2026
