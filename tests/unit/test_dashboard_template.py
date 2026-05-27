from pathlib import Path
import re


def _extract_js_ids(content: str) -> set[str]:
    return set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", content))


def _extract_html_ids(content: str) -> set[str]:
    # Match standalone id="..." attributes only; ignore data-*-id and similar attribute names.
    return set(re.findall(r'(?<![-\w])id="([^"]+)"', content))


def test_dashboard_template_contains_cleanup_modal_and_shared_modal_language():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "dashboard.html"
    content = template.read_text(encoding="utf-8")

    required_snippets = [
        "id=\"cleanupModal\"",
        "Preview policy impact",
        "modal-note",
        "modal-grid",
        "modal-section",
        "result-panel",
        "cleanup-results-scroll",
        "result-summary",
        "result-list",
        "boxarr-protected",
        "Execute disabled in this build. Dry-run only.",
        "Review Market Policy Impact",
        "Current add limit:",
        "Current fetch top:",
        "Auto-add:",
        "Preview impact",
        "value=\"{{ market_policy.effective.maximum_movies_to_add|default(auto_add_limit, true) }}\"",
        "id=\"cleanupCurrentLimit\">{{ market_policy.effective.maximum_movies_to_add|default(auto_add_limit, true) }}</span>",
        "id=\"cleanupCurrentFetch\">{{ market_policy.effective.box_office_fetch_limit|default(box_office_limit, true) }}</span>",
        "limitInput.value = value;",
        "class=\"action-btn {% if dangerous_actions_enabled %}cleanup{% else %}secondary{% endif %}\"",
    ]
    for snippet in required_snippets:
        assert snippet in content, f"missing dashboard template snippet: {snippet}"

    assert "Cleanup Boxarr-added movies" not in content

    modal_start = content.index('<div id="cleanupModal"')
    modal_end = content.index('{% endblock %}', modal_start)
    modal_block = content[modal_start:modal_end]
    visible_block, advanced_block = modal_block.split('<details class="advanced-options"', 1)
    assert "Market:</span> <span class=\"value\">{{ market_policy.label }} ({{ market }})</span>" in visible_block
    assert "Default or overridden market policy values" not in visible_block
    for field in [
        'cleanupProtectTag',
        'cleanupConfirmText',
        'cleanupYearFrom',
        'cleanupWeekFrom',
        'cleanupYearTo',
        'cleanupWeekTo',
        'cleanupMarket',
        'cleanupAllStored',
        'cleanupDeleteFiles',
        'cleanupWithoutFilesOnly',
        'cleanupMaxWeeks',
    ]:
        assert field not in visible_block, f"{field} should be hidden behind advanced options"
        assert field in advanced_block, f"{field} should be present in advanced options"
    assert 'Execute disabled in this build' in modal_block
    assert 'Preview impact' in modal_block
    assert 'action-btn secondary' in modal_block
    assert 'cleanup-results-scroll' in content


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
    assert "cleanupExecuteBtnFooter" not in html_ids
    assert "cleanupExecuteBtn" in html_ids
    assert "cleanupResultsScroll" not in html_ids
