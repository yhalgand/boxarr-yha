"""Tests for the JPBoxOffice France provider."""

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.core.boxoffice import BoxOfficeError, BoxOfficeService

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
LIVE_FIXTURES_DIR = FIXTURES_DIR / "live_debug"


def _response(url: str, html: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, request=request, content=html.encode("utf-8"))


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_fr_provider_parses_fixture_and_enriches_imdb():
    year_html = _load_fixture("jpboxoffice_fr_year_2026.html")
    weekly_html = _load_fixture("jpboxoffice_fr_week_2026w02.html")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2926&view=2" in url:
            return _response(url, weekly_html)
        if "fichfilm.php?id=12345&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        if "fichfilm.php?id=23456&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt7654321/'>IMDb</a></body></html>",
            )
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")
    movies = service.fetch_weekend_box_office(2026, 4, limit=10)

    assert len(movies) >= 10
    assert [movie.rank for movie in movies[:10]] == list(range(1, 11))
    assert movies[0].title == "La Femme de ménage"
    assert movies[0].weekend_gross == 373410.0
    assert movies[0].total_gross == 3823351.0
    assert movies[0].weeks_released == 4
    assert movies[0].theater_count == 967
    assert movies[0].imdb_id == "tt1234567"

    assert movies[1].title == "Avatar : de feu et de cendres"
    assert movies[1].weekend_gross == 336843.0
    assert movies[1].total_gross == 8242711.0
    assert movies[1].weeks_released == 6
    assert movies[1].theater_count == 866
    assert movies[1].imdb_id == "tt7654321"

    assert movies[3].rank == 4
    assert movies[3].title == "L'Affaire Bojarski"
    assert movies[3].weekend_gross == 267123.0
    assert movies[3].total_gross == 645346.0
    assert movies[3].weeks_released == 2
    assert movies[3].theater_count == 666

    assert movies[4].rank == 5
    assert movies[4].title == "Zootopie 2"
    assert movies[4].weekend_gross == 195116.0
    assert movies[4].total_gross == 8164429.0
    assert movies[4].weeks_released == 9
    assert movies[4].theater_count == 723

    mufasa = next(movie for movie in movies if movie.title == "Mufasa: Le Roi Lion")
    assert mufasa.weekend_gross == 215252.0
    assert mufasa.total_gross == 215252.0
    assert mufasa.weeks_released == 1
    assert mufasa.theater_count == 812


def test_fr_provider_parses_live_debug_fixture():
    year_html = (
        LIVE_FIXTURES_DIR
        / "jpboxoffice_https_www.jpbox-office.com_v9_hebdomadaire.php_view_2_year_2026.html"
    ).read_text(encoding="utf-8", errors="ignore")
    weekly_html = (
        LIVE_FIXTURES_DIR
        / "jpboxoffice_https_www.jpbox-office.com_v9_tophebdo.php_idsem_2926_view_2.html"
    ).read_text(encoding="utf-8", errors="ignore")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2926&view=2" in url:
            return _response(url, weekly_html)
        if "fichfilm.php?id=24858&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")
    movies = service.fetch_weekend_box_office(2026, 4, limit=10)

    assert len(movies) >= 10
    assert [movie.rank for movie in movies[:10]] == list(range(1, 11))
    assert movies[0].title == "La Femme de ménage"
    assert movies[0].weekend_gross == 373410.0
    assert movies[0].total_gross == 3823351.0
    assert movies[0].weeks_released == 5
    assert movies[0].theater_count == 967

    assert movies[1].title == "Avatar : de feu et de cendres"
    assert movies[1].weekend_gross == 336843.0
    assert movies[1].total_gross == 8242711.0
    assert movies[1].weeks_released == 6
    assert movies[1].theater_count == 866

    assert movies[3].rank == 4
    assert movies[4].rank == 5

    mufasa = next(movie for movie in movies if movie.title == "Mufasa: Le Roi Lion")
    assert mufasa.weekend_gross == 215252.0
    assert mufasa.total_gross == 215252.0
    assert mufasa.weeks_released == 1
    assert mufasa.theater_count == 615


def test_fr_provider_raises_clean_error_on_empty_page():
    year_html = _load_fixture("jpboxoffice_fr_year_2026.html")
    empty_week_html = "<html><body><p>No data yet</p></body></html>"

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2926&view=2" in url:
            return _response(url, empty_week_html)
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")

    with pytest.raises(BoxOfficeError) as excinfo:
        service.fetch_weekend_box_office(2026, 4, limit=10)

    assert "JPBoxOffice" in str(excinfo.value)
