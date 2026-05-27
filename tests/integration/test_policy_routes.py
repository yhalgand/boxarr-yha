"""Integration tests for market policy routes."""

from pathlib import Path
import json
import threading
import time

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.radarr import RadarrMovie
from src.core.matcher import MovieMatcher
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
    path.write_text(yaml.safe_dump(cfg))
    return path


def _write_weekly_page(
    weekly_dir: Path,
    year: int,
    week: int,
    title: str,
    *,
    market: str = "us",
    provider: str = "mojo",
    source: str = "boxofficemojo",
    units: str = "usd",
) -> None:
    weekly_dir.mkdir(parents=True, exist_ok=True)
    (weekly_dir / f"{year}W{week:02d}.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": market,
                "provider": provider,
                "source": source,
                "units": units,
                "year": year,
                "week": week,
                "movies": [
                    {
                        "rank": 1,
                        "title": title,
                        "tmdb_id": 1000 + week,
                        "weeks_released": 1,
                        "weeks_in_release": 1,
                    }
                ],
            },
            indent=2,
        )
    )


class _FakeRadarrService:
    def __init__(self, *_, **__):
        pass

    def get_tags(self):
        return []

    def get_all_movies(self, ignore_cache: bool = False):
        return []

    def search_movie(self, term: str):
        return []

    def ensure_tag(self, label: str):
        return 1

    def update_movie(self, movie):
        return movie


class _FakeMigrationRadarrService:
    def __init__(self, tags):
        self._tags = tags
        self.updated_movies = []
        self._tag_ids_by_label = {}
        self._next_tag_id = 100
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            tag_id = tag.get("id")
            label = tag.get("label") or tag.get("name") or tag.get("title") or tag.get("tag")
            if isinstance(tag_id, int) and isinstance(label, str):
                self._tag_ids_by_label[label.lower()] = tag_id

    def get_tags(self):
        return self._tags

    def ensure_tag(self, label: str):
        normalized = label.lower()
        if normalized not in self._tag_ids_by_label:
            self._tag_ids_by_label[normalized] = self._next_tag_id
            self._next_tag_id += 1
        return self._tag_ids_by_label[normalized]

    def update_movie(self, movie):
        self.updated_movies.append(movie)
        return movie


class _FakeAddMovieQualityProfile:
    def __init__(self):
        self.id = 1
        self.name = "HD-1080p"


class _FakeAddedMovie:
    def __init__(self, tmdb_id, title):
        self.id = tmdb_id
        self.title = title


class _FakeAddMovieRadarrService:
    def __init__(self, movies=None):
        self._movies = movies or []
        self._tags = [{"id": 1, "label": "boxarr-added"}]
        self.add_calls = []

    def get_tags(self):
        return self._tags

    def get_all_movies(self, ignore_cache: bool = False):
        return self._movies

    def get_quality_profiles(self):
        return [_FakeAddMovieQualityProfile()]

    def search_movie(self, term: str):
        return [{"tmdbId": 9001, "title": "Backfill Movie", "year": 2026, "genres": []}]

    def ensure_tag(self, label: str):
        return 1

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id=None,
        root_folder: str | None = None,
        monitored: bool = True,
        search_for_movie: bool = True,
        additional_tag_labels=None,
    ):
        self.add_calls.append(
            {
                "tmdb_id": tmdb_id,
                "quality_profile_id": quality_profile_id,
                "root_folder": root_folder,
                "monitored": monitored,
                "search_for_movie": search_for_movie,
                "additional_tag_labels": list(additional_tag_labels or []),
            }
        )
        return _FakeAddedMovie(tmdb_id, "Backfill Movie")


