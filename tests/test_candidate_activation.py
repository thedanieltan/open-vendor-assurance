"""WP-OPENVA-CANDIDATE-ACTIVATION-01 candidate-bound activation tests.

Covers the controller, promotion-binding and mutation boundaries (not only a
pure helper):

- ``evaluate_persisted_candidate`` recomputation + each bound field;
- the same-candidate end-to-end invariant
  (selected == dispatched == verified == mutated, plus digest equality);
- the fail-closed adversarial cases, each proving NO canonical catalogue vendor
  or decision is written.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tools.openva import (
    autonomous_growth_controller as agc,
    candidate_activation as ca,
    candidate_record as cr,
    vendor_resolution as vr,
)

NOW = datetime(2026, 6, 14, tzinfo=UTC)
OBSERVED_AT = "2026-06-10T00:00:00Z"
LANE = "catalog_growth_promotion"


def _live_state(**overrides):
    state = {
        "lane_id": LANE,
        "state_source": "github_live",
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "pause": {"active": False},
        "evidence": {"generated_at": "2026-06-14T00:00:00Z"},
    }
    state.update(overrides)
    return state


def _complete_record(
    *,
    origin: str = "catalog_discovery",
    origin_reference: str = "smoke-vendor",
    vendor_id: str = "smoke-vendor",
    country: str | None = "US",
    on_domain: bool = True,
    eligibility_state: str | None = None,
) -> dict:
    identity = {
        "vendor_id_candidate": vendor_id,
        "vendor_name": "Smoke Vendor",
        "official_domain": "smoke.example",
    }
    if country is not None:
        identity["headquarters_country"] = country
    sources = [
        {
            "candidate_url": "https://smoke.example/dpa",
            "final_url": "https://smoke.example/dpa",
            "http_status": 200,
            "source_type_candidate": "dpa",
            "access_state": "public_reachable",
            "source_role": "primary_assurance",
            "on_vendor_domain": on_domain,
        }
    ]
    evidence = [{"candidate_url": "https://smoke.example/dpa", "verification_result": "ok", "observed_at": OBSERVED_AT}]
    state, reasons = cr.evaluate_eligibility(identity, sources, is_new_vendor=(origin == "catalog_discovery"))
    record = cr.build_candidate(
        candidate_origin=origin,
        origin_reference=origin_reference,
        vendor_identity_candidate=identity,
        source_candidates=sources,
        evidence_references=evidence,
        discovery_component="vendor-resolution:catalog_discovery",
        created_at=OBSERVED_AT,
        eligibility_state=eligibility_state or state,
        decision_reasons=reasons,
    )
    return record


def _write(root: Path, record: dict) -> str:
    store = root / "maintenance" / "candidates"
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{record['candidate_id']}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path.relative_to(root).as_posix()


def _no_catalogue_writes(root: Path) -> bool:
    vendors = list((root / "data" / "vendors").glob("*/vendor.yaml")) if (root / "data").exists() else []
    decisions = (
        list((root / "maintenance" / "machine-decisions").glob("*.ndjson"))
        if (root / "maintenance" / "machine-decisions").exists()
        else []
    )
    return not vendors and not decisions


# --- evaluate_persisted_candidate -------------------------------------------


def test_persisted_candidate_recomputes_eligible_and_consistent():
    record = _complete_record()
    decision = vr.evaluate_persisted_candidate(record, candidate_path="maintenance/candidates/x.json")
    assert decision.consistent is True
    assert decision.eligible is True
    assert decision.recomputed_state == "eligible"
    assert decision.selected_vendor == "smoke-vendor"
    assert decision.origin == "catalog_discovery"
    assert decision.content_digest.startswith("sha256:")
    assert decision.candidate_id == record["candidate_id"]


def test_persisted_candidate_forged_eligibility_state_fails_closed():
    # A genuinely deferred candidate (off-domain, unproven) with a forged
    # "eligible" state must not recompute to eligible.
    record = _complete_record(on_domain=False, eligibility_state="eligible")
    decision = vr.evaluate_persisted_candidate(record)
    assert decision.eligible is False
    assert any("eligibility_mismatch" in r for r in decision.reasons)


def test_persisted_candidate_altered_evidence_digest_fails_closed():
    record = _complete_record()
    record["evidence_digest"] = "sha256:" + "0" * 64  # forged digest
    decision = vr.evaluate_persisted_candidate(record)
    assert decision.eligible is False
    assert any("evidence_digest_mismatch" in r for r in decision.reasons)


def test_persisted_candidate_forged_candidate_id_fails_closed():
    record = _complete_record()
    record["candidate_id"] = "cand-catalog-discovery-not-the-real-id"
    decision = vr.evaluate_persisted_candidate(record)
    assert decision.eligible is False
    assert any("candidate_id_mismatch" in r for r in decision.reasons)


def test_content_digest_changes_when_record_changes():
    record = _complete_record()
    before = cr.compute_candidate_content_digest(record)
    record["source_candidates"][0]["candidate_url"] = "https://smoke.example/changed"
    after = cr.compute_candidate_content_digest(record)
    assert before != after


# --- controller binding ------------------------------------------------------


def test_controller_binds_selected_candidate(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    eligible = ca.collect_eligible_candidates(tmp_path / "maintenance" / "candidates", root=tmp_path)
    assert len(eligible) == 1
    result = agc.decide_cycle(_live_state(), eligible, now=NOW)
    assert result["proceed"] is True
    binding = result["selected_candidate"]
    assert binding["candidate_id"] == record["candidate_id"]
    assert binding["candidate_path"] == rel
    assert binding["selected_vendor"] == "smoke-vendor"
    assert binding["origin"] == "catalog_discovery"
    assert binding["content_digest"] == cr.compute_candidate_content_digest(record)


def test_controller_fails_closed_on_forged_candidate(tmp_path: Path):
    record = _complete_record(on_domain=False, eligibility_state="eligible")  # forged
    record["candidate_path"] = "maintenance/candidates/x.json"
    result = agc.decide_cycle(_live_state(), [record], now=NOW)
    assert result["proceed"] is False
    assert result["reason"] == "candidate_eligibility_mismatch"
    assert result["selected_candidate"] is None
    assert result.get("candidate_mismatch_reasons")


# --- same-candidate end-to-end invariant ------------------------------------


def test_same_candidate_selected_dispatched_verified_mutated(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)

    # selected (controller)
    eligible = ca.collect_eligible_candidates(tmp_path / "maintenance" / "candidates", root=tmp_path)
    decision = agc.decide_cycle(_live_state(), eligible, now=NOW)
    binding = decision["selected_candidate"]
    selected_id = decision["selected_candidate_id"]

    # dispatched binding == selected binding (what the workflow passes on)
    assert binding["candidate_id"] == selected_id

    # verified (mutation workflow re-check on the exact PR head)
    assert ca.verify_binding(record, rel, binding) == []

    # mutated
    report = ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)

    # selected == dispatched == verified == mutated (candidate id), and vendor
    assert selected_id == binding["candidate_id"] == report["candidate_id"]
    assert binding["selected_vendor"] == report["mutated_vendor"] == "smoke-vendor"

    # digest equality across the whole path
    assert binding["content_digest"] == report["content_digest"] == report["candidate_digest"]

    # the catalogue vendor links the committed decision
    vendor = (tmp_path / "data" / "vendors" / "smoke-vendor" / "vendor.yaml").read_text(encoding="utf-8")
    assert "catalog_status: machine_provisional" in vendor
    assert report["decision_id"] in vendor

    # the decision pins the candidate identity + digest
    decisions = list((tmp_path / "maintenance" / "machine-decisions").glob("*.ndjson"))
    assert decisions
    rows = [json.loads(line) for line in decisions[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["candidate_digest"] == binding["content_digest"]
    assert rows[0]["subject_id"] == "smoke-vendor"
    assert rows[0]["evidence"]["candidate_id"] == record["candidate_id"]


# --- fail-closed adversarial cases ------------------------------------------


def _clean_binding(record: dict, rel: str) -> dict:
    return vr.evaluate_persisted_candidate(record, candidate_path=rel).binding()


def test_changed_candidate_after_decision_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    # The committed candidate changes after the controller decided.
    record["source_candidates"][0]["candidate_url"] = "https://smoke.example/swapped"
    reasons = ca.verify_binding(record, rel, binding)
    assert any("content_digest_mismatch" in r for r in reasons)
    try:
        ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
        raised = False
    except ca.CandidateBindingError:
        raised = True
    assert raised
    assert _no_catalogue_writes(tmp_path)


def test_candidate_id_mismatch_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    binding["candidate_id"] = "cand-catalog-discovery-other"
    try:
        ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
        raised = False
    except ca.CandidateBindingError as exc:
        raised = any("candidate_id_mismatch" in r for r in exc.reasons)
    assert raised
    assert _no_catalogue_writes(tmp_path)


def test_selected_vendor_mismatch_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    binding["selected_vendor"] = "some-other-vendor"
    try:
        ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
        raised = False
    except ca.CandidateBindingError:
        raised = True
    assert raised
    assert _no_catalogue_writes(tmp_path)


def test_origin_mismatch_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    binding["origin"] = "human_submission"
    reasons = ca.verify_binding(record, rel, binding)
    assert any("origin_mismatch" in r for r in reasons)
    assert _no_catalogue_writes(tmp_path)


def test_path_substitution_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    reasons = ca.verify_binding(record, "maintenance/candidates/substituted.json", binding)
    assert any("candidate_path_mismatch" in r for r in reasons)


def test_digest_mismatch_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    binding["content_digest"] = "sha256:" + "0" * 64
    try:
        ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
        raised = False
    except ca.CandidateBindingError as exc:
        raised = any("content_digest_mismatch" in r for r in exc.reasons)
    assert raised
    assert _no_catalogue_writes(tmp_path)


def test_missing_record_fields_fail_closed(tmp_path: Path):
    reasons = ca.verify_binding({}, "maintenance/candidates/missing.json", _clean_binding(_complete_record(), "x"))
    assert reasons  # schema invalid / not eligible


def test_replay_of_obsolete_decision_fails_closed(tmp_path: Path):
    record = _complete_record()
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    first = ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
    assert first["mutated_vendor"] == "smoke-vendor"
    # Re-dispatching the same (now stale) decision must not write again.
    try:
        ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
        raised = False
    except ca.CandidateBindingError as exc:
        raised = any("vendor_already_exists" in r for r in exc.reasons)
    assert raised


def test_off_origin_candidate_without_country_fails_closed(tmp_path: Path):
    # An eligible candidate that lacks an ISO headquarters country cannot be
    # materialized into a schema-valid vendor: fail closed, never fabricate it.
    record = _complete_record(country=None)
    rel = _write(tmp_path, record)
    binding = _clean_binding(record, rel)
    assert binding["content_digest"]  # still eligible / bindable
    try:
        ca.materialize_candidate(record, rel, binding, root=tmp_path, now=NOW)
        raised = False
    except ca.CandidateBindingError as exc:
        raised = any("headquarters_country" in r for r in exc.reasons)
    assert raised
    assert _no_catalogue_writes(tmp_path)
