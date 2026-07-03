from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/source-maintenance-report.yml")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_source_maintenance_workflow_is_read_only_scheduled_and_manual():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow_triggers(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    # WP35.5: twice weekly (Wed + Sun).
    assert [entry["cron"] for entry in triggers["schedule"]] == ["29 5 * * 3", "29 5 * * 0"]


def test_source_maintenance_workflow_runs_full_non_mutating_pipeline():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.openva.source_health build --output source-health-report.json" in text
    assert "python -m tools.openva.source_verification verify" in text
    assert "python -m tools.openva.source_discovery discover" in text
    assert "python -m tools.openva.source_repair_sweep build" in text
    assert "python -m tools.openva.source_repair_batch build" in text
    assert "python -m tools.openva.source_review_triage build" in text
    assert "python -m tools.openva.source_review_decisions build-sheet" in text
    assert "python -m tools.openva.promotion_planner plan" in text
    assert "python -m tools.openva.cleanup_proposals build" in text
    assert "--verification-report source-verification-report.json" in text
    assert "--discovery-report source-discovery-report.json" in text
    assert "--source-verification-report source-verification-report.json" in text
    assert "--source-discovery-report source-discovery-report.json" in text
    assert "summary.md" in text
    assert "source-health.csv" in text
    assert "source-verification.csv" in text
    assert "source-discovery-candidates.csv" in text
    assert "source-discovery-unavailable.csv" in text
    assert "source-repair-sweep-report.json" in text
    assert "source-repair-sweep-strict-candidates.csv" in text
    assert "source-repair-sweep-human-review.csv" in text
    assert "source-repair-sweep-no-replacement.csv" in text
    assert "source-repair-batch-plan.json" in text
    assert "source-repair-batch-plan.csv" in text
    assert "source-repair-batch-summary.md" in text
    assert "source-review-triage-plan.json" in text
    assert "source-review-triage-plan.csv" in text
    assert "source-review-triage-summary.md" in text
    assert "source-review-decision-sheet.csv" in text
    assert "source-review-decision-sheet-summary.md" in text
    assert "promotion-plan-actions.csv" in text
    assert "cleanup-proposal.md" in text
    assert "actions/upload-artifact@v6" in text
    assert "source_repair_actions apply" not in text
    assert "gh pr create" not in text
    assert "--write" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "peter-evans/create-pull-request" not in text


def test_source_maintenance_bounds_optional_discovery_and_uses_defaults():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Build candidate source discovery report")
    end = text.index("- name: Build source repair sweep report")
    block = text[start:end]

    assert 'VENDOR_LIMIT="10"' in block
    assert 'MAX_URLS_PER_TYPE="4"' in block
    assert 'FETCH_TIMEOUT="3"' in block
    assert 'DISCOVERY_DEADLINE="15m"' in block
    assert 'timeout --signal=TERM --kill-after=30s "$DISCOVERY_DEADLINE" \\' in block
    assert '--vendor-limit "$VENDOR_LIMIT" \\' in block
    assert '--max-urls-per-type "$MAX_URLS_PER_TYPE" \\' in block
    assert '--fetch-timeout "$FETCH_TIMEOUT" \\' in block
    assert "vendor_limit must be a positive integer" in block
    assert "max_urls_per_type must be a positive integer" in block
    assert "fetch_timeout must be a positive number" in block


def test_source_maintenance_timeout_degrades_only_explicit_timeout():
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Build candidate source discovery report")
    end = text.index("- name: Build source repair sweep report")
    block = text[start:end]

    assert 'if [ "$STATUS" -eq 124 ]; then' in block
    assert "::warning::candidate source discovery reached" in block
    assert '"partial": True' in block
    assert '"degraded": True' in block
    assert '"reason": "discovery_timeout"' in block
    assert '"network_fetch_performed": True' in block
    assert '"candidate_sources_written_or_reported": 0' in block
    assert '"unavailable_sources_written_or_reported": 0' in block
    assert '"vendors": []' in block
    assert 'elif [ "$STATUS" -ne 0 ]; then' in block
    assert 'exit "$STATUS"' in block


def test_source_maintenance_uploads_observation_continuity_before_optional_enrichment():
    text = WORKFLOW.read_text(encoding="utf-8")

    build = text.index("- name: Build observation ledger v2 reports (read-only artifacts)")
    upload = text.index("- name: Upload observation continuity artifacts")
    discovery = text.index("- name: Build candidate source discovery report")

    assert build < upload < discovery
    upload_block = text[upload:discovery]
    assert "name: openva-source-maintenance-observation-continuity" in upload_block
    assert "observation-ledger/observation-ledger-delta.ndjson" in upload_block
    assert "observation-ledger/latest-observations.json" in upload_block
    assert "source-verification-report.json" in upload_block
    assert "source-observation-ledger-summary.md" in upload_block
    assert "latest-source-health.json" in upload_block
    assert "public/source-health-snapshot.json" in upload_block
