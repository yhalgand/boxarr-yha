"""Tests for TMDb/Radarr identity resolution."""

from src.core.boxoffice import BoxOfficeMovie
from src.core.movie_identity import resolve_movie_identity


def test_resolve_avatar_from_french_and_original_titles():
    calls = []

    def fake_search(term: str, language=None, region=None):
        calls.append((term, language, region))
        if "avatar" in term.lower():
            return [
                {
                    "title": "Avatar: Fire and Ash",
                    "tmdbId": 424242,
                    "year": 2026,
                    "overview": "Avatar entry",
                    "remotePoster": "poster",
                },
                {
                    "title": "A Completely Different Movie",
                    "tmdbId": 111111,
                    "year": 2026,
                },
            ]
        return []

    movie = BoxOfficeMovie(
        rank=2,
        title="Avatar : de feu et de cendres",
        original_title="Avatar: Fire and Ash",
        year=2026,
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is True
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 424242
    assert resolution.confidence >= 0.84
    assert resolution.search_term is not None
    assert resolution.search_term == "Avatar : de feu et de cendres"
    assert any("avatar" in term.lower() for term, _, _ in calls)
    assert calls[0][1] == "fr-FR"
    assert calls[0][2] == "FR"
    assert calls[0][0] == "Avatar : de feu et de cendres"
    assert resolution.debug["source_title"] == "Avatar : de feu et de cendres"
    assert resolution.debug["tmdb_query"] is not None
    assert resolution.debug["tmdb_language"] == "fr-FR"
    assert resolution.debug["tmdb_region"] == "FR"
    assert resolution.debug["selected_candidate"] is not None


def test_resolve_zootopie_with_accent_and_punctuation_variations():
    def fake_search(term: str, language=None, region=None):
        if "zootopia" in term.lower() or "zootopie" in term.lower():
            return [
                {
                    "title": "Zootopia 2",
                    "tmdbId": 515151,
                    "year": 2026,
                    "remotePoster": "poster",
                },
                {
                    "title": "Some Other Film",
                    "tmdbId": 999999,
                    "year": 2026,
                },
            ]
        return []

    movie = BoxOfficeMovie(
        rank=5,
        title="Zootopie 2",
        original_title="Zootopia 2",
        year=2026,
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is True
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 515151
    assert resolution.confidence >= 0.84
    assert resolution.debug["cleaned_title"] == "zootopie 2"
    assert resolution.debug["tmdb_language"] == "fr-FR"
    assert resolution.debug["tmdb_region"] == "FR"


def test_resolve_unknown_movie_rejects_false_positive():
    def fake_search(term: str):
        return [
            {
                "title": "Completely Unrelated Film",
                "tmdbId": 333333,
                "year": 2026,
            }
        ]

    movie = BoxOfficeMovie(
        rank=99,
        title="Un film inconnu",
        original_title="Unknown Film",
        year=2026,
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is False
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 333333
    assert resolution.confidence < 0.84
