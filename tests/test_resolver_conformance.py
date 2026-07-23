"""Cross-runtime resolver conformance is the single-authority contract lock.

WP-OPENVA-RESOLVER-UNIFICATION.

The authoritative matching core (`openva_vendor_inventory_matcher.core`) owns the confidence
threshold, normalization, legal-suffix stripping, registration matching, ambiguity rules, and
the status vocabulary. Every transport (browser, Cloudflare Worker, MCP, CSV adapter, hosted
service) must reproduce the same outcomes. This test locks the committed conformance artifact to
the core so a matching-behaviour change cannot land silently, and proves the generator fails
closed on drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.openva import resolver_conformance as rc

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "tests" / "conformance" / "resolver-conformance.json"

REQUIRED_CLASSES = {
    "exact_domain",
    "subdomain",
    "shared_parent_domain",
    "exact_name",
    "stripped_legal_suffix",
    "ambiguous",
    "no_match",
    "malformed_input",
    "internationalized_domain",
    "conflicting_identity",
    "registration_number",
}


def test_committed_artifact_is_fresh_and_core_reproduces_every_vector():
    assert rc.check() == []


def test_artifact_matches_generator_output_byte_for_byte():
    assert ARTIFACT.read_text(encoding="utf-8") == rc.render()


def test_every_required_case_class_is_present():
    suite = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    covered = {vector["class"] for vector in suite["vectors"]}
    assert REQUIRED_CLASSES <= covered


def test_contract_constants_equal_the_core():
    suite = rc.build_suite()
    assert suite["contract"]["minimum_match_confidence"] == rc.core.MINIMUM_MATCH_CONFIDENCE
    assert suite["contract"]["ambiguity_margin"] == rc.core.AMBIGUITY_MARGIN
    assert suite["contract"]["status_vocabulary"] == [
        rc.core.STATUS_MATCHED,
        rc.core.STATUS_NO_MATCH,
        rc.core.STATUS_AMBIGUOUS,
    ]


def test_shared_domain_fails_closed_to_ambiguous():
    result = rc._resolve({"domain": "shared.example"})
    assert result["status"] == "ambiguous"
    assert result["vendor_id"] is None


def test_registration_vendor_conflict_attributes_neither_vendor():
    # Domain -> acme, registration -> globex's entity: contradictory strong identity.
    result = rc._resolve(
        {"domain": "acme.com", "registration_number": "99999999", "jurisdiction": "us"}
    )
    assert result["vendor_id"] is None
    assert result["legal_entity_method"] == "registration_vendor_conflict"


def test_check_fails_closed_when_a_vector_expectation_is_tampered(tmp_path, monkeypatch):
    # Point the module at a tampered copy: one vector's expected outcome flipped.
    suite = rc.build_suite()
    suite["vectors"][0]["expected"]["vendor_id"] = "not-the-real-vendor"
    tampered = tmp_path / "resolver-conformance.json"
    tampered.write_text(
        json.dumps(suite, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(rc, "ARTIFACT", tampered)
    problems = rc.check()
    assert problems
    assert any("stale" in problem for problem in problems)
