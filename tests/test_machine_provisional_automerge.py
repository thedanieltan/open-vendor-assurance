"""WP36b machine-provisional automerge gate tests (negative fixtures)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

from tools.openva import machine_provisional_automerge as mp
from tools.openva.candidate_promotion_actions import build_retrieval_claim, retrieval_independence
from tools.openva.pack import canonical_json, sha256_bytes

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
VENDOR_PATH = "data/vendors/okta/vendor.yaml"
DECISION_PATH = "maintenance/machine-decisions/2026-06.ndjson"
GENERATED = "indexes/vendors.json"
LABELS = [mp.MARKER_LABEL, mp.MACHINE_PROVISIONAL_LABEL]


def decision_evidence(**overrides):
    evidence = {
        "official_domain": "okta.com",
        "candidate_source_id": "okta-security-page-a1b2c3d4",
        "source_type": "security_page",
        "candidate_url": "https://okta.com/security",
        "http_status": 200,
        "matched_terms": ["security"],
        "final_url": "https://okta.com/security",
        "name_supported_by_official_domain_metadata": True,
        "source_host_authority": "vendor_controlled",
        "adversarial_review": "clean",
        "evidence_fresh": True,
        "materialization_envelope_digest": "sha256:" + "a" * 64,
    }
    evidence.update(overrides)
    return evidence


def threshold_results(evidence, *, retrieval_ids=None, duplicate_ids=None, attempts=None):
    retrieval_ids = retrieval_ids or ["retrieval-1:https://okta.com/security", "retrieval-2:https://okta.com/security"]
    duplicate_ids = duplicate_ids or ["duplicate-collision:okta:okta.com"]
    attempts = attempts if attempts is not None else [
        {"workflow_run_id": "run-1", "retrieval_mode": "direct_http"},
        {"workflow_run_id": "run-2", "retrieval_mode": "direct_http"},
    ]
    distinct_runs, distinct_modes, independent = retrieval_independence(attempts, 2, 2)
    retrieval_claim = build_retrieval_claim(
        required=2,
        observed=2,
        agreeing=True,
        evidence_ids=retrieval_ids,
        final_url=evidence.get("final_url"),
        candidate_url=evidence.get("candidate_url"),
        http_status=evidence.get("http_status"),
        min_distinct_workflow_runs=2,
        min_distinct_retrieval_modes=2,
        distinct_workflow_runs=distinct_runs,
        distinct_retrieval_modes=distinct_modes,
        independent=independent,
    )
    duplicate_claim = {
        "maximum": 0.0,
        "observed": 0.0,
        "evidence_ids": duplicate_ids,
        "candidate_vendor_id": "okta",
        "official_domain": evidence.get("official_domain"),
    }
    return {
        "official_entrypoint": "pass",
        "name_supported_by_official_metadata": "pass",
        "retrieval_attempts": {
            **retrieval_claim,
            "result_digest": sha256_bytes(canonical_json(retrieval_claim)),
        },
        "duplicate_collision_score": {
            **duplicate_claim,
            "result_digest": sha256_bytes(canonical_json(duplicate_claim)),
        },
        "source_host_authority": "pass",
        "adversarial_review": "pass",
        "evidence_freshness": "pass",
    }


def vendor_yaml(**overrides) -> str:
    record = {
        "vendor_id": "okta",
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": "okta-vendor-materialization",
        "reversal": {"method": "remove", "reference": "revert", "reversal_decision_id": None},
    }
    record.update(overrides)
    import yaml

    return yaml.safe_dump(record)


def decision_line(**overrides) -> str:
    evidence = overrides.pop("evidence", decision_evidence())
    thresholds = overrides.pop(
        "thresholds",
        {
            "required_score": 1.0,
            "actual_score": 1.0,
            "results": threshold_results(evidence),
        },
    )
    record = {
        "decision_id": "okta-vendor-materialization",
        "subject_id": "okta",
        "decision": "materialize_provisional",
        "deciding_bot": "strict-growth-materializer",
        "discovery_bot": "catalog-growth-discovery",
        "evidence": evidence,
        "not_before": "2026-06-15T00:00:00Z",  # past relative to NOW
        "thresholds": thresholds,
        "candidate_digest": "sha256:" + "b" * 64,
        "not_advice": True,
    }
    record.update(overrides)
    return json.dumps(record)


def make_loader(*, base_has_vendor=False, vendor_text=None, decision_text=None):
    vendor_text = vendor_text if vendor_text is not None else vendor_yaml()
    decision_text = decision_text if decision_text is not None else decision_line()

    def loader(ref: str, path: str) -> str:
        if ref == "BASE":
            if path == VENDOR_PATH and not base_has_vendor:
                raise subprocess.CalledProcessError(128, ["git", "show"])
            return vendor_yaml()  # base copy if it exists
        if path == VENDOR_PATH:
            return vendor_text
        if path == DECISION_PATH:
            return decision_text
        raise subprocess.CalledProcessError(128, ["git", "show"])

    return loader


PATHS = [VENDOR_PATH, DECISION_PATH, GENERATED]


def test_accepts_valid_new_provisional_vendor():
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert result.eligible, result.reasons
    assert result.vendor_id == "okta"


def test_rejects_not_before_in_future():
    loader = make_loader(decision_text=decision_line(not_before="2026-06-25T00:00:00Z"))
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)
    assert not result.eligible
    assert any("not_before_not_passed" in r for r in result.reasons)


def test_rejects_existing_vendor_modification():
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=make_loader(base_has_vendor=True), now=NOW)
    assert not result.eligible
    assert any("vendor_already_exists" in r for r in result.reasons)


def test_rejects_non_provisional_status():
    loader = make_loader(vendor_text=vendor_yaml(catalog_status="active"))
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)
    assert not result.eligible
    assert any("catalog_status_not_machine_provisional" in r for r in result.reasons)


def test_rejects_disallowed_path():
    paths = PATHS + ["tools/openva/validate.py"]
    result = mp.check_machine_provisional_automerge(paths, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("disallowed_path" in r for r in result.reasons)


def test_rejects_two_vendors():
    paths = [VENDOR_PATH, "data/vendors/auth0/vendor.yaml", DECISION_PATH]
    result = mp.check_machine_provisional_automerge(paths, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("expected_exactly_one_new_vendor" in r for r in result.reasons)


def test_requires_both_labels():
    result = mp.check_machine_provisional_automerge(PATHS, [mp.MARKER_LABEL], "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("missing_label:automerge:machine-provisional" in r for r in result.reasons)


def test_rejects_separation_of_duty_violation():
    loader = make_loader(decision_text=decision_line(deciding_bot="same", discovery_bot="same"))
    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)
    assert not result.eligible
    assert any("separation_of_duty" in r for r in result.reasons)


def test_rejects_missing_decision_record():
    paths = [VENDOR_PATH, GENERATED]  # no decision ndjson
    result = mp.check_machine_provisional_automerge(paths, LABELS, "BASE", "HEAD", loader=make_loader(), now=NOW)
    assert not result.eligible
    assert any("missing_machine_decision_record" in r for r in result.reasons)


def test_rejects_forged_name_support_without_metadata():
    evidence = decision_evidence(name_supported_by_official_domain_metadata=False)
    loader = make_loader(decision_text=decision_line(evidence=evidence))

    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)

    assert not result.eligible
    assert "decision_threshold_recompute_failed:name_supported_by_official_metadata" in result.reasons


def test_rejects_forged_retrieval_count_without_evidence_ids():
    evidence = decision_evidence()
    thresholds = {
        "required_score": 1.0,
        "actual_score": 1.0,
        "results": threshold_results(evidence, retrieval_ids=["retrieval-1:https://okta.com/security"]),
    }
    loader = make_loader(decision_text=decision_line(evidence=evidence, thresholds=thresholds))

    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)

    assert not result.eligible
    assert "decision_threshold_evidence_missing:retrieval_attempts" in result.reasons


def test_rejects_source_type_not_permitted_for_materialization():
    evidence = decision_evidence(
        source_type="status_page",
        candidate_url="https://status.okta.com",
        final_url="https://status.okta.com",
    )
    loader = make_loader(decision_text=decision_line(evidence=evidence))

    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)

    assert not result.eligible
    assert "decision_source_type_not_materialization:status_page" in result.reasons


def test_rejects_source_host_authority_pass_on_unrelated_host():
    evidence = decision_evidence(candidate_url="https://status.example.net", final_url="https://status.example.net")
    loader = make_loader(decision_text=decision_line(evidence=evidence))

    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)

    assert not result.eligible
    assert "decision_threshold_recompute_failed:source_host_authority_url" in result.reasons


def test_rejects_forged_duplicate_threshold_digest():
    evidence = decision_evidence()
    results = threshold_results(evidence)
    results["duplicate_collision_score"]["result_digest"] = "sha256:forged"
    thresholds = {"required_score": 1.0, "actual_score": 1.0, "results": results}
    loader = make_loader(decision_text=decision_line(evidence=evidence, thresholds=thresholds))

    result = mp.check_machine_provisional_automerge(PATHS, LABELS, "BASE", "HEAD", loader=loader, now=NOW)

    assert not result.eligible
    assert "decision_threshold_digest_mismatch:duplicate_collision_score" in result.reasons
