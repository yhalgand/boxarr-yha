from pathlib import Path
from types import SimpleNamespace

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


class _FakeAddRadarrService:
    def __init__(self, *_, **__):
        self.add_calls = []

    def get_all_movies(self, ignore_cache: bool = False):
        return []

    def search_movie_tmdb(self, title: str):
        return [{"tmdbId": 9001, "title": title, "genres": ["Action"]}]

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id=None,
        root_folder: str | None = None,
        monitored: bool = True,
        search_for_movie: bool = True,
    ):
        self.add_calls.append(
            {
                "tmdb_id": tmdb_id,
                "quality_profile_id": quality_profile_id,
                "root_folder": root_folder,
                "monitored": monitored,
                "search": search_for_movie,
            }
        )
        return SimpleNamespace(id=tmdb_id, title="Added Movie")


class _FakeUpgradeProfile:
    def __init__(self, profile_id: int, name: str):
        self.id = profile_id
        self.name = name


class _FakeUpgradeMovie:
    def __init__(self, movie_id: int, title: str):
        self.id = movie_id
        self.title = title


class _FakeUpgradeRadarrService:
    def __init__(self, *_, **__):
        self.update_calls = []
        self.search_calls = []

    def get_movie(self, movie_id: int):
        return SimpleNamespace(id=movie_id, title="Upgradeable Movie", qualityProfileId=1)

    def get_quality_profiles(self):
        return [_FakeUpgradeProfile(1, "HD-1080p"), _FakeUpgradeProfile(2, "Ultra-HD")]

    def update_movie_quality_profile(self, movie_id: int, profile_id: int):
        self.update_calls.append((movie_id, profile_id))
        return _FakeUpgradeMovie(movie_id, "Upgradeable Movie")

    def trigger_movie_search(self, movie_id: int):
        self.search_calls.append(movie_id)
        return True


def test_add_movie_route_refreshes_stored_status(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    refresh_calls = []
    monkeypatch.setattr(
        movies_routes,
        "refresh_stored_status_for_market",
        lambda market, provider=None: refresh_calls.append(market) or {
            "weeks_scanned": 0,
            "weeks_updated": 0,
            "movies_refreshed": 0,
            "movies_linked": 0,
        },
    )
    monkeypatch.setattr(movies_routes, "RadarrService", _FakeAddRadarrService)
    monkeypatch.setattr(
        movies_routes,
        "resolve_movie_identity",
        lambda *_, **__: SimpleNamespace(
            matched=True,
            movie_info={"tmdbId": 9001, "title": "Added Movie", "genres": ["Action"]},
        ),
    )
    monkeypatch.setattr(
        movies_routes,
        "RootFolderManager",
        lambda *_: SimpleNamespace(determine_root_folder=lambda **__: "/movies"),
    )
    monkeypatch.setattr(movies_routes, "regenerate_weeks_with_movie", lambda *_, **__: None)
    monkeypatch.setattr(
        movies_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/movies/add?market=us", json={"title": "Added Movie"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert refresh_calls == ["us"]


def test_upgrade_movie_route_refreshes_stored_status(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(movies_routes.settings, "boxarr_features_quality_upgrade", True)

    refresh_calls = []
    monkeypatch.setattr(
        movies_routes,
        "refresh_stored_status_for_market",
        lambda market, provider=None: refresh_calls.append(market) or {
            "weeks_scanned": 0,
            "weeks_updated": 0,
            "movies_refreshed": 0,
            "movies_linked": 0,
        },
    )
    monkeypatch.setattr(movies_routes, "RadarrService", _FakeUpgradeRadarrService)
    monkeypatch.setattr(movies_routes, "regenerate_weeks_with_movie", lambda *_, **__: None)

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/movies/5/upgrade?market=fr")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert refresh_calls == ["fr"]
