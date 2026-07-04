from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.openva.discovery_ledger import append_events
from tools.openva.machine_decisions import append_decisions, load_decisions
from tools.openva.observation_automerge import (
    AUTOMERGE_OBSERVATION_LABEL,
    LATEST_INDEX_PATH,
    OBSERVATION_LEDGER_LABEL,
    check_observation_automerge,
    latest_index_regressions,
    plan_new_rows,
)
from tools.openva.observation_ledger import DOCTRINE
from tools.openva.source_quarantine import quarantine_eligibility

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "operations" / "contracts" / "work-package-scope.yaml"
AGENT_AUTOMERGE = ROOT / ".github" / "workflows" / "agent-automerge.yml"


def work_packages() -> dict[str, dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["work_packages"]


def workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def job_step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def test_operational_data_work_packages_are_narrow_and_separate() -> None:
    packages = work_packages()
    assert packages["WP-DISCOVERY-LEDGER-APPEND-01"]["allowed_paths"] == [
        "maintenance/discovery-events/*.ndjson"
    ]
    assert packages["WP-SOURCE-OBSERVATION-LEDGER-APPEND-01"]["allowed_paths"] == [
        "maintenance/source-observations/events/*.ndjson",
        "maintenance/source-observations/latest-observations.json",
    ]
    assert packages["WP-SOURCE-QUARANTINE-01"]["allowed_paths"] == [
        "data/vendors/*/sources/*.yaml",
        "dist/vendors/*.json",
        "indexes/sources.json",
        "maintenance/machine-decisions/*.ndjson",
    ]


def test_operational_control_plane_cannot_write_operational_data_or_scope_policy() -> None:
    allowed = set(work_packages()["WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01"]["allowed_paths"])
    rejected = {
        "maintenance/discovery-events/*.ndjson",
        "maintenance/source-observations/events/*.ndjson",
        "maintenance/source-observations/latest-observations.json",
        "data/vendors/*/sources/*.yaml",
        "indexes/sources.json",
        "maintenance/machine-decisions/*.ndjson",
        "docs/operations/contracts/work-package-scope.yaml",
        "tools/openva/pr_scope_guard.py",
        "schemas/openva/*",
    }
    assert allowed.isdisjoint(rejected)


def test_generated_operational_pr_bodies_declare_the_registered_work_packages_once() -> None:
    discovery = (ROOT / ".github" / "workflows" / "discovery-ledger-append-pr.yml").read_text(encoding="utf-8")
    observation = (ROOT / ".github" / "workflows" / "observation-ledger-append-pr.yml").read_text(encoding="utf-8")
    candidate = (ROOT / ".github" / "workflows" / "candidate-promotion-pr.yml").read_text(encoding="utf-8")

    assert discovery.count("Work-Package: WP-DISCOVERY-LEDGER-APPEND-01") == 1
    assert observation.count("Work-Package: WP-SOURCE-OBSERVATION-LEDGER-APPEND-01") == 1
    assert candidate.count("Work-Package: WP-SOURCE-QUARANTINE-01") == 1


def test_discovery_append_workflow_provisions_labels_before_application() -> None:
    text = (ROOT / ".github" / "workflows" / "discovery-ledger-append-pr.yml").read_text(encoding="utf-8")

    discovery_label = text.index('gh label create "discovery-ledger"')
    automerge_label = text.index('gh label create "automerge:observation"')
    apply = text.index('gh pr edit "$PR_NUMBER" --add-label "discovery-ledger" --add-label "automerge:observation"')

    assert discovery_label < apply
    assert automerge_label < apply
    assert "--force" in text[discovery_label:apply]
    assert "Autonomous append-only discovery ledger update" in text[discovery_label:apply]
    assert "Eligible for the bounded observation/discovery automerge lane" in text[automerge_label:apply]
    assert "maintenance/discovery-events/*.ndjson" in text


def test_agent_automerge_has_discovery_ledger_consumer_with_distinct_label_gate() -> None:
    jobs = workflow(AGENT_AUTOMERGE)["jobs"]

    assert "discovery-ledger" in jobs
    condition = jobs["discovery-ledger"]["if"]
    observation_condition = jobs["observation-ledger"]["if"]
    assert "discovery-ledger" in condition
    assert "automerge:observation" in condition
    assert "observation-ledger" in observation_condition
    assert "discovery-ledger" not in observation_condition
    assert "!contains(join(github.event.pull_request.labels.*.name, ','), 'observation-ledger')" in condition
    for unrelated in (
        "quarantine",
        "candidate-intake",
        "catalog-growth",
        "machine-canonical",
        "machine-provisional",
    ):
        assert f"'%s'" % unrelated in condition


def test_agent_automerge_discovery_ledger_gates_before_native_automerge() -> None:
    steps = workflow(AGENT_AUTOMERGE)["jobs"]["discovery-ledger"]["steps"]
    names = [step.get("name") for step in steps]
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout"))
    collect = job_step(steps, "Collect changed paths")
    check = job_step(steps, "Check discovery-ledger automerge eligibility")
    tests = job_step(steps, "Run discovery ledger tests")
    merge = job_step(steps, "Enable GitHub native auto-merge")

    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"
    assert "git fetch origin ${{ github.event.pull_request.base.sha }}" in "\n".join(
        str(step.get("run", "")) for step in steps
    )
    assert 'gh pr diff "$PR_NUMBER" --name-only > changed-files.txt' in collect["run"]
    assert "python -m tools.openva.discovery_ledger check" in check["run"]
    assert "--paths-file changed-files.txt" in check["run"]
    assert "--base-ref ${{ github.event.pull_request.base.sha }}" in check["run"]
    assert "--head-ref HEAD" in check["run"]
    assert "tests/test_discovery_ledger.py" in tests["run"]
    assert "tests/test_operational_pr_scope.py" in tests["run"]
    assert "tests/test_wp41_workflows.py" in tests["run"]
    assert 'gh pr merge "$PR_NUMBER" --auto --squash --delete-branch' in merge["run"]

    for required in (
        "Fetch base commit",
        "Collect changed paths",
        "Check discovery-ledger automerge eligibility",
        "Run source-intelligence release gate (pr profile)",
        "Run discovery ledger tests",
    ):
        assert names.index(required) < names.index("Enable GitHub native auto-merge")


def discovery_event(event_id: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "discovery_event_id": event_id,
        "candidate_id": "vendor-security-abc123",
        "origin": "source_discovery",
        "candidate_url": "https://example.com/security",
        "evidence_digest": "sha256:" + "a" * 64,
        "classification": "strong_same_authority_canonical_url",
        "reason_codes": ["strong_same_authority_canonical_url"],
        "discovery_run_id": "vendor-2026-07-01T00:00:00Z",
        "policy_version": "source_discovery_registry_0.2.0",
        "discovered_at": "2026-07-01T00:00:00Z",
        "not_advice": True,
    }


def test_discovery_ledger_refuses_an_event_id_already_committed(tmp_path: Path) -> None:
    ledger = tmp_path / "discovery"
    event = discovery_event("a" * 32)
    append_events([event], ledger)
    with pytest.raises(ValueError, match="duplicate_existing_event_id"):
        append_events([event], ledger)


def test_observation_plan_suppresses_an_already_committed_record_id(tmp_path: Path) -> None:
    ledger = tmp_path / "events"
    ledger.mkdir()
    existing = {
        "ledger_record_id": "observation-record-1",
        "source_id": "vendor-security",
        "observed_at": "2026-07-01T00:00:00Z",
    }
    (ledger / "2026-07.ndjson").write_text(json.dumps(existing) + "\n", encoding="utf-8")
    new_rows, reasons = plan_new_rows([existing], ledger)
    assert new_rows == []
    assert reasons == []


def latest_index(observed_at: str, *, include_source: bool = True) -> dict:
    sources = []
    if include_source:
        sources.append(
            {
                "source_id": "vendor-security",
                "vendor_id": "vendor",
                "source_url": "https://example.com/security",
                "observed_at": observed_at,
                "observation_id": "observation-1",
                "source_health_status": "reachable",
                "change_class": "none",
                "carried_forward": False,
            }
        )
    return {
        "schema_version": "0.1.0",
        "report_type": "latest_observations_index",
        "generated_at": observed_at,
        "doctrine": DOCTRINE,
        "summary": {
            "source_count": len(sources),
            "observed_this_run": len(sources),
            "carried_forward": 0,
        },
        "sources": sources,
        "not_advice": True,
    }


def test_latest_index_rejects_regression_and_source_drop() -> None:
    committed = latest_index("2026-07-02T00:00:00Z")
    assert latest_index_regressions(latest_index("2026-07-01T00:00:00Z"), committed) == [
        "latest_index_regressed:vendor-security:2026-07-01T00:00:00Z<2026-07-02T00:00:00Z"
    ]
    assert latest_index_regressions(latest_index("2026-07-03T00:00:00Z", include_source=False), committed) == [
        "latest_index_source_dropped:vendor-security"
    ]
    assert latest_index_regressions(latest_index("2026-07-03T00:00:00Z"), committed) == []


def latest_loader(candidate: dict, committed: dict):
    payloads = {
        ("BASE", LATEST_INDEX_PATH): json.dumps(committed, sort_keys=True),
        ("HEAD", LATEST_INDEX_PATH): json.dumps(candidate, sort_keys=True),
    }

    def loader(ref: str, path: str) -> str:
        return payloads[(ref, path)]

    return loader


def test_observation_automerge_rejects_latest_index_removal_and_regression() -> None:
    committed = latest_index("2026-07-02T00:00:00Z")
    labels = [AUTOMERGE_OBSERVATION_LABEL, OBSERVATION_LEDGER_LABEL]

    dropped = check_observation_automerge(
        [LATEST_INDEX_PATH],
        labels,
        "BASE",
        "HEAD",
        loader=latest_loader(latest_index("2026-07-03T00:00:00Z", include_source=False), committed),
    )
    assert dropped.eligible is False
    assert "latest_index_source_dropped:vendor-security" in dropped.reasons

    regressed = check_observation_automerge(
        [LATEST_INDEX_PATH],
        labels,
        "BASE",
        "HEAD",
        loader=latest_loader(latest_index("2026-07-01T00:00:00Z"), committed),
    )
    assert regressed.eligible is False
    assert (
        "latest_index_regressed:vendor-security:2026-07-01T00:00:00Z<2026-07-02T00:00:00Z"
        in regressed.reasons
    )


def test_observation_automerge_accepts_newer_or_equal_latest_index_only_update() -> None:
    committed = latest_index("2026-07-02T00:00:00Z")
    labels = [AUTOMERGE_OBSERVATION_LABEL, OBSERVATION_LEDGER_LABEL]

    equal = check_observation_automerge(
        [LATEST_INDEX_PATH],
        labels,
        "BASE",
        "HEAD",
        loader=latest_loader(latest_index("2026-07-02T00:00:00Z"), committed),
    )
    assert equal.eligible is True
    assert equal.appended_rows == 0

    newer = check_observation_automerge(
        [LATEST_INDEX_PATH],
        labels,
        "BASE",
        "HEAD",
        loader=latest_loader(latest_index("2026-07-03T00:00:00Z"), committed),
    )
    assert newer.eligible is True
    assert newer.appended_rows == 0


def test_quarantine_eligibility_refuses_an_already_quarantined_source() -> None:
    source = {"source_id": "vendor-security", "source_url": "https://example.com/security", "review_state": "quarantined"}
    events = [
        {
            "source_id": "vendor-security",
            "observed_at": f"2026-06-0{day}T00:00:00Z",
            "http_status": 404,
            "source_health_status": "unreachable",
        }
        for day in range(1, 4)
    ]
    result = quarantine_eligibility(source, events, {"failed_http_statuses": [404, 410], "min_failed_observations": 3})
    assert result.eligible is False
    assert "already_quarantined" in result.reasons


def test_machine_decision_store_refuses_duplicate_decision_id(tmp_path: Path) -> None:
    committed_files = sorted((ROOT / "maintenance" / "machine-decisions").glob("*.ndjson"))
    assert committed_files, "expected at least one committed machine decision fixture"
    record = json.loads(committed_files[0].read_text(encoding="utf-8").splitlines()[0])
    append_decisions([record], tmp_path)
    assert len(load_decisions(tmp_path)) == 1
    with pytest.raises(ValueError, match="duplicate decision_id"):
        append_decisions([record], tmp_path)
