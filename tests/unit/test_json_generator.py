"""Tests for weekly JSON generation safety and duplicate match rejection."""

from pathlib import Path
from types import SimpleNamespace

import json
import yaml

from src.core.boxoffice import BoxOfficeMovie
from src.core.json_generator import WeeklyDataGenerator
from src.core.matcher import MatchResult
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
                    "limit": 10,
                    "genre_filter_enabled": False,
                    "rating_filter_enabled": False,
                },
            },
            "ui": {"theme": "light"},
        },
    }
    path = dir_path / "local.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return path


class _FakeRadarrService:
    def get_quality_profiles(self):
        return []


def test_duplicate_tmdb_and_radarr_matches_are_rejected(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    generator = WeeklyDataGenerator(
        radarr_service=_FakeRadarrService(),
        market="us",
        provider="mojo",
        provider_config={"area": "us"},
    )

    shared_movie = RadarrMovie(
        id=100,
        title="Shared Movie",
        tmdbId=5000,
        hasFile=False,
        status=None,
    )
    results = [
        MatchResult(
            box_office_movie=BoxOfficeMovie(
                rank=1,
                title="Shared Movie FR",
                original_title="Shared Movie EN",
                normalized_source_title="shared movie fr",
                source_href="/fichfilm.php?id=100&view=2",
                source_url="https://www.jpbox-office.com/v9_tophebdo.php?idsem=1&view=2",
                source_title="Shared Movie FR",
                jpboxoffice_id=100,
                country="fr",
            ),
            radarr_movie=shared_movie,
            confidence=0.98,
            match_method="tmdb_exact",
        ),
        MatchResult(
            box_office_movie=BoxOfficeMovie(
                rank=2,
                title="Different Movie FR",
                original_title="Different Movie EN",
                normalized_source_title="different movie fr",
                source_href="/fichfilm.php?id=101&view=2",
                source_url="https://www.jpbox-office.com/v9_tophebdo.php?idsem=1&view=2",
                source_title="Different Movie FR",
                jpboxoffice_id=101,
                country="fr",
            ),
            radarr_movie=shared_movie,
            confidence=0.97,
            match_method="tmdb_exact",
        ),
    ]

    output = generator.generate_weekly_data(results, year=2026, week=21)
    payload = json.loads(Path(output).read_text(encoding="utf-8"))

    assert payload["movies"][0]["tmdb_id"] == 5000
    assert payload["movies"][0]["radarr_id"] == 100
    assert payload["movies"][0]["match_confidence"] == 0.98
    assert payload["movies"][0]["source_href"] == "/fichfilm.php?id=100&view=2"
    assert payload["movies"][0]["normalized_source_title"] == "shared movie fr"
    assert payload["movies"][0]["source_title"] == "Shared Movie FR"
    assert payload["movies"][0]["jpboxoffice_id"] == 100
    assert payload["movies"][0]["country"] == "fr"
    assert payload["movies"][1]["tmdb_id"] is None
    assert payload["movies"][1]["radarr_id"] is None
    assert payload["movies"][1]["match_confidence"] == 0.0
    assert payload["movies"][1]["match_method"] == "duplicate_rejected"
    assert payload["movies"][1]["normalized_source_title"] == "different movie fr"


def test_weekly_json_keeps_allocine_movie_id(tmp_path, monkeypatch):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    generator = WeeklyDataGenerator(
        radarr_service=_FakeRadarrService(),
        market="fr",
        provider="france_boxoffice",
        provider_config={"country": "fr", "primary": "allocine", "fallback": "jpboxoffice"},
    )

    results = [
        MatchResult(
            box_office_movie=BoxOfficeMovie(
                rank=1,
                title="Un p'tit truc en plus",
                normalized_source_title="un ptit truc en plus",
                source_href="/film/fichefilm_gen_cfilm=300001.html",
                source_url="https://www.allocine.fr/boxoffice/france/sem-2024-05-01/",
                source_title="Un p'tit truc en plus",
                allocine_movie_id=300001,
                country="fr",
            ),
            confidence=0.0,
            match_method="none",
        )
    ]

    output = generator.generate_weekly_data(results, year=2024, week=18)
    payload = json.loads(Path(output).read_text(encoding="utf-8"))

    assert payload["movies"][0]["allocine_movie_id"] == 300001
    assert payload["movies"][0]["jpboxoffice_id"] is None


def test_unmatched_allocine_rows_are_not_duplicate_rejected_and_keep_source(
    tmp_path, monkeypatch
):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    generator = WeeklyDataGenerator(
        radarr_service=_FakeRadarrService(),
        market="fr",
        provider="france_boxoffice",
        provider_config={"country": "fr", "primary": "allocine", "fallback": "jpboxoffice"},
    )

    examples = [
        ("Le Diable s'habille en Prada 2", 1000006868),
        ("Super Mario Galaxy Le Film", 327878),
        ("Vivaldi et moi", 1000018672),
        ("Le Réveil de la Momie", 1000005009),
    ]
    results = [
        MatchResult(
            box_office_movie=BoxOfficeMovie(
                rank=index,
                title=title,
                normalized_source_title=title.lower(),
                source_href=f"/film/fichefilm_gen_cfilm={allocine_id}.html",
                source_url="https://www.allocine.fr/boxoffice/france/sem-2026-05-20/",
                source_title=title,
                allocine_movie_id=allocine_id,
                market="fr",
                country="fr",
            ),
            confidence=0.0,
            match_method="none",
        )
        for index, (title, allocine_id) in enumerate(examples, start=1)
    ]

    output = generator.generate_weekly_data(results, year=2026, week=21)
    payload = json.loads(Path(output).read_text(encoding="utf-8"))

    assert [movie["title"] for movie in payload["movies"]] == [
        title for title, _ in examples
    ]
    for movie, (_title, allocine_id) in zip(payload["movies"], examples):
        assert movie["allocine_movie_id"] == allocine_id
        assert movie["source_href"] == f"/film/fichefilm_gen_cfilm={allocine_id}.html"
        assert movie["source_url"].startswith("https://www.allocine.fr/")
        assert movie["tmdb_id"] is None
        assert movie["poster"] is None
        assert movie["match_method"] == "unmatched"
        assert movie["identity_status"] == "Unmatched / needs identity"


def test_same_allocine_movie_repeated_across_weeks_is_not_duplicate_rejected(
    tmp_path, monkeypatch
):
    config_path = _seed_config(tmp_path)
    monkeypatch.setenv("BOXARR_DATA_DIRECTORY", str(tmp_path))
    Settings.reload_from_file(config_path)

    generator = WeeklyDataGenerator(
        radarr_service=_FakeRadarrService(),
        market="fr",
        provider="france_boxoffice",
        provider_config={"country": "fr", "primary": "allocine", "fallback": "jpboxoffice"},
    )

    def _result(rank: int) -> MatchResult:
        return MatchResult(
            box_office_movie=BoxOfficeMovie(
                rank=rank,
                title="Super Mario Galaxy Le Film",
                normalized_source_title="super mario galaxy le film",
                source_href="/film/fichefilm_gen_cfilm=327878.html",
                source_url="https://www.allocine.fr/boxoffice/france/sem-2026-05-20/",
                source_title="Super Mario Galaxy Le Film",
                allocine_movie_id=327878,
                market="fr",
                country="fr",
            ),
            confidence=0.0,
            match_method="none",
        )

    week_21 = generator.generate_weekly_data([_result(1)], year=2026, week=21)
    week_22 = generator.generate_weekly_data([_result(1)], year=2026, week=22)

    for output in (week_21, week_22):
        payload = json.loads(Path(output).read_text(encoding="utf-8"))
        assert payload["movies"][0]["allocine_movie_id"] == 327878
        assert payload["movies"][0]["match_method"] == "unmatched"
        assert payload["movies"][0]["match_method"] != "duplicate_rejected"
