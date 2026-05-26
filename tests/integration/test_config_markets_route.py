"""Integration tests for the markets config preview endpoint."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.utils.config import Settings


def _write_config(dir_path: Path) -> Path:
    payload = {
        "radarr": {
            "url": "http://localhost:7878",
            "api_key": "test-key",
            "root_folder": "/movies",
            "quality_profile_default": "HD-1080p",
        },
        "boxarr": {
            "features": {
                "box_office_limit": 10,
                "auto_add": True,
                "auto_add_limit": 10,
                "auto_tag_text": "boxarr",
            }
        },
        "markets": {
            "us": {
                "label": "US Box Office",
                "provider": "mojo",
                "provider_config": {"area": "us"},
                "enabled": True,
                "maximum_movies_to_add": 3,
                "cleanup_protect_tag": "boxarr-keep",
            },
            "fr": {
                "label": "France Box Office",
                "provider": "jpboxoffice",
                "provider_config": {"country": "fr"},
                "enabled": True,
                "maximum_movies_to_add": None,
                "cleanup_protect_tag": "boxarr-keep",
            },
        },
    }
    path = dir_path / "local.yaml"
    path.write_text(yaml.safe_dump(payload))
    return path


def test_get_config_markets_returns_effective_values(tmp_path, monkeypatch):
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    config_path = _write_config(tmp_path)
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/config/markets")
    assert resp.status_code == 200
    body = resp.json()

    assert body["global"]["maximum_movies_to_add"] == 10
    assert body["markets"]["us"]["effective"]["maximum_movies_to_add"] == 3
    assert body["markets"]["us"]["sources"]["maximum_movies_to_add"] == "market"
    assert body["markets"]["fr"]["effective"]["maximum_movies_to_add"] == 10
    assert body["markets"]["fr"]["sources"]["maximum_movies_to_add"] == "global"
    assert body["markets"]["us"]["definition"]["aliases"] == ["mojo_us"]
    assert body["markets"]["fr"]["definition"]["aliases"] == ["jpboxoffice_fr"]
    assert body["markets"]["us"]["effective"]["cleanup_protect_tag"] == "boxarr-keep"
