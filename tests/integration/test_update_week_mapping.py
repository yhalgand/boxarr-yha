"""Integration test: historical update uses genre→root-folder mapping.

This verifies that POST /api/scheduler/update-week applies the same
genre-based root folder mapping as the main scheduler/manual add paths.
"""

from pathlib import Path
import json
from datetime import datetime
import httpx

import yaml
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.boxoffice import BoxOfficeError, BoxOfficeMovie
from src.core.models import MovieStatus
from src.core.radarr import RadarrMovie
from src.utils.config import Settings, settings
from tests.helpers import FakeWeeklyDataGenerator


def _jpboxoffice_week_html(idsem: int, title: str, movie_title: str) -> str:
    rows = []
    for rank in range(1, 11):
        rows.append(
            f"""
          <div class="movie-block">
            <div>{rank}</div>
            <div>Image</div>
            <a href="/fichfilm.php?id={idsem}{rank:02d}&view=2">{movie_title} {rank}</a>
            <div>{movie_title} {rank} Original</div>
            <div>(Studio)</div>
            <div>France / Drame / 2h00 1 100 000 120 200 000</div>
          </div>
            """
        )
    return f"""
    <html>
      <head><title>{title}</title></head>
      <body>
        <div class="weekly-fr">
          {''.join(rows)}
        </div>
      </body>
    </html>
    """


def _allocine_week_html(date_label: str, movie_title: str = "Allocine Movie") -> str:
    rows = []
    for rank in range(1, 11):
        allocine_id = 500000 + rank
        rows.append(
            f"""
            <tr>
              <td>{rank}</td>
              <td><a href="/film/fichefilm_gen_cfilm={allocine_id}.html">{movie_title} {rank}</a></td>
              <td>{100000 + rank}</td>
              <td>{200000 + rank}</td>
            </tr>
            """
        )
    return f"""
    <html>
      <head><title>Box Office Cinéma - Semaine du {date_label}</title></head>
      <body>
        <h1>Box Office Cinéma - Semaine du {date_label}</h1>
        <table><tbody>{''.join(rows)}</tbody></table>
      </body>
    </html>
    """


def _http_response(url: str, html: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, request=request, content=html.encode("utf-8"))


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
    if market == "fr" and country == "fr":
        provider = "france_boxoffice"
        provider_config = {"country": "fr", "primary": "allocine", "min_entries": 10}
    else:
        provider = "jpboxoffice"
        provider_config = {"country": country}

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
                "provider": provider,
                "provider_config": provider_config,
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
        ("fr", "fr", 1998),
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
    assert data["provider"] == "france_boxoffice"
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
    assert by_title["Le Mage du Kremlin"]["tmdb_id"] == 20004
    assert by_title["Le Mage du Kremlin"]["radarr_id"] is None
    assert by_title["Le Mage du Kremlin"]["match_method"] == "tmdb_confirmed"
    assert by_title["Le Mage du Kremlin"]["match_confidence"] > 0
    assert by_title["La Femme de ménage"]["tmdb_id"] == 20005
    assert by_title["La Femme de ménage"]["radarr_id"] == 5
    assert by_title["La Femme de ménage"]["match_method"] == "tmdb_confirmed"
    assert by_title["Avatar : de feu et de cendres"]["tmdb_id"] == 20006
    assert by_title["Avatar : de feu et de cendres"]["radarr_id"] == 6
    assert by_title["Avatar : de feu et de cendres"]["match_method"] == "tmdb_confirmed"
    assert refresh_calls == []


def test_update_week_fr_skips_incomplete_jpboxoffice_week_cleanly(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "test-key")

    import src.core.boxoffice as core_boxoffice
    import src.core.json_generator as core_json_generator

    class _IncompleteFrBoxOfficeService:
        def __init__(self, *_, **__):
            pass

        def fetch_weekend_box_office(self, year: int, week: int, limit: int = 10):
            raise BoxOfficeError(
                "skipped_incomplete_week: source_url=https://www.jpbox-office.com/v9_tophebdo.php?idsem=2944&view=2 country=fr view=2 latest_completed_idsem=2943 date_range=DU 27 Mai AU 02 Juin 2026 (5 Jours)"
            )

        def extract_detail_metadata(self, release_url):
            return {}

        def get_root_folder_paths(self):
            return ["/movies"]

        def get_quality_profiles(self):
            return [_FakeQualityProfile()]

    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _IncompleteFrBoxOfficeService)
    monkeypatch.setattr(
        core_json_generator, "WeeklyDataGenerator", FakeWeeklyDataGenerator
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 22},
    )
    assert resp.status_code == 409
    assert "skipped_incomplete_week" in resp.json()["detail"]
    assert "latest_completed_idsem=2943" in resp.json()["detail"]

    weekly_path = tmp_path / "weekly_pages" / "fr" / "2026W22.json"
    assert not weekly_path.exists()


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
    assert data["provider"] == "france_boxoffice"

    output_file = tmp_path / "weekly_pages" / "fr" / "2024W10.json"
    assert output_file.exists()
    payload = json.loads(output_file.read_text())
    assert payload["market"] == "fr"
    assert payload["provider"] == "france_boxoffice"
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
    assert data["provider"] == "france_boxoffice"

    output_file = tmp_path / "weekly_pages" / "fr" / "2026W02.json"
    assert output_file.exists()
    assert not (tmp_path / "weekly_pages" / "us" / "2026W02.json").exists()


