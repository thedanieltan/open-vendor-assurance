import copy

import pytest
import yaml

from tools.openva.candidate_promotion_actions import apply_candidate_promotions
from tools.openva.materialization_envelope import build_envelope
from tools.openva.promotion_planner import build_strict_growth_plan


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def write_json(path, data):
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def attach_envelope(action, root):
    write_json(root / "vendor-candidate-discovery-report.json", {"report_type": "vendor_candidate_discovery_report"})
    write_json(root / "source-discovery-report.json", {"report_type": "source_discovery_report"})
    write_json(root / "catalog-growth-eligibility-report.json", {"report_type": "catalog_growth_eligibility_report"})
    action["materialization_envelope"] = build_envelope(
        action,
        root=root,
        artifact_paths={
            "vendor_candidate_report": root / "vendor-candidate-discovery-report.json",
            "source_discovery_report": root / "source-discovery-report.json",
            "eligibility_report": root / "catalog-growth-eligibility-report.json",
        },
        generated_at="2099-06-14T00:00:00Z",
        base_sha="b" * 40,
    )
    return action


def reviewed_action():
    return {
        "action": "promote_candidate_source_for_review",
        "vendor_id": "example",
        "source_type": "dpa",
        "candidate_source_id": "example-dpa-candidate",
        "candidate_url": "https://example.test/dpa",
        "path": "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }


def strict_growth_action():
    return {
        "action": "strict_catalog_growth_promotion",
        "reason": "Candidate passed strict catalog growth eligibility.",
        "vendor": {
            "candidate_vendor_id": "candidate-a",
            "display_name_candidate": "Candidate A",
            "official_domain_candidate": "candidate-a.example",
            "coverage_lane": "security",
            "cohort_id": "security-001",
            "vendor_category_candidates": ["security_software"],
            "headquarters_country_candidate": "US",
        },
        "source": {
            "candidate_source_id": "candidate-a-security-page-candidate",
            "vendor_id": "candidate-a",
            "source_type_candidate": "security_page",
            "candidate_url": "https://candidate-a.example/security",
            "confidence": "likely",
            "evidence": {
                "page_title": "Security",
                "matched_terms": ["security", "encryption"],
                "final_url": "https://candidate-a.example/security",
                "http_status": 200,
                "content_type": "text/html",
                "name_supported_by_official_domain_metadata": True,
                "retrieval_attempts": {"observed": 2, "agreeing": True},
                "source_host_authority": "vendor_controlled",
                "adversarial_review": "clean",
                "evidence_fresh": True,
            },
        },
        "requires_human_review": False,
        "writes_canonical_vendors": False,
        "writes_canonical_sources": False,
        "strict_machine_candidate": True,
        "non_advisory": True,
    }


def test_apply_reviewed_candidate_promotion_writes_canonical_source(tmp_path):
    write_yaml(
        tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        {
            "schema_version": "0.1.0",
            "candidate_source_id": "example-dpa-candidate",
            "vendor_id": "example",
            "source_type_candidate": "dpa",
            "candidate_url": "https://example.test/dpa",
            "confidence": "likely",
            "requires_review": True,
            "evidence": {"http_status": 200, "matched_terms": ["data processing"]},
            "not_advice": True,
        },
    )

    report = apply_candidate_promotions({"actions": [reviewed_action()]}, root=tmp_path)
    source_path = tmp_path / "data/vendors/example/sources/example-dpa.yaml"
    artifact_path = tmp_path / "data/vendors/example/artifacts/example-dpa.yaml"
    change_path = tmp_path / "data/vendors/example/changes/candidate-promotion-example-dpa.yaml"
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    artifact = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))
    change = yaml.safe_load(change_path.read_text(encoding="utf-8"))

    assert report["summary"]["canonical_sources_written"] == 1
    assert report["summary"]["canonical_artifacts_written"] == 1
    assert report["summary"]["change_events_written"] == 1
    assert source["source_id"] == "example-dpa"
    assert source["source_url"] == "https://example.test/dpa"
    assert source["rights_class"] == "metadata_only"
    assert source["provenance"]["confidence"] == "high"
    assert source["not_advice"] is True
    assert artifact["artifact_id"] == "example-dpa"
    assert artifact["source_id"] == "example-dpa"
    assert artifact["hashes"]["raw_sha256"] == "sha256:TBD"
    assert artifact["storage"]["raw_document_stored"] is False
    assert change["change_type"] == "created"
    assert change["not_advice"] is True


