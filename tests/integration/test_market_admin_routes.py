"""Integration tests for market admin API routes."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.utils.config import MarketConfig, Settings, settings


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
    assert isinstance(settings.markets["fr"], MarketConfig)

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
            "cleanup_protect_tag": "boxarr-protected",
            "root_folder": "/movies/de",
            "quality_profile_default": "HD-1080p",
            "language_filter_enabled": True,
            "language_filter_mode": "whitelist",
            "language_whitelist": ["German"],
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
    assert created["effective"]["root_folder"] == "/movies/de"
    assert created["effective"]["quality_profile_default"] == "HD-1080p"
    assert created["effective"]["language_filter_enabled"] is True
    assert created["effective"]["language_filter_mode"] == "whitelist"
    assert created["effective"]["language_whitelist"] == ["German"]

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
    assert markets_body["markets"]["de"]["overrides"]["root_folder"] == "/movies/de"
    assert markets_body["markets"]["de"]["overrides"]["language_filter_enabled"] is True

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
            "cleanup_protect_tag": "boxarr-protected",
            "root_folder": "/movies/de",
            "quality_profile_default": "HD-1080p",
            "quality_profile_upgrade": "UHD-4K",
            "language_filter_enabled": True,
            "language_filter_mode": "blacklist",
            "language_blacklist": ["Spanish"],
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
    assert updated["effective"]["root_folder"] == "/movies/de"
    assert updated["effective"]["quality_profile_default"] == "HD-1080p"
    assert updated["effective"]["quality_profile_upgrade"] == "UHD-4K"
    assert updated["effective"]["language_filter_enabled"] is True
    assert updated["effective"]["language_filter_mode"] == "blacklist"

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
    assert disabled["effective"]["root_folder"] == "/movies/de"

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
    assert enabled["effective"]["root_folder"] == "/movies/de"

    markets_after_enable = client.get("/api/config/markets").json()
    assert markets_after_enable["markets"]["de"]["effective"]["maximum_movies_to_add"] == 4
    assert markets_after_enable["markets"]["de"]["sources"]["maximum_movies_to_add"] == "market"
    assert markets_after_enable["markets"]["de"]["effective"]["box_office_fetch_limit"] == 7
    assert markets_after_enable["markets"]["de"]["sources"]["box_office_fetch_limit"] == "market"

    current_enabled = client.get("/api/boxoffice/current?market=de")
    assert current_enabled.status_code == 501
    assert "not implemented yet" in current_enabled.json()["detail"].lower()


def test_default_market_override_save_persists_for_us_and_fr(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    assert isinstance(settings.markets["fr"], MarketConfig)

    app = create_app()
    client = TestClient(app)

    fr_resp = client.put(
        "/api/config/markets/fr",
        json={
            "maximum_movies_to_add": 3,
            "box_office_fetch_limit": 10,
            "auto_add_enabled": True,
            "tags": ["boxarr", "boxarr-fr"],
            "cleanup_protect_tag": "boxarr-protected",
        },
    )
    assert fr_resp.status_code == 200
    fr_data = fr_resp.json()
    assert fr_data["market"] == "fr"
    assert fr_data["definition"]["maximum_movies_to_add"] == 3
    assert fr_data["definition"]["box_office_fetch_limit"] == 10
    assert fr_data["definition"]["tags"] == ["boxarr", "boxarr-fr"]
    assert fr_data["effective"]["maximum_movies_to_add"] == 3
    assert fr_data["effective"]["box_office_fetch_limit"] == 10
    assert fr_data["effective"]["tags"] == ["boxarr", "boxarr-fr"]

    us_resp = client.put(
        "/api/config/markets/us",
        json={
            "maximum_movies_to_add": 4,
            "box_office_fetch_limit": 12,
            "auto_add_enabled": False,
            "tags": ["boxarr", "boxarr-us"],
            "cleanup_protect_tag": "boxarr-protected",
        },
    )
    assert us_resp.status_code == 200
    us_data = us_resp.json()
    assert us_data["market"] == "us"
    assert us_data["definition"]["maximum_movies_to_add"] == 4
    assert us_data["definition"]["box_office_fetch_limit"] == 12
    assert us_data["definition"]["tags"] == ["boxarr", "boxarr-us"]

    saved_yaml = yaml.safe_load(config_path.read_text())
    assert saved_yaml["markets"]["fr"]["maximum_movies_to_add"] == 3
    assert saved_yaml["markets"]["fr"]["box_office_fetch_limit"] == 10
    assert saved_yaml["markets"]["fr"]["tags"] == ["boxarr", "boxarr-fr"]
    assert saved_yaml["markets"]["us"]["maximum_movies_to_add"] == 4
    assert saved_yaml["markets"]["us"]["box_office_fetch_limit"] == 12
    assert saved_yaml["markets"]["us"]["tags"] == ["boxarr", "boxarr-us"]


def test_update_existing_marketconfig_object_does_not_crash(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config["markets"] = {
        "fr": {
            "label": "France Box Office",
            "provider": "jpboxoffice",
            "provider_config": {"country": "fr"},
            "enabled": True,
            "box_office_fetch_limit": 10,
            "maximum_movies_to_add": 3,
            "auto_add_enabled": True,
            "tags": ["boxarr", "boxarr-fr"],
            "auto_tag_text": "boxarr-fr",
            "cleanup_protect_tag": "boxarr-protected",
            "root_folder": "/movies/fr",
        }
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))

    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    resp = client.put(
        "/api/config/markets/fr",
        json={
            "maximum_movies_to_add": 3,
            "box_office_fetch_limit": 12,
            "auto_add_enabled": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["market"] == "fr"
    assert data["definition"]["maximum_movies_to_add"] == 3
    assert data["definition"]["box_office_fetch_limit"] == 12
    assert data["definition"]["auto_add_enabled"] is False
    assert data["definition"]["tags"] == ["boxarr", "boxarr-fr"]
    assert data["effective"]["maximum_movies_to_add"] == 5
    assert data["effective"]["box_office_fetch_limit"] == 12

    saved_yaml = yaml.safe_load(config_path.read_text())
    assert saved_yaml["markets"]["fr"]["maximum_movies_to_add"] == 3
    assert saved_yaml["markets"]["fr"]["box_office_fetch_limit"] == 12
    assert saved_yaml["markets"]["fr"]["tags"] == ["boxarr", "boxarr-fr"]


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
