from pathlib import Path
import re


def _extract_js_ids(content: str) -> set[str]:
    return set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", content))


def _extract_html_ids(content: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', content))


def test_dashboard_template_contains_cleanup_modal_and_shared_modal_language():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "dashboard.html"
    content = template.read_text(encoding="utf-8")

    required_snippets = [
        "id=\"cleanupModal\"",
        "modal-note",
        "modal-grid",
        "modal-section",
        "result-panel",
        "result-summary",
        "result-list",
        "boxarr-protected",
        "Execute disabled in this build. Dry-run only.",
    ]
    for snippet in required_snippets:
        assert snippet in content, f"missing dashboard template snippet: {snippet}"


def test_dashboard_template_js_ids_are_rendered():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "dashboard.html"
    content = template.read_text(encoding="utf-8")

    js_ids = _extract_js_ids(content)
    html_ids = _extract_html_ids(content)

    missing = sorted(js_ids - html_ids)

    assert not missing, f"dashboard template JS references missing ids: {missing}"
    assert "cleanupModal" in html_ids
    assert "cleanupResults" in html_ids
    assert "progressModal" in html_ids
    assert "summaryModal" in html_ids