def test_apply_reviewed_candidate_promotion_preserves_plan_coverage_claims(tmp_path):
    write_yaml(
        tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        {
            "schema_version": "0.1.0",
            "candidate_source_id": "example-dpa-candidate",
            "vendor_id": "example",
            "source_type_candidate": "dpa",
            "candidate_url": "https://example.test/legal",
            "confidence": "likely",
            "requires_review": True,
            "evidence": {"http_status": 200, "matched_terms": ["data processing"]},
            "not_advice": True,
        },
    )
    action = reviewed_action()
    action["candidate_url"] = "https://example.test/legal"
    action["coverage_claims"] = [
        {
            "role": "ai_terms",
            "coverage_type": "contains",
            "evidence": "The same page includes AI-specific terms.",
        }
    ]

    report = apply_candidate_promotions({"actions": [action]}, root=tmp_path)
    source = yaml.safe_load((tmp_path / "data/vendors/example/sources/example-dpa.yaml").read_text(encoding="utf-8"))

    assert report["summary"]["canonical_sources_written"] == 1
    assert source["coverage_claims"] == action["coverage_claims"]


def test_apply_reviewed_candidate_promotion_skips_duplicate_source(tmp_path):
    write_yaml(
        tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml",
        {
            "schema_version": "0.1.0",
            "candidate_source_id": "example-dpa-candidate",
            "vendor_id": "example",
            "source_type_candidate": "dpa",
            "candidate_url": "https://example.test/dpa",
            "requires_review": True,
            "evidence": {"http_status": 200, "matched_terms": ["data processing"]},
            "not_advice": True,
        },
    )
    write_yaml(
        tmp_path / "data/vendors/example/sources/example-dpa.yaml",
        {"schema_version": "0.1.0", "source_id": "example-dpa", "vendor_id": "example"},
    )

    with pytest.raises(ValueError, match="canonical source already exists"):
        apply_candidate_promotions({"actions": [reviewed_action()]}, root=tmp_path)


