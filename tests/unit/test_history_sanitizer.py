"""Tests for sanitizing historical weekly box office payloads."""

from src.core.history_sanitizer import sanitize_history_movies


def test_sanitize_history_movies_clears_dirty_fr_jpboxoffice_matches():
    dirty_movies = [
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
    ]

    sanitized = sanitize_history_movies(dirty_movies, market="fr")

    assert len(sanitized) == 1
    cleaned = sanitized[0]
    assert cleaned["tmdb_id"] is None
    assert cleaned["radarr_id"] is None
    assert cleaned["radarr_title"] is None
    assert cleaned["radarr_status"] is None
    assert cleaned["radarr_has_file"] is False
    assert cleaned["has_file"] is False
    assert cleaned["quality_profile_id"] is None
    assert cleaned["quality_profile_name"] is None
    assert cleaned["poster"] is None
    assert cleaned["year"] is None
    assert cleaned["genres"] is None
    assert cleaned["overview"] is None
    assert cleaned["imdb_id"] is None
    assert cleaned["original_language"] is None
    assert cleaned["can_upgrade_quality"] is False
    assert cleaned["status"] == "Not in Radarr"
    assert cleaned["status_color"] == "#718096"
    assert cleaned["status_icon"] == "➕"
    assert cleaned["match_confidence"] == 0.0
    assert cleaned["match_method"] == "unmatched"
    assert cleaned["identity_status"] == "Unmatched / needs identity"


def test_sanitize_history_movies_keeps_manual_confirmed_fr_matches():
    movies = [
        {
            "rank": 1,
            "title": "La Femme de ménage",
            "provider": "jpboxoffice",
            "match_method": "manual_confirmed",
            "match_confidence": 1.0,
            "tmdb_id": 424242,
            "radarr_id": None,
            "radarr_title": None,
            "radarr_status": None,
            "radarr_has_file": False,
            "has_file": False,
            "year": 2026,
        }
    ]

    sanitized = sanitize_history_movies(movies, market="fr")
    assert len(sanitized) == 1
    assert sanitized[0]["tmdb_id"] == 424242
    assert sanitized[0]["match_method"] == "manual_confirmed"


def test_sanitize_history_movies_marks_only_real_duplicate_id_conflicts():
    movies = [
        {
            "rank": 1,
            "title": "Movie A",
            "provider": "france_boxoffice",
            "match_method": "tmdb_confirmed",
            "match_confidence": 1.0,
            "tmdb_id": 100,
            "poster": "poster-a",
        },
        {
            "rank": 2,
            "title": "Movie B",
            "provider": "france_boxoffice",
            "match_method": "tmdb_confirmed",
            "match_confidence": 0.95,
            "tmdb_id": 100,
            "poster": "poster-b",
        },
    ]

    sanitized = sanitize_history_movies(movies, market="fr")

    assert sanitized[0]["match_method"] == "tmdb_confirmed"
    assert sanitized[0]["tmdb_id"] == 100
    assert sanitized[1]["match_method"] == "duplicate_rejected"
    assert sanitized[1]["tmdb_id"] is None
