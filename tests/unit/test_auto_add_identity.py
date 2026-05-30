"""Tests for auto-add using confirmed identity resolution."""

from src.core.auto_add import auto_add_missing_movies
from src.core.boxoffice import BoxOfficeMovie
from src.core.matcher import MatchResult
from src.core.radarr import RadarrMovie
from src.utils.config import settings


class _FakeQualityProfile:
    def __init__(self, id=1, name="HD-1080p"):
        self.id = id
        self.name = name


class _FakeRadarrService:
    def __init__(self):
        self.add_calls = []

    def get_quality_profiles(self):
        return [_FakeQualityProfile()]

    def add_movie(
        self,
        tmdb_id,
        quality_profile_id=None,
        root_folder=None,
        monitored=True,
        search_for_movie=True,
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
        return RadarrMovie(id=999, title="The Housemaid", tmdbId=tmdb_id, hasFile=False)


def test_auto_add_uses_manual_confirmed_tmdb_identity(monkeypatch):
    monkeypatch.setattr(settings, "radarr_quality_profile_default", "HD-1080p")
    monkeypatch.setattr(settings, "boxarr_features_auto_add_language_filter_enabled", False)
    monkeypatch.setattr(settings, "boxarr_features_auto_add_genre_filter_enabled", False)
    monkeypatch.setattr(settings, "boxarr_features_auto_add_rating_filter_enabled", False)
    monkeypatch.setattr(settings, "boxarr_features_auto_add_ignore_rereleases", False)
    monkeypatch.setattr(settings, "boxarr_features_auto_add_limit", 10)

    result = MatchResult(
        box_office_movie=BoxOfficeMovie(
            rank=1,
            title="La Femme de ménage",
            source_href="/fichfilm.php?id=50001&view=2",
            jpboxoffice_id=50001,
            identity_metadata={
                "original_title": "The Housemaid",
                "year": 2026,
            },
        ),
        confidence=1.0,
        match_method="manual_confirmed",
        resolved_tmdb_id=424242,
        resolved_movie_info={
            "tmdbId": 424242,
            "title": "The Housemaid",
            "genres": ["Drama"],
            "year": 2026,
        },
        identity_status="Manual confirmed / not in Radarr",
    )

    radarr_service = _FakeRadarrService()
    added = auto_add_missing_movies([result], radarr_service, top_year=2026, market="fr")

    assert added == [
        {
            "title": "The Housemaid",
            "tmdbId": 424242,
            "id": 999,
        }
    ]
    assert radarr_service.add_calls[0]["tmdb_id"] == 424242
    assert radarr_service.add_calls[0]["additional_tag_labels"] == [
        "boxarr-added",
        "boxarr-market-fr",
    ]
