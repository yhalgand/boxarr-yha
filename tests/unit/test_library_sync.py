"""Tests for refreshing stored weekly data from Radarr."""

import json

from src.core.library_sync import refresh_weekly_data_from_radarr
from src.core.models import MovieStatus


class _FakeProfile:
    def __init__(self, profile_id: int, name: str):
        self.id = profile_id
        self.name = name


class _FakeMovie:
    def __init__(
        self,
        movie_id: int,
        tmdb_id: int,
        title: str,
        *,
        has_file: bool,
        status: MovieStatus,
        is_available: bool,
        quality_profile_id: int,
        poster_url: str,
    ):
        self.id = movie_id
        self.tmdbId = tmdb_id
        self.title = title
        self.hasFile = has_file
        self.status = status
        self.isAvailable = is_available
        self.qualityProfileId = quality_profile_id
        self.poster_url = poster_url
        self.year = 2024
        self.genres = ["Action", "Adventure"]
        self.overview = f"{title} overview"
        self.imdbId = f"tt{movie_id}"
        self.original_language = "English"


class _FakeRadarrService:
    def __init__(self, movies, profiles):
        self._movies = movies
        self._profiles = profiles
        self.ignore_cache_calls = []

    def get_all_movies(self, ignore_cache: bool = False):
        self.ignore_cache_calls.append(ignore_cache)
        return self._movies

    def get_quality_profiles(self):
        return self._profiles


def test_refresh_weekly_data_from_radarr_updates_stale_entries(tmp_path, monkeypatch):
    weekly_pages_dir = tmp_path / "weekly_pages"
    weekly_pages_dir.mkdir()

    legacy_week_file = weekly_pages_dir / "2024W10.json"
    with open(legacy_week_file, "w") as f:
        json.dump(
            {
                "generated_at": "2026-04-05T10:00:00",
                "market": "us",
                "provider": "mojo_us",
                "year": 2024,
                "week": 10,
                "matched_movies": 1,
                "movies": [
                    {
                        "title": "Downloaded Later",
                        "radarr_id": 101,
                        "tmdb_id": 1001,
                        "status": "Missing",
                        "status_color": "#f56565",
                        "status_icon": "❌",
                        "quality_profile_id": 1,
                        "quality_profile_name": "HD-1080p",
                        "has_file": False,
                        "can_upgrade_quality": False,
                        "poster": None,
                        "year": 2024,
                        "genres": None,
                        "overview": None,
                        "imdb_id": None,
                        "original_language": None,
                    },
                    {
                        "title": "Linked From TMDB",
                        "radarr_id": None,
                        "tmdb_id": 1002,
                        "status": "Not in Radarr",
                        "status_color": "#718096",
                        "status_icon": "➕",
                        "quality_profile_id": None,
                        "quality_profile_name": None,
                        "has_file": False,
                        "can_upgrade_quality": False,
                        "poster": None,
                        "year": 2024,
                        "genres": None,
                        "overview": None,
                        "imdb_id": None,
                        "original_language": None,
                    },
                    {
                        "title": "Stale Deleted",
                        "radarr_id": 303,
                        "tmdb_id": 1003,
                        "status": "Downloaded",
                        "status_color": "#48bb78",
                        "status_icon": "✅",
                        "quality_profile_id": 1,
                        "quality_profile_name": "HD-1080p",
                        "has_file": True,
                        "movie_file": {"size": 123456789, "path": "/movies/Stale Deleted/Stale Deleted.mkv"},
                        "size_on_disk": 123456789,
                        "radarr_title": "Stale Deleted",
                        "radarr_status": "released",
                        "radarr_has_file": True,
                        "can_upgrade_quality": False,
                        "poster": None,
                        "year": 2024,
                        "genres": None,
                        "overview": None,
                        "imdb_id": None,
                        "original_language": None,
                        "path": "/movies/Stale Deleted/Stale Deleted.mkv",
                    },
                ],
            },
            f,
            indent=2,
        )

    monkeypatch.setattr(
        "src.core.library_sync.settings.boxarr_features_quality_upgrade", True
    )
    monkeypatch.setattr(
        "src.core.library_sync.settings.radarr_quality_profile_upgrade", "Ultra-HD"
    )

    fake_service = _FakeRadarrService(
        movies=[
            _FakeMovie(
                101,
                1001,
                "Downloaded Later",
                has_file=True,
                status=MovieStatus.RELEASED,
                is_available=True,
                quality_profile_id=1,
                poster_url="https://example.com/101.jpg",
            ),
            _FakeMovie(
                202,
                1002,
                "Linked From TMDB",
                has_file=False,
                status=MovieStatus.RELEASED,
                is_available=True,
                quality_profile_id=1,
                poster_url="https://example.com/202.jpg",
            ),
        ],
        profiles=[_FakeProfile(1, "HD-1080p"), _FakeProfile(2, "Ultra-HD")],
    )

    results = refresh_weekly_data_from_radarr(
        radarr_service=fake_service,
        data_directory=tmp_path,
        ignore_cache=True,
    )

    assert fake_service.ignore_cache_calls == [True]
    assert results == {
        "weeks_scanned": 1,
        "weeks_updated": 1,
        "movies_refreshed": 3,
        "movies_linked": 1,
    }

    provider_week_file = weekly_pages_dir / "us" / "2024W10.json"
    assert provider_week_file.exists()
    assert legacy_week_file.exists()

    with open(provider_week_file) as f:
        refreshed = json.load(f)

    downloaded = refreshed["movies"][0]
    assert downloaded["status"] == "Downloaded"
    assert downloaded["has_file"] is True
    assert downloaded["radarr_id"] == 101
    assert downloaded["quality_profile_name"] == "HD-1080p"

    linked = refreshed["movies"][1]
    assert linked["radarr_id"] == 202
    assert linked["status"] == "Missing"
    assert linked["can_upgrade_quality"] is True
    assert linked["poster"] == "https://example.com/202.jpg"

    stale = refreshed["movies"][2]
    assert stale["radarr_id"] is None
    assert stale["radarr_title"] is None
    assert stale["radarr_status"] is None
    assert stale["radarr_has_file"] is False
    assert stale["has_file"] is False
    assert stale["movie_file"] is None
    assert stale["size_on_disk"] is None
    assert stale["path"] is None
    assert stale["status"] == "Not in Radarr"
    assert stale["status_color"] == "#718096"
    assert stale["status_icon"] == "➕"

    assert refreshed["matched_movies"] == 2
    assert "status_refreshed_at" in refreshed
    assert refreshed["market"] == "us"
    assert refreshed["provider"] == "mojo"


