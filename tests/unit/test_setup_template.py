from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _render_setup_template(**context) -> str:
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "src" / "web" / "templates")),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    )
    env.filters["tojson"] = lambda value: __import__("json").dumps(value)
    template = env.get_template("setup.html")
    return template.render(**context)


def test_setup_template_renders_with_raw_market_preview_without_definition():
    request = SimpleNamespace(scope={"root_path": ""}, path="/setup")

    html = _render_setup_template(
        request=request,
        version="test",
        theme="light",
        market="us",
        provider="mojo",
        configured_markets={
            "us": {"label": "US Box Office", "provider": "mojo"},
            "fr": {"label": "France Box Office", "provider": "jpboxoffice"},
        },
        market_definition={
            "market": "us",
            "label": "US Box Office",
            "provider": "mojo",
            "provider_config": {"area": "us"},
            "enabled": True,
        },
        market_previews={
            "us": {
                "effective": {
                    "box_office_fetch_limit": 10,
                    "maximum_movies_to_add": 3,
                    "auto_add_enabled": True,
                    "tags": ["boxarr", "boxarr-us"],
                    "cleanup_protect_tag": "boxarr-protected",
                },
                "sources": {
                    "box_office_fetch_limit": "global",
                    "maximum_movies_to_add": "market",
                    "auto_add_enabled": "global",
                    "tags": "market",
                    "cleanup_protect_tag": "global",
                },
                "tag_policy": {},
            }
        },
        radarr_configured=False,
        is_configured=False,
        radarr_url="http://localhost:7878",
        radarr_api_key="",
        root_folder="/movies",
        quality_profile_default="HD-1080p",
        quality_profile_upgrade="",
        radarr_minimum_availability_enabled=False,
        radarr_minimum_availability="announced",
        root_folder_mapping_enabled=False,
        root_folder_mappings=[],
        scheduler_enabled=False,
        scheduler_cron="0 23 * * 2",
        scheduler_day=2,
        scheduler_time=23,
        auto_add=True,
        quality_upgrade=False,
        box_office_limit=10,
        auto_tag_enabled=False,
        auto_tag_text="boxarr",
        auto_add_limit=3,
        genre_filter_enabled=False,
        genre_filter_mode="whitelist",
        genre_whitelist=[],
        genre_blacklist=[],
        rating_filter_enabled=False,
        rating_whitelist=[],
        ignore_rereleases=False,
        language_filter_enabled=False,
        language_filter_mode="whitelist",
        language_whitelist=[],
        language_blacklist=[],
        url_base="",
        dangerous_actions_enabled=False,
    )

    assert "Market Settings Preview" in html
    assert "US Box Office" in html
    assert "Canonical:" in html
    assert "Legacy compat:" in html
    assert "boxarr-added" in html
    assert "boxarr-protected" in html
