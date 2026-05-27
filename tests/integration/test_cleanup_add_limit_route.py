"""Integration tests for add-limit cleanup API routes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.models import MovieStatus
from src.core.radarr import RadarrMovie
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
                    "limit": 3,
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


class _FakeRadarrService:
    def __init__(self, movies, tags, queue_items=None):
        self._movies = movies
        self._tags = tags
        self.delete_calls = []
        self.remove_queue_calls = []
        self._queue_items = queue_items or []

    def get_all_movies(self, ignore_cache: bool = False):
        return self._movies

    def get_tags(self):
        return self._tags

    def delete_movie(self, movie_id: int, delete_files: bool = False):
        self.delete_calls.append((movie_id, delete_files))
        return SimpleNamespace(status_code=200)

    def get_queue(self):
        return self._queue_items

    def remove_queue_item(self, queue_id: int, remove_from_client: bool = True):
        self.remove_queue_calls.append((queue_id, remove_from_client))
        return SimpleNamespace(status_code=200)

    def search_movie(self, term: str):
        return []

    def get_movie(self, movie_id: int):
        for movie in self._movies:
            if movie.id == movie_id:
                return movie
        raise KeyError(movie_id)


class _StatefulCleanupRadarrService(_FakeRadarrService):
    def __init__(self, movies, tags, queue_items=None):
        super().__init__(movies, tags, queue_items=queue_items)
        self.update_calls = []

    def delete_movie(self, movie_id: int, delete_files: bool = False):
        self.delete_calls.append((movie_id, delete_files))
        self._movies = [movie for movie in self._movies if movie.id != movie_id]
        return SimpleNamespace(status_code=200)

    def update_movie(self, movie):
        self.update_calls.append((movie.id, list(getattr(movie, "tags", []))))
        for idx, existing in enumerate(self._movies):
            if existing.id == movie.id:
                self._movies[idx] = movie
                break
        return movie


def _movie(
    movie_id: int,
    tmdb_id: int,
    title: str,
    *,
    tags: list[int],
    size_bytes: int,
    path: str | None = None,
    has_file: bool | None = None,
    monitored: bool = True,
    quality_profile_id: int | None = None,
):
    movie_has_file = has_file if has_file is not None else bool(size_bytes)
    movie_file = None
    if movie_has_file:
        movie_file = {"size": size_bytes, "path": path}
    return RadarrMovie(
        id=movie_id,
        title=title,
        tmdbId=tmdb_id,
        year=2026,
        status=MovieStatus.RELEASED,
        hasFile=movie_has_file,
        monitored=monitored,
        qualityProfileId=quality_profile_id,
        movieFile=movie_file,
        path=path,
        size_on_disk=size_bytes if movie_has_file else None,
        tags=tags,
        _raw_data={
            "id": movie_id,
            "title": title,
            "tmdbId": tmdb_id,
            "tags": tags,
            "hasFile": movie_has_file,
            "monitored": monitored,
            "qualityProfileId": quality_profile_id,
            "movieFile": movie_file,
            "path": path,
            "sizeOnDisk": size_bytes if movie_has_file else None,
        },
    )


def _canonical_tags():
    return [
        {"id": 1, "label": "boxarr-added"},
        {"id": 2, "label": "boxarr-market-fr"},
        {"id": 3, "label": "boxarr-market-us"},
        {"id": 4, "label": "boxarr-protected"},
        {"id": 5, "label": "boxarr-keep"},
    ]


def test_cleanup_routes_disabled_by_default(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    monkeypatch.setattr("src.core.cleanup.settings.boxarr_features_auto_add_ignore_rereleases", False)
    monkeypatch.setattr("src.core.cleanup.settings.boxarr_features_auto_add_genre_filter_enabled", False)
    monkeypatch.setattr("src.core.cleanup.settings.boxarr_features_auto_add_rating_filter_enabled", False)
    monkeypatch.setattr("src.core.cleanup.settings.boxarr_features_auto_add_language_filter_enabled", False)

    weekly_dir = tmp_path / "weekly_pages" / "fr"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "2026W01.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice_fr",
                "source": "jpboxoffice",
                "units": "admissions",
                "year": 2026,
                "week": 1,
                "movies": [
                    {
                        "rank": 6,
                        "title": "No File Movie",
                        "tmdb_id": 205,
                        "radarr_id": 6,
                    },
                    {
                        "rank": 7,
                        "title": "Delete Me",
                        "tmdb_id": 202,
                        "radarr_id": 3,
                    },
                    {
                        "rank": 6,
                        "title": "Unsafe Delete",
                        "tmdb_id": 203,
                        "radarr_id": 4,
                    },
                    {
                        "rank": 8,
                        "title": "Detach Me",
                        "tmdb_id": 204,
                        "radarr_id": 5,
                    },
                    {
                        "rank": 9,
                        "title": "Unknown Size With File",
                        "tmdb_id": 206,
                        "radarr_id": 6,
                    },
                ],
            },
            indent=2,
        )
    )

    fake_service = _StatefulCleanupRadarrService(
        [
            _movie(
                4,
                203,
                "Unsafe Delete",
                tags=[1, 2],
                size_bytes=0,
                has_file=False,
                path="/movies/Unsafe Delete/Unsafe Delete.mkv",
                quality_profile_id=4,
            ),
            _movie(
                6,
                205,
                "No File Movie",
                tags=[1, 2],
                size_bytes=0,
                has_file=False,
                path="/movies/No File Movie/No File Movie.mkv",
                quality_profile_id=4,
            ),
            _movie(
                3,
                202,
                "Delete Me",
                tags=[1, 2],
                size_bytes=1024 * 1024 * 1024,
                path="/movies/Delete Me/Delete Me.mkv",
                quality_profile_id=4,
            ),
            _movie(
                6,
                206,
                "Unknown Size With File",
                tags=[1, 2],
                size_bytes=0,
                has_file=True,
                path="/movies/Unknown Size With File/Unknown Size With File.mkv",
                quality_profile_id=4,
            ),
            _movie(
                5,
                204,
                "Detach Me",
                tags=[1, 2, 3],
                size_bytes=1024 * 1024 * 1024,
                path="/movies/Detach Me/Detach Me.mkv",
                quality_profile_id=4,
            ),
        ],
        _canonical_tags(),
    )

    monkeypatch.setattr("src.api.routes.cleanup.RadarrService", lambda: fake_service)

    app = create_app()
    client = TestClient(app)

    payload = {
        "market": "fr",
        "target_add_limit": 3,
        "delete_files": True,
        "require_boxarr_tag": True,
        "protect_tag": "boxarr-protected",
    }

    dry_run = client.post("/api/cleanup/add-limit/dry-run", json=payload)
    assert dry_run.status_code == 200
    dry_data = dry_run.json()
    assert dry_data["mode"] == "dry-run"
    assert dry_data["dry_run"] is True
    assert dry_data["considered_total"] == 4
    assert dry_data["candidates"][0]["title"] == "Delete Me"
    assert dry_data["candidates"][0]["safe_to_delete"] is True
    assert dry_data["candidates"][0]["eligible_under_target_limit"] is False
    assert dry_data["candidates"][0]["path"] == "/movies/Delete Me/Delete Me.mkv"
    assert dry_data["candidates"][0]["size_on_disk"] == 1024 * 1024 * 1024
    assert dry_data["candidates"][0]["best_rank"] == 7
    assert dry_data["candidates"][0]["weeks_found"] == [{"market": "fr", "year": 2026, "week": 1}]
    assert dry_data["movies_with_files_to_delete"] == 1
    assert dry_data["movies_without_files_to_remove"] == 1
    assert dry_data["would_detach_market_tag_only"][0]["title"] == "Detach Me"
    assert dry_data["would_detach_market_tag_only"][0]["safe_to_detach"] is True
    candidate_titles = {item["title"] for item in dry_data["candidates"]}
    assert candidate_titles == {"Delete Me", "Unsafe Delete"}
    no_file_candidate = next(item for item in dry_data["candidates"] if item["title"] == "Unsafe Delete")
    assert no_file_candidate["has_file"] is False
    assert no_file_candidate["size_on_disk"] is None
    assert no_file_candidate["estimated_size_bytes"] == 0
    unsafe = next(item for item in dry_data["unsafe"] if item["title"] == "Unknown Size With File")
    assert unsafe["reason"] == "unsafe to delete: file exists but size_on_disk unknown"
    assert unsafe["safe_to_delete"] is False
    assert dry_data["estimated_size_to_delete"] == 1024 * 1024 * 1024
    assert fake_service.delete_calls == []

    execute = client.post("/api/cleanup/add-limit/execute", json=payload)
    assert execute.status_code == 403
    assert fake_service.delete_calls == []
    assert fake_service.update_calls == []


def test_cleanup_routes_execute_with_dangerous_actions_enabled(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("BOXARR_ENABLE_DANGEROUS_ACTIONS", "true")
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "fr"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "2026W01.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "provider_aliases": ["jpboxoffice_fr"],
                "source": "jpboxoffice",
                "units": "admissions",
                "year": 2026,
                "week": 1,
                "movies": [
                    {
                        "rank": 6,
                        "title": "No File Movie",
                        "tmdb_id": 205,
                        "radarr_id": 6,
                    },
                    {
                        "rank": 7,
                        "title": "Delete Me",
                        "tmdb_id": 202,
                        "radarr_id": 3,
                    },
                    {
                        "rank": 8,
                        "title": "Detach Me",
                        "tmdb_id": 204,
                        "radarr_id": 5,
                    },
                    {
                        "rank": 9,
                        "title": "Unknown Size With File",
                        "tmdb_id": 206,
                        "radarr_id": 4,
                    },
                ],
            },
            indent=2,
        )
    )

    fake_service = _StatefulCleanupRadarrService(
        [
            _movie(
                6,
                205,
                "No File Movie",
                tags=[1, 2],
                size_bytes=0,
                has_file=False,
                path="/movies/No File Movie/No File Movie.mkv",
                quality_profile_id=4,
            ),
            _movie(
                3,
                202,
                "Delete Me",
                tags=[1, 2],
                size_bytes=1024 * 1024 * 1024,
                path="/movies/Delete Me/Delete Me.mkv",
                quality_profile_id=4,
            ),
            _movie(
                4,
                206,
                "Unknown Size With File",
                tags=[1, 2],
                size_bytes=0,
                has_file=True,
                path="/movies/Unknown Size With File/Unknown Size With File.mkv",
                quality_profile_id=4,
            ),
            _movie(
                5,
                204,
                "Detach Me",
                tags=[1, 2, 3],
                size_bytes=1024 * 1024 * 1024,
                path="/movies/Detach Me/Detach Me.mkv",
                quality_profile_id=4,
            ),
        ],
        _canonical_tags(),
        queue_items=[{"id": 91, "movieId": 6, "title": "No File Movie"}],
    )

    monkeypatch.setattr("src.api.routes.cleanup.RadarrService", lambda: fake_service)

    app = create_app()
    client = TestClient(app)

    payload = {
        "market": "fr",
        "target_add_limit": 3,
        "delete_files": True,
        "require_boxarr_tag": True,
        "protect_tag": "boxarr-protected",
    }

    dry_run = client.post("/api/cleanup/add-limit/dry-run", json=payload)
    assert dry_run.status_code == 200
    dry_data = dry_run.json()
    assert [item["title"] for item in dry_data["candidates"]] == ["Delete Me", "No File Movie"]
    assert [item["title"] for item in dry_data["would_detach_market_tag_only"]] == ["Detach Me"]
    assert dry_data["movies_without_files_to_remove"] == 1
    assert dry_data["movies_with_files_to_delete"] == 1
    assert dry_data["would_remove_downloads_count"] == 1
    queued = next(item for item in dry_data["candidates"] if item["title"] == "No File Movie")
    assert queued["has_file"] is False
    assert queued["size_on_disk"] is None
    assert queued["in_download_queue"] is True
    assert queued["would_remove_download"] is True
    assert queued["would_delete_files"] is False
    assert queued["estimated_size_bytes"] == 0
    assert any(item["title"] == "Unknown Size With File" for item in dry_data["unsafe"])
    assert next(item for item in dry_data["unsafe"] if item["title"] == "Unknown Size With File")["reason"] == "unsafe to delete: file exists but size_on_disk unknown"

    execute = client.post("/api/cleanup/add-limit/execute", json=payload)
    assert execute.status_code == 200
    exec_data = execute.json()
    assert exec_data["mode"] == "execute"
    assert exec_data["dry_run"] is False
    assert [item["title"] for item in exec_data["deleted"]] == ["Delete Me", "No File Movie"]
    assert fake_service.remove_queue_calls == [(91, True)]
    assert fake_service.delete_calls == [(3, True), (6, True)]
    assert fake_service.update_calls == [(5, [1, 3])]
    assert exec_data["would_remove_downloads_count"] == 1
    assert exec_data["estimated_size_deleted"] == 1024 * 1024 * 1024
    assert exec_data["actual_size_deleted"] == 1024 * 1024 * 1024

    second = client.post("/api/cleanup/add-limit/execute", json=payload)
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["deleted"] == []
    assert second_data["detached"] == []
    assert fake_service.delete_calls == [(3, True), (6, True)]
    assert fake_service.remove_queue_calls == [(91, True)]
    assert fake_service.update_calls == [(5, [1, 3])]


def test_cleanup_routes_execute_remove_without_files_only(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("BOXARR_ENABLE_DANGEROUS_ACTIONS", "true")
    Settings.reload_from_file(config_path)

    weekly_dir = tmp_path / "weekly_pages" / "fr"
    weekly_dir.mkdir(parents=True)
    (weekly_dir / "2026W01.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "provider_aliases": ["jpboxoffice_fr"],
                "source": "jpboxoffice",
                "units": "admissions",
                "year": 2026,
                "week": 1,
                "movies": [
                    {
                        "rank": 6,
                        "title": "No File Movie",
                        "tmdb_id": 205,
                        "radarr_id": 6,
                    },
                    {
                        "rank": 7,
                        "title": "Delete Me",
                        "tmdb_id": 202,
                        "radarr_id": 3,
                    },
                ],
            },
            indent=2,
        )
    )

    fake_service = _StatefulCleanupRadarrService(
        [
            _movie(
                6,
                205,
                "No File Movie",
                tags=[1, 2],
                size_bytes=0,
                has_file=False,
                path="/movies/No File Movie/No File Movie.mkv",
                quality_profile_id=4,
            ),
            _movie(
                3,
                202,
                "Delete Me",
                tags=[1, 2],
                size_bytes=1024 * 1024 * 1024,
                path="/movies/Delete Me/Delete Me.mkv",
                quality_profile_id=4,
            ),
        ],
        _canonical_tags(),
        queue_items=[{"id": 91, "movieId": 6, "title": "No File Movie"}],
    )

    monkeypatch.setattr("src.api.routes.cleanup.RadarrService", lambda: fake_service)

    app = create_app()
    client = TestClient(app)

    payload = {
        "market": "fr",
        "target_add_limit": 3,
        "delete_files": True,
        "remove_without_files_only": True,
        "require_boxarr_tag": True,
        "protect_tag": "boxarr-protected",
    }

    dry_run = client.post("/api/cleanup/add-limit/dry-run", json=payload)
    assert dry_run.status_code == 200
    dry_data = dry_run.json()
    assert [item["title"] for item in dry_data["candidates"]] == ["No File Movie"]
    assert [item["title"] for item in dry_data["skipped"]] == ["Delete Me"]
    assert dry_data["would_remove_downloads_count"] == 1
    assert dry_data["remove_without_files_only"] is True

    execute = client.post("/api/cleanup/add-limit/execute", json=payload)
    assert execute.status_code == 200
    exec_data = execute.json()
    assert [item["title"] for item in exec_data["deleted"]] == ["No File Movie"]
    assert exec_data["would_remove_downloads_count"] == 1
    assert exec_data["remove_without_files_only"] is True
    assert fake_service.remove_queue_calls == [(91, True)]
    assert fake_service.delete_calls == [(6, True)]
    assert all(call[0] != 3 for call in fake_service.delete_calls)