def test_refresh_weekly_data_from_radarr_reuses_stable_identity_across_weeks(
    tmp_path, monkeypatch
):
    weekly_pages_dir = tmp_path / "weekly_pages" / "fr"
    weekly_pages_dir.mkdir(parents=True)

    shared_source = {
        "source_href": "/fichfilm.php?id=24871&view=2",
        "source_url": "https://www.jpbox-office.com/v9_tophebdo.php?idsem=2926&view=2",
        "source_title": "Le Mage du Kremlin",
        "normalized_source_title": "le mage du kremlin",
        "jpboxoffice_id": 24871,
    }

    confirmed_week = weekly_pages_dir / "2026W21.json"
    confirmed_week.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-25T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "year": 2026,
                "week": 21,
                "matched_movies": 0,
                "movies": [
                    {
                        "rank": 1,
                        "title": "Le Mage du Kremlin",
                        "match_confidence": 0.95,
                        "match_method": "tmdb_confirmed",
                        "identity_status": "TMDB confirmed / not in Radarr",
                        "tmdb_id": 5001,
                        "radarr_id": None,
                        "radarr_title": None,
                        "radarr_status": None,
                        "radarr_has_file": False,
                        "has_file": False,
                        "quality_profile_id": None,
                        "quality_profile_name": None,
                        "poster": None,
                        "year": 2026,
                        "genres": None,
                        "overview": None,
                        "imdb_id": None,
                        "original_language": None,
                        **shared_source,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    unresolved_week = weekly_pages_dir / "2026W20.json"
    unresolved_week.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18T10:00:00",
                "market": "fr",
                "provider": "jpboxoffice",
                "year": 2026,
                "week": 20,
                "matched_movies": 0,
                "movies": [
                    {
                        "rank": 1,
                        "title": "Le Mage du Kremlin",
                        "match_confidence": 0.0,
                        "match_method": "unmatched",
                        "identity_status": "Unmatched / needs identity",
                        "tmdb_id": None,
                        "radarr_id": None,
                        "radarr_title": None,
                        "radarr_status": None,
                        "radarr_has_file": False,
                        "has_file": False,
                        "quality_profile_id": None,
                        "quality_profile_name": None,
                        "poster": None,
                        "year": None,
                        "genres": None,
                        "overview": None,
                        "imdb_id": None,
                        "original_language": None,
                        **shared_source,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.core.library_sync.settings.boxarr_features_quality_upgrade", False
    )

    fake_service = _FakeRadarrService(
        movies=[],
        profiles=[_FakeProfile(1, "HD-1080p")],
    )

    results = refresh_weekly_data_from_radarr(
        radarr_service=fake_service,
        data_directory=tmp_path,
        ignore_cache=True,
        market="fr",
    )

    assert results["weeks_scanned"] == 2
    assert results["weeks_updated"] == 1
    assert results["movies_refreshed"] == 1

    unresolved_payload = json.loads(unresolved_week.read_text(encoding="utf-8"))
    movie = unresolved_payload["movies"][0]
    assert movie["tmdb_id"] == 5001
    assert movie["match_confidence"] == 0.95
    assert movie["match_method"] == "tmdb_confirmed"
    assert movie["identity_status"] == "TMDB confirmed / not in Radarr"
