"""Tests for the JPBoxOffice provider across supported JPBoxOffice countries."""

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.core.boxoffice import BoxOfficeError, BoxOfficeService, create_provider
from src.core.boxoffice_provider import get_jpboxoffice_country_spec

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _response(url: str, html: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, request=request, content=html.encode("utf-8"))


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _country_fixture_html(html: str, view: int) -> str:
    return html.replace("view=2", f"view={view}")


@pytest.mark.parametrize(
    "country,expected_view",
    [
        ("fr", 2),
        ("de", 4),
        ("br", 36),
        ("cn", 30),
        ("kr", 34),
        ("es", 33),
        ("it", 32),
        ("ru", 35),
    ],
)
def test_supported_jpboxoffice_countries_use_country_specific_view_and_parse(
    monkeypatch, country, expected_view
):
    spec = get_jpboxoffice_country_spec(country)
    assert spec is not None
    assert spec["view"] == expected_view

    monkeypatch.setattr(
        "src.core.boxoffice_provider._runtime_market_registry",
        lambda: {
            country: {
                "market": country,
                "label": f"{country.upper()} Box Office",
                "provider": "jpboxoffice",
                "provider_config": {"country": country},
                "enabled": True,
            }
        },
    )
    monkeypatch.setattr(
        "src.core.market_settings.ensure_market_enabled",
        lambda *_args, **_kwargs: {"provider_config": {"country": country}},
    )

    year_html = _country_fixture_html(_load_fixture("jpboxoffice_fr_year_2026.html"), expected_view)
    weekly_html = _country_fixture_html(_load_fixture("jpboxoffice_fr_week_2026w02.html"), expected_view)

    client = MagicMock()

    def fake_get(url: str):
        if f"v9_hebdomadaire.php?view={expected_view}&year=2026" in url:
            return _response(url, year_html)
        if f"v9_tophebdo.php?idsem=2926&view={expected_view}" in url:
            return _response(url, weekly_html)
        if f"fichfilm.php?id=12345&view={expected_view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        if f"fichfilm.php?id=23456&view={expected_view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt7654321/'>IMDb</a></body></html>",
            )
        if f"fichfilm.php?id=24858&view={expected_view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="jpboxoffice",
        provider_config={"country": country},
    )
    movies = service.fetch_weekend_box_office(2026, 4, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies[:10]] == list(range(1, 11))
    assert movies[0].title == "La Femme de ménage"
    assert movies[0].original_title == "The Housemaid"
    assert movies[0].weekend_gross is not None
    assert movies[0].total_gross is not None
    assert movies[0].weeks_released is not None
    assert movies[0].theater_count is not None
    assert movies[0].imdb_id == "tt1234567"

    assert movies[1].title == "Avatar : de feu et de cendres"
    assert movies[1].original_title == "Avatar: Fire and Ash"
    assert movies[1].weekend_gross is not None
    assert movies[1].total_gross is not None
    assert movies[1].weeks_released is not None
    assert movies[1].theater_count is not None
    assert movies[1].imdb_id == "tt7654321"

    assert movies[3].rank == 4
    assert movies[3].title

    assert movies[4].rank == 5
    assert movies[4].title
    assert movies[4].original_title

    assert movies[-1].title == "28 Ans Plus Tard : Le Temple Des Morts"

    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["country"] == country
    assert diagnostics["view"] == expected_view
    assert diagnostics["rows_seen"] >= 10
    assert diagnostics["rows_parsed"] == 10
    assert diagnostics["rows_skipped"] >= 0


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

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="jpboxoffice",
        provider_config={"country": "fr"},
    )
    movies = service.fetch_weekend_box_office(2026, 4, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies[:10]] == list(range(1, 11))
    assert all(movie.title != "Titre" for movie in movies)
    assert movies[0].title == "La Femme de ménage"
    assert movies[0].original_title == "The Housemaid"
    assert movies[0].weekend_gross is not None
    assert movies[0].total_gross is not None
    assert movies[0].weeks_released is not None
    assert movies[0].theater_count is not None
    assert movies[0].imdb_id == "tt1234567"

    assert movies[1].title == "Avatar : de feu et de cendres"
    assert movies[1].original_title == "Avatar: Fire and Ash"
    assert movies[1].rank == 2
    assert movies[1].weekend_gross is not None
    assert movies[1].total_gross is not None
    assert movies[1].weeks_released is not None
    assert movies[1].theater_count is not None
    assert movies[1].imdb_id == "tt7654321"

    assert movies[3].rank == 4
    assert movies[3].title

    assert movies[4].rank == 5
    assert movies[4].title
    assert movies[4].original_title

    assert movies[-1].title == "28 Ans Plus Tard : Le Temple Des Morts"

    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["rows_seen"] >= 10
    assert diagnostics["valid_rows"] == 10
    assert diagnostics["rows_parsed"] == 10
    assert diagnostics["rows_skipped"] >= 0
    assert diagnostics["skipped_header_rows"] == 0
    assert diagnostics["parsed_rows"][1]["rank"] == 2
    assert diagnostics["parsed_rows"][1]["extracted_rank"] is not None
    assert diagnostics["parsed_rows"][1]["final_rank"] == 2
    assert diagnostics["parsed_rows"][1]["rank_source"] == "row_order"


