"""Integration test: historical update uses genre→root-folder mapping.

This verifies that POST /api/scheduler/update-week applies the same
genre-based root folder mapping as the main scheduler/manual add paths.
"""

from pathlib import Path
import json
from datetime import datetime

import yaml
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.boxoffice import BoxOfficeMovie
from src.core.models import MovieStatus
from src.core.radarr import RadarrMovie
from src.utils.config import Settings, settings
from tests.helpers import FakeWeeklyDataGenerator


def _seed_config(dir_path: Path) -> Path:
    cfg = {
        "radarr": {
            "url": "http://localhost:7878",
            "api_key": "test-key",
            "root_folder": "/movies",
            "quality_profile_default": "HD-1080p",
            # Enable mapping: any Horror movie should go to /movies/horror
            "root_folder_config": {
                "enabled": True,
                "mappings": [
                    {
                        "genres": ["Horror"],
                        "root_folder": "/movies/horror",
                        "priority": 50,
                    }
                ],
            },
        },
        "boxarr": {
            "scheduler": {"enabled": False, "cron": "0 23 * * 1"},
            "features": {
                "auto_add": True,  # required for update-week auto-add path
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


def _seed_historical_market_config(dir_path: Path, market: str, country: str) -> Path:
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
        "markets": {
            market: {
                "label": f"{market.upper()} Box Office",
                "provider": "jpboxoffice",
                "provider_config": {"country": country},
                "enabled": True,
            }
        },
    }
    p = dir_path / "local.yaml"
    with open(p, "w") as f:
        yaml.safe_dump(cfg, f)
    return p


class _FakeQualityProfile:
    def __init__(self):
        self.id = 1
        self.name = "HD-1080p"


class _FakeAddedMovie:
    def __init__(self, tmdb_id, title):
        self.id = tmdb_id
        self.title = title


class _FakeFrRadarrService:
    """Fake Radarr client with TMDB-aware lookup responses for FR matching tests."""

    def __init__(self, *_, **__):
        pass

    def get_all_movies(self):
        return [
            RadarrMovie(id=1, title="X-Men: Apocalypse", tmdbId=20001, year=2016, status=MovieStatus.RELEASED, hasFile=True),
            RadarrMovie(id=2, title="3-Iron", tmdbId=20002, year=2004, status=MovieStatus.RELEASED, hasFile=True),
            RadarrMovie(id=3, title="2:22", tmdbId=20003, year=2017, status=MovieStatus.RELEASED, hasFile=False),
            RadarrMovie(id=4, title="n", tmdbId=20004, year=2026, status=MovieStatus.RELEASED, hasFile=False),
            RadarrMovie(id=5, title="The Housemaid", tmdbId=20005, year=2026, status=MovieStatus.RELEASED, hasFile=False),
            RadarrMovie(id=6, title="Avatar: Fire and Ash", tmdbId=20006, year=2026, status=MovieStatus.RELEASED, hasFile=False),
        ]

    def get_root_folder_paths(self):
        return ["/movies"]

    def get_quality_profiles(self):
        return [_FakeQualityProfile()]

    def search_movie(self, title: str):
        return self.search_movie_tmdb(title)

    def search_movie_tmdb(self, title: str, language=None, region=None):
        lowered = title.lower()
        if "bojarski" in lowered:
            return [{"tmdbId": 20001, "title": "X-Men: Apocalypse", "originalTitle": "X-Men: Apocalypse", "year": 2016}]
        if "forêts" in lowered or "forets" in lowered:
            return [{"tmdbId": 20002, "title": "3-Iron", "originalTitle": "3-Iron", "year": 2004}]
        if "greenland" in lowered:
            return [{"tmdbId": 20003, "title": "2:22", "originalTitle": "2:22", "year": 2017}]
        if "kremlin" in lowered:
            return [{"tmdbId": 20004, "title": "Le Mage du Kremlin", "originalTitle": "The Kremlin Wizard", "year": 2026}]
        if "femme" in lowered or "housemaid" in lowered:
            return [
                {
                    "tmdbId": 20005,
                    "title": "La Femme de ménage",
                    "originalTitle": "The Housemaid",
                    "alternateTitles": [{"title": "The Housemaid"}],
                    "year": 2026,
                }
            ]
        if "avatar" in lowered:
            return [
                {
                    "tmdbId": 20006,
                    "title": "Avatar : de feu et de cendres",
                    "originalTitle": "Avatar: Fire and Ash",
                    "alternateTitles": [{"title": "Avatar: Fire and Ash"}],
                    "year": 2026,
                }
            ]
        return []


class _FakeRadarrService:
    """Captures add_movie calls and simulates minimal Radarr behavior."""

    added_calls = []  # class-level capture for simplicity

    def __init__(self, *_, **__):
        pass

    def get_all_movies(self):  # no movies in library -> all unmatched
        return []

    def get_root_folder_paths(self):
        # Advertise both default and mapped folder so mapping validates
        return ["/movies", "/movies/horror"]

    def get_quality_profiles(self):
        return [_FakeQualityProfile()]

    def search_movie(self, title: str):
        # Return a Horror movie to trigger mapping
        return [{"tmdbId": 999999, "title": title, "genres": ["Horror"]}]

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id=None,
        root_folder: str | None = None,
        monitored: bool = True,
        search_for_movie: bool = True,
        additional_tag_labels=None,
    ):
        _FakeRadarrService.added_calls.append(
            {
                "tmdb_id": tmdb_id,
                "root_folder": root_folder,
                "monitored": monitored,
                "search": search_for_movie,
                "additional_tag_labels": list(additional_tag_labels or []),
            }
        )
        return _FakeAddedMovie(tmdb_id, f"Movie {tmdb_id}")


class _FakeBoxOfficeService:
    def __init__(self, *_, **__):
        pass

    def fetch_weekend_box_office(self, year: int, week: int, limit: int = 10):
        if week == 2:
            titles = [
                "L'Affaire Bojarski",
                "Le Chant des forêts",
                "Greenland Migration",
                "Le Mage du Kremlin",
                "La Femme de ménage",
                "Avatar : de feu et de cendres",
            ]
        else:
            titles = ["Scary Movie"]
        return [
            BoxOfficeMovie(
                rank=index,
                title=title,
                weekend_gross=123456,
                total_gross=654321,
                weeks_released=2,
                theater_count=789,
                original_title=title,
                year=2026,
            )
            for index, title in enumerate(titles, start=1)
        ]


@pytest.mark.parametrize(
    "market,country,min_year",
    [
        ("fr", "fr", 1993),
        ("de", "de", 1976),
        ("br", "br", 1976),
        ("cn", "cn", 2002),
        ("kr", "kr", 1976),
        ("es", "es", 1976),
        ("it", "it", 1976),
        ("ru", "ru", 1997),
    ],
)
def test_update_week_historical_year_bounds_follow_market_capabilities(
    tmp_path, monkeypatch, market, country, min_year
):
    config_path = _seed_historical_market_config(tmp_path, market, country)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    import src.core.boxoffice as core_boxoffice

    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FakeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    ok_resp = client.post(
        "/api/scheduler/update-week",
        json={"year": min_year, "week": 10, "market": market},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["success"] is True
    assert ok_resp.json()["market"] == market

    bad_resp = client.post(
        "/api/scheduler/update-week",
        json={"year": min_year - 1, "week": 10, "market": market},
    )
    assert bad_resp.status_code == 400
    assert (
        bad_resp.json()["detail"]
        == f"Market {market} supports historical updates from {min_year} to {datetime.now().year}"
    )


def test_update_week_respects_genre_mapping(tmp_path, monkeypatch):
    # Seed config and force reload
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    # Patch route dependencies to fakes
    # Patch core services that the route imports dynamically inside the function
    import src.core.boxoffice as core_boxoffice
    import src.core.radarr as core_radarr
    import src.core.json_generator as core_json_generator
    import src.api.routes.scheduler as scheduler_routes

    monkeypatch.setattr(core_radarr, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FakeBoxOfficeService)
    monkeypatch.setattr(
        core_json_generator, "WeeklyDataGenerator", FakeWeeklyDataGenerator
    )
    refresh_calls = []
    monkeypatch.setattr(
        scheduler_routes,
        "refresh_stored_status_for_market",
        lambda market: refresh_calls.append(market) or {"weeks_scanned": 0, "weeks_updated": 0, "movies_refreshed": 0, "movies_linked": 0},
    )

    app = create_app()
    client = TestClient(app)

    _FakeRadarrService.added_calls.clear()

    # Use any valid-ish year/week; BoxOfficeService is faked anyway
    resp = client.post(
        "/api/scheduler/update-week",
        json={"year": 2024, "week": 10, "market": "us"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["market"] == "us"
    assert data["provider"] == "mojo"
    assert data["movies_found"] == 1
    assert data["movies_added"] == 1

    # Assert mapping chose the Horror folder
    assert _FakeRadarrService.added_calls, "No add_movie calls captured"
    assert _FakeRadarrService.added_calls[0]["root_folder"] == "/movies/horror"


def test_update_week_fr_uses_tmdb_confirmed_matching_and_rejects_false_positives(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "test-key")

    import src.core.boxoffice as core_boxoffice
    import src.core.radarr as core_radarr
    import src.core.json_generator as core_json_generator
    import src.api.routes.scheduler as scheduler_routes

    monkeypatch.setattr(core_radarr, "RadarrService", _FakeFrRadarrService)
    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FakeBoxOfficeService)
    monkeypatch.setattr(
        core_json_generator, "WeeklyDataGenerator", FakeWeeklyDataGenerator
    )
    refresh_calls = []
    monkeypatch.setattr(
        scheduler_routes,
        "refresh_stored_status_for_market",
        lambda market: refresh_calls.append(market)
        or {
            "weeks_scanned": 0,
            "weeks_updated": 0,
            "movies_refreshed": 0,
            "movies_linked": 0,
        },
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["market"] == "fr"
    assert data["provider"] == "jpboxoffice"
    assert data["movies_found"] == 6
    assert data["movies_added"] == 0
    assert refresh_calls == []

    weekly_path = (
        tmp_path / "weekly_pages" / "fr" / "2026W02.json"
    )
    assert weekly_path.exists()
    with open(weekly_path) as f:
        weekly = json.load(f)
    movies = weekly["movies"]
    by_title = {movie["title"]: movie for movie in movies}
    assert by_title["L'Affaire Bojarski"]["tmdb_id"] is None
    assert by_title["Le Chant des forêts"]["tmdb_id"] is None
    assert by_title["Greenland Migration"]["tmdb_id"] is None
    assert by_title["Le Mage du Kremlin"]["tmdb_id"] is None
    assert by_title["Le Mage du Kremlin"]["radarr_id"] is None
    assert by_title["La Femme de ménage"]["tmdb_id"] == 20005
    assert by_title["La Femme de ménage"]["radarr_id"] == 5
    assert by_title["La Femme de ménage"]["match_method"] == "tmdb_confirmed"
    assert by_title["Avatar : de feu et de cendres"]["tmdb_id"] == 20006
    assert by_title["Avatar : de feu et de cendres"]["radarr_id"] == 6
    assert by_title["Avatar : de feu et de cendres"]["match_method"] == "tmdb_confirmed"
    assert refresh_calls == []


def test_update_week_rejects_invalid_provider(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week",
        json={"year": 2024, "week": 10, "market": "bogus"},
    )
    assert resp.status_code == 400
    assert "Unsupported market" in resp.json()["detail"]


def test_update_week_fr_uses_provider_wiring(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    import src.core.boxoffice as core_boxoffice
    import src.core.radarr as core_radarr

    monkeypatch.setattr(core_radarr, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FakeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2024, "week": 10, "market": "us"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["market"] == "fr"
    assert data["provider"] == "jpboxoffice"

    output_file = tmp_path / "weekly_pages" / "fr" / "2024W10.json"
    assert output_file.exists()
    payload = json.loads(output_file.read_text())
    assert payload["market"] == "fr"
    assert payload["provider"] == "jpboxoffice"
    assert payload["policy_snapshot"]["market"] == "fr"
    assert payload["policy_snapshot"]["fetch_limit_used"] == 10
    assert payload["policy_snapshot"]["add_limit_used"] == 10
    assert payload["movies"][0]["weeks_released"] == 2
    assert payload["movies"][0]["weeks_in_release"] == 2
    assert payload["movies"][0]["theater_count"] == 789
    assert payload["policy_snapshot"]["tag_policy_used"]["added_tag"] == "boxarr-added"


def test_update_week_query_market_wins_over_body_market(tmp_path, monkeypatch):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    import src.core.boxoffice as core_boxoffice
    import src.core.radarr as core_radarr

    monkeypatch.setattr(core_radarr, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FakeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 2, "market": "us"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["market"] == "fr"
    assert data["provider"] == "jpboxoffice"

    output_file = tmp_path / "weekly_pages" / "fr" / "2026W02.json"
    assert output_file.exists()
    assert not (tmp_path / "weekly_pages" / "us" / "2026W02.json").exists()
