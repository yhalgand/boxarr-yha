"""Unit tests for add-limit cleanup."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.core.cleanup import AddLimitCleanupService
from src.core.models import MovieStatus
from src.core.radarr import RadarrMovie


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
        movie_file = {"size": size_bytes, "path": path}
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
                "provider": "mojo" if market == "us" else "jpboxoffice",
                "provider_aliases": ["mojo_us"] if market == "us" else ["jpboxoffice_fr"],
                "source": "boxofficemojo" if market == "us" else "jpboxoffice",
                "units": "usd" if market == "us" else "admissions",
                "year": year,
                "week": week,
                "movies": movies,
            },
            indent=2,
        )
    )


def _canonical_tags():
    return [
        {"id": 1, "label": "boxarr-added"},
        {"id": 2, "label": "boxarr-market-fr"},
        {"id": 3, "label": "boxarr-market-us"},
        {"id": 4, "label": "boxarr-protected"},
        {"id": 5, "label": "boxarr-keep"},
        {"id": 6, "label": "boxarr-existing-fr"},
        {"id": 7, "label": "boxarr"},
    ]


def test_cleanup_dry_run_reports_delete_detach_protected_and_legacy(
    tmp_path, monkeypatch
):
    _seed_settings(monkeypatch)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))

    # Two weeks so we can prove best_rank is collected across the stored range.
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W01.json",
        "fr",
        2026,
        1,
        [
            {"rank": 1, "title": "Top Rank", "tmdb_id": 204, "radarr_id": 5},
            {"rank": 3, "title": "Boundary Rank", "tmdb_id": 205, "radarr_id": 6},
            {"rank": 7, "title": "Safe Delete", "tmdb_id": 202, "radarr_id": 3},
            {"rank": 8, "title": "Detach Me", "tmdb_id": 206, "radarr_id": 12},
            {"rank": 8, "title": "Unsafe Delete", "tmdb_id": 203, "radarr_id": 4},
            {
                "rank": 9,
                "title": "Unknown Size With File",
                "tmdb_id": 207,
                "radarr_id": 14,
            },
        ],
    )
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W02.json",
        "fr",
        2026,
        2,
        [
            {"rank": 1, "title": "Top Rank", "tmdb_id": 204, "radarr_id": 5},
            {"rank": 3, "title": "Boundary Rank", "tmdb_id": 205, "radarr_id": 6},
            {"rank": 10, "title": "Safe Delete", "tmdb_id": 202, "radarr_id": 3},
            {"rank": 9, "title": "Detach Me", "tmdb_id": 206, "radarr_id": 12},
            {"rank": 9, "title": "Unsafe Delete", "tmdb_id": 203, "radarr_id": 4},
            {
                "rank": 10,
                "title": "Unknown Size With File",
                "tmdb_id": 207,
                "radarr_id": 14,
            },
        ],
    )
    _write_week(
        tmp_path / "weekly_pages" / "2026W01.json",
        "us",
        2026,
        1,
        [{"rank": 1, "title": "US Legacy", "tmdb_id": 301, "radarr_id": 8}],
    )

    movies = [
        _movie(
            2,
            201,
            "US Keep",
            tags=[1, 3],
            size_bytes=20 * 1024 * 1024 * 1024,
            path="/movies/US Keep/US Keep.mkv",
            quality_profile_id=5,
        ),
        _movie(
            3,
            202,
            "Safe Delete",
            tags=[1, 2],
            size_bytes=30 * 1024 * 1024 * 1024,
            path="/movies/Safe Delete/Safe Delete.mkv",
            quality_profile_id=4,
        ),
        _movie(
            4,
            203,
            "Unsafe Delete",
            tags=[1, 2],
            size_bytes=0,
            path="/movies/Unsafe Delete/Unsafe Delete.mkv",
            has_file=False,
            quality_profile_id=4,
        ),
        _movie(
            14,
            207,
            "Unknown Size With File",
            tags=[1, 2],
            size_bytes=0,
            path="/movies/Unknown Size With File/Unknown Size With File.mkv",
            has_file=True,
            quality_profile_id=4,
        ),
        _movie(
            7,
            402,
            "Legacy Protected",
            tags=[5],
            size_bytes=4 * 1024 * 1024 * 1024,
            path="/movies/Legacy Protected/Legacy Protected.mkv",
            quality_profile_id=4,
        ),
        _movie(
            5,
            204,
            "Top Rank",
            tags=[1, 2],
            size_bytes=15 * 1024 * 1024 * 1024,
            path="/movies/Top Rank/Top Rank.mkv",
            quality_profile_id=4,
        ),
        _movie(
            6,
            205,
            "Boundary Rank",
            tags=[1, 2],
            size_bytes=16 * 1024 * 1024 * 1024,
            path="/movies/Boundary Rank/Boundary Rank.mkv",
            quality_profile_id=4,
        ),
        _movie(
            12,
            206,
            "Detach Me",
            tags=[1, 2, 3],
            size_bytes=10 * 1024 * 1024 * 1024,
            path="/movies/Detach Me/Detach Me.mkv",
            quality_profile_id=4,
        ),
        _movie(
            9,
            401,
            "Protected",
            tags=[1, 4],
            size_bytes=5 * 1024 * 1024 * 1024,
            path="/movies/Protected/Protected.mkv",
        ),
        _movie(
            10,
            None,
            "Legacy Boxarr",
            tags=[7],
            size_bytes=1 * 1024 * 1024 * 1024,
            path="/movies/Legacy Boxarr/Legacy Boxarr.mkv",
        ),
        _movie(
            11,
            999,
            "Manual Existing",
            tags=[6],
            size_bytes=2 * 1024 * 1024 * 1024,
            path="/movies/Manual Existing/Manual Existing.mkv",
        ),
    ]
    fake_service = _FakeRadarrService(movies, _canonical_tags())

    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="fr",
        execute=False,
    )

    assert report["market"] == "fr"
    assert report["dry_run"] is True
    assert report["considered_total"] == len(movies)

    candidate_titles = {item["title"] for item in report["candidates"]}
    assert candidate_titles == {"Safe Delete", "Unsafe Delete"}
    assert report["movies_with_files_to_delete"] == 1
    assert report["movies_without_files_to_remove"] == 1

    safe_candidate = next(item for item in report["candidates"] if item["title"] == "Safe Delete")
    assert safe_candidate["size_on_disk"] == 30 * 1024 * 1024 * 1024
    assert safe_candidate["path"] == "/movies/Safe Delete/Safe Delete.mkv"
    assert safe_candidate["has_file"] is True
    assert safe_candidate["monitored"] is True
    assert safe_candidate["quality_profile_id"] == 4
    assert safe_candidate["tags"] == [1, 2]
    assert safe_candidate["tag_names"] == ["boxarr-added", "boxarr-market-fr"]
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

    detach = next(
        item for item in report["would_detach_market_tag_only"] if item["title"] == "Detach Me"
    )
    assert detach["safe_to_detach"] is True
    assert detach["safe_to_delete"] is False
    assert detach["reason"] == "tagged for multiple markets; detach current market tag only"

    protected_titles = {item["title"] for item in report["protected"]}
    assert {"Protected", "Legacy Protected"} <= protected_titles

    no_file_candidate = next(item for item in report["candidates"] if item["title"] == "Unsafe Delete")
    assert no_file_candidate["has_file"] is False
    assert no_file_candidate["size_on_disk"] is None
    assert no_file_candidate["safe_to_delete"] is True
    assert no_file_candidate["estimated_size_bytes"] == 0

    unsafe = next(item for item in report["unsafe"] if item["title"] == "Unknown Size With File")
    unknown_size_with_file = next(item for item in report["unsafe"] if item["title"] == "Unknown Size With File")
    assert unknown_size_with_file["has_file"] is True
    assert unknown_size_with_file["size_on_disk"] is None
    assert unknown_size_with_file["reason"] == "unsafe to delete: file exists but size_on_disk unknown"
    assert unsafe["reason"] == "unsafe to delete: file exists but size_on_disk unknown"
    assert unsafe["safe_to_delete"] is False

    skipped = {item["title"]: item["reason"] for item in report["skipped"]}
    assert skipped["Top Rank"] == "present in eligible range by best_rank"
    assert skipped["Boundary Rank"] == "present in eligible range by best_rank"
    assert skipped["US Keep"] == "missing required market tag for fr"
    assert skipped["Legacy Boxarr"] == "legacy boxarr tag requires migration"
    assert skipped["Manual Existing"] == "missing required boxarr-added tag"

    assert fake_service.delete_calls == []
    assert report["estimated_size_to_delete"] == 30 * 1024 * 1024 * 1024


def test_cleanup_dry_run_no_file_candidate_uses_radarr_queue_and_zero_size(tmp_path):
    movies = [
        _movie(
            21,
            501,
            "Queued No File",
            tags=[1, 2],
            size_bytes=0,
            has_file=False,
            path="/movies/Queued No File/Queued No File.mkv",
            quality_profile_id=4,
        ),
        _movie(
            22,
            502,
            "Queued With File Unknown",
            tags=[1, 2],
            size_bytes=0,
            has_file=True,
            path="/movies/Queued With File Unknown/Queued With File Unknown.mkv",
            quality_profile_id=4,
        ),
    ]
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W01.json",
        "fr",
        2026,
        1,
        [
            {"rank": 7, "title": "Queued No File", "tmdb_id": 501, "radarr_id": 21},
            {
                "rank": 8,
                "title": "Queued With File Unknown",
                "tmdb_id": 502,
                "radarr_id": 22,
            },
        ],
    )
    fake_service = _FakeRadarrService(
        movies,
        _canonical_tags(),
        queue_items=[
            {"id": 91, "movieId": 21, "title": "Queued No File"},
        ],
    )
    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="fr",
        execute=False,
    )

    queued = next(item for item in report["candidates"] if item["title"] == "Queued No File")
    assert queued["has_file"] is False
    assert queued["size_on_disk"] is None
    assert queued["in_download_queue"] is True
    assert queued["would_remove_download"] is True
    assert queued["would_remove_radarr"] is True
    assert queued["would_delete_files"] is False
    assert queued["estimated_size_bytes"] == 0

    unknown = next(item for item in report["unsafe"] if item["title"] == "Queued With File Unknown")
    assert unknown["has_file"] is True
    assert unknown["size_on_disk"] is None
    assert unknown["reason"] == "unsafe to delete: file exists but size_on_disk unknown"


def test_cleanup_remove_without_files_only_filters_file_backed_candidates(tmp_path):
    movies = [
        _movie(
            31,
            601,
            "No File Candidate",
            tags=[1, 2],
            size_bytes=0,
            has_file=False,
            path="/movies/No File Candidate/No File Candidate.mkv",
            quality_profile_id=4,
        ),
        _movie(
            32,
            602,
            "File Candidate",
            tags=[1, 2],
            size_bytes=2 * 1024 * 1024 * 1024,
            path="/movies/File Candidate/File Candidate.mkv",
            quality_profile_id=4,
        ),
    ]
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W01.json",
        "fr",
        2026,
        1,
        [
            {"rank": 7, "title": "No File Candidate", "tmdb_id": 601, "radarr_id": 31},
            {"rank": 8, "title": "File Candidate", "tmdb_id": 602, "radarr_id": 32},
        ],
    )
    fake_service = _FakeRadarrService(movies, _canonical_tags(), queue_items=[{"id": 77, "movieId": 31}])
    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        remove_without_files_only=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="fr",
        execute=False,
    )

    candidate_titles = [item["title"] for item in report["candidates"]]
    assert candidate_titles == ["No File Candidate"]
    assert report["remove_without_files_only"] is True
    assert report["would_delete"][0]["title"] == "No File Candidate"
    assert report["would_delete"][0]["would_remove_download"] is True
    assert report["would_delete"][0]["would_delete_files"] is False
    assert report["would_remove_downloads_count"] == 1
    skipped_titles = {item["title"] for item in report["skipped"]}
    assert "File Candidate" in skipped_titles
    assert any(item["reason"] == "skipped by remove_without_files_only" for item in report["skipped"])

    executed = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        remove_without_files_only=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="fr",
        execute=True,
    )

    assert executed["remove_without_files_only"] is True
    assert [item["title"] for item in executed["deleted"]] == ["No File Candidate"]
    assert [item["title"] for item in executed["detached"]] == []
    assert fake_service.remove_queue_calls == [(77, True)]
    assert fake_service.delete_calls == [(31, True)]


def test_cleanup_execute_deletes_and_detaches_once(tmp_path, monkeypatch):
    _seed_settings(monkeypatch)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))

    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W01.json",
        "fr",
        2026,
        1,
        [
            {"rank": 7, "title": "Safe Delete", "tmdb_id": 202, "radarr_id": 3},
            {"rank": 8, "title": "Detach Me", "tmdb_id": 206, "radarr_id": 12},
        ],
    )
    _write_week(
        tmp_path / "weekly_pages" / "fr" / "2026W02.json",
        "fr",
        2026,
        2,
        [
            {"rank": 10, "title": "Safe Delete", "tmdb_id": 202, "radarr_id": 3},
            {"rank": 9, "title": "Detach Me", "tmdb_id": 206, "radarr_id": 12},
        ],
    )

    movies = [
        _movie(3, 202, "Safe Delete", tags=[1, 2], size_bytes=3 * 1024 * 1024 * 1024),
        _movie(12, 206, "Detach Me", tags=[1, 2, 3], size_bytes=4 * 1024 * 1024 * 1024),
    ]
    fake_service = _StatefulCleanupRadarrService(movies, _canonical_tags())

    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="fr",
        execute=True,
    )

    assert [item["title"] for item in report["deleted"]] == ["Safe Delete"]
    assert [item["title"] for item in report["detached"]] == ["Detach Me"]
    assert fake_service.delete_calls == [(3, True)]
    assert fake_service.update_calls == [(12, [1, 3])]
    assert report["actual_size_deleted"] == 3 * 1024 * 1024 * 1024
    assert report["estimated_size_deleted"] == 3 * 1024 * 1024 * 1024

    second = cleanup.run(
        market="fr",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="fr",
        execute=True,
    )
    assert second["deleted"] == []
    assert second["detached"] == []
    assert fake_service.delete_calls == [(3, True)]
    assert fake_service.update_calls == [(12, [1, 3])]


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
        _movie(8, 501, "Legacy US Keep", tags=[1, 3], size_bytes=1024),
    ]
    fake_service = _FakeRadarrService(
        movies,
        _canonical_tags(),
    )

    cleanup = AddLimitCleanupService(fake_service, data_directory=tmp_path)
    report = cleanup.run(
        market="us",
        target_add_limit=3,
        delete_files=True,
        require_boxarr_tag=True,
        protect_tag="boxarr-protected",
        required_market_tag="us",
        execute=False,
    )

    assert report["market"] == "us"
    assert report["eligible_count"] == 2
    assert report["candidates"] == []
    assert report["skipped"][0]["reason"] == "present in eligible range by best_rank"
