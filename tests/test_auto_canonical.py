from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.openva.auto_canonical import (
    build_machine_validated_source,
    is_machine_canonical_eligible,
)

VENDOR = {
    "vendor_id": "stripe",
    "display_name": "Stripe",
    "official_domains": ["stripe.com"],
}

DPA_CANDIDATE = {
    "vendor_id": "stripe",
    "candidate_source_id": "stripe-dpa-candidate",
    "source_type_candidate": "dpa",
    "candidate_url": "https://stripe.com/legal/dpa",
    "title": "Stripe Data Processing Addendum",
}

OK_VERIFICATION = {
    "verification_status": "ok",
    "http_status": 200,
    "final_url": "https://stripe.com/legal/dpa",
    "page_title": "Data Processing Addendum",
    "observed_at": "2026-05-23T00:00:00Z",
}


def test_public_same_domain_dpa_candidate_is_eligible():
    eligible, reasons = is_machine_canonical_eligible(DPA_CANDIDATE, VENDOR, OK_VERIFICATION)
    assert eligible is True
    assert reasons == []


def test_public_same_domain_privacy_notice_candidate_is_eligible():
    candidate = {
        **DPA_CANDIDATE,
        "candidate_source_id": "stripe-privacy-candidate",
        "source_type_candidate": "privacy_notice",
        "candidate_url": "https://stripe.com/privacy",
        "title": "Stripe Privacy Notice",
    }
    verification = {
        **OK_VERIFICATION,
        "final_url": "https://stripe.com/privacy",
        "page_title": "Privacy Notice",
    }
    eligible, reasons = is_machine_canonical_eligible(candidate, VENDOR, verification)
    assert eligible is True
    assert reasons == []


def test_https_required():
    candidate = {**DPA_CANDIDATE, "candidate_url": "http://stripe.com/legal/dpa"}
    eligible, reasons = is_machine_canonical_eligible(candidate, VENDOR, OK_VERIFICATION)
    assert eligible is False
    assert "candidate_url_not_https" in reasons


@pytest.mark.parametrize(
    "status",
    ["login_required", "gated_or_login_required", "bot_protected", "rate_limited", "form_gated"],
)
def test_gated_or_blocked_status_rejected(status):
    verification = {**OK_VERIFICATION, "verification_status": status}
    eligible, reasons = is_machine_canonical_eligible(DPA_CANDIDATE, VENDOR, verification)
    assert eligible is False
    assert any(reason.startswith("gated_or_blocked:") for reason in reasons)


def test_cross_domain_redirect_rejected_unless_allowlisted():
    verification = {**OK_VERIFICATION, "final_url": "https://evil.example/legal/dpa"}
    eligible, reasons = is_machine_canonical_eligible(DPA_CANDIDATE, VENDOR, verification)
    assert eligible is False
    assert "unsafe_redirect_or_non_vendor_domain" in reasons
    assert "final_url_not_on_vendor_domain" in reasons


def test_allowlisted_vendor_controlled_redirect_can_pass():
    vendor = {**VENDOR, "allowlisted_source_domains": ["stripe-cdn.com"]}
    verification = {**OK_VERIFICATION, "final_url": "https://legal.stripe-cdn.com/dpa"}
    eligible, reasons = is_machine_canonical_eligible(DPA_CANDIDATE, vendor, verification)
    assert eligible is True
    assert reasons == []


def test_unknown_source_type_rejected():
    candidate = {**DPA_CANDIDATE, "source_type_candidate": "unknown"}
    eligible, reasons = is_machine_canonical_eligible(candidate, VENDOR, OK_VERIFICATION)
    assert eligible is False
    assert "unknown_source_type" in reasons


def test_source_type_mismatch_rejected():
    candidate = {**DPA_CANDIDATE, "source_type_candidate": "subprocessors_list"}
    eligible, reasons = is_machine_canonical_eligible(candidate, VENDOR, OK_VERIFICATION)
    assert eligible is False
    assert "source_type_evidence_missing" in reasons


def test_advisory_wording_rejected():
    candidate = {**DPA_CANDIDATE, "title": "Stripe approved low risk vendor"}
    eligible, reasons = is_machine_canonical_eligible(candidate, VENDOR, OK_VERIFICATION)
    assert eligible is False
    assert "advisory_wording_present" in reasons


def test_build_machine_validated_source_has_required_tier_fields():
    source = build_machine_validated_source(DPA_CANDIDATE, VENDOR, OK_VERIFICATION)
    assert source["catalog_tier"] == "machine_validated"
    assert source["review_state"] == "auto_validated"
    assert source["advisory_boundary"] == "non_advisory"
    assert source["not_advice"] is True
    assert source["provenance"]["observer"] == "agent"


def test_machine_validated_source_validates_against_source_schema():
    schema = json.loads(Path("schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))
    source = build_machine_validated_source(DPA_CANDIDATE, VENDOR, OK_VERIFICATION)
    Draft202012Validator(schema).validate(source)
