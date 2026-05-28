from pathlib import Path


def test_active_write_defaults_do_not_use_legacy_boxarr():
    root = Path(__file__).resolve().parents[2]
    active_files = {
        "src/utils/config.py": [
            'boxarr_features_auto_tag_text: str = "boxarr"',
        ],
        "src/api/routes/config.py": [
            'boxarr_features_auto_tag_text: str = "boxarr"',
        ],
        "src/core/market_admin.py": [
            'auto_tag_text = "boxarr"',
            'tags = ["boxarr"',
        ],
        "src/web/static/js/app.js": [
            "|| 'boxarr'",
            '|| "boxarr"',
        ],
        "src/web/templates/setup.html": [
            'placeholder="boxarr"',
            "or 'boxarr'",
        ],
        "src/web/templates/weekly.html": [
            'placeholder="boxarr"',
            "or 'boxarr'",
        ],
    }

    for relative_path, prohibited_snippets in active_files.items():
        content = (root / relative_path).read_text()
        for snippet in prohibited_snippets:
            assert snippet not in content, f"{relative_path} still uses legacy active default: {snippet}"

    # Sanity-check that the canonical defaults are present in the active write paths.
    for relative_path in [
        "src/utils/config.py",
        "src/api/routes/config.py",
        "src/core/market_admin.py",
        "src/core/market_settings.py",
        "src/web/static/js/app.js",
        "src/web/templates/setup.html",
        "src/web/templates/weekly.html",
    ]:
        content = (root / relative_path).read_text()
        assert "boxarr-added" in content, f"{relative_path} should use canonical boxarr-added defaults"
