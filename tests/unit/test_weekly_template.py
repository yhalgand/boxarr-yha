from pathlib import Path
import re


def _extract_js_ids(content: str) -> set[str]:
    return set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", content))


def _extract_html_ids(content: str) -> set[str]:
    # Match standalone id="..." attributes only; ignore data-*-id and other composites.
    return set(re.findall(r'(?<![-\w])id="([^"]+)"', content))


def test_weekly_template_contains_policy_wizard_modals():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "weekly.html"
    content = template.read_text(encoding="utf-8")

    required_snippets = [
        "id=\"changePolicyModal\"",
        "id=\"policyImpactModal\"",
        "id=\"policyImpactResultTitle\"",
        "id=\"backfillModal\"",
        "id=\"cleanupPolicyModal\"",
        "id=\"migrationModal\"",
        "Change Market Policy",
        "Preview Impact",
        "Backfill Missing Adds",
        "Review Market Policy Impact",
        "Legacy Tag Migration",
        "Canonical tags",
        "Legacy compat:",
        "title=\\\"Execute disabled in this build\\\"",
        "id=\"policyCurrentValueAdd\"",
        "id=\"policyFetchLimit\"",
        "id=\"policyAddLimit\"",
        "id=\"policyAutoAdd\"",
        "id=\"policyTags\"",
        "id=\"policyAutoTagText\"",
        "id=\"policyProtectTag\"",
        "id=\"policyScopeFuture\"",
        "id=\"policyScopeCurrent\"",
        "id=\"policyScopeRange\"",
        "id=\"policyScopeAll\"",
        "id=\"policyYearFrom\"",
        "id=\"policyWeekFrom\"",
        "id=\"policyYearTo\"",
        "id=\"policyWeekTo\"",
        "id=\"cleanupWithoutFilesOnly\"",
        "id=\"backfillResult\"",
        "id=\"backfillResultSummary\"",
        "id=\"backfillResultDetails\"",
        "id=\"backfillResultJson\"",
        "id=\"backfillCurrentLimit\"",
        "id=\"cleanupResult\"",
        "id=\"cleanupResultSummary\"",
        "id=\"cleanupResultDetails\"",
        "id=\"cleanupResultJson\"",
        "id=\"migrationResult\"",
        "id=\"migrationResultSummary\"",
        "id=\"migrationResultDetails\"",
        "id=\"migrationResultJson\"",
        "Manage policy",
        "Preview impact",
        "Preview Legacy Tag Migration",
        "id=\"policyCurrentValueFetch\"",
        "id=\"policyCurrentValueAutoAdd\"",
        "id=\"policyCurrentValueProtect\"",
        "id=\"policyCanonicalTags\"",
        "id=\"policyLegacyTags\"",
        "max-height: 85vh",
        "class=\"modal-section result-panel\"",
        "class=\"result-scroll\"",
        "id=\"cleanupCurrentLimit\">{{ market_policy.effective.maximum_movies_to_add|default(auto_add_limit, true) }}</span>",
        "id=\"cleanupCurrentFetch\">{{ market_policy.effective.box_office_fetch_limit|default(box_office_limit, true) }}</span>",
        "value=\"{{ market_policy.effective.maximum_movies_to_add|default(auto_add_limit, true) }}\"",
        "getRequiredElement('cleanupTargetLimit').value = current.maximum_movies_to_add ?? '';",
        "getRequiredElement('backfillCurrentLimit').textContent = formatValue(current.maximum_movies_to_add);",
        "getRequiredElement('policyScopeCurrent').checked = true;",
        "backfill-add/dry-run",
        "cleanup/dry-run",
        "No policy change",
        "would_add_count_total",
        "skipped_count_total",
    ]
    for snippet in required_snippets:
        assert snippet in content, f"missing weekly template snippet: {snippet}"

    assert "prompt(" not in content
    assert content.count("Advanced options") >= 3
    assert "Cleanup Boxarr-added movies" not in content
    assert 'value="{{ market_policy.effective.maximum_movies_to_add|default(auto_add_limit, true) }}"' in content
    assert 'class="action-btn {% if dangerous_actions_enabled %}cleanup{% else %}secondary{% endif %}"' in content
    assert 'title="Execute disabled in this build"' in content or 'title=\\"Execute disabled in this build\\"' in content

    cleanup_block_start = content.index("<!-- Cleanup / Policy Impact Modal -->")
    cleanup_block_end = content.index("<!-- Legacy Tag Migration Modal -->")
    cleanup_block = content[cleanup_block_start:cleanup_block_end]
    visible_cleanup_block, advanced_cleanup_block = cleanup_block.split('<details class="advanced-options">', 1)
    assert "for=\"cleanupProtectTag\"" not in visible_cleanup_block
    assert "for=\"cleanupConfirmText\"" not in visible_cleanup_block
    assert "for=\"cleanupYearFrom\"" not in visible_cleanup_block
    assert "for=\"cleanupWeekFrom\"" not in visible_cleanup_block
    assert "for=\"cleanupDeleteFiles\"" not in visible_cleanup_block
    assert "for=\"cleanupAllStored\"" not in visible_cleanup_block
    assert "for=\"cleanupMarket\"" not in visible_cleanup_block
    assert "for=\"cleanupMaxWeeks\"" not in visible_cleanup_block
    assert "for=\"cleanupWithoutFilesOnly\"" not in visible_cleanup_block
    assert "for=\"cleanupProtectTag\"" in advanced_cleanup_block
    assert "for=\"cleanupConfirmText\"" in advanced_cleanup_block
    assert "for=\"cleanupYearFrom\"" in advanced_cleanup_block
    assert "for=\"cleanupWeekFrom\"" in advanced_cleanup_block
    assert "cleanupWithoutFilesOnly" in advanced_cleanup_block
    assert "Current add limit:" in visible_cleanup_block
    assert "Current fetch top:" in visible_cleanup_block
    assert "Auto-add:" in visible_cleanup_block
    assert "Market:</span> <span class=\"value\">{{ market_policy.label }} ({{ market }})</span>" in visible_cleanup_block
    assert "Cleanup Boxarr-added movies" not in visible_cleanup_block
    assert "class=\"action-btn {% if dangerous_actions_enabled %}primary{% else %}secondary{% endif %}\"" in content
    assert "id=\"migrationExecuteBtn\" class=\"action-btn {% if dangerous_actions_enabled %}primary{% else %}secondary{% endif %}\"" in content


def test_weekly_template_js_ids_are_rendered():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "weekly.html"
    content = template.read_text(encoding="utf-8")

    js_ids = _extract_js_ids(content)
    html_ids = _extract_html_ids(content)

    missing = sorted(js_ids - html_ids)
    unused = sorted(html_ids - js_ids)

    assert not missing, f"weekly template JS references missing ids: {missing}"
    # Informational only: unused ids are expected for modal containers and anchors.
    assert "backfillResult" in html_ids
    assert "cleanupResult" in html_ids
    assert "migrationResult" in html_ids
    assert "policyImpactModal" in html_ids
    assert "policyCanonicalTags" in html_ids
    assert "policyLegacyTags" in html_ids
    assert "cleanupResultDetails" in html_ids
    assert "cleanupResultJson" in html_ids
    assert unused  # keep the report meaningful; unused IDs are normal here
