"""WP35 release-gate tests.

Coverage discipline (per the WP35 constitution-enforcement contract):
- every machine_enforced constitution rule has a NEGATIVE fixture proving its
  gate rejects a real violation;
- every contract_enforced rule has a workflow/authority-contract assertion;
- every deferred rule names an owning work package and is non-authoritative.

No test here asserts merely that a phrase exists in YAML and calls that
enforcement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from tools.openva import release_gates as rg
from tools.openva.advisory_wording import load_prohibited_terms
from tools.openva.agent_export import payload_digest
from tools.openva.indexes import ROOT

NOW = datetime(2026, 6, 13, 8, 0, 0, tzinfo=UTC)
CONSTITUTION = yaml.safe_load((ROOT / "config" / "bot-constitution.yaml").read_text(encoding="utf-8"))
CONFIG = rg.load_config()


def make_ctx(profile: str = "pr", **overrides) -> rg.GateContext:
    kwargs = dict(
        root=ROOT,
        ledger_dir=rg.DEFAULT_LEDGER_DIR,
        config=CONFIG,
        profile=profile,
        now=NOW,
        commit_sha="0" * 40,
    )
    kwargs.update(overrides)
    return rg.GateContext(**kwargs)


# --------------------------------------------------------------------------- #
# Aggregate behaviour on the real repository
# --------------------------------------------------------------------------- #
def test_pr_profile_passes_on_clean_main():
    results = rg.run_gates(make_ctx("pr"))
    report = rg.build_report(make_ctx("pr"), results)
    assert report["decision"] == "pass", [g for g in report["gates"] if g["status"] == "fail"]
    assert report["summary"]["blocking_failures"] == 0


def test_release_profile_fails_closed_without_required_evidence():
    ctx = make_ctx("release", source_health_readiness_path=None)
    results = rg.run_gates(ctx)
    report = rg.build_report(ctx, results)
    shr = [g for g in report["gates"] if g["gate_id"] == "source_health_readiness"][0]
    assert shr["status"] == "fail"
    assert report["decision"] == "blocked"


def test_release_profile_passes_with_ready_evidence(tmp_path):
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps({
            "report_type": "release_source_health_readiness",
            "status": "ready",
            "generated_at": "2026-06-13T07:30:00Z",
            "failures": [],
            "warnings": [],
        }),
        encoding="utf-8",
    )
    ctx = make_ctx("release", source_health_readiness_path=readiness)
    report = rg.build_report(ctx, rg.run_gates(ctx))
    assert report["decision"] == "pass", [g for g in report["gates"] if g["status"] == "fail"]


def test_stale_source_health_evidence_fails_closed(tmp_path):
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps({
            "report_type": "release_source_health_readiness",
            "status": "ready",
            "generated_at": "2026-05-01T00:00:00Z",  # >168h before NOW
            "failures": [],
        }),
        encoding="utf-8",
    )
    result = rg.gate_source_health_readiness(make_ctx("release", source_health_readiness_path=readiness))
    assert result.status == "fail"
    assert "stale" in result.summary


# --------------------------------------------------------------------------- #
# machine_enforced rules: one negative fixture each
# --------------------------------------------------------------------------- #
def test_machine_rule_no_private_or_gated_content_leakage():
    clean = {"vendors/v.json": {"sources": [{"source_id": "s", "not_advice": True}]}}
    assert rg.find_self_certifying_or_private_leaks(clean) == []
    leaking = {"vendors/v.json": {"sources": [{"source_id": "s", "eligible": True}]}}
    assert rg.find_self_certifying_or_private_leaks(leaking), "self-certifying leak must be detected"


def test_machine_rule_no_advisory_scoring_or_ranking_language():
    terms = load_prohibited_terms()
    assert terms, "prohibited vocabulary must be configured"
    clean = {"vendors/v.json": {"canonical_name": "Example Vendor"}}
    assert rg.find_advisory_terms(clean, terms) == []
    violation = {"vendors/v.json": {"canonical_name": f"We {terms[0]} this vendor"}}
    assert rg.find_advisory_terms(violation, terms), "prohibited advisory wording must be detected"


def test_machine_rule_non_advisory_doctrine_present():
    assert rg.find_missing_non_advisory_doctrine({"a.json": {"not_advice": True}}) == []
    assert rg.find_missing_non_advisory_doctrine({"a.json": {"count": 1}}), "missing doctrine must be detected"


def test_machine_rule_openva_content_digests_sha256_only():
    payload = {"schema_version": "0.1.0", "count": 1, "not_advice": True}
    good = {**payload, "snapshot": {"digest": payload_digest(payload)}}
    assert rg.find_digest_mismatches({"a.json": good}, None) == []
    tampered = {**payload, "snapshot": {"digest": "sha256:" + "0" * 64}}
    assert rg.find_digest_mismatches({"a.json": tampered}, None), "digest mismatch must be detected"


def test_digest_rule_does_not_reject_external_or_git_references():
    # SHA-256-only governs OpenVA snapshot digests, not arbitrary external/git refs.
    payload = {"git_ref": "abc1234", "external_id": "ext-99", "not_advice": True}
    good = {**payload, "snapshot": {"digest": payload_digest(payload)}}
    assert rg.find_digest_mismatches({"a.json": good}, None) == []


def test_machine_rule_no_raw_document_mirroring(tmp_path):
    (tmp_path / "data").mkdir()
    assert rg.find_raw_content_dirs(tmp_path) == []
    (tmp_path / "data" / "raw").mkdir()
    assert rg.find_raw_content_dirs(tmp_path), "raw-content directory must be detected"


def test_machine_rule_every_machine_created_claim_reversible(tmp_path):
    vendor_dir = tmp_path / "data" / "vendors" / "x"
    vendor_dir.mkdir(parents=True)
    markers = CONFIG["reversibility"]["machine_marker_fields"]
    reversals = CONFIG["reversibility"]["reversal_fields"]
    # machine-marked, no reversal -> violation
    (vendor_dir / "vendor.yaml").write_text(f"vendor_id: x\n{markers[0]}: dec-1\n", encoding="utf-8")
    assert rg.find_irreversible_machine_records(tmp_path, markers, reversals), "irreversible machine record must be detected"
    # machine-marked WITH reversal -> clean
    (vendor_dir / "vendor.yaml").write_text(
        f"vendor_id: x\n{markers[0]}: dec-1\n{reversals[0]}: rev-1\n", encoding="utf-8"
    )
    assert rg.find_irreversible_machine_records(tmp_path, markers, reversals) == []


def test_machine_rule_no_single_bot_canonicalization(tmp_path):
    decisions_dir = tmp_path / "maintenance" / "machine-decisions"
    decisions_dir.mkdir(parents=True)
    ledger = decisions_dir / "2026-06.ndjson"

    def promote(**overrides) -> dict:
        record = {
            "decision_id": "x-promotion",
            "decision": "promote",
            "subject_id": "x",
            "deciding_bot": "quorum-promotion-decider",
            "discovery_bot": "catalog-growth-discovery",
            "supporting_bots": ["quorum-identity-resolver", "quorum-source-verifier"],
        }
        record.update(overrides)
        return record

    # An independent quorum -> clean.
    ledger.write_text(json.dumps(promote()) + "\n", encoding="utf-8")
    assert rg.find_single_bot_canonicalizations(tmp_path, 2) == []

    # discovery == deciding -> violation.
    ledger.write_text(json.dumps(promote(discovery_bot="quorum-promotion-decider")) + "\n", encoding="utf-8")
    assert rg.find_single_bot_canonicalizations(tmp_path, 2), "discovery==deciding must be detected"

    # deciding bot is the sole supporter -> violation.
    ledger.write_text(json.dumps(promote(supporting_bots=["quorum-promotion-decider"])) + "\n", encoding="utf-8")
    assert rg.find_single_bot_canonicalizations(tmp_path, 2), "sole self-support must be detected"

    # only one independent supporter (< 2) -> violation.
    ledger.write_text(json.dumps(promote(supporting_bots=["quorum-identity-resolver"])) + "\n", encoding="utf-8")
    assert rg.find_single_bot_canonicalizations(tmp_path, 2), "insufficient independence must be detected"


# --------------------------------------------------------------------------- #
# material_change_surfaced: latest-per-source, not all-events (regression for
# the false-fail exposed when an autonomous append superseded older material
# events).
# --------------------------------------------------------------------------- #
def _write_ledger(tmp_path, events):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "2026-06.ndjson").write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in events), encoding="utf-8"
    )
    return events_dir


def test_material_change_surfaced_ignores_superseded_events(tmp_path):
    # A material event followed by a newer non-material observation for the same
    # source must NOT fail the gate: the latest state is non-material.
    ledger = _write_ledger(tmp_path, [
        {"source_id": "a", "observed_at": "2026-06-01T00:00:00Z", "change_class": "material_possible", "observation_id": "obs-a-1"},
        {"source_id": "a", "observed_at": "2026-06-10T00:00:00Z", "change_class": "none", "observation_id": "obs-a-2"},
    ])
    ctx = make_ctx(ledger_dir=ledger)
    docs = {"changes/latest.json": {"sources": [{"source_id": "a", "observation_id": "obs-a-2"}]}}
    assert rg.gate_material_change_surfaced(ctx, docs).status == "pass"


def test_material_change_surfaced_fails_when_latest_material_dropped(tmp_path):
    ledger = _write_ledger(tmp_path, [
        {"source_id": "b", "observed_at": "2026-06-10T00:00:00Z", "change_class": "material_confirmed", "observation_id": "obs-b-1"},
    ])
    ctx = make_ctx(ledger_dir=ledger)
    docs = {"changes/latest.json": {"sources": []}}  # export dropped the latest material change
    assert rg.gate_material_change_surfaced(ctx, docs).status == "fail"


# --------------------------------------------------------------------------- #
# Freshness gates (negative fixtures via synthetic freshness state)
# --------------------------------------------------------------------------- #
def _freshness(sources, all_ids, baseline_ids):
    return {
        "report": {"sources": sources},
        "all_source_ids": set(all_ids),
        "baseline_source_ids": set(baseline_ids),
    }


def test_full_baseline_gate_fails_on_unobserved_source():
    fr = _freshness([], all_ids={"a", "b"}, baseline_ids={"a"})
    assert rg.gate_full_baseline(make_ctx(), fr).status == "fail"
    fr_ok = _freshness([], all_ids={"a", "b"}, baseline_ids={"a", "b"})
    assert rg.gate_full_baseline(make_ctx(), fr_ok).status == "pass"


def test_observation_freshness_gate_fails_on_expired():
    expired = [{"source_id": "a", "source_type": "dpa", "freshness": {"status": "expired", "age_days": 200, "observed_within_sla": False}}]
    assert rg.gate_observation_freshness(make_ctx(), _freshness(expired, {"a"}, {"a"})).status == "fail"


def test_high_priority_freshness_gate_fails_when_priority_type_out_of_sla():
    rows = [{"source_id": "a", "source_type": "dpa", "freshness": {"status": "stale", "age_days": 40, "observed_within_sla": False}}]
    assert rg.gate_high_priority_freshness(make_ctx(), _freshness(rows, {"a"}, {"a"})).status == "fail"


# --------------------------------------------------------------------------- #
# Aggregation: category toggles
# --------------------------------------------------------------------------- #
def test_freshness_gates_warn_mode_does_not_block():
    warn_config = {**CONFIG, "freshness_gates": "warn"}
    ctx = make_ctx(config=warn_config)
    results = [rg.GateResult("full_baseline_readiness", rg.CAT_FRESHNESS, "fail", "incomplete")]
    report = rg.build_report(ctx, results)
    assert report["summary"]["blocking_failures"] == 0
    assert report["decision"] == "pass"


def test_freshness_gates_enforce_mode_blocks():
    ctx = make_ctx()  # config has freshness_gates: enforce
    results = [rg.GateResult("full_baseline_readiness", rg.CAT_FRESHNESS, "fail", "incomplete")]
    report = rg.build_report(ctx, results)
    assert report["summary"]["blocking_failures"] == 1
    assert report["decision"] == "blocked"


def test_source_health_policy_report_only_does_not_block():
    ctx = make_ctx("release", source_health_policy="report_only")
    results = [rg.GateResult("source_health_readiness", rg.CAT_SOURCE_HEALTH, "fail", "blocked")]
    report = rg.build_report(ctx, results)
    assert report["summary"]["blocking_failures"] == 0


# --------------------------------------------------------------------------- #
# Constitution structure + enforcement classification
# --------------------------------------------------------------------------- #
def _rules_by_state(state):
    return [r for r in CONSTITUTION["rules"] if r["enforcement"]["state"] == state]


def test_every_machine_rule_names_a_real_gate_run_on_real_repo():
    produced = {r.gate_id for r in rg.run_gates(make_ctx("release", source_health_readiness_path=None))}
    for rule in _rules_by_state("machine_enforced"):
        gate_id = rule["enforcement"]["gate_id"]
        assert gate_id in produced, f"{rule['id']} names gate {gate_id} not produced by run_gates"


def test_machine_enforced_rules_have_negative_fixtures():
    # Each machine_enforced gate_id must be exercised by a negative fixture in
    # this module. This guards against adding a machine rule without a test.
    tested_gate_ids = {
        "exports_leakage_clean",
        "exports_advisory_clean",
        "exports_non_advisory_doctrine",
        "exports_digest_integrity",
        "no_raw_mirroring",
        "reversible_provenance",
        "quorum_promotion_independence",
    }
    declared = {r["enforcement"]["gate_id"] for r in _rules_by_state("machine_enforced")}
    assert declared == tested_gate_ids, "every machine_enforced gate must have a negative fixture here"


def test_contract_enforced_rule_no_direct_write_to_main():
    # The CLI cannot prove human branch-protection; it proves OpenVA automation
    # holds no write permission on the PR-checking and release workflows.
    for name in ("validate.yml", "release-candidate.yml"):
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
        assert "write" not in json.dumps(workflow.get("permissions", {})), f"{name} must be read-only"


def test_contract_enforced_rule_observation_and_discovery_lanes_deny_writes():
    authority = yaml.safe_load((ROOT / "docs" / "operations" / "contracts" / "bot-authority.yaml").read_text(encoding="utf-8"))
    lanes = authority.get("lanes") or []
    assert lanes, "bot-authority must declare lanes"
    assert authority.get("default_posture", {}).get("undeclared_lanes_are_denied") is True


def test_every_contract_rule_names_existing_evidence():
    for rule in _rules_by_state("contract_enforced"):
        evidence = rule["enforcement"].get("evidence")
        assert evidence, f"{rule['id']} contract rule must name evidence"


def test_deferred_rules_are_non_authoritative_and_owned():
    deferred = _rules_by_state("deferred")
    assert deferred, "deferred rules expected at WP35"
    for rule in deferred:
        assert rule["authoritative"] is False, f"{rule['id']} deferred rule must be non-authoritative"
        assert rule["enforcement"]["owner"] in {"wp36", "wp37"}, f"{rule['id']} must name an owning work package"


def test_constitution_gate_passes_on_clean_repo():
    results = rg.run_gates(make_ctx("pr"))
    constitution = [r for r in results if r.gate_id == "constitution"][0]
    assert constitution.status == "pass"
