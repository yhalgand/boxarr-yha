"""Integration tests for market admin API routes."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.utils.config import Settings


def _seed_config(dir_path: Path) -> Path:
    cfg = {
        "radarr": {
            "url": "http://localhost:7878",
            "api_key": "test-key",
            "root_folder": "/movies",
            "quality_profile_default": "HD-1080p",
            "root_folder_config": {
                "enabled": True,
                "mappings": [
                    {
                        "genres": ["Horror"],
                        "root_folder": "/movies/horror",
                        "priority": 0,
                    }
                ],
            },
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
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_create_update_disable_enable_market(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    create_resp = client.post(
        "/api/config/markets",
        json={
            "market": "de",
            "label": "Germany Box Office",
            "provider": "jpboxoffice",
            "provider_config": {"country": "de"},
            "enabled": True,
            "box_office_fetch_limit": 10,
            "maximum_movies_to_add": 3,
            "auto_tag_text": "boxarr-de",
            "tags": ["boxarr", "boxarr-de"],
            "cleanup_protect_tag": "boxarr-keep",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["market"] == "de"
    assert created["definition"]["provider"] == "jpboxoffice"
    assert created["definition"]["provider_config"] == {"country": "de"}
    assert created["definition"]["aliases"] == ["jpboxoffice_de"]
    assert created["enabled"] is True
    assert created["definition"]["box_office_fetch_limit"] == 10
    assert created["definition"]["maximum_movies_to_add"] == 3
    assert created["definition"]["tags"] == ["boxarr", "boxarr-de"]

    markets_resp = client.get("/api/config/markets")
    assert markets_resp.status_code == 200
    markets_body = markets_resp.json()
    assert "de" in markets_body["markets"]
    assert markets_body["markets"]["de"]["definition"]["provider"] == "jpboxoffice"
    assert markets_body["markets"]["de"]["definition"]["provider_config"] == {
        "country": "de"
    }
    assert markets_body["markets"]["de"]["overrides"]["maximum_movies_to_add"] == 3
    assert markets_body["markets"]["de"]["overrides"]["box_office_fetch_limit"] == 10
    assert markets_body["markets"]["de"]["overrides"]["tags"] == ["boxarr", "boxarr-de"]

    update_resp = client.put(
        "/api/config/markets/de",
        json={
            "label": "Germany Cinema",
            "provider_config": {"country": "de"},
            "box_office_fetch_limit": 7,
            "maximum_movies_to_add": 4,
            "auto_add_enabled": True,
            "auto_tag_text": "boxarr-de",
            "tags": ["boxarr", "boxarr-de"],
            "cleanup_protect_tag": "boxarr-keep",
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["definition"]["label"] == "Germany Cinema"
    assert updated["effective"]["box_office_fetch_limit"] == 7
    assert updated["effective"]["maximum_movies_to_add"] == 4
    assert updated["effective"]["auto_add_enabled"] is True
    assert updated["effective"]["tags"] == ["boxarr", "boxarr-de"]
    assert updated["effective"]["box_office_fetch_limit"] == 7
    assert updated["effective"]["maximum_movies_to_add"] == 4

    saved_yaml = yaml.safe_load(config_path.read_text())
    assert "root_folder_config" in saved_yaml["radarr"]
    assert saved_yaml["radarr"]["root_folder_config"]["enabled"] is True

    disable_resp = client.post("/api/config/markets/de/disable")
    assert disable_resp.status_code == 200
    disabled = disable_resp.json()
    assert disabled["enabled"] is False
    assert disabled["definition"]["maximum_movies_to_add"] == 4
    assert disabled["definition"]["box_office_fetch_limit"] == 7
    assert disabled["definition"]["tags"] == ["boxarr", "boxarr-de"]

    markets_after_disable = client.get("/api/config/markets").json()
    assert (
        markets_after_disable["markets"]["de"]["effective"]["maximum_movies_to_add"] == 4
    )
    assert markets_after_disable["markets"]["de"]["sources"]["maximum_movies_to_add"] == "market"
    assert markets_after_disable["markets"]["de"]["effective"]["box_office_fetch_limit"] == 7
    assert markets_after_disable["markets"]["de"]["sources"]["box_office_fetch_limit"] == "market"
    assert markets_after_disable["markets"]["de"]["effective"]["tags"] == [
        "boxarr",
        "boxarr-de",
    ]
    assert markets_after_disable["markets"]["de"]["sources"]["tags"] == "market"

    current_disabled = client.get("/api/boxoffice/current?market=de")
    assert current_disabled.status_code == 400
    assert "disabled" in current_disabled.json()["detail"].lower()

    enable_resp = client.post("/api/config/markets/de/enable")
    assert enable_resp.status_code == 200
    enabled = enable_resp.json()
    assert enabled["enabled"] is True
    assert enabled["definition"]["maximum_movies_to_add"] == 4
    assert enabled["definition"]["box_office_fetch_limit"] == 7
    assert enabled["definition"]["tags"] == ["boxarr", "boxarr-de"]

    markets_after_enable = client.get("/api/config/markets").json()
    assert markets_after_enable["markets"]["de"]["effective"]["maximum_movies_to_add"] == 4
    assert markets_after_enable["markets"]["de"]["sources"]["maximum_movies_to_add"] == "market"
    assert markets_after_enable["markets"]["de"]["effective"]["box_office_fetch_limit"] == 7
    assert markets_after_enable["markets"]["de"]["sources"]["box_office_fetch_limit"] == "market"

    current_enabled = client.get("/api/boxoffice/current?market=de")
    assert current_enabled.status_code == 501
    assert "not implemented yet" in current_enabled.json()["detail"].lower()


def test_market_admin_rejects_invalid_or_existing_keys(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    invalid_resp = client.post(
        "/api/config/markets",
        json={
            "market": "bad/key",
            "label": "Bad",
            "provider": "jpboxoffice",
            "provider_config": {"country": "de"},
        },
    )
    assert invalid_resp.status_code == 400

    existing_resp = client.post(
        "/api/config/markets",
        json={
            "market": "us",
            "label": "Duplicate US",
            "provider": "mojo",
            "provider_config": {"area": "us"},
        },
    )
    assert existing_resp.status_code == 400


def test_no_markets_config_keeps_us_fr_defaults(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    config_path.write_text(
        yaml.safe_dump(
            {
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
        )
    )
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/config/markets")
    assert resp.status_code == 200
    body = resp.json()
    assert "us" in body["markets"]
    assert "fr" in body["markets"]
    assert body["markets"]["us"]["definition"]["provider"] == "mojo"
    assert body["markets"]["fr"]["definition"]["provider"] == "jpboxoffice"
