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
        market="fr",
        provider="jpboxoffice",
        provider_config={"country": "fr"},
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
            box_office_movie=BoxOfficeMovie(rank=1, title="Shared Movie FR", original_title="Shared Movie EN"),
            radarr_movie=shared_movie,
            confidence=0.98,
            match_method="tmdb_exact",
        ),
        MatchResult(
            box_office_movie=BoxOfficeMovie(rank=2, title="Different Movie FR", original_title="Different Movie EN"),
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
    assert payload["movies"][1]["tmdb_id"] is None
    assert payload["movies"][1]["radarr_id"] is None
    assert payload["movies"][1]["match_confidence"] == 0.0
    assert payload["movies"][1]["match_method"] == "duplicate_rejected"
