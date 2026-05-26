from pathlib import Path
import re


def _extract_js_ids(content: str) -> set[str]:
    return set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", content))


def _extract_html_ids(content: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', content))


def test_weekly_template_contains_policy_wizard_modals():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "weekly.html"
    content = template.read_text(encoding="utf-8")

    required_snippets = [
        "id=\"changePolicyModal\"",
        "id=\"policyImpactModal\"",
        "id=\"backfillModal\"",
        "id=\"cleanupPolicyModal\"",
        "id=\"migrationModal\"",
        "Change Market Policy",
        "Preview Impact",
        "Backfill Missing Adds",
        "Cleanup Outside Policy",
        "Legacy Tag Migration",
        "Canonical tags",
        "Legacy compatibility",
        "{% if not dangerous_actions_enabled %}disabled{% endif %}",
        "id=\"policyCurrentValueFetch\"",
        "id=\"policyCurrentValueAdd\"",
        "id=\"policyCurrentValueAutoAdd\"",
        "id=\"policyCurrentValueTags\"",
        "id=\"policyCurrentValueProtect\"",
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
        "id=\"backfillResult\"",
        "id=\"backfillResultSummary\"",
        "id=\"backfillResultDetails\"",
        "id=\"backfillResultJson\"",
        "id=\"cleanupResult\"",
        "id=\"cleanupResultSummary\"",
        "id=\"cleanupResultDetails\"",
        "id=\"cleanupResultJson\"",
        "id=\"migrationResult\"",
        "id=\"migrationResultSummary\"",
        "id=\"migrationResultDetails\"",
        "id=\"migrationResultJson\"",
    ]
    for snippet in required_snippets:
        assert snippet in content, f"missing weekly template snippet: {snippet}"

    assert "prompt(" not in content


def test_weekly_template_js_ids_are_rendered():
    template = Path(__file__).resolve().parents[2] / "src" / "web" / "templates" / "weekly.html"
    content = template.read_text(encoding="utf-8")

    js_ids = _extract_js_ids(content)
    html_ids = _extract_html_ids(content)

    missing = sorted(js_ids - html_ids)
    unused = sorted(html_ids - js_ids)

    assert not missing, f"weekly template JS references missing ids: {missing}"
    # Informational only: unused ids are expected for modal containers and anchors.
    assert "policyCurrentValueTags" in html_ids
    assert "backfillResult" in html_ids
    assert "cleanupResult" in html_ids
    assert "migrationResult" in html_ids
    assert "policyImpactModal" in html_ids
    assert unused  # keep the report meaningful; unused IDs are normal here