def test_policy_get_put_apply_and_backfill(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Policy Movie")

    import src.api.routes.policy as policy_routes

    monkeypatch.setattr(policy_routes, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )

    app = create_app()
    client = TestClient(app)

    get_resp = client.get("/api/policy/us")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["market"] == "us"
    assert body["effective"]["box_office_fetch_limit"] == 10
    assert body["tag_policy"]["added_tag"] == "boxarr-added"
    assert body["tag_policy"]["market_tag"] == "boxarr-market-us"
    assert body["tag_policy"]["existing_tag"] == "boxarr-existing-us"
    assert body["tag_policy"]["protected_tag"] == "boxarr-protected"

    put_resp = client.put(
        "/api/policy/us",
        json={
            "box_office_fetch_limit": 12,
            "maximum_movies_to_add": 3,
            "auto_add_enabled": True,
            "cleanup_protect_tag": "boxarr-protected",
        },
    )
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["effective"]["box_office_fetch_limit"] == 12
    assert updated["effective"]["maximum_movies_to_add"] == 3
    assert updated["effective"]["auto_add_enabled"] is True
    assert updated["effective"]["cleanup_protect_tag"] == "boxarr-protected"

    impact_resp = client.post(
        "/api/policy/us/impact",
        json={
            "box_office_fetch_limit": 14,
            "maximum_movies_to_add": 5,
            "auto_add_enabled": True,
        },
    )
    assert impact_resp.status_code == 200
    impact = impact_resp.json()
    assert any(change["field"] == "maximum_movies_to_add" for change in impact["changes"])

    apply_resp = client.post(
        "/api/policy/us/apply",
        json={
            "box_office_fetch_limit": 12,
            "maximum_movies_to_add": 3,
        },
    )
    assert apply_resp.status_code == 200
    snapshot = json.loads((weekly_dir / "2026W12.json").read_text())
    assert snapshot["policy_snapshot"]["market"] == "us"
    assert snapshot["policy_snapshot"]["add_limit_used"] == 3
    assert snapshot["policy_snapshot"]["tag_policy_used"]["added_tag"] == "boxarr-added"
    assert snapshot["policy_snapshot"]["tag_policy_used"]["market_tag"] == "boxarr-market-us"

    backfill_resp = client.post(
        "/api/policy/us/backfill-add/dry-run",
        json={
            "maximum_movies_to_add": 3,
            "year_from": 2026,
            "week_from": 12,
            "year_to": 2026,
            "week_to": 12,
            "all_stored": False,
            "max_weeks": 1,
        },
    )
    assert backfill_resp.status_code == 200
    backfill = backfill_resp.json()
    assert backfill["market"] == "us"
    assert backfill["weeks"][0]["needs_refetch"] is True
    assert backfill["would_add_count_total"] == 1
    assert backfill["skipped_count_total"] == 0

    no_scope_resp = client.post(
        "/api/policy/us/backfill-add/dry-run",
        json={"maximum_movies_to_add": 3},
    )
    assert no_scope_resp.status_code == 400
    assert "Scope required for backfill dry-run" in no_scope_resp.json()["detail"]

    invalid_resp = client.get("/api/policy/de")
    assert invalid_resp.status_code == 400




def test_policy_apply_supports_default_markets_without_local_markets_section(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    _write_weekly_page(tmp_path / "weekly_pages" / "us", 2026, 21, "US Apply Movie", market="us")
    _write_weekly_page(tmp_path / "weekly_pages" / "fr", 2026, 21, "FR Apply Movie", market="fr", provider="jpboxoffice", source="jpboxoffice", units="admissions")
    _write_weekly_page(tmp_path / "weekly_pages" / "us", 2026, 22, "US Apply Movie 2", market="us")

    app = create_app()
    client = TestClient(app)

    us_resp = client.post(
        "/api/policy/us/apply",
        json={
            "year_from": 2026,
            "week_from": 21,
            "year_to": 2026,
            "week_to": 21,
            "maximum_movies_to_add": 3,
        },
    )
    assert us_resp.status_code == 200
    us_snapshot_21 = json.loads((tmp_path / "weekly_pages" / "us" / "2026W21.json").read_text())
    us_snapshot_22 = json.loads((tmp_path / "weekly_pages" / "us" / "2026W22.json").read_text())
    assert us_snapshot_21["policy_snapshot"]["market"] == "us"
    assert us_snapshot_21["policy_snapshot"]["add_limit_used"] == 3
    assert us_snapshot_21["policy_snapshot"]["fetch_limit_used"] == 10
    assert us_snapshot_21["policy_snapshot"]["cleanup_protect_tag_used"] == "boxarr-protected"
    assert us_snapshot_21["policy_snapshot"]["tag_policy_used"]["added_tag"] == "boxarr-added"
    assert "policy_snapshot" not in us_snapshot_22

    fr_resp = client.post(
        "/api/policy/fr/apply",
        json={
            "year_from": 2026,
            "week_from": 21,
            "year_to": 2026,
            "week_to": 21,
            "maximum_movies_to_add": 5,
        },
    )
    assert fr_resp.status_code == 200
    fr_snapshot = json.loads((tmp_path / "weekly_pages" / "fr" / "2026W21.json").read_text())
    assert fr_snapshot["policy_snapshot"]["market"] == "fr"
    assert fr_snapshot["policy_snapshot"]["add_limit_used"] == 5
    assert fr_snapshot["policy_snapshot"]["fetch_limit_used"] == 10
    assert fr_snapshot["policy_snapshot"]["cleanup_protect_tag_used"] == "boxarr-protected"
    assert fr_snapshot["policy_snapshot"]["tag_policy_used"]["market_tag"] == "boxarr-market-fr"


def test_policy_apply_rejects_unknown_or_disabled_markets(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    config = yaml.safe_load(config_path.read_text())
    config["markets"] = {
        "de": {
            "label": "Germany Box Office",
            "provider": "jpboxoffice",
            "provider_config": {"country": "de"},
            "enabled": False,
        }
    }
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    app = create_app()
    client = TestClient(app)

    bogus_resp = client.post(
        "/api/policy/bogus/apply",
        json={"year_from": 2026, "week_from": 21, "year_to": 2026, "week_to": 21},
    )
    assert bogus_resp.status_code == 400

    disabled_resp = client.post(
        "/api/policy/de/apply",
        json={"year_from": 2026, "week_from": 21, "year_to": 2026, "week_to": 21},
    )
    assert disabled_resp.status_code == 400
    assert "disabled" in disabled_resp.json()["detail"].lower()


def test_policy_tag_migration_detects_legacy_tags_and_reports_counts(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Legacy Movie")

    import src.api.routes.policy as policy_routes

    movies = [
        RadarrMovie(
            id=1,
            title="Legacy Movie",
            tmdbId=1012,
            year=2026,
            tags=[1],
            _raw_data={"tags": [1]},
        ),
        RadarrMovie(
            id=2,
            title="Legacy Keep",
            tmdbId=2012,
            year=2026,
            tags=[2],
            _raw_data={"tags": [2]},
        ),
        RadarrMovie(
            id=3,
            title="Legacy US",
            tmdbId=3012,
            year=2026,
            tags=[4],
            _raw_data={"tags": [4]},
        ),
        RadarrMovie(
            id=4,
            title="Legacy FR",
            tmdbId=4012,
            year=2026,
            tags=[5],
            _raw_data={"tags": [5]},
        ),
        RadarrMovie(
            id=5,
            title="Plain Movie",
            tmdbId=5012,
            year=2026,
            tags=[99],
            _raw_data={"tags": [99]},
        ),
    ]

    monkeypatch.setattr(
        policy_routes,
        "RadarrService",
        lambda: _FakeMigrationRadarrService(
            [
                {"id": 1, "name": "boxarr"},
                {"id": 2, "label": "boxarr-keep"},
                {"id": 3, "title": "boxarr-protected"},
                {"id": 4, "label": "boxarr-us"},
                {"id": 5, "label": "boxarr-fr"},
            ]
        ),
    )
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: movies,
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/policy/tags/migrate/dry-run",
        json={"market": "us", "year_from": 2026, "week_from": 12, "year_to": 2026, "week_to": 12},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["total_movies_scanned"] == 5
    assert body["total_tagged_legacy_boxarr"] == 1
    assert body["total_tagged_boxarr_keep"] == 1
    assert body["total_tagged_boxarr_us"] == 1
    assert body["total_tagged_boxarr_fr"] == 1
    assert any(tag["label"] == "boxarr" for tag in body["resolved_tags"])
    assert body["message"] is None
    assert len(body["candidates"]) == 4
    assert any(item["title"] == "Legacy Movie" for item in body["candidates"])
    assert any(item["title"] == "Plain Movie" for item in body["skipped"])


def test_policy_execute_endpoints_are_disabled_by_default(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Backfill Movie")

    import src.api.routes.policy as policy_routes

    monkeypatch.setattr(policy_routes, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )

    app = create_app()
    client = TestClient(app)

    backfill_resp = client.post(
        "/api/policy/us/backfill-add/execute",
        json={
            "maximum_movies_to_add": 1,
            "year_from": 2026,
            "week_from": 12,
            "year_to": 2026,
            "week_to": 12,
            "all_stored": False,
            "max_weeks": 1,
        },
    )
    assert backfill_resp.status_code == 403

    cleanup_resp = client.post(
        "/api/policy/us/cleanup/execute",
        json={
            "maximum_movies_to_add": 3,
            "cleanup_protect_tag": "boxarr-protected",
        },
    )
    assert cleanup_resp.status_code == 403

    migrate_resp = client.post(
        "/api/policy/tags/migrate/execute",
        json={"market": "us", "year_from": 2026, "week_from": 12, "year_to": 2026, "week_to": 12},
    )
    assert migrate_resp.status_code == 403


def test_policy_execute_endpoints_work_with_dangerous_actions_enabled(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("BOXARR_ENABLE_DANGEROUS_ACTIONS", "true")
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Backfill Movie")

    import src.api.routes.policy as policy_routes

    add_service = _FakeAddMovieRadarrService()
    monkeypatch.setattr(policy_routes, "RadarrService", lambda: add_service)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )
    refresh_calls = []
    monkeypatch.setattr(
        policy_routes,
        "refresh_stored_status_for_market",
        lambda market: refresh_calls.append(market) or {"weeks_scanned": 0, "weeks_updated": 0, "movies_refreshed": 0, "movies_linked": 0},
    )

    app = create_app()
    client = TestClient(app)

    backfill_resp = client.post(
        "/api/policy/us/backfill-add/execute",
        json={
            "maximum_movies_to_add": 1,
            "year_from": 2026,
            "week_from": 12,
            "year_to": 2026,
            "week_to": 12,
            "all_stored": False,
            "max_weeks": 1,
        },
    )
    assert backfill_resp.status_code == 200
    backfill = backfill_resp.json()
    assert backfill["added_count"] == 1
    assert backfill["would_add_count_total"] == 1
    assert backfill["skipped_count_total"] == 0
    assert add_service.add_calls[0]["additional_tag_labels"] == [
        "boxarr-added",
        "boxarr-market-us",
    ]
    assert refresh_calls == ["us"]

    # Reuse the same week file so the legacy migration can match against stored pages.
    _write_weekly_page(weekly_dir, 2026, 12, "Legacy Movie")

    migration_movies = [
        RadarrMovie(
            id=1,
            title="Legacy Movie",
            tmdbId=1012,
            year=2026,
            tags=[1],
            _raw_data={"tags": [1]},
        )
    ]
    migration_service = _FakeMigrationRadarrService(
        [
            {"id": 1, "label": "boxarr"},
            {"id": 2, "label": "boxarr-keep"},
            {"id": 3, "label": "boxarr-us"},
        ]
    )
    monkeypatch.setattr(policy_routes, "RadarrService", lambda: migration_service)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: migration_movies,
    )

    migrate_resp = client.post(
        "/api/policy/tags/migrate/execute",
        json={"market": "us", "year_from": 2026, "week_from": 12, "year_to": 2026, "week_to": 12},
    )
    assert migrate_resp.status_code == 200
    migrate = migrate_resp.json()
    assert migrate["migrated"] == 1
    assert migrate["already_migrated_count"] == 0
    assert migration_service.updated_movies, "expected safe tag migration to update Radarr"
    assert len(migration_service.updated_movies[0].tags) == 3
    assert refresh_calls == ["us", "us"]

    migrate_again_resp = client.post(
        "/api/policy/tags/migrate/execute",
        json={"market": "us", "year_from": 2026, "week_from": 12, "year_to": 2026, "week_to": 12},
    )
    assert migrate_again_resp.status_code == 200
    migrate_again = migrate_again_resp.json()
    assert migrate_again["migrated"] == 0
    assert migrate_again["already_migrated_count"] == 1
    assert len(migrate_again["already_migrated"]) == 1
    assert refresh_calls == ["us", "us"]

    migrate_dry_run_resp = client.post(
        "/api/policy/tags/migrate/dry-run",
        json={"market": "us", "year_from": 2026, "week_from": 12, "year_to": 2026, "week_to": 12},
    )
    assert migrate_dry_run_resp.status_code == 200
    migrate_dry_run = migrate_dry_run_resp.json()
    assert migrate_dry_run["candidates"] == []
    assert migrate_dry_run["already_migrated_count"] == 1
    assert len(migrate_dry_run["already_migrated"]) == 1


def test_policy_backfill_scope_limits_matcher_build_once(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Policy Movie A")
    _write_weekly_page(weekly_dir, 2026, 13, "Policy Movie B")

    import src.api.routes.policy as policy_routes

    monkeypatch.setattr(policy_routes, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )

    build_calls = {"count": 0}
    original_build = MovieMatcher.build_movie_index

    def _counting_build(self, movies):
        build_calls["count"] += 1
        return original_build(self, movies)

    monkeypatch.setattr(MovieMatcher, "build_movie_index", _counting_build)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/policy/us/backfill-add/dry-run",
        json={
            "maximum_movies_to_add": 3,
            "year_from": 2026,
            "week_from": 12,
            "year_to": 2026,
            "week_to": 13,
            "all_stored": False,
            "max_weeks": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["weeks"]) == 2
    assert build_calls["count"] == 1


def test_policy_backfill_all_stored_requires_explicit_flag_and_is_limited(
    tmp_path, monkeypatch
):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Policy Movie A")
    _write_weekly_page(weekly_dir, 2026, 13, "Policy Movie B")

    import src.api.routes.policy as policy_routes

    monkeypatch.setattr(policy_routes, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )

    build_calls = {"count": 0}
    original_build = MovieMatcher.build_movie_index

    def _counting_build(self, movies):
        build_calls["count"] += 1
        return original_build(self, movies)

    monkeypatch.setattr(MovieMatcher, "build_movie_index", _counting_build)

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/policy/us/backfill-add/dry-run",
        json={
            "maximum_movies_to_add": 3,
            "all_stored": True,
            "max_weeks": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"]["all_stored"] is True
    assert len(body["weeks"]) == 1
    assert build_calls["count"] == 1


def test_policy_backfill_scope_too_large_requires_all_stored(
    tmp_path, monkeypatch
):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    for week in range(1, 14):
        _write_weekly_page(weekly_dir, 2026, week, f"Policy Movie {week}")

    import src.api.routes.policy as policy_routes

    monkeypatch.setattr(policy_routes, "RadarrService", _FakeRadarrService)
    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        lambda *_, **__: [],
    )

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/policy/us/backfill-add/dry-run",
        json={
            "maximum_movies_to_add": 3,
            "year_from": 2026,
            "week_from": 1,
            "year_to": 2026,
            "week_to": 13,
            "all_stored": False,
        },
    )
    assert resp.status_code == 400
    assert "Backfill scope too large" in resp.json()["detail"]


def test_policy_backfill_dry_run_keeps_health_responsive(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "us"
    _write_weekly_page(weekly_dir, 2026, 12, "Policy Movie A")

    import src.api.routes.policy as policy_routes

    monkeypatch.setattr(policy_routes, "RadarrService", _FakeRadarrService)

    def _slow_fetch(*_, **__):
        time.sleep(0.3)
        return []

    monkeypatch.setattr(
        policy_routes,
        "get_all_movies_with_optional_cache_bypass",
        _slow_fetch,
    )

    build_calls = {"count": 0}
    original_build = MovieMatcher.build_movie_index

    def _counting_build(self, movies):
        build_calls["count"] += 1
        return original_build(self, movies)

    monkeypatch.setattr(MovieMatcher, "build_movie_index", _counting_build)

    app = create_app()
    backfill_client = TestClient(app)
    health_client = TestClient(app)

    response_holder = {}

    def _run_backfill():
        response_holder["resp"] = backfill_client.post(
            "/api/policy/us/backfill-add/dry-run",
            json={
                "maximum_movies_to_add": 3,
                "year_from": 2026,
                "week_from": 12,
                "year_to": 2026,
                "week_to": 12,
                "all_stored": False,
                "max_weeks": 1,
            },
        )

    worker = threading.Thread(target=_run_backfill)
    worker.start()
    time.sleep(0.05)

    health_resp = health_client.get("/api/health")
    assert health_resp.status_code == 200

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert response_holder["resp"].status_code == 200
    assert build_calls["count"] == 1
