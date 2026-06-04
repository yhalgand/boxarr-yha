"""Tests for stable cross-week identity reuse."""

from src.core.identity_reuse import (
    apply_stable_identity_reuse,
    build_stable_identity_cache,
    stable_identity_aliases,
)


def test_stable_identity_aliases_read_allocine_id_from_identity_metadata():
    record = {
        "market": "fr",
        "title": "Un p'tit truc en plus",
        "identity_metadata": {"allocine_movie_id": 318031},
    }

    assert "fr:allocine_movie_id:318031" in stable_identity_aliases(record)


def test_stable_identity_reuse_applies_confirmed_allocine_identity_from_metadata():
    confirmed = {
        "market": "fr",
        "title": "Un p'tit truc en plus",
        "allocine_movie_id": 318031,
        "tmdb_id": 1152014,
        "match_confidence": 1.0,
        "match_method": "tmdb_confirmed",
        "identity_status": "TMDB confirmed / not in Radarr",
        "poster": "https://image.tmdb.org/t/p/original/poster.jpg",
        "imdb_id": "tt30795948",
    }
    unresolved = {
        "market": "fr",
        "title": "Un p'tit truc en plus",
        "identity_metadata": {"allocine_movie_id": 318031},
        "tmdb_id": None,
        "match_confidence": 0.0,
        "match_method": "none",
        "poster": None,
        "imdb_id": None,
    }

    cache = build_stable_identity_cache([confirmed, unresolved], market="fr")

    assert apply_stable_identity_reuse(unresolved, cache, market="fr") is True
    assert unresolved["tmdb_id"] == 1152014
    assert unresolved["poster"] == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert unresolved["imdb_id"] == "tt30795948"
