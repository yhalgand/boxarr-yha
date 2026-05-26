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
    def __init__(self, movies, tags):
        self._movies = movies
        self._tags = tags
        self.delete_calls = []

    def get_all_movies(self, ignore_cache: bool = False):
        return self._movies

    def get_tags(self):
        return self._tags

    def delete_movie(self, movie_id: int, delete_files: bool = False):
        self.delete_calls.append((movie_id, delete_files))
        return SimpleNamespace(status_code=200)

    def search_movie(self, term: str):
        return []

    def get_movie(self, movie_id: int):
        for movie in self._movies:
            if movie.id == movie_id:
                return movie
        raise KeyError(movie_id)


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


def test_cleanup_routes_dry_run_then_execute(tmp_path, monkeypatch):
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
                        "rank": 7,
                        "title": "Delete Me",
                        "tmdb_id": 202,
                        "radarr_id": 3,
                    },
                    {
                        "rank": 8,
                        "title": "Unsafe Delete",
                        "tmdb_id": 203,
                        "radarr_id": 4,
                    }
                ],
            },
            indent=2,
        )
    )

    fake_service = _FakeRadarrService(
        [
            _movie(
                3,
                202,
                "Delete Me",
                tags=[1],
                size_bytes=1024 * 1024 * 1024,
                path="/movies/Delete Me/Delete Me.mkv",
                quality_profile_id=4,
            ),
            _movie(
                4,
                203,
                "Unsafe Delete",
                tags=[1],
                size_bytes=0,
                has_file=False,
                path=None,
                quality_profile_id=4,
            ),
        ],
        [{"id": 1, "label": "boxarr"}],
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
    assert dry_data["considered_total"] == 2
    assert dry_data["candidates"][0]["title"] == "Delete Me"
    assert dry_data["candidates"][0]["safe_to_delete"] is True
    assert dry_data["candidates"][0]["eligible_under_target_limit"] is False
    assert dry_data["candidates"][0]["path"] == "/movies/Delete Me/Delete Me.mkv"
    assert dry_data["candidates"][0]["size_on_disk"] == 1024 * 1024 * 1024
    assert dry_data["candidates"][0]["best_rank"] == 7
    assert dry_data["candidates"][0]["weeks_found"] == [{"market": "fr", "year": 2026, "week": 1}]
    assert len(dry_data["candidates"]) == 1
    skipped = {item["title"]: item for item in dry_data["skipped"]}
    assert skipped["Unsafe Delete"]["reason"] == "unsafe to delete: size_on_disk unknown"
    assert skipped["Unsafe Delete"]["safe_to_delete"] is False
    assert dry_data["estimated_size_to_delete"] == 1024 * 1024 * 1024
    assert fake_service.delete_calls == []

    execute = client.post("/api/cleanup/add-limit/execute", json=payload)
    assert execute.status_code == 200
    exec_data = execute.json()
    assert exec_data["mode"] == "execute"
    assert exec_data["dry_run"] is False
    assert exec_data["deleted"][0]["title"] == "Delete Me"
    assert all(item["title"] != "Unsafe Delete" for item in exec_data["deleted"])
    assert fake_service.delete_calls == [(3, True)]
    assert exec_data["estimated_size_deleted"] == 1024 * 1024 * 1024
    assert exec_data["actual_size_deleted"] == 1024 * 1024 * 1024
