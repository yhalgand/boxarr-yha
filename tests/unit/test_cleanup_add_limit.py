"""Unit tests for add-limit cleanup."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from src.core.cleanup import AddLimitCleanupService
from src.core.models import MovieStatus
from src.core.radarr import RadarrMovie


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


def _seed_settings(monkeypatch):
    monkeypatch.setattr(
        "src.core.cleanup.settings.boxarr_features_auto_add_ignore_rereleases", False
    )
    monkeypatch.setattr(
        "src.core.cleanup.settings.boxarr_features_auto_add_genre_filter_enabled",
        False,
    )
    monkeypatch.setattr(
        "src.core.cleanup.settings.boxarr_features_auto_add_rating_filter_enabled",
        False,
    )
    monkeypatch.setattr(
        "src.core.cleanup.settings.boxarr_features_auto_add_language_filter_enabled",
        False,
    )


def _movie(
    movie_id: int,
    tmdb_id: int | None,
    title: str,
    *,
    tags: list[int],
    size_bytes: int = 0,
    path: str | None = None,
    has_file: bool | None = None,
    monitored: bool = True,
    quality_profile_id: int | None = None,
):
    movie_has_file = has_file if has_file is not None else bool(size_bytes)
    movie_file = None
    if movie_has_file:
        movie_file = {
            "size": size_bytes,
            "path": path,
        }
    raw_data = {
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
    }
    return RadarrMovie(
        id=movie_id,
        title=title,
        tmdbId=tmdb_id or 0,
        year=2026,
        status=MovieStatus.RELEASED,
        hasFile=movie_has_file,
        monitored=monitored,
        qualityProfileId=quality_profile_id,
        movieFile=movie_file,
        path=path,
        size_on_disk=size_bytes if movie_has_file else None,
        tags=tags,
        _raw_data=raw_data,
    )


def _write_week(path: Path, market: str, year: int, week: int, movies: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": market,
                "provider": "mojo_us" if market == "us" else "jpboxoffice_fr",
                "source": "boxofficemojo" if market == "us" else "jpboxoffice",
                "units": "usd" if market == "us" else "admissions",
                "year": year,
                "week": week,
                "movies": movies,
            },
            indent=2,
        )
    )


def test_cleanup_dry_run_keeps_any_movie_eligible_in_selected_market(tmp_path, monkeypatch):
    _seed_settings(monkeypatch)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))

    boxarr_tag = {"id": 1, "label": "boxarr"}
    keep_tag = {"id": 2, "label": "boxarr-keep"}

    # FR market pages. Movie 201 is rank 7 in week 1 but rank 2 in week 2, so it stays.
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W01.json",
        "fr",
        2026,
        1,
        [
            {
                "rank": 1,
                "title": "Top Rank",
                "tmdb_id": 204,
                "radarr_id": 5,
                "weekend_gross": 12,
                "total_gross": 12,
            },
            {
                "rank": 3,
                "title": "Boundary Rank",
                "tmdb_id": 205,
                "radarr_id": 6,
                "weekend_gross": 11,
                "total_gross": 11,
            },
            {
                "rank": 7,
                "title": "Safe Delete",
                "tmdb_id": 202,
                "radarr_id": 3,
                "weekend_gross": 10,
                "total_gross": 10,
            },
            {
                "rank": 8,
                "title": "Unsafe Delete",
                "tmdb_id": 203,
                "radarr_id": 4,
                "weekend_gross": 9,
                "total_gross": 9,
            },
            {
                "rank": 7,
                "title": "FR Keep",
                "tmdb_id": 201,
                "radarr_id": 2,
                "weekend_gross": 9,
                "total_gross": 9,
            },
        ],
    )
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W02.json",
        "fr",
        2026,
        2,
        [
            {
                "rank": 1,
                "title": "Top Rank",
                "tmdb_id": 204,
                "radarr_id": 5,
                "weekend_gross": 13,
                "total_gross": 25,
            },
            {
                "rank": 3,
                "title": "Boundary Rank",
                "tmdb_id": 205,
                "radarr_id": 6,
                "weekend_gross": 14,
                "total_gross": 25,
            },
            {
                "rank": 2,
                "title": "FR Keep",
                "tmdb_id": 201,
                "radarr_id": 2,
                "weekend_gross": 11,
                "total_gross": 20,
            },
            {
                "rank": 10,
                "title": "Safe Delete",
                "tmdb_id": 202,
                "radarr_id": 3,
                "weekend_gross": 8,
                "total_gross": 18,
            },
        ],
    )

    # Legacy flat US page should not affect market=fr cleanup.
    _write_week(
        tmp_path / "weekly_pages" / "2026W01.json",
        "us",
        2026,
        1,
        [
            {
                "rank": 1,
                "title": "US Keep",
                "tmdb_id": 301,
                "radarr_id": 4,
                "weekend_gross": 100,
                "total_gross": 100,
            }
        ],
    )

    movies = [
        _movie(
            2,
            201,
            "FR Keep",
            tags=[1],
            size_bytes=20 * 1024 * 1024 * 1024,
            path="/movies/FR Keep/FR Keep.mkv",
            quality_profile_id=5,
        ),
        _movie(
            3,
            202,
            "Safe Delete",
            tags=[1],
            size_bytes=30 * 1024 * 1024 * 1024,
            path="/movies/Safe Delete/Safe Delete.mkv",
            quality_profile_id=4,
        ),
        _movie(
            4,
            203,
            "Unsafe Delete",
            tags=[1],
            size_bytes=0,
            path=None,
            has_file=False,
            quality_profile_id=4,
        ),
        _movie(
            5,
            204,
            "Top Rank",
            tags=[1],
            size_bytes=15 * 1024 * 1024 * 1024,
            path="/movies/Top Rank/Top Rank.mkv",
            quality_profile_id=4,
        ),
        _movie(
            6,
            205,
            "Boundary Rank",
            tags=[1],
            size_bytes=16 * 1024 * 1024 * 1024,
            path="/movies/Boundary Rank/Boundary Rank.mkv",
            quality_profile_id=4,
        ),
        _movie(8, 301, "US Keep", tags=[1], size_bytes=40 * 1024 * 1024 * 1024),
        _movie(9, 401, "Protected", tags=[1, 2], size_bytes=5 * 1024 * 1024 * 1024),
        _movie(10, None, "Ambiguous", tags=[1], size_bytes=1 * 1024 * 1024 * 1024),
        _movie(11, 999, "Manual", tags=[], size_bytes=2 * 1024 * 1024 * 1024),
    ]
    fake_service = _FakeRadarrService(movies, [boxarr_tag, keep_tag])

    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-keep",
        execute=False,
    )

    assert report["market"] == "fr"
    assert report["dry_run"] is True
    assert report["considered_total"] == len(movies)

    candidate_titles = {item["title"] for item in report["candidates"]}
    assert candidate_titles == {"Safe Delete"}

    safe_candidate = next(item for item in report["candidates"] if item["title"] == "Safe Delete")
    assert safe_candidate["size_on_disk"] == 30 * 1024 * 1024 * 1024
    assert safe_candidate["path"] == "/movies/Safe Delete/Safe Delete.mkv"
    assert safe_candidate["has_file"] is True
    assert safe_candidate["monitored"] is True
    assert safe_candidate["quality_profile_id"] == 4
    assert safe_candidate["tags"] == [1]
    assert safe_candidate["tag_names"] == ["boxarr"]
    assert safe_candidate["best_rank"] == 7
    assert safe_candidate["weeks_found"] == [
        {"market": "fr", "year": 2026, "week": 1},
        {"market": "fr", "year": 2026, "week": 2},
    ]
    assert safe_candidate["ranks_by_week"] == [
        {"market": "fr", "year": 2026, "week": 1, "rank": 7},
        {"market": "fr", "year": 2026, "week": 2, "rank": 10},
    ]
    assert safe_candidate["eligible_under_target_limit"] is False
    assert safe_candidate["safe_to_delete"] is True
    assert safe_candidate["unsafe_to_delete"] is False

    skipped = {item["title"]: item["reason"] for item in report["skipped"]}
    assert skipped["Top Rank"] == "present in eligible range by best_rank"
    assert skipped["Boundary Rank"] == "present in eligible range by best_rank"
    assert skipped["FR Keep"] == "present in eligible range by best_rank"
    assert skipped["Unsafe Delete"] == "unsafe to delete: size_on_disk unknown"
    assert skipped["US Keep"] == "no reliable Boxarr association"
    assert skipped["Protected"] == "protected by tag 'boxarr-keep'"
    assert skipped["Ambiguous"] == "no reliable Boxarr association"
    assert skipped["Manual"] == "missing required boxarr tag"

    assert fake_service.delete_calls == []
    assert report["estimated_size_to_delete"] == 30 * 1024 * 1024 * 1024


def test_cleanup_execute_calls_delete_files_true(tmp_path, monkeypatch):
    _seed_settings(monkeypatch)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))

    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W01.json",
        "fr",
        2026,
        1,
        [
            {
                "rank": 1,
                "title": "Delete Me",
                "tmdb_id": 202,
                "radarr_id": 3,
                "weekend_gross": 10,
                "total_gross": 10,
            },
            {
                "rank": 8,
                "title": "Unsafe Delete",
                "tmdb_id": 203,
                "radarr_id": 4,
                "weekend_gross": 4,
                "total_gross": 4,
            }
        ],
    )

    movies = [
        _movie(3, 202, "Delete Me", tags=[1], size_bytes=3 * 1024 * 1024 * 1024),
        _movie(4, 203, "Unsafe Delete", tags=[1], size_bytes=0, has_file=False),
    ]
    fake_service = _FakeRadarrService(movies, [{"id": 1, "label": "boxarr"}])

    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-keep",
        execute=True,
    )

    assert fake_service.delete_calls == [(3, True)]
    assert [item["title"] for item in report["deleted"]] == ["Delete Me"]
    assert all(item["title"] != "Unsafe Delete" for item in report["deleted"])
    assert report["actual_size_deleted"] == 3 * 1024 * 1024 * 1024
    assert report["estimated_size_deleted"] == 3 * 1024 * 1024 * 1024


def test_cleanup_market_us_reads_legacy_flat_file(tmp_path, monkeypatch):
    _seed_settings(monkeypatch)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))

    _write_week(
        tmp_path / "weekly_pages" / "2026W01.json",
        "us",
        2026,
        1,
        [
            {
                "rank": 1,
                "title": "Legacy US Keep",
                "tmdb_id": 501,
                "radarr_id": 8,
                "weekend_gross": 25,
                "total_gross": 25,
            }
        ],
    )

    movies = [
        _movie(8, 501, "Legacy US Keep", tags=[1], size_bytes=1024),
    ]
    fake_service = _FakeRadarrService(movies, [{"id": 1, "label": "boxarr"}])

    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="us",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-keep",
        execute=False,
    )

    assert report["market"] == "us"
    assert report["eligible_count"] == 1
    assert report["candidates"] == []
    assert report["skipped"][0]["reason"] == "present in eligible set"
