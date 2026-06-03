"""Tests for the AlloCiné France provider and France fallback wrapper."""

from unittest.mock import MagicMock

import httpx
import pytest

import src.core.boxoffice as core_boxoffice
from src.core.boxoffice import BoxOfficeError, BoxOfficeService, create_provider


def _response(url: str, html: str, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status_code, request=request, content=html.encode("utf-8"))


def _allocine_html(date_label: str = "mercredi 1 mai 2024", count: int = 10) -> str:
    rows = []
    for rank in range(1, count + 1):
        title = "Un p'tit truc en plus" if rank == 1 else f"Film AlloCiné {rank}"
        allocine_id = 300000 + rank
        entries = 1_131_341 if rank == 1 else 100_000 + rank
        total = entries * 2
        rows.append(
            f"""
            <tr>
              <td>{rank}</td>
              <td><a href="/film/fichefilm_gen_cfilm={allocine_id}.html">{title}</a></td>
              <td>{entries:,}</td>
              <td>{total:,}</td>
            </tr>
            """.replace(",", " ")
        )
    return f"""
    <html>
      <head><title>Box Office Cinéma - Semaine du {date_label}</title></head>
      <body>
        <h1>Box Office Cinéma - Semaine du {date_label}</h1>
        <table><tbody>{''.join(rows)}</tbody></table>
      </body>
    </html>
    """


def _jpboxoffice_html() -> str:
    rows = []
    for rank in range(1, 11):
        rows.append(
            f"""
            <div class="movie-block">
              <div>{rank}</div>
              <div>Image</div>
              <a href="/fichfilm.php?id=2943{rank:02d}&view=2">JP Fallback {rank}</a>
              <div>JP Fallback {rank} Original</div>
              <div>(Studio)</div>
              <div>France / Genre / 2h00 1 000 000 100 2 000 000</div>
            </div>
            """
        )
    return (
        "<html><head><title>DU 20 Mai AU 26 Mai 2026</title></head>"
        f"<body>{''.join(rows)}</body></html>"
    )


def test_allocine_provider_parses_top10_for_fr_week():
    client = MagicMock()

    def fake_get(url: str):
        assert url == "https://www.allocine.fr/boxoffice/france/sem-2024-05-01/"
        return _response(url, _allocine_html())

    client.get.side_effect = fake_get
    client.close = MagicMock()

    provider = create_provider("allocine", http_client=client)
    movies = provider.fetch_weekend_box_office(2024, 18, limit=10)

    assert len(movies) == 10
    assert [movie.rank for movie in movies] == list(range(1, 11))
    assert movies[0].title == "Un p'tit truc en plus"
    assert movies[0].weekend_gross == 1_131_341
    assert movies[0].source_url.endswith("/sem-2024-05-01/")
    assert movies[0].identity_metadata["source_provider"] == "allocine"
    assert movies[0].identity_metadata["allocine_movie_id"] == 300001
    assert movies[0].identity_metadata["source_week_start_date"] == "2024-05-01"
    assert movies[0].identity_metadata["source_week_end_date"] == "2024-05-07"


def test_allocine_provider_rejects_empty_or_partial_pages():
    client = MagicMock()

    def fake_get(url: str):
        return _response(url, _allocine_html(count=1))

    client.get.side_effect = fake_get
    client.close = MagicMock()

    provider = create_provider("allocine", http_client=client)

    with pytest.raises(BoxOfficeError) as excinfo:
        provider.fetch_weekend_box_office(2024, 18, limit=10)

    assert "insufficient ranking rows" in str(excinfo.value)
    assert "rows_parsed=1" in str(excinfo.value)


def test_allocine_provider_rejects_wrong_page_date():
    client = MagicMock()

    def fake_get(url: str):
        return _response(url, _allocine_html(date_label="vendredi 29 mars 2002"))

    client.get.side_effect = fake_get
    client.close = MagicMock()

    provider = create_provider("allocine", http_client=client)

    with pytest.raises(BoxOfficeError) as excinfo:
        provider.fetch_weekend_box_office(2002, 13, limit=10)

    assert "explicit week mismatch" in str(excinfo.value)


def test_france_boxoffice_provider_uses_allocine_before_jpboxoffice():
    client = MagicMock()
    requested_urls = []

    def fake_get(url: str):
        requested_urls.append(url)
        if "allocine.fr/boxoffice/france/sem-2024-05-01" in url:
            return _response(url, _allocine_html())
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="france_boxoffice",
        provider_config={"country": "fr"},
    )
    movies = service.fetch_weekend_box_office(2024, 18, limit=10)

    assert len(movies) == 10
    assert movies[0].identity_metadata["source_provider"] == "allocine"
    assert not any("jpbox-office.com" in url for url in requested_urls)


def test_france_boxoffice_provider_falls_back_to_jpboxoffice_on_allocine_failure():
    client = MagicMock()
    requested_urls = []

    def fake_get(url: str):
        requested_urls.append(url)
        if "allocine.fr" in url:
            return _response(url, _allocine_html(count=1))
        if "jpbox-office.com/v9_tophebdo.php?idsem=2943&view=2" in url:
            return _response(url, _jpboxoffice_html())
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="france_boxoffice",
        provider_config={"country": "fr"},
    )
    movies = service.fetch_weekend_box_office(2026, 21, limit=10)

    assert len(movies) == 10
    assert movies[0].title == "JP Fallback 1"
    assert any("allocine.fr" in url for url in requested_urls)
    assert any("jpbox-office.com" in url for url in requested_urls)


def test_france_boxoffice_current_uses_latest_completed_week_with_allocine_first(monkeypatch):
    class FixedDateTime(core_boxoffice.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 3, 12, 0, 0, tzinfo=tz)

    client = MagicMock()
    requested_urls = []

    def fake_get(url: str):
        requested_urls.append(url)
        if "allocine.fr/boxoffice/france/sem-2026-05-20" in url:
            return _response(url, _allocine_html(date_label="mercredi 20 mai 2026"))
        raise AssertionError(f"Unexpected URL: {url}")

    client.get.side_effect = fake_get
    client.close = MagicMock()
    monkeypatch.setattr(core_boxoffice, "datetime", FixedDateTime)

    service = BoxOfficeService(
        http_client=client,
        market="fr",
        provider="france_boxoffice",
        provider_config={"country": "fr"},
    )
    movies = service.get_current_week_movies(limit=10)

    assert len(movies) == 10
    assert movies[0].source_url == "https://www.allocine.fr/boxoffice/france/sem-2026-05-20/"
    assert movies[0].allocine_movie_id == 300001
    assert service._provider.last_provider_used == "allocine"
    assert any("allocine.fr" in url for url in requested_urls)
    assert not any("jpbox-office.com" in url for url in requested_urls)
