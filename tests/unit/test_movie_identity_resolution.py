"""Tests for TMDb/Radarr identity resolution."""

from src.core.boxoffice import BoxOfficeMovie
from src.core.movie_identity import resolve_movie_identity
from src.utils.config import settings


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
    assert resolution.debug["normalized_source_title"] == "avatar de feu et de cendres"
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


def test_resolve_french_false_positive_rejects_unrelated_candidate():
    def fake_search(term: str, language=None, region=None):
        if "bojarski" in term.lower():
            return [
                {
                    "title": "X-Men: Apocalypse",
                    "originalTitle": "X-Men: Apocalypse",
                    "tmdbId": 999001,
                    "year": 2016,
                }
            ]
        return []

    movie = BoxOfficeMovie(
        rank=6,
        title="L'Affaire Bojarski",
        original_title="L'Affaire Bojarski",
        year=2026,
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is False
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 999001
    assert "confidence threshold" in resolution.debug["rejection_reason"] or "confirmation" in resolution.debug["rejection_reason"]


def test_resolve_french_localized_title_confirms_positive_match():
    def fake_search(term: str, language=None, region=None):
        if "femme" in term.lower() or "housemaid" in term.lower():
            return [
                {
                    "title": "La Femme de ménage",
                    "originalTitle": "The Housemaid",
                    "alternateTitles": [{"title": "The Housemaid"}],
                    "tmdbId": 424200,
                    "year": 2026,
                    "remotePoster": "poster",
                }
            ]
        return []

    movie = BoxOfficeMovie(
        rank=1,
        title="La Femme de ménage",
        original_title="The Housemaid",
        year=2026,
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is True
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 424200
    assert resolution.confidence >= 0.84
    assert resolution.debug["selected_candidate"] is not None
    assert resolution.debug["selected_candidate"]["title_similarity"] >= 0.55


def test_resolve_movie_identity_uses_detail_metadata_and_override(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "boxarr_data_directory", tmp_path)

    overrides_path = tmp_path / "identity_overrides.json"
    overrides_path.write_text(
        """
        {
          "markets": {
            "fr": {
              "jpboxoffice_ids": {
                "24871": {
                  "tmdb_id": 424242,
                  "notes": "manual override"
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    calls = []

    def fake_search(term: str, language=None, region=None):
        calls.append((term, language, region))
        return []

    movie = BoxOfficeMovie(
        rank=10,
        title="Le Mage du Kremlin",
        source_href="/fichfilm.php?id=24871&view=2",
        jpboxoffice_id=24871,
        identity_metadata={
            "english_title": "The Kremlin Wizard",
            "original_title": "Le Mage du Kremlin",
            "director": "J. Doe",
            "year": 2026,
        },
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is True
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 424242
    assert resolution.reason == "manual override"
    assert resolution.debug["selected_candidate"]["source"] == "manual_override"
    assert calls == []


def test_resolve_movie_identity_uses_allocine_manual_override(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "boxarr_data_directory", tmp_path)

    overrides_path = tmp_path / "identity_overrides.json"
    overrides_path.write_text(
        """
        {
          "markets": {
            "fr": {
              "allocine_movie_ids": {
                "318031": {
                  "tmdb_id": 1152014,
                  "title": "Un p'tit truc en plus",
                  "notes": "allocine manual override"
                }
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    calls = []

    def fake_search(term: str, language=None, region=None):
        calls.append((term, language, region))
        return []

    movie = BoxOfficeMovie(
        rank=1,
        title="Un p’tit truc en plus",
        allocine_movie_id=318031,
        source_href="/film/fichefilm_gen_cfilm=318031.html",
        identity_metadata={"source_provider": "allocine"},
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is True
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 1152014
    assert resolution.reason == "manual override"
    assert resolution.debug["override"]["notes"] == "allocine manual override"
    assert calls == []


def test_resolve_allocine_rows_with_original_title_metadata():
    examples = [
        (
            "Le Diable s'habille en Prada 2",
            "The Devil Wears Prada 2",
            1000006868,
            1001,
        ),
        (
            "Super Mario Galaxy Le Film",
            "The Super Mario Galaxy Movie",
            327878,
            1002,
        ),
        ("Vivaldi et moi", "Vivaldi and Me", 1000018672, 1003),
        ("Le Réveil de la Momie", "The Mummy's Awakening", 1000005009, 1004),
    ]

    for source_title, original_title, allocine_id, tmdb_id in examples:
        calls = []

        def fake_search(term: str, language=None, region=None):
            calls.append((term, language, region))
            if original_title.lower() in term.lower():
                return [
                    {
                        "title": original_title,
                        "originalTitle": original_title,
                        "tmdbId": tmdb_id,
                        "year": 2026,
                        "remotePoster": f"poster-{tmdb_id}",
                    }
                ]
            return []

        movie = BoxOfficeMovie(
            rank=1,
            title=source_title,
            allocine_movie_id=allocine_id,
            identity_metadata={
                "source_provider": "allocine",
                "original_title": original_title,
                "year": 2026,
            },
        )

        resolution = resolve_movie_identity(movie, fake_search, market="fr")

        assert resolution.matched is True
        assert resolution.movie_info is not None
        assert resolution.movie_info["tmdbId"] == tmdb_id
        assert resolution.confidence >= 0.84
        assert any(call[0] == original_title for call in calls)


def test_resolve_allocine_row_uses_source_detail_tmdb_id_without_search():
    calls = []

    def fake_search(term: str, language=None, region=None):
        calls.append((term, language, region))
        return []

    movie = BoxOfficeMovie(
        rank=1,
        title="Vivaldi et moi",
        allocine_movie_id=1000018672,
        identity_metadata={
            "source_provider": "allocine",
            "detail_title": "Vivaldi et moi",
            "original_title": "Vivaldi and Me",
            "tmdb_id": 123456,
            "year": 2026,
        },
    )

    resolution = resolve_movie_identity(movie, fake_search, market="fr")

    assert resolution.matched is True
    assert resolution.movie_info is not None
    assert resolution.movie_info["tmdbId"] == 123456
    assert resolution.reason == "source tmdb id"
    assert resolution.debug["selected_candidate"]["source"] == "source_detail"
    assert calls == []