@pytest.mark.parametrize(
    "country,expected_view",
    [
        ("fr", 2),
        ("de", 4),
        ("br", 36),
        ("cn", 30),
        ("kr", 34),
        ("es", 33),
        ("it", 32),
        ("ru", 35),
    ],
)
def test_supported_country_saved_weekly_fixtures_parse_10_rows(
    monkeypatch, country, expected_view
):
    year_html = (
        "<html><body><div class='annual-listing'>"
        f"<a href='/v9_tophebdo.php?idsem=2901&view={expected_view}'>1</a>"
        "</div></body></html>"
    )
    weekly_html = _load_fixture(f"jpboxoffice_{country}_week_2024w01.html")

    client = MagicMock()

    def fake_get(url: str):
        if f"v9_hebdomadaire.php?view={expected_view}&year=2024" in url:
            return _response(url, year_html)
        if f"v9_tophebdo.php?idsem=2901&view={expected_view}" in url:
            return _response(url, weekly_html)
        if f"fichfilm.php?id=12345&view={expected_view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        if f"fichfilm.php?id=23456&view={expected_view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt7654321/'>IMDb</a></body></html>",
            )
        if f"fichfilm.php?id=34567&view={expected_view}" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt3456789/'>IMDb</a></body></html>",
            )
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="jpboxoffice",
        provider_config={"country": country},
    )
    movies = service.fetch_weekend_box_office(2024, 1, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies[:10]] == list(range(1, 11))
    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["rows_seen"] >= 10
    assert diagnostics["rows_parsed"] == 10
    assert diagnostics["rows_skipped"] >= 0


def test_jpboxoffice_rows_without_numeric_fields_still_parse(monkeypatch):
    year_html = "<html><body><div class='annual-listing'><a href='/v9_tophebdo.php?idsem=2901&view=34'>1</a></div></body></html>"
    weekly_html = """
    <html><body>
      <div class="movie-block">
        <div>1</div>
        <div>Image</div>
        <a href="/fichfilm.php?id=50001&view=34">Korean Movie 1</a>
        <div>Original Korean Movie 1</div>
        <div>(Studio)</div>
        <div>Some country / Genre / 2h00</div>
      </div>
      <div class="movie-block">
        <div>2</div>
        <div>Image</div>
        <a href="/fichfilm.php?id=50002&view=34">Korean Movie 2</a>
        <div>Original Korean Movie 2</div>
        <div>(Studio)</div>
        <div>Some country / Genre / 2h00 123 456 +10%</div>
        <div>(+1) 10 1 234 567</div>
      </div>
    </body></html>
    """

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=34&year=2024" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2901&view=34" in url:
            return _response(url, weekly_html)
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="jpboxoffice",
        provider_config={"country": "kr"},
    )
    movies = service.fetch_weekend_box_office(2024, 1, limit=10)

    assert len(movies) == 2
    assert movies[0].title == "Korean Movie 1"
    assert movies[0].weekend_gross is None
    assert movies[0].total_gross is None
    assert movies[1].title == "Korean Movie 2"
    assert movies[1].weekend_gross is not None
    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["rows_seen"] >= 2
    assert diagnostics["rows_parsed"] == 2
    assert diagnostics["rows_skipped"] >= 0


def test_fr_provider_parses_saved_fixture():
    year_html = (
        "<html><body><div class='annual-listing'>"
        "<a href='/v9_tophebdo.php?idsem=2901&view=2'>1</a>"
        "</div></body></html>"
    )
    weekly_html = _load_fixture("jpboxoffice_fr_week_2024w01.html")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2024" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2901&view=2" in url:
            return _response(url, weekly_html)
        if "fichfilm.php?id=12345&view=2" in url:
            return _response(
                url,
                "<html><body><a href='https://pro.imdb.com/title/tt1234567/'>IMDb</a></body></html>",
            )
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")
    movies = service.fetch_weekend_box_office(2024, 1, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies[:10]] == list(range(1, 11))
    assert movies[0].title == "La Femme de ménage"
    assert movies[0].original_title == "The Housemaid"
    assert movies[0].weekend_gross is not None
    assert movies[0].total_gross is not None
    assert movies[0].weeks_released is not None
    assert movies[0].theater_count is not None

    assert movies[1].title == "Avatar : de feu et de cendres"
    assert movies[1].original_title == "Avatar: Fire and Ash"
    assert movies[1].weekend_gross is not None
    assert movies[1].total_gross is not None
    assert movies[1].weeks_released is not None
    assert movies[1].theater_count is not None

    assert movies[3].rank == 4
    assert movies[4].rank == 5

    mufasa = next(movie for movie in movies if movie.title == "Mufasa: Le Roi Lion")
    assert mufasa.title == "Mufasa: Le Roi Lion"


