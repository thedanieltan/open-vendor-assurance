from tools.openva.source_repair_plan import validate_source_repair_plan


def evidence():
    return {
        "report_type": "p0_source_repair_evidence",
        "generated_at": "2026-05-24T00:00:00Z",
        "repairs": [
            {
                "vendor_id": "vendor-a",
                "source_id": "vendor-a-dpa",
                "source_type": "dpa",
                "source_url": "https://example.com/old-dpa",
                "original": {
                    "prior": {"verification_status": "not_found", "http_status": 404},
                    "fresh": {"verification_status": "not_found", "http_status": 404},
                },
                "replacement": None,
                "proposed_change": None,
            }
        ],
    }


def plan_row(**updates):
    row = {
        "vendor_id": "vendor-a",
        "source_id": "vendor-a-dpa",
        "source_type": "dpa",
        "original_source_url": "https://example.com/old-dpa",
        "replacement_source_url": "https://example.com/new-dpa",
        "replacement_verification_status": "ok",
        "replacement_http_status": 200,
        "replacement_semantic_status": "strong",
        "replacement_authority_status": "vendor_controlled",
        "replacement_access_status": "public",
        "replacement_url_safety_status": "passed",
    }
    row.update(updates)
    return row


def plan(rows):
    return {
        "report_type": "p0_source_repair_plan",
        "generated_at": "2026-05-24T01:00:00Z",
        "repairs": rows,
    }


def test_approves_strict_valid_repair_plan_row():
    result = validate_source_repair_plan(evidence(), plan([plan_row()]))

    assert result["summary"] == {
        "evidence_repair_count": 1,
        "plan_repair_count": 1,
        "approved_count": 1,
        "rejected_count": 0,
        "unmatched_count": 0,
    }
    assert result["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "opens_pull_requests": False,
        "mutates_catalog": False,
        "enables_automerge": False,
        "non_advisory": True,
    }
    assert result["approved"][0]["reasons"] == []


def test_rejects_source_type_change_and_weak_semantic_match():
    result = validate_source_repair_plan(
        evidence(),
        plan([
            plan_row(
                source_type="security_page",
                replacement_semantic_status="weak",
            )
        ]),
    )

    assert result["summary"]["approved_count"] == 0
    assert result["summary"]["rejected_count"] == 1
    assert set(result["rejected"][0]["reasons"]) == {
        "source_type_changed",
        "replacement_semantic_status_not_strong",
    }


def test_rejects_same_replacement_url():
    result = validate_source_repair_plan(
        evidence(),
        plan([plan_row(replacement_source_url="https://example.com/old-dpa")]),
    )

    assert result["summary"]["rejected_count"] == 1
    assert result["rejected"][0]["reasons"] == ["replacement_url_same_as_original"]


def test_rejects_explicit_soft_404_replacement_diagnostic():
    result = validate_source_repair_plan(
        evidence(),
        plan([plan_row(replacement_verification_status="soft_not_found", replacement_soft_404_detected=True)]),
    )

    assert result["summary"]["rejected_count"] == 1
    assert set(result["rejected"][0]["reasons"]) == {
        "replacement_verification_status_not_ok",
        "soft_404_detected",
    }
    assert result["rejected"][0]["replacement_soft_404_detected"] is True


def test_records_unmatched_plan_rows():
    result = validate_source_repair_plan(
        evidence(),
        plan([plan_row(vendor_id="vendor-b")]),
    )

    assert result["summary"]["approved_count"] == 0
    assert result["summary"]["unmatched_count"] == 1
    assert result["unmatched"][0]["reasons"] == ["no_matching_evidence_row"]
