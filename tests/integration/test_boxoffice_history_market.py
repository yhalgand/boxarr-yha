"""Integration tests for market-aware historical box office API."""

from pathlib import Path
import json
from datetime import datetime
from unittest.mock import MagicMock

import yaml
import pytest
import httpx
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.boxoffice import BoxOfficeError, BoxOfficeMovie, BoxOfficeService
from src.utils.config import Settings, settings


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


def _response(url: str, html: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, request=request, content=html.encode("utf-8"))


def _country_fixture_html(html: str, view: int) -> str:
    return html.replace("view=2", f"view={view}")


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
                    {
                        "rank": 3,
                        "title": "Low Confidence Movie",
                        "original_title": "Low Confidence Movie",
                        "source_year": 2026,
                        "weekend_gross": 1000,
                        "total_gross": 2000,
                        "weeks_released": 1,
                        "weeks_in_release": 1,
                        "theater_count": 10,
                        "radarr_id": 999,
                        "radarr_title": "Should Be Cleared",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "match_confidence": 0.0,
                        "tmdb_id": 888,
                        "status": "Downloaded",
                        "has_file": True,
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

    assert len(data) == 3
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

    assert data[2]["match_confidence"] == 0.0
    assert data[2]["tmdb_id"] is None
    assert data[2]["radarr_id"] is None
    assert data[2]["radarr_status"] is None
    assert data[2]["radarr_has_file"] is False


def _assert_history_response_has_no_duplicate_ids_and_no_confidence_zero_ids(data):
    titles = [item["title"] for item in data]
    assert "Titre" not in titles
    assert "Title" not in titles

    seen_tmdb = {}
    seen_radarr = {}
    for item in data:
        confidence = float(item.get("match_confidence") or 0.0)
        if confidence <= 0:
            assert item.get("tmdb_id") is None
            assert item.get("radarr_id") is None
            assert item.get("radarr_status") is None
        tmdb_id = item.get("tmdb_id")
        radarr_id = item.get("radarr_id")
        if tmdb_id is not None:
            assert tmdb_id not in seen_tmdb
            seen_tmdb[tmdb_id] = item["title"]
        if radarr_id is not None:
            assert radarr_id not in seen_radarr
            seen_radarr[radarr_id] = item["title"]


def test_history_boxoffice_route_sanitizes_fr_w02_header_and_duplicate_ids(
    tmp_path, monkeypatch
):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    fr_dir = tmp_path / "weekly_pages" / "fr"
    fr_dir.mkdir(parents=True)
    with open(fr_dir / "2026W02.json", "w") as f:
        json.dump(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "provider_config": {"country": "fr"},
                "year": 2026,
                "week": 2,
                "movies": [
                    {
                        "rank": 1,
                        "title": "Titre",
                        "radarr_id": 9167,
                        "radarr_title": "Header Artifact",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "match_confidence": 0.0,
                        "tmdb_id": 246655,
                        "status": "Downloaded",
                        "has_file": True,
                    },
                    {
                        "rank": 2,
                        "title": "La Femme de ménage",
                        "original_title": "The Housemaid",
                        "source_year": 2026,
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
                        "rank": 3,
                        "title": "Avatar : de feu et de cendres",
                        "original_title": "Avatar: Fire and Ash",
                        "source_year": 2026,
                        "radarr_id": 12510,
                        "radarr_title": "Avatar: Fire and Ash",
                        "radarr_status": "released",
                        "radarr_has_file": False,
                        "match_confidence": 0.97,
                        "tmdb_id": 12345678,
                        "status": "Missing",
                        "has_file": False,
                    },
                    {
                        "rank": 4,
                        "title": "Mufasa: Le Roi Lion",
                        "original_title": "Mufasa: The Lion King",
                        "source_year": 2025,
                        "radarr_id": 9167,
                        "radarr_title": "Mufasa: The Lion King",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "match_confidence": 0.0,
                        "tmdb_id": 246655,
                        "status": "Downloaded",
                        "has_file": True,
                    },
                    {"rank": 5, "title": "Le Mage du Kremlin", "match_confidence": 0.95, "tmdb_id": 300001, "radarr_id": 13001, "radarr_status": "released", "radarr_has_file": True, "status": "Downloaded", "has_file": True},
                    {"rank": 6, "title": "L’Affaire Bojarski", "match_confidence": 0.94, "tmdb_id": 300002, "radarr_id": 13002, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
                    {"rank": 7, "title": "Zootopie 2", "match_confidence": 0.93, "tmdb_id": 300003, "radarr_id": 13003, "radarr_status": "released", "radarr_has_file": True, "status": "Downloaded", "has_file": True},
                    {"rank": 8, "title": "Sonic 3", "match_confidence": 0.92, "tmdb_id": 300004, "radarr_id": 13004, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
                    {"rank": 9, "title": "Wicked", "match_confidence": 0.91, "tmdb_id": 300005, "radarr_id": 13005, "radarr_status": "released", "radarr_has_file": True, "status": "Downloaded", "has_file": True},
                    {"rank": 10, "title": "Mickey 17", "match_confidence": 0.90, "tmdb_id": 300006, "radarr_id": 13006, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
                    {"rank": 11, "title": "Paddington au Pérou", "match_confidence": 0.89, "tmdb_id": 300007, "radarr_id": 13007, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
                ],
            },
            f,
            indent=2,
        )

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/history/2026/W02?market=fr")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 10
    assert [item["rank"] for item in data] == list(range(1, 11))
    _assert_history_response_has_no_duplicate_ids_and_no_confidence_zero_ids(data)


def test_history_boxoffice_route_sanitizes_fr_w21_confidence_and_duplicates(
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
                "provider": "jpboxoffice",
                "provider_config": {"country": "fr"},
                "year": 2026,
                "week": 21,
                "movies": [
                    {
                        "rank": 1,
                        "title": "La Femme de ménage",
                        "original_title": "The Housemaid",
                        "source_year": 2026,
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
                        "radarr_id": 12510,
                        "radarr_title": "Avatar: Fire and Ash",
                        "radarr_status": "released",
                        "radarr_has_file": False,
                        "match_confidence": 0.97,
                        "tmdb_id": 12345678,
                        "status": "Missing",
                        "has_file": False,
                    },
                    {
                        "rank": 3,
                        "title": "Low Confidence Movie A",
                        "original_title": "Low Confidence Movie A",
                        "source_year": 2026,
                        "radarr_id": 9167,
                        "radarr_title": "Shared Radarr Title",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "match_confidence": 0.0,
                        "tmdb_id": 246655,
                        "status": "Downloaded",
                        "has_file": True,
                    },
                    {
                        "rank": 4,
                        "title": "Low Confidence Movie B",
                        "original_title": "Low Confidence Movie B",
                        "source_year": 2026,
                        "radarr_id": 9167,
                        "radarr_title": "Shared Radarr Title",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "match_confidence": 0.0,
                        "tmdb_id": 246655,
                        "status": "Downloaded",
                        "has_file": True,
                    },
                    {"rank": 5, "title": "Le Mage du Kremlin", "match_confidence": 0.95, "tmdb_id": 300001, "radarr_id": 13001, "radarr_status": "released", "radarr_has_file": True, "status": "Downloaded", "has_file": True},
                    {"rank": 6, "title": "L’Affaire Bojarski", "match_confidence": 0.94, "tmdb_id": 300002, "radarr_id": 13002, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
                    {"rank": 7, "title": "Zootopie 2", "match_confidence": 0.93, "tmdb_id": 300003, "radarr_id": 13003, "radarr_status": "released", "radarr_has_file": True, "status": "Downloaded", "has_file": True},
                    {"rank": 8, "title": "Sonic 3", "match_confidence": 0.92, "tmdb_id": 300004, "radarr_id": 13004, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
                    {"rank": 9, "title": "Wicked", "match_confidence": 0.91, "tmdb_id": 300005, "radarr_id": 13005, "radarr_status": "released", "radarr_has_file": True, "status": "Downloaded", "has_file": True},
                    {"rank": 10, "title": "Mickey 17", "match_confidence": 0.90, "tmdb_id": 300006, "radarr_id": 13006, "radarr_status": "released", "radarr_has_file": False, "status": "Missing", "has_file": False},
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
    assert len(data) == 10
    assert [item["rank"] for item in data] == list(range(1, 11))
    _assert_history_response_has_no_duplicate_ids_and_no_confidence_zero_ids(data)


def test_history_boxoffice_route_clears_dirty_fr_jpboxoffice_matches(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    fr_dir = tmp_path / "weekly_pages" / "fr"
    fr_dir.mkdir(parents=True)
    with open(fr_dir / "2026W02.json", "w") as f:
        json.dump(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "provider_config": {"country": "fr"},
                "year": 2026,
                "week": 2,
                "movies": [
                    {
                        "rank": 1,
                        "title": "L'Affaire Bojarski",
                        "provider": "jpboxoffice",
                        "match_method": "fuzzy",
                        "match_confidence": 0.95,
                        "tmdb_id": 12345,
                        "radarr_id": 67890,
                        "radarr_title": "X-Men: Apocalypse",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "has_file": True,
                        "quality_profile_name": "HD-1080p",
                        "year": 2016,
                        "genres": "Action",
                    }
                ],
            },
            f,
            indent=2,
        )

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/history/2026/W02?market=fr")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["tmdb_id"] is None
    assert data[0]["radarr_id"] is None
    assert data[0]["radarr_title"] is None
    assert data[0]["radarr_status"] is None
    assert data[0]["radarr_has_file"] is False
    assert data[0]["has_file"] is False
    assert data[0]["quality_profile_name"] is None


@pytest.mark.parametrize(
    "market,country,view,min_year",
    [
        ("fr", "fr", 2, 1993),
        ("de", "de", 4, 1976),
    ],
)
def test_history_boxoffice_route_smoke_fetches_supported_jpboxoffice_countries(
    tmp_path, monkeypatch, market, country, view, min_year
):
    config_path = _seed_historical_market_config(tmp_path, market, country)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    year_html = _country_fixture_html(
        (Path(__file__).resolve().parents[1] / "fixtures" / "jpboxoffice_fr_year_2026.html").read_text(encoding="utf-8"),
        view,
    )
    weekly_html = _country_fixture_html(
        (Path(__file__).resolve().parents[1] / "fixtures" / "jpboxoffice_fr_week_2026w02.html").read_text(encoding="utf-8"),
        view,
    )

    client = MagicMock()

    def fake_get(url: str):
        if f"v9_hebdomadaire.php?view={view}&year={min_year}" in url or f"v9_hebdomadaire.php?view={view}&year=2026" in url:
            return _response(url, year_html)
        if f"v9_tophebdo.php?idsem=2926&view={view}" in url:
            return _response(url, weekly_html)
        if f"fichfilm.php?id=12345&view={view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        if f"fichfilm.php?id=23456&view={view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt7654321/'>IMDb</a></body></html>",
            )
        if f"fichfilm.php?id=24858&view={view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    real_service = BoxOfficeService(http_client=client, market=market)
    import src.api.routes.boxoffice as boxoffice_routes

    monkeypatch.setattr(boxoffice_routes, "BoxOfficeService", lambda *_, **__: real_service)

    app = create_app()
    test_client = TestClient(app)

    resp = test_client.get(f"/api/boxoffice/history/{min_year}/W04?market={market}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 10
    assert data[0]["title"] == "La Femme de ménage"
    assert data[0]["radarr_has_file"] is False
    assert data[0]["match_confidence"] == 0.0

    bad_resp = test_client.get(f"/api/boxoffice/history/{min_year - 1}/W04?market={market}")
    assert bad_resp.status_code == 400
    assert f"supports historical updates from {min_year} to " in bad_resp.json()["detail"]


def test_history_boxoffice_route_de_returns_200_with_mocked_live_fetch(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "de", "de")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    class _FakeDeBoxOfficeService:
        def __init__(self, *_, **__):
            pass

        def fetch_weekend_box_office(self, year, week, limit=10):
            assert year == 1976
            assert week == 1
            assert limit == 10
            return [
                BoxOfficeMovie(
                    rank=1,
                    title="German Movie",
                    weekend_gross=123.0,
                    total_gross=456.0,
                    weeks_released=1,
                    theater_count=100,
                    source_href="/fichfilm.php?id=50001&view=4",
                    source_url="https://www.jpbox-office.com/v9_tophebdo.php?idsem=2901&view=4",
                    source_title="German Movie",
                    jpboxoffice_id=50001,
                )
            ]

    import src.api.routes.boxoffice as boxoffice_routes

    monkeypatch.setattr(boxoffice_routes, "BoxOfficeService", _FakeDeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/history/1976/W01?market=de")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "German Movie"
    assert data[0]["weeks_released"] == 1
    assert data[0]["is_new_release"] is True
    assert data[0]["source_href"] == "/fichfilm.php?id=50001&view=4"
    assert data[0]["jpboxoffice_id"] == 50001
    assert data[0]["identity_status"] == "Unmatched / needs identity"


def test_history_boxoffice_route_de_returns_200_on_live_fetch_error(tmp_path, monkeypatch):
    config_path = _seed_historical_market_config(tmp_path, "de", "de")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    class _ErroringDeBoxOfficeService:
        def __init__(self, *_, **__):
            pass

        def fetch_weekend_box_office(self, year, week, limit=10):
            raise BoxOfficeError("JPBoxOffice country 'de' is not implemented yet")

    import src.api.routes.boxoffice as boxoffice_routes

    monkeypatch.setattr(boxoffice_routes, "BoxOfficeService", _ErroringDeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/history/1976/W01?market=de")
    assert resp.status_code == 200
    assert resp.json() == []


def test_history_boxoffice_route_de_returns_500_on_parse_error(tmp_path, monkeypatch):
    config_path = _seed_historical_market_config(tmp_path, "de", "de")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    class _ParseErrorDeBoxOfficeService:
        def __init__(self, *_, **__):
            pass

        def fetch_weekend_box_office(self, year, week, limit=10):
            raise BoxOfficeError(
                "JPBoxOffice parse error: partial ranking parse "
                "(source_url=https://example.test, country=de, view=4, rows_seen=10, rows_parsed=8)"
            )

    import src.api.routes.boxoffice as boxoffice_routes

    monkeypatch.setattr(boxoffice_routes, "BoxOfficeService", _ParseErrorDeBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/boxoffice/history/1976/W01?market=de")
    assert resp.status_code == 500
    assert "JPBoxOffice parse error" in resp.json()["detail"]


def test_history_boxoffice_route_fr_w02_uses_row_order_rank_and_returns_10(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    year_html = (
        "<html><body><table><tr>"
        "<td><a href='/v9_tophebdo.php?idsem=2902&view=2'>2</a></td>"
        "</tr></table></body></html>"
    )
    weekly_html = (Path(__file__).resolve().parents[1] / "fixtures" / "jpboxoffice_fr_week_2026w02.html").read_text(encoding="utf-8")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2902&view=2" in url:
            return _response(url, weekly_html)
        if "fichfilm.php?id=12345&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        if "fichfilm.php?id=23456&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt7654321/'>IMDb</a></body></html>",
            )
        if "fichfilm.php?id=34567&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt3456789/'>IMDb</a></body></html>",
            )
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    real_service = BoxOfficeService(http_client=client, market="fr")
    import src.api.routes.boxoffice as boxoffice_routes

    monkeypatch.setattr(boxoffice_routes, "BoxOfficeService", lambda *_, **__: real_service)

    app = create_app()
    test_client = TestClient(app)

    resp = test_client.get("/api/boxoffice/history/2026/W02?market=fr")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 10
    assert [item["rank"] for item in data] == list(range(1, 11))
    expected_titles = [
        "La Femme de ménage",
        "Avatar : de feu et de cendres",
        "Le Mage du Kremlin",
        "L'Affaire Bojarski",
        "Zootopie 2",
        "Primate",
        "Hamnet",
        "Le Chant des forêts",
        "Greenland Migration",
        "28 Ans Plus Tard : Le Temple Des Morts",
    ]
    assert [item["title"] for item in data] == expected_titles
    assert all(not item["title"].startswith("N°1 ") for item in data)


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
def test_history_boxoffice_route_uses_market_historical_bounds(
    tmp_path, monkeypatch, market, country, min_year
):
    config_path = _seed_historical_market_config(tmp_path, market, country)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    market_dir = tmp_path / "weekly_pages" / market
    market_dir.mkdir(parents=True, exist_ok=True)
    with open(market_dir / f"{min_year}W21.json", "w") as f:
        json.dump(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": market,
                "provider": "jpboxoffice",
                "provider_config": {"country": country},
                "year": min_year,
                "week": 21,
                "movies": [
                    {
                        "rank": 1,
                        "title": f"{market.upper()} Historical Movie",
                        "radarr_id": None,
                    }
                ],
            },
            f,
            indent=2,
        )

    app = create_app()
    client = TestClient(app)

    ok_resp = client.get(f"/api/boxoffice/history/{min_year}/W21?market={market}")
    assert ok_resp.status_code == 200
    assert ok_resp.json()[0]["title"] == f"{market.upper()} Historical Movie"

    bad_resp = client.get(f"/api/boxoffice/history/{min_year - 1}/W21?market={market}")
    assert bad_resp.status_code == 400
    assert (
        bad_resp.json()["detail"]
        == f"Market {market} supports historical updates from {min_year} to {datetime.now().year}"
    )