def test_apply_strict_growth_writes_vendor_source_artifact_and_change(tmp_path):
    report = apply_candidate_promotions({"actions": [attach_envelope(strict_growth_action(), tmp_path)]}, root=tmp_path)
    vendor_path = tmp_path / "data/vendors/candidate-a/vendor.yaml"
    source_path = tmp_path / "data/vendors/candidate-a/sources/candidate-a-security-page.yaml"
    artifact_path = tmp_path / "data/vendors/candidate-a/artifacts/candidate-a-security-page.yaml"
    change_path = tmp_path / "data/vendors/candidate-a/changes/strict-growth-candidate-a-security-page.yaml"

    vendor = yaml.safe_load(vendor_path.read_text(encoding="utf-8"))
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    artifact = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))
    change = yaml.safe_load(change_path.read_text(encoding="utf-8"))

    assert report["summary"]["canonical_vendors_written"] == 1
    assert report["summary"]["canonical_sources_written"] == 1
    assert report["summary"]["canonical_artifacts_written"] == 1
    assert report["summary"]["change_events_written"] == 1
    assert vendor["vendor_id"] == "candidate-a"
    # WP36: machine materialization writes machine_provisional, never active.
    assert vendor["catalog_status"] == "machine_provisional"
    assert vendor["machine_generated"] is True
    assert vendor["machine_decision_id"].startswith("candidate-a-materialization-")
    assert vendor["reversal"]["method"] == "remove"
    assert vendor["source_policy"]["public_sources_only"] is True
    assert source["source_id"] == "candidate-a-security-page"
    assert source["source_url"] == "https://candidate-a.example/security"
    assert artifact["source_id"] == "candidate-a-security-page"
    assert change["change_type"] == "created"

    # A linked, append-only machine decision record is emitted with separation
    # of duties (deciding bot != discovery bot) and a not_before delay window.
    import json as _json

    decision_files = sorted((tmp_path / "maintenance/machine-decisions").glob("*.ndjson"))
    assert len(decision_files) == 1
    decisions = [_json.loads(line) for line in decision_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["decision_id"].startswith("candidate-a-materialization-")
    assert decision["decision"] == "materialize_provisional"
    assert decision["subject_id"] == "candidate-a"
    assert decision["deciding_bot"] != decision["discovery_bot"]
    assert decision["not_before"] > decision["created_at"]
    assert decision["not_advice"] is True


def test_apply_strict_growth_preserves_canonicalized_final_url(tmp_path):
    action = strict_growth_action()
    action["source"]["candidate_url"] = "https://candidate-a.example/company/security"
    action["source"]["evidence"]["verification_status"] = "redirected"
    action["source"]["evidence"]["final_url"] = "https://candidate-a.example/company/security"
    action["source"]["evidence"]["original_candidate_url"] = "https://candidate-a.example/security"
    action["source"]["evidence"]["redirect_status"] = "canonicalized"
    action["source"]["evidence"]["redirect_decision"] = "canonicalize"
    action["source"]["evidence"]["redirect_reason"] = "redirect_canonicalized"

    report = apply_candidate_promotions({"actions": [attach_envelope(action, tmp_path)]}, root=tmp_path)
    source = yaml.safe_load(
        (tmp_path / "data/vendors/candidate-a/sources/candidate-a-security-page.yaml").read_text(encoding="utf-8")
    )
    artifact = yaml.safe_load(
        (tmp_path / "data/vendors/candidate-a/artifacts/candidate-a-security-page.yaml").read_text(encoding="utf-8")
    )

    assert report["summary"]["canonical_sources_written"] == 1
    assert report["summary"]["redirect_canonicalized_count"] == 1
    assert source["source_url"] == "https://candidate-a.example/company/security"
    assert artifact["canonical_url"] == "https://candidate-a.example/company/security"


def test_apply_strict_growth_rejects_unresolved_redirect_before_writes(tmp_path):
    action = strict_growth_action()
    action["source"]["evidence"]["verification_status"] = "redirected"
    action["source"]["evidence"]["final_url"] = "https://candidate-a.example/company/security"

    with pytest.raises(ValueError, match="redirect_canonicalization_required"):
        apply_candidate_promotions({"actions": [action]}, root=tmp_path)
    assert not (tmp_path / "data/vendors/candidate-a/vendor.yaml").exists()


def test_apply_strict_growth_writes_multiple_sources_for_same_new_vendor(tmp_path):
    security = strict_growth_action()
    privacy = copy.deepcopy(security)
    privacy["source"]["candidate_source_id"] = "candidate-a-privacy-notice-candidate"
    privacy["source"]["source_type_candidate"] = "privacy_notice"
    privacy["source"]["candidate_url"] = "https://candidate-a.example/privacy"
    privacy["source"]["evidence"] = {
        "page_title": "Privacy Notice",
        "matched_terms": ["privacy", "personal data"],
        "final_url": "https://candidate-a.example/privacy",
        "http_status": 200,
        "content_type": "text/html",
        "name_supported_by_official_domain_metadata": True,
        "retrieval_attempts": {"observed": 2, "agreeing": True},
        "source_host_authority": "vendor_controlled",
        "adversarial_review": "clean",
        "evidence_fresh": True,
    }

    report = apply_candidate_promotions(
        {"actions": [attach_envelope(security, tmp_path), attach_envelope(privacy, tmp_path)]},
        root=tmp_path,
    )

    assert report["summary"]["promotion_actions_seen"] == 2
    assert report["summary"]["canonical_vendors_written"] == 1
    assert report["summary"]["canonical_sources_written"] == 2
    assert report["summary"]["canonical_artifacts_written"] == 2
    assert report["summary"]["change_events_written"] == 2
    assert report["summary"]["skipped_actions"] == 0
    assert (tmp_path / "data/vendors/candidate-a/vendor.yaml").exists()
    assert (tmp_path / "data/vendors/candidate-a/sources/candidate-a-security-page.yaml").exists()
    assert (tmp_path / "data/vendors/candidate-a/sources/candidate-a-privacy-notice.yaml").exists()


def test_apply_strict_growth_rejects_missing_country(tmp_path):
    action = strict_growth_action()
    del action["vendor"]["headquarters_country_candidate"]

    with pytest.raises(ValueError, match="headquarters_country_candidate"):
        apply_candidate_promotions({"actions": [action]}, root=tmp_path)


def test_apply_strict_growth_rejects_advisory_page_title_before_writes(tmp_path):
    action = strict_growth_action()
    action["source"]["evidence"]["page_title"] = "Cloud Security | How Candidate A Keeps Your Data Safe"

    with pytest.raises(ValueError, match="strict growth advisory wording detected: safe"):
        apply_candidate_promotions({"actions": [action]}, root=tmp_path)
    assert not (tmp_path / "data/vendors/candidate-a/vendor.yaml").exists()


def test_apply_strict_growth_does_not_infer_coverage_claims_from_broad_title(tmp_path):
    action = strict_growth_action()
    action["source"]["evidence"]["page_title"] = "Security and Trust Center"

    report = apply_candidate_promotions({"actions": [attach_envelope(action, tmp_path)]}, root=tmp_path)
    source = yaml.safe_load(
        (tmp_path / "data/vendors/candidate-a/sources/candidate-a-security-page.yaml").read_text(encoding="utf-8")
    )

    assert report["summary"]["canonical_sources_written"] == 1
    assert "coverage_claims" not in source


def test_strict_growth_batch_cap_prevents_applying_five_actions(tmp_path):
    strict_promotions = []
    items = []
    for index in range(5):
        action = strict_growth_action()
        vendor_id = f"candidate-{index}"
        action["vendor"]["candidate_vendor_id"] = vendor_id
        action["vendor"]["display_name_candidate"] = f"Candidate {index}"
        action["vendor"]["official_domain_candidate"] = f"{vendor_id}.example"
        action["source"]["vendor_id"] = vendor_id
        action["source"]["candidate_source_id"] = f"{vendor_id}-dpa-candidate"
        action["source"]["source_type_candidate"] = "dpa"
        action["source"]["candidate_url"] = f"https://{vendor_id}.example/dpa"
        action["source"]["evidence"]["page_title"] = "Data Processing Addendum"
        strict_promotions.append(action)
        items.append(
            {
                "candidate_vendor_id": vendor_id,
                "classification": "strict_promote_ready",
                "reason_codes": ["strict_source_candidate_evidence_present"],
            }
        )
    plan = build_strict_growth_plan(
        {
            "report_type": "catalog_growth_eligibility_report",
            "items": items,
            "strict_promotions": strict_promotions,
        },
        max_actions_per_plan=2,
    )
    for action in plan["actions"]:
        attach_envelope(action, tmp_path)

    report = apply_candidate_promotions(plan, root=tmp_path)

    assert plan["summary"]["uncapped_action_count"] == 5
    assert plan["summary"]["action_count"] == 2
    assert plan["summary"]["batch_deferred_action_count"] == 3
    assert report["summary"]["promotion_actions_seen"] == 2
    assert report["summary"]["canonical_vendors_written"] == 2
    assert report["summary"]["canonical_sources_written"] == 2
    assert report["summary"]["skipped_actions"] == 0
