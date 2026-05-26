import copy

import yaml

from tools.openva.candidate_promotion_actions import apply_candidate_promotions


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


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

    report = apply_candidate_promotions({"actions": [reviewed_action()]}, root=tmp_path)

    assert report["summary"]["canonical_sources_written"] == 0
    assert report["summary"]["skipped_actions"] == 1


def test_apply_strict_growth_writes_vendor_source_artifact_and_change(tmp_path):
    report = apply_candidate_promotions({"actions": [strict_growth_action()]}, root=tmp_path)
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
    assert vendor["catalog_status"] == "active"
    assert vendor["source_policy"]["public_sources_only"] is True
    assert source["source_id"] == "candidate-a-security-page"
    assert source["source_url"] == "https://candidate-a.example/security"
    assert artifact["source_id"] == "candidate-a-security-page"
    assert change["change_type"] == "created"


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
    }

    report = apply_candidate_promotions({"actions": [security, privacy]}, root=tmp_path)

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

    report = apply_candidate_promotions({"actions": [action]}, root=tmp_path)

    assert report["summary"]["canonical_vendors_written"] == 0
    assert report["summary"]["skipped_actions"] == 1
    assert "headquarters_country_candidate" in report["skipped"][0]["reason"]
