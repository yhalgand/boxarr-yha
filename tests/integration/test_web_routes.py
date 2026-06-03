"""Integration tests for rendered HTML/web routes.

This suite covers the web HTML routes in ``src/api/routes/web.py`` and
verifies that the common pages render for both US and FR markets using
minimal weekly JSON fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from bs4 import BeautifulSoup
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


def _seed_weekly_page(
    dir_path: Path,
    market: str,
    provider: str,
    provider_config: dict,
    movie_specs: list[dict],
    *,
    year: int = 2026,
    week: int = 21,
) -> Path:
    market_dir = dir_path / "weekly_pages" / market
    market_dir.mkdir(parents=True, exist_ok=True)
    path = market_dir / f"{year}W{week:02d}.json"

    payload = {
        "generated_at": "2026-05-25T10:00:00",
        "market": market,
        "provider": provider,
        "provider_config": provider_config,
        "source": provider,
        "units": "admissions" if market == "fr" else "gross",
        "year": year,
        "week": week,
        "policy_snapshot": {
            "market": market,
            "provider": provider,
            "provider_config": provider_config,
            "fetch_limit_used": 10,
            "add_limit_used": 3,
            "auto_add_enabled_used": True,
            "tags_used": ["boxarr-added", f"boxarr-market-{market}"],
            "auto_tag_text_used": "boxarr-added",
            "cleanup_protect_tag_used": "boxarr-protected",
            "tag_policy_used": {
                "legacy_tags": ["boxarr", "boxarr-keep"],
                "added_tag": "boxarr-added",
                "market_tag": f"boxarr-market-{market}",
                "existing_tag": f"boxarr-existing-{market}",
                "protected_tag": "boxarr-protected",
                "auto_tag_text": "boxarr-added",
            },
            "policy_applied_at": "2026-05-25T10:00:00",
            "policy_version": 1,
            "year": year,
            "week": week,
        },
        "movies": movie_specs,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _seed_fixture_data(dir_path: Path) -> None:
    _seed_weekly_page(
        dir_path,
        "us",
        "mojo",
        {"area": "us"},
        [
            {
                "rank": 1,
                "title": "US Blockbuster",
                "year": 2026,
                "weekend_gross": 123456.0,
                "total_gross": 223456.0,
                "weeks_released": 1,
                "weeks_in_release": 1,
                "theater_count": 3200,
                "radarr_id": 501,
                "radarr_title": "US Blockbuster",
                "radarr_status": "released",
                "radarr_has_file": True,
                "match_confidence": 0.99,
                "tmdb_id": 900001,
                "status": "Downloaded",
                "has_file": True,
                "quality_profile_name": "HD-1080p",
                "can_upgrade_quality": False,
                "poster": "https://image.example/us.jpg",
                "imdb_id": "tt9000001",
                "genres": "Action, Adventure",
                "source_href": "/release/us-blockbuster",
                "source_url": "https://www.boxofficemojo.com/weekend/2026W21/",
                "source_title": "US Blockbuster",
                "normalized_source_title": "us blockbuster",
            },
            {
                "rank": 2,
                "title": "US Indie",
                "year": 2026,
                "weekend_gross": "65432",
                "total_gross": "95432",
                "weeks_released": 2,
                "weeks_in_release": 2,
                "theater_count": 1200,
                "radarr_id": None,
                "radarr_title": None,
                "radarr_status": None,
                "radarr_has_file": False,
                "match_confidence": 0.0,
                "tmdb_id": 900002,
                "status": "Missing",
                "has_file": False,
                "quality_profile_name": None,
                "can_upgrade_quality": False,
                "poster": "",
                "imdb_id": "",
                "genres": "Drama",
                "source_href": "/release/us-indie",
                "source_url": "https://www.boxofficemojo.com/weekend/2026W21/",
                "source_title": "US Indie",
                "normalized_source_title": "us indie",
            },
        ],
    )

    _seed_weekly_page(
        dir_path,
        "fr",
        "jpboxoffice",
        {"country": "fr"},
        [
            {
                "rank": 1,
                "title": "Mufasa: Le Roi Lion",
                "year": 2025,
                "weekend_gross": "373410",
                "total_gross": 3823351.0,
                "weeks_released": 5,
                "weeks_in_release": 5,
                "theater_count": 967,
                "radarr_id": 12582,
                "radarr_title": "Mufasa: Le Roi Lion",
                "radarr_status": "released",
                "radarr_has_file": True,
                "match_confidence": 0.98,
                "tmdb_id": 27047903,
                "status": "Downloaded",
                "has_file": True,
                "quality_profile_name": "HD-1080p",
                "can_upgrade_quality": False,
                "poster": "https://image.example/fr1.jpg",
                "imdb_id": "tt1234567",
                "genres": "Animation / Adventure",
                "source_href": "/fichfilm.php?id=1001&view=2",
                "source_url": "https://www.jpbox-office.com/v9_tophebdo.php?idsem=2926&view=2",
                "source_title": "Mufasa: Le Roi Lion",
                "normalized_source_title": "mufasa le roi lion",
                "jpboxoffice_id": 1001,
            },
            {
                "rank": 2,
                "title": "Avatar : de feu et de cendres",
                "year": 2026,
                "weekend_gross": 336843.0,
                "total_gross": "8242711",
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
                "quality_profile_name": "HD-1080p",
                "can_upgrade_quality": True,
                "poster": "https://image.example/fr2.jpg",
                "imdb_id": "tt7654321",
                "genres": "Science-Fiction",
                "source_href": "/fichfilm.php?id=1002&view=2",
                "source_url": "https://www.jpbox-office.com/v9_tophebdo.php?idsem=2926&view=2",
                "source_title": "Avatar : de feu et de cendres",
                "normalized_source_title": "avatar de feu et de cendres",
                "jpboxoffice_id": 1002,
            },
        ],
    )


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    config_path = _seed_config_without_markets(tmp_path)
    _seed_fixture_data(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)
    yield client

    Settings.reload_from_file(Path("config/default.yaml").resolve())


def _assert_successful_html(response, *markers: str) -> None:
    assert response.status_code == 200
    assert "Internal Server Error" not in response.text
    assert "Traceback" not in response.text
    for marker in markers:
        assert marker in response.text


def _assert_redirect(response, expected_fragment: str) -> None:
    assert response.status_code in {302, 307}
    assert expected_fragment in response.headers["location"]


@pytest.mark.parametrize(
    "path,expected_fragment",
    [
        ("/", "/overview?market=us"),
        ("/settings", "/setup?market=us"),
        ("/overview", "/overview?market=us"),
        ("/weeks", "/weeks?market=us"),
        ("/dashboard", "/weeks?market=us"),
        ("/setup", "/setup?market=us"),
        ("/2026W21", "/2026W21?market=us"),
    ],
)
def test_html_routes_redirect_to_default_market_when_missing_query(
    web_client, path, expected_fragment
):
    no_follow_client = TestClient(web_client.app, follow_redirects=False)
    response = no_follow_client.get(path)
    _assert_redirect(response, expected_fragment)


@pytest.mark.parametrize(
    "path,markers",
    [
        (
            "/setup?market=us",
            [
                "Global Settings",
                "Markets",
                "Maintenance / Migration",
                "US Box Office",
            ],
        ),
        (
            "/setup?market=fr",
            [
                "Global Settings",
                "Markets",
                "Maintenance / Migration",
                "France Box Office",
            ],
        ),
        (
            "/overview?market=us",
            [
                "Movie Overview",
                "US Blockbuster",
                "US Indie",
                "Best: $123,456",
            ],
        ),
        (
            "/overview?market=fr",
            [
                "Movie Overview",
                "France Box Office uses admissions/entries, not USD gross.",
                "Mufasa: Le Roi Lion",
                "Avatar : de feu et de cendres",
            ],
        ),
        (
            "/weeks?market=us",
            [
                "Boxarr Dashboard",
                "Current Market Policy",
                "US Box Office",
                "Weekly Box Office Reports",
            ],
        ),
        (
            "/weeks?market=fr",
            [
                "Boxarr Dashboard",
                "Current Market Policy",
                "France Box Office",
                "Weekly Box Office Reports",
            ],
        ),
        (
            "/dashboard?market=us",
            [
                "Boxarr Dashboard",
                "Current Market Policy",
                "US Box Office",
                "Weekly Box Office Reports",
            ],
        ),
        (
            "/dashboard?market=fr",
            [
                "Boxarr Dashboard",
                "Current Market Policy",
                "France Box Office",
                "Weekly Box Office Reports",
            ],
        ),
        (
            "/2026W21?market=us",
            [
                "Box Office Week 21, 2026",
                "Current Market Policy",
                "US Blockbuster",
            ],
        ),
        (
            "/2026W21?market=fr",
            [
                "Box Office Week 21, 2026",
                "France Box Office uses admissions/entries, not USD gross.",
                "Mufasa: Le Roi Lion",
            ],
        ),
        (
            "/api/widget?market=us",
            [
                "Box Office Week 21, 2026",
                "View Full List",
            ],
        ),
        (
            "/api/widget?market=fr",
            [
                "Box Office Week 21, 2026",
                "View Full List",
            ],
        ),
    ],
)
def test_html_routes_render_successfully(web_client, path, markers):
    response = web_client.get(path)
    _assert_successful_html(response, *markers)


def test_setup_page_renders_when_preview_has_no_definition_key(web_client, monkeypatch):
    def _raw_market_previews(_settings_obj):
        return {
            "us": {
                "effective": {
                    "box_office_fetch_limit": 10,
                    "maximum_movies_to_add": 3,
                    "auto_add_enabled": True,
                    "tags": ["boxarr-added", "boxarr-market-us"],
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
                    "tags": ["boxarr-added", "boxarr-market-fr"],
                    "cleanup_protect_tag": "boxarr-protected",
                },
                "sources": {},
                "tag_policy": {},
            },
        }

    monkeypatch.setattr(web_routes, "_build_market_previews", _raw_market_previews)

    response = web_client.get("/setup?market=us")
    _assert_successful_html(response, "US Box Office", "Canonical:", "boxarr-protected")


def test_web_route_pages_do_not_return_tracebacks(web_client):
    paths = [
        "/overview?market=fr",
        "/weeks?market=fr",
        "/dashboard?market=fr",
        "/2026W21?market=fr",
        "/api/widget?market=fr",
    ]
    for path in paths:
        response = web_client.get(path)
        assert "Traceback" not in response.text
        assert "Internal Server Error" not in response.text


def test_overview_merges_matched_and_unmatched_fr_occurrences(
    tmp_path, monkeypatch
):
    config_path = _seed_config_without_markets(tmp_path)
    _seed_fixture_data(tmp_path)
    _seed_weekly_page(
        tmp_path,
        "fr",
        "jpboxoffice",
        {"country": "fr"},
        [
            {
                "rank": 1,
                "title": "Le Mage du Kremlin",
                "year": 2026,
                "weekend_gross": 123456,
                "total_gross": 223456,
                "weeks_released": 1,
                "weeks_in_release": 1,
                "theater_count": 500,
                "radarr_id": None,
                "radarr_title": None,
                "radarr_status": None,
                "radarr_has_file": False,
                "match_confidence": 0.0,
                "tmdb_id": None,
                "status": "Not in Radarr",
                "has_file": False,
                "quality_profile_name": None,
                "can_upgrade_quality": False,
                "poster": None,
                "imdb_id": None,
                "genres": "Drama",
                "source_href": "/fichfilm.php?id=24871&view=2",
                "source_url": "https://www.jpbox-office.com/v9_tophebdo.php?idsem=2926&view=2",
                "source_title": "Le Mage du Kremlin",
                "normalized_source_title": "le mage du kremlin",
                "jpboxoffice_id": 24871,
            }
        ],
        year=2026,
        week=20,
    )
    _seed_weekly_page(
        tmp_path,
        "fr",
        "jpboxoffice",
        {"country": "fr"},
        [
            {
                "rank": 1,
                "title": "Le Mage du Kremlin",
                "year": 2026,
                "weekend_gross": 223456,
                "total_gross": 323456,
                "weeks_released": 1,
                "weeks_in_release": 1,
                "theater_count": 550,
                "radarr_id": 777,
                "radarr_title": "Le Mage du Kremlin",
                "radarr_status": "released",
                "radarr_has_file": True,
                "match_confidence": 0.95,
                "match_method": "tmdb_confirmed",
                "tmdb_id": 900777,
                "status": "Downloaded",
                "has_file": True,
                "quality_profile_name": "HD-1080p",
                "can_upgrade_quality": False,
                "poster": "https://image.example/kremlin.jpg",
                "imdb_id": "tt9000777",
                "genres": "Drama",
                "identity_status": "Matched in Radarr",
                "source_href": "/fichfilm.php?id=24871&view=2",
                "source_url": "https://www.jpbox-office.com/v9_tophebdo.php?idsem=2926&view=2",
                "source_title": "Le Mage du Kremlin",
                "normalized_source_title": "le mage du kremlin",
                "jpboxoffice_id": 24871,
            }
        ],
        year=2026,
        week=21,
    )

    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    response = client.get("/overview?market=fr")
    _assert_successful_html(response, "Movie Overview", "Le Mage du Kremlin")
    soup = BeautifulSoup(response.text, "html.parser")
    titles = [node.get_text(strip=True) for node in soup.select(".movie-title")]
    assert titles.count("Le Mage du Kremlin") == 1
    week_badges = [node.get_text(strip=True) for node in soup.select(".week-badge")]
    assert "2026W20" in week_badges
    assert "2026W21" in week_badges
