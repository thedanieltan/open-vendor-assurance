from __future__ import annotations

import json

import yaml

from tools.openva.source_repair_automerge import (
    check_source_repair_automerge,
    extract_reviewed_inputs,
    validate_reviewed_report_path,
)


def source(url: str, **updates):
    data = {
        "schema_version": "0.1.0",
        "source_id": "microsoft-compliance",
        "vendor_id": "microsoft",
        "source_type": "compliance_page",
        "title_native": "Microsoft Trust Center Compliance",
        "title_en": "Microsoft Trust Center Compliance",
        "source_url": url,
        "source_language": "en",
        "source_authority_class": "vendor_published",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "summary_native": "Public Microsoft Trust Center compliance page metadata reference.",
        "summary_en": "Public Microsoft Trust Center compliance page metadata reference.",
        "provenance": {
            "publisher": "vendor",
            "collected_at": "2026-05-15T00:00:00Z",
            "observer": "human",
            "confidence": "high",
        },
        "not_advice": True,
    }
    data.update(updates)
    return data


def validation_row(**updates):
    row = {
        "vendor_id": "microsoft",
        "source_id": "microsoft-compliance",
        "source_type": "compliance_page",
        "original_source_url": "https://www.microsoft.com/en-us/trust-center/compliance",
        "replacement_source_url": "https://www.microsoft.com/en-us/trust-center/compliance/compliance-overview",
        "replacement_verification_status": "ok",
        "replacement_http_status": 200,
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public_web",
        "replacement_url_safety_status": "passed",
        "reasons": [],
    }
    row.update(updates)
    return row


def validation_report(row=None, **updates):
    report = {
        "report_type": "p0_source_repair_plan_validation",
        "approved": [row or validation_row()],
        "rejected": [],
        "unmatched": [],
    }
    report.update(updates)
    return report


def evidence_row(**updates):
    row = {
        "vendor_id": "microsoft",
        "source_id": "microsoft-compliance",
        "source_type": "compliance_page",
        "source_url": "https://www.microsoft.com/en-us/trust-center/compliance",
        "original": {
            "prior": {"verification_status": "not_found", "http_status": 404},
            "fresh": {"verification_status": "not_found", "http_status": 404},
        },
        "replacement": None,
        "proposed_change": None,
    }
    row.update(updates)
    return row


def evidence_report(row=None, **updates):
    report = {
        "report_type": "p0_source_repair_evidence",
        "repairs": [row or evidence_row()],
    }
    report.update(updates)
    return report


def memory_loader(files):
    def load(ref: str, path: str) -> str:
        value = files[(ref, path)]
        if isinstance(value, str):
            return value
        if path.endswith(".json"):
            return json.dumps(value)
        return yaml.safe_dump(value, sort_keys=False)

    return load


def check(validation=None, evidence=None, base=None, head=None, paths=None):
    base_source = base or source("https://www.microsoft.com/en-us/trust-center/compliance")
    head_source = head or source(
        "https://www.microsoft.com/en-us/trust-center/compliance/compliance-overview",
        review_state="human_reviewed",
        catalog_tier="human_reviewed",
    )
    return check_source_repair_automerge(
        paths or [
            "data/vendors/microsoft/sources/microsoft-compliance.yaml",
            "indexes/sources.json",
            "dist/vendors/microsoft.json",
        ],
        validation or validation_report(),
        evidence or evidence_report(),
        "base",
        "head",
        loader=memory_loader(
            {
                ("base", "data/vendors/microsoft/sources/microsoft-compliance.yaml"): base_source,
                ("head", "data/vendors/microsoft/sources/microsoft-compliance.yaml"): head_source,
            }
        ),
    )


def test_source_repair_automerge_accepts_strict_confirmed_p0_repair():
    result = check()

    assert result.eligible is True
    assert result.source_repairs == 1
    assert result.reasons == ()


def test_source_repair_automerge_rejects_missing_raw_evidence_match():
    result = check(evidence=evidence_report(evidence_row(source_url="https://example.com/other")))

    assert result.eligible is False
    assert "evidence_row_missing:microsoft:microsoft-compliance" in result.reasons


