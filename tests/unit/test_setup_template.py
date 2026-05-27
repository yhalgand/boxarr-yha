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
                "definition": {
                    "market": "us",
                    "label": "US Box Office",
                    "provider": "mojo",
                    "provider_config": {"area": "us"},
                    "enabled": True,
                    "configured": False,
                },
                "effective": {
                    "box_office_fetch_limit": 10,
                    "maximum_movies_to_add": 3,
                    "auto_add_enabled": True,
                    "tags": ["boxarr", "boxarr-us"],
                    "cleanup_protect_tag": "boxarr-protected",
                    "root_folder": "/movies",
                    "quality_profile_default": "HD-1080p",
                    "language_filter_enabled": True,
                    "language_filter_mode": "whitelist",
                    "language_whitelist": ["English"],
                },
                "sources": {
                    "box_office_fetch_limit": "global",
                    "maximum_movies_to_add": "market",
                    "auto_add_enabled": "global",
                    "tags": "market",
                    "cleanup_protect_tag": "global",
                    "root_folder": "global",
                    "quality_profile_default": "global",
                    "language_filter_enabled": "global",
                },
                "tag_policy": {},
            },
            "fr": {
                "definition": {
                    "market": "fr",
                    "label": "France Box Office",
                    "provider": "jpboxoffice",
                    "provider_config": {"country": "fr"},
                    "enabled": True,
                    "configured": True,
                },
                "effective": {
                    "box_office_fetch_limit": 10,
                    "maximum_movies_to_add": 5,
                    "auto_add_enabled": True,
                    "tags": ["boxarr", "boxarr-fr"],
                    "cleanup_protect_tag": "boxarr-protected",
                    "root_folder": "/movies/fr",
                    "quality_profile_default": "HD-1080p",
                    "language_filter_enabled": False,
                },
                "sources": {
                    "box_office_fetch_limit": "global",
                    "maximum_movies_to_add": "market",
                    "auto_add_enabled": "global",
                    "tags": "market",
                    "cleanup_protect_tag": "global",
                    "root_folder": "market",
                    "quality_profile_default": "global",
                    "language_filter_enabled": "global",
                },
                "tag_policy": {
                    "added_tag": "boxarr-added",
                    "market_tag": "boxarr-market-fr",
                    "existing_tag": "boxarr-existing-fr",
                    "protected_tag": "boxarr-protected",
                    "legacy_tags": ["boxarr", "boxarr-keep"],
                },
            },
        },
        jpboxoffice_countries={
            "fr": {"label": "France"},
            "de": {"label": "Germany / Allemagne"},
            "br": {"label": "Brazil / Brésil"},
            "cn": {"label": "China / Chine"},
            "kr": {"label": "South Korea / Corée du Sud"},
            "es": {"label": "Spain / Espagne"},
            "it": {"label": "Italy / Italie"},
            "ru": {"label": "Russia / Russie"},
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

    assert "Global Settings" in html
    assert "Markets" in html
    assert "Maintenance / Migration" in html
    assert "Global Radarr Connection" in html
    assert "Global Radarr Defaults" in html
    assert "Global Automation Defaults" in html
    assert "Global UI Settings" in html
    assert "Global Advanced Settings" in html
    assert "US Box Office (us)" in html
    assert "France Box Office (fr)" in html
    assert "Canonical:" in html
    assert "Legacy compat:" in html
    assert "boxarr-added" in html
    assert "boxarr-protected" in html
    assert "boxarr-keep" in html
    assert 'option value="de"' in html
    assert 'option value="fr"' in html
    assert 'option value="ru"' in html
    assert 'option value="world"' not in html
    assert "Language filter uses TMDB original language" in html
    assert "Preview legacy tag migration" in html
    assert "Edit overrides" in html
    assert html.count("Edit overrides") >= 2
    assert "Root folder override" in html
    assert "Quality profile default override" in html
    assert "inherit global" in html
    assert "<h2 class=\"section-title\">Market Overrides</h2>" not in html
    assert "Market Overrides" not in html
    assert "source-pill" in html
    assert "selected" in html


def test_setup_template_renders_legacy_migration_execute_only_when_enabled():
    request = SimpleNamespace(scope={"root_path": ""}, path="/setup")
    common_context = dict(
        request=request,
        version="test",
        theme="light",
        market="us",
        provider="mojo",
        configured_markets={"us": {"label": "US Box Office", "provider": "mojo"}},
        market_definition={
            "market": "us",
            "label": "US Box Office",
            "provider": "mojo",
            "provider_config": {"area": "us"},
            "enabled": True,
        },
        market_previews={
            "us": {
                "definition": {
                    "market": "us",
                    "label": "US Box Office",
                    "provider": "mojo",
                    "provider_config": {"area": "us"},
                    "enabled": True,
                    "configured": False,
                },
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
                "tag_policy": {
                    "added_tag": "boxarr-added",
                    "market_tag": "boxarr-market-us",
                    "existing_tag": "boxarr-existing-us",
                    "protected_tag": "boxarr-protected",
                    "legacy_tags": ["boxarr", "boxarr-keep"],
                },
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
        jpboxoffice_countries={
            "fr": {"label": "France"},
            "de": {"label": "Germany / Allemagne"},
        },
    )

    html_disabled = _render_setup_template(
        **common_context,
        dangerous_actions_enabled=False,
    )
    html_enabled = _render_setup_template(
        **common_context,
        dangerous_actions_enabled=True,
    )

    assert "Execute migration disabled" in html_disabled
    assert "title=\"Execute migration disabled in this build." in html_disabled
    assert "class=\"btn btn-secondary\" disabled" in html_disabled
    assert "runLegacyMigrationExecute()" not in html_disabled
    assert "Execute migration" in html_enabled
    assert "class=\"btn btn-primary\" onclick=\"runLegacyMigrationExecute()\"" in html_enabled
    assert "runLegacyMigrationExecute()" in html_enabled
    assert "boxarr-added" in html_enabled
    assert "boxarr-protected" in html_enabled