def test_fr_provider_skips_header_row_and_parses_week_2026w01():
    year_html = (
        "<html><body><div class='annual-listing'>"
        "<a href='/v9_tophebdo.php?idsem=2901&view=2'>1</a>"
        "</div></body></html>"
    )
    weekly_html = _load_fixture("jpboxoffice_fr_week_2026w01.html")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2901&view=2" in url:
            return _response(url, weekly_html)
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")
    movies = service.fetch_weekend_box_office(2026, 1, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies] == list(range(1, 11))
    assert all(movie.title != "Titre" for movie in movies)
    assert all(movie.title != "title" for movie in movies)

    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["rows_seen"] >= 10
    assert diagnostics["valid_rows"] == 10
    assert diagnostics["rows_parsed"] == 10
    assert diagnostics["rows_skipped"] >= 1
    assert any(row.get("reason") == "missing_title" for row in diagnostics["skipped_rows"])


def test_fr_provider_parses_week_2026w02_header_rows_and_keeps_top10():
    year_html = (
        "<html><body><div class='annual-listing'>"
        "<a href='/v9_tophebdo.php?idsem=2926&view=2'>2</a>"
        "</div></body></html>"
    )
    weekly_html = _load_fixture("jpboxoffice_fr_week_2026w02.html")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2926&view=2" in url:
            return _response(url, weekly_html)
        return _response(url, "<html><body></body></html>")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")
    movies = service.fetch_weekend_box_office(2026, 2, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies] == list(range(1, 11))
    assert all(movie.title != "Titre" for movie in movies)
    expected_titles = [
        "La Femme de ménage",
        "Avatar : de feu et de cendres",
        "Le Mage du Kremlin",
        "L'Affaire Bojarski",
        "Zootopie 2",
        "Primate",
        "Hamnet",
        "Le Chant des forêts",
        "Greenland Migration",
        "28 Ans Plus Tard : Le Temple Des Morts",
    ]
    assert [movie.title for movie in movies] == expected_titles

    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["rows_seen"] >= 10
    assert diagnostics["valid_rows"] == 10
    assert diagnostics["rows_parsed"] == 10
    assert diagnostics["skipped_header_rows"] >= 0
    assert diagnostics["candidate_rows"][0]["title"] == "La Femme de ménage"
    assert diagnostics["candidate_rows"][-1]["title"] == "28 Ans Plus Tard : Le Temple Des Morts"
    assert diagnostics["candidate_rows"][-1]["source_href"] == "/fichfilm.php?id=24871&view=2"


def test_fr_provider_ignores_sidebar_artifacts_in_2026w21_fixture():
    year_html = (
        "<html><body><table><tr>"
        "<td><a href='/v9_tophebdo.php?idsem=2926&view=2'>21</a></td>"
        "</tr></table></body></html>"
    )
    weekly_html = _load_fixture("jpboxoffice_fr_week_2026w21.html")

    client = MagicMock()

    def fake_get(url: str):
        if "v9_hebdomadaire.php?view=2&year=2026" in url:
            return _response(url, year_html)
        if "v9_tophebdo.php?idsem=2926&view=2" in url:
            return _response(url, weekly_html)
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(http_client=client, market="fr")
    movies = service.fetch_weekend_box_office(2026, 21, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies] == list(range(1, 11))
    assert all(not movie.title.startswith("N°1 ") for movie in movies)
    diagnostics = getattr(service._provider, "last_parse_diagnostics", {})
    assert diagnostics["rows_seen"] >= 10
    assert diagnostics["rows_parsed"] == 10
    assert diagnostics["rows_skipped"] >= 0
    assert diagnostics["parsed_rows"][0]["rank"] == 1
    assert diagnostics["parsed_rows"][0]["title"] == "Mufasa: Le Roi Lion"


def test_unsupported_jpboxoffice_country_raises_clean_error():
    with pytest.raises(BoxOfficeError) as excinfo:
        create_provider("jpboxoffice", provider_config={"country": "world"})
    assert "not implemented yet" in str(excinfo.value)


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