def test_source_repair_automerge_rejects_non_confirmed_p0_evidence():
    result = check(
        evidence=evidence_report(
            evidence_row(
                original={
                    "prior": {"verification_status": "not_found", "http_status": 404},
                    "fresh": {"verification_status": "ok", "http_status": 200},
                }
            )
        )
    )

    assert result.eligible is False
    assert "evidence_status_pair_not_confirmed_p0:not_found:ok" in result.reasons


def test_source_repair_automerge_rejects_weak_semantic_replacement():
    result = check(validation=validation_report(validation_row(replacement_semantic_status="weak")))

    assert result.eligible is False
    assert "replacement_semantic_status_not_strong" in result.reasons


def test_source_repair_automerge_rejects_soft_404_replacement():
    row = validation_row(replacement_soft_404_detected=True, reasons=["soft_404_detected"])
    result = check(validation=validation_report(row))

    assert result.eligible is False
    assert "soft_404_detected" in result.reasons


def test_source_repair_automerge_rejects_redirected_replacement_not_canonical():
    row = validation_row(
        replacement_verification_status="redirected",
        replacement_source_url="https://www.microsoft.com/compliance",
        replacement_final_url="https://www.microsoft.com/en-us/trust-center/compliance/compliance-overview",
    )
    head = source(
        "https://www.microsoft.com/compliance",
        review_state="human_reviewed",
        catalog_tier="human_reviewed",
    )
    result = check(validation=validation_report(row), head=head)

    assert result.eligible is False
    assert "redirected_replacement_not_canonical" in result.reasons


def test_source_repair_automerge_accepts_redirected_replacement_when_stored_url_is_final():
    row = validation_row(
        replacement_verification_status="redirected",
        replacement_final_url="https://www.microsoft.com/en-us/trust-center/compliance/compliance-overview/",
    )
    result = check(validation=validation_report(row))

    assert result.eligible is True


def test_source_repair_automerge_rejects_redirected_replacement_without_final_url():
    row = validation_row(replacement_verification_status="redirected")
    result = check(validation=validation_report(row))

    assert result.eligible is False
    assert "final_url_missing" in result.reasons


def test_source_repair_automerge_rejects_self_certifying_fields():
    result = check(validation=validation_report(eligible_for_automerge=True))

    assert result.eligible is False
    assert "validation_self_certifying_field:$.eligible_for_automerge" in result.reasons


def test_source_repair_automerge_rejects_unexpected_source_field_change():
    head = source(
        "https://www.microsoft.com/en-us/trust-center/compliance/compliance-overview",
        title_native="Unexpected title change",
        review_state="human_reviewed",
        catalog_tier="human_reviewed",
    )
    result = check(head=head)

    assert result.eligible is False
    assert "unexpected_source_field_change:title_native" in result.reasons


def test_source_repair_automerge_rejects_maintenance_paths_in_repair_pr():
    result = check(paths=["maintenance/reviewed/p0-source-repair-validation-test-1.json"])

    assert result.eligible is False
    assert "disallowed_path:maintenance/reviewed/p0-source-repair-validation-test-1.json" in result.reasons


def test_source_repair_automerge_rejects_more_than_ten_source_repairs():
    paths = [f"data/vendors/vendor-{index}/sources/vendor-{index}-dpa.yaml" for index in range(11)]
    result = check(paths=paths)

    assert result.eligible is False
    assert "source_repair_record_limit_exceeded:11>10" in result.reasons


def test_extract_reviewed_inputs_requires_validation_and_evidence_paths():
    values = extract_reviewed_inputs(
        "\n".join(
            [
                "- Validation report: `maintenance/reviewed/validation.json`",
                "- Evidence report: `maintenance/reviewed/evidence.json`",
            ]
        )
    )

    assert values == {
        "VALIDATION_REPORT_PATH": "maintenance/reviewed/validation.json",
        "EVIDENCE_REPORT_PATH": "maintenance/reviewed/evidence.json",
    }


def test_reviewed_input_path_rejects_traversal():
    try:
        validate_reviewed_report_path("maintenance/reviewed/../secret.json", "evidence_report")
    except ValueError as error:
        assert "maintenance/reviewed/" in str(error)
    else:
        raise AssertionError("expected ValueError")
