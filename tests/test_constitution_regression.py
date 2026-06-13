"""WP39 constitution regression suite.

For every rule in config/bot-constitution.yaml this suite asserts a reason code
and both-direction coverage:

- machine_enforced rules: the backing release-gate checker ACCEPTS a clean
  fixture and REJECTS a violating fixture (a passing and a failing fixture);
- contract_enforced rules: the named evidence exists on disk;
- deferred rules: non-authoritative and owned by a work package.

A new constitution rule with no entry here fails `test_every_rule_is_covered`,
so the suite cannot silently fall behind the constitution.
"""

from __future__ import annotations

import json

import yaml

from tools.openva import release_gates as rg
from tools.openva.indexes import ROOT

CONSTITUTION = yaml.safe_load((ROOT / "config" / "bot-constitution.yaml").read_text(encoding="utf-8"))
RULES = {r["id"]: r for r in CONSTITUTION["rules"]}

# A stable reason code per rule (forces a deliberate entry for every new rule).
REASON_CODES = {
    "no_private_or_gated_content_leakage": "leakage_clean",
    "no_advisory_scoring_or_ranking_language": "advisory_clean",
    "non_advisory_doctrine_present_in_exports": "non_advisory_doctrine",
    "openva_content_digests_sha256_only": "digest_integrity",
    "no_raw_document_mirroring_by_default": "no_raw_mirroring",
    "every_machine_created_claim_reversible": "reversible_provenance",
    "no_single_bot_canonicalization": "quorum_independence",
    "no_rollback_by_authoring_bot": "rollback_reverser_not_author",
    "machine_claims_reproducible_and_consistent": "catalog_reproducibility",
    "openva_automation_no_direct_write_to_main": "no_direct_write_to_main",
    "declared_gated_sources_excluded_and_not_fetched": "declared_gated_excluded",
    "observation_and_discovery_lanes_deny_catalog_writes": "discovery_denies_writes",
    "no_bot_approves_its_own_discovery": "separation_of_duty",
    "no_identity_merge_without_resolution_evidence": "identity_resolution_required",
    "rollback_never_rewrites_decision_history": "append_only_history",
    "no_fabricated_source_replacement_and_quarantine_reversible": "no_fabricated_replacement",
    "no_source_mutation_without_linked_evidence": "source_mutation_evidence",
    "machine_writes_carry_provenance_and_decision_path": "provenance_decision_path",
}


# Each machine_enforced rule_id -> (positive fixture -> no findings, negative fixture -> findings).
def _digest_fixtures():
    bad = {"v.json": {"snapshot": {"digest": "sha256:" + "0" * 64}, "not_advice": True}}
    return rg.find_digest_mismatches({}, None) == [], bool(rg.find_digest_mismatches(bad, None))


def _leak_fixtures():
    return (rg.find_self_certifying_or_private_leaks({"v.json": {"x": 1}}) == [],
            bool(rg.find_self_certifying_or_private_leaks({"v.json": {"eligible": True}})))


def _advisory_fixtures():
    from tools.openva.advisory_wording import load_prohibited_terms
    terms = load_prohibited_terms()
    return (rg.find_advisory_terms({"v.json": {"name": "Example"}}, terms) == [],
            bool(rg.find_advisory_terms({"v.json": {"x": terms[0]}}, terms)))


def _doctrine_fixtures():
    return (rg.find_missing_non_advisory_doctrine({"v.json": {"not_advice": True}}) == [],
            bool(rg.find_missing_non_advisory_doctrine({"v.json": {}})))


MACHINE_FIXTURES = {
    "exports_leakage_clean": _leak_fixtures,
    "exports_advisory_clean": _advisory_fixtures,
    "exports_non_advisory_doctrine": _doctrine_fixtures,
    "exports_digest_integrity": _digest_fixtures,
}


def test_every_rule_is_covered():
    assert set(REASON_CODES) == set(RULES), "every constitution rule needs a regression reason code"


def test_machine_enforced_rules_have_both_direction_export_or_state_coverage(tmp_path):
    for rule in CONSTITUTION["rules"]:
        if rule["enforcement"]["state"] != "machine_enforced":
            continue
        gate_id = rule["enforcement"]["gate_id"]
        if gate_id in MACHINE_FIXTURES:
            clean_ok, violation_caught = MACHINE_FIXTURES[gate_id]()
            assert clean_ok, f"{gate_id}: clean fixture must pass"
            assert violation_caught, f"{gate_id}: violating fixture must be caught"


def test_state_based_machine_rules_reject_violations(tmp_path):
    decisions = tmp_path / "maintenance" / "machine-decisions"
    decisions.mkdir(parents=True)
    ledger = decisions / "2026-06.ndjson"

    # quorum independence
    ledger.write_text(json.dumps({"decision": "promote", "decision_id": "p", "deciding_bot": "d", "discovery_bot": "d", "supporting_bots": []}) + "\n", encoding="utf-8")
    assert rg.find_single_bot_canonicalizations(tmp_path, 2)
    # rollback reverser != author
    ledger.write_text(json.dumps({"decision": "rollback", "decision_id": "r", "deciding_bot": "x", "discovery_bot": "x"}) + "\n", encoding="utf-8")
    assert rg.find_rollback_author_violations(tmp_path)
    # reproducibility: machine vendor with no decision
    vd = tmp_path / "data" / "vendors" / "z"
    vd.mkdir(parents=True)
    (vd / "vendor.yaml").write_text("vendor_id: z\ncatalog_status: machine_provisional\nmachine_generated: true\nmachine_decision_id: missing\nreversal:\n  reference: r\n", encoding="utf-8")
    ledger.write_text("", encoding="utf-8")
    from tools.openva.catalog_audit import audit_catalog
    assert not audit_catalog(root=tmp_path, decisions_dir=decisions).clean


def test_contract_enforced_rules_name_existing_evidence():
    for rule in CONSTITUTION["rules"]:
        if rule["enforcement"]["state"] != "contract_enforced":
            continue
        evidence = rule["enforcement"].get("evidence", "")
        assert evidence, f"{rule['id']} must name evidence"
        # Evidence references at least one real path token.
        tokens = [t for t in evidence.replace(";", " ").split() if "/" in t and (t.endswith(".py") or t.endswith(".yaml"))]
        for token in tokens:
            assert (ROOT / token.split("::")[0]).exists(), f"{rule['id']} evidence path missing: {token}"


def test_deferred_rules_are_non_authoritative_and_owned():
    for rule in CONSTITUTION["rules"]:
        if rule["enforcement"]["state"] != "deferred":
            continue
        assert rule["authoritative"] is False
        assert rule["enforcement"]["owner"]


def test_authoritative_rules_have_reason_codes():
    for rule in CONSTITUTION["rules"]:
        if rule.get("authoritative"):
            assert REASON_CODES.get(rule["id"]), f"{rule['id']} authoritative rule needs a reason code"