def test_update_week_existing_data_is_kept_on_upstream_failure(tmp_path, monkeypatch):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    existing_file = tmp_path / "weekly_pages" / "fr" / "2026W22.json"
    existing_file.parent.mkdir(parents=True, exist_ok=True)
    existing_file.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "year": 2026,
                "week": 22,
                "movies": [{"rank": 1, "title": "Existing Movie"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class _FailingBoxOfficeService:
        def __init__(self, *_, **__):
            pass

        def fetch_weekend_box_office(self, year: int, week: int, limit: int = 10):
            raise BoxOfficeError("Failed to fetch JPBoxOffice data after retries: boom")

    import src.core.boxoffice as core_boxoffice

    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FailingBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 22},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "refresh_failed_but_existing_data_kept"
    assert "after retries" in data["detail"]
    assert existing_file.exists()
    assert json.loads(existing_file.read_text(encoding="utf-8"))["movies"][0]["title"] == "Existing Movie"


def test_update_week_failure_does_not_poison_next_week(tmp_path, monkeypatch):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    class _FlakyThenStableBoxOfficeService:
        calls = []

        def __init__(self, *_, **__):
            pass

        def fetch_weekend_box_office(self, year: int, week: int, limit: int = 10):
            self.calls.append((year, week))
            if week == 21 and len([c for c in self.calls if c[1] == 21]) == 1:
                raise BoxOfficeError("Failed to fetch JPBoxOffice data after retries: boom")
            return [
                BoxOfficeMovie(
                    rank=1,
                    title=f"Week {week}",
                    weekend_gross=1000,
                    total_gross=2000,
                    weeks_released=1,
                    theater_count=100,
                    year=2026,
                )
            ]

    import src.core.boxoffice as core_boxoffice
    import src.core.json_generator as core_json_generator

    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _FlakyThenStableBoxOfficeService)
    monkeypatch.setattr(
        core_json_generator, "WeeklyDataGenerator", FakeWeeklyDataGenerator
    )

    app = create_app()
    client = TestClient(app)

    first = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 21},
    )
    assert first.status_code == 200
    assert first.json()["success"] is False

    second = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 22},
    )
    assert second.status_code == 200
    assert second.json()["success"] is True
    assert second.json()["market"] == "fr"
    assert second.json()["provider"] == "france_boxoffice"
    assert (tmp_path / "weekly_pages" / "fr" / "2026W22.json").exists()


def test_update_week_fr_explicit_weeks_use_allocine_week_urls(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    import src.core.boxoffice as core_boxoffice

    page_by_date = {
        "2026-05-06": _allocine_week_html("mercredi 6 mai 2026", "Week 19 Movie"),
        "2026-05-13": _allocine_week_html("mercredi 13 mai 2026", "Week 20 Movie"),
        "2026-05-20": _allocine_week_html("mercredi 20 mai 2026", "Week 21 Movie"),
    }
    requested_urls = []

    class _FakeHttpClient:
        def get(self, url: str):
            requested_urls.append(url)
            if "jpbox-office.com" in url:
                raise AssertionError("official FR update must not call JPBoxOffice")
            for date_key, html in page_by_date.items():
                if f"sem-{date_key}" in url:
                    return _http_response(url, html)
            if "fichefilm_gen_cfilm" in url:
                return _http_response(url, "<html><body></body></html>")
            raise AssertionError(f"Unexpected URL: {url}")

        def close(self):
            pass

    original_service = core_boxoffice.BoxOfficeService

    class _DirectFrBoxOfficeService(original_service):
        def __init__(self, *args, **kwargs):
            kwargs["http_client"] = _FakeHttpClient()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _DirectFrBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    for week, expected_date in [(19, "2026-05-06"), (20, "2026-05-13"), (21, "2026-05-20")]:
        resp = client.post(
            "/api/scheduler/update-week?market=fr",
            json={"year": 2026, "week": week},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        output_file = tmp_path / "weekly_pages" / "fr" / f"2026W{week:02d}.json"
        assert output_file.exists()
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        assert payload["year"] == 2026
        assert payload["week"] == week
        assert payload["source_year"] == 2026
        assert payload["source_week"] == week
        assert payload["movies"][0]["source_week"] == week
        source_url = payload["movies"][0]["source_url"]
        assert source_url == f"https://www.allocine.fr/boxoffice/france/sem-{expected_date}/"
        assert "jpbox-office.com" not in source_url

    assert not any("jpbox-office.com" in url for url in requested_urls)


def test_update_week_fr_allocine_week_mismatch_fails_without_writing(
    tmp_path, monkeypatch
):
    config_path = _seed_historical_market_config(tmp_path, "fr", "fr")
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)
    monkeypatch.setattr(settings, "radarr_api_key", "")

    import src.core.boxoffice as core_boxoffice

    wrong_page = _allocine_week_html(
        "mercredi 14 janvier 2026",
        "Wrong Week Movie",
    )

    class _FakeHttpClient:
        def get(self, url: str):
            if "jpbox-office.com" in url:
                raise AssertionError("official FR update must not call JPBoxOffice")
            if "sem-2026-05-06" in url:
                return _http_response(url, wrong_page)
            raise AssertionError(f"Unexpected URL: {url}")

        def close(self):
            pass

    original_service = core_boxoffice.BoxOfficeService

    class _DirectFrBoxOfficeService(original_service):
        def __init__(self, *args, **kwargs):
            kwargs["http_client"] = _FakeHttpClient()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(core_boxoffice, "BoxOfficeService", _DirectFrBoxOfficeService)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/scheduler/update-week?market=fr",
        json={"year": 2026, "week": 19},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "upstream_failed"
    assert "AlloCiné explicit week mismatch" in data["detail"]
    assert not (tmp_path / "weekly_pages" / "fr" / "2026W19.json").exists()
