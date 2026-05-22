import json
from pathlib import Path

import yaml

from tools.openva import automation_rules
from tools.openva.observe import classify_rule_set_f_result
from tools.openva.source_verification import FetchResult
from tools.openva.validate import validate_adapter_record


def fetch_result(status=200, url="https://example.com/source", content_type="text/html"):
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=status,
        content_type=content_type,
        content_length=None,
        etag=None,
        last_modified=None,
        body_sample=b"<html><title>Example</title><body>privacy security trust</body></html>",
        error=None if status else "timeout",
    )


def test_validate_adapter_record_accepts_and_rejects_records():
    assert validate_adapter_record(
        {
            "record_class": "canonical",
            "canonical": True,
            "catalog_tier": "human_reviewed",
            "review_state": "human_reviewed",
            "advisory_boundary": "non_advisory",
        }
    ) == []

    failures = validate_adapter_record(
        {
            "record_class": "candidate",
            "canonical": True,
            "catalog_tier": "discovery",
            "review_state": "human_review_required",
            "advisory_boundary": "non_advisory",
        }
    )
    assert failures


def evaluate_wording_case(case):
    findings = []
    warnings = []
    if "payload" in case:
        automation_rules.scan_structured_value(
            case["payload"],
            rel_path=case["path"],
            field_path="",
            findings=findings,
            warnings=warnings,
        )
        for summary_path, summary in automation_rules.iter_summary_strings(case["payload"]):
            for phrase in automation_rules.implication_phrases():
                if phrase in summary.lower():
                    findings.append(f"{case['path']}: {summary_path}: implication language detected: {phrase}")
    else:
        doc_findings, doc_warnings = automation_rules.scan_plain_doc(case["path"], case["text"])
        findings.extend(doc_findings)
        warnings.extend(doc_warnings)
    if findings:
        return "fail"
    if warnings:
        return "ambiguous"
    return "pass"


def test_advisory_wording_calibration_fixtures_are_ground_truth():
    fixture = yaml.safe_load(Path("fixtures/advisory-wording-calibration.yaml").read_text(encoding="utf-8"))
    assert 10 <= len(fixture["cases"]) <= 15

    outcomes = {case["id"]: evaluate_wording_case(case) for case in fixture["cases"]}
    expected = {case["id"]: case["expected"] for case in fixture["cases"]}

    assert outcomes == expected


def test_new_vendor_rules_allow_stub_but_escalate_regulated_category(tmp_path, monkeypatch):
    vendor = {
        "schema_version": "0.1.0",
        "vendor_id": "acme-bank",
        "display_name": "Acme Bank",
        "legal_name": "Acme Bank Pte Ltd",
        "headquarters_country": "SG",
        "official_domains": ["acme.example"],
        "public_entrypoints": ["https://acme.example"],
        "vendor_categories": ["financial_services"],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        "catalog_status": "stub",
    }
    path = tmp_path / "data/vendors/acme-bank/vendor.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(vendor), encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / "category-taxonomy.yaml").write_text(
        yaml.safe_dump({"vendor_categories": {"financial_services": {}}}),
        encoding="utf-8",
    )
    (config / "domain-blocklist.yaml").write_text("blocked_domain_classes: {}\n", encoding="utf-8")
    (config / "controlled-vocabulary.yaml").write_text(
        yaml.safe_dump({"regulated_legal_terms": ["bank", "insurance", "hospital"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(automation_rules, "ROOT", tmp_path)
    monkeypatch.setattr(automation_rules, "records_for", lambda kind: [{**vendor, "_openva_path": "data/vendors/acme-bank/vendor.yaml"}])

    result = automation_rules.new_vendor_rules(
        ["data/vendors/acme-bank/vendor.yaml"],
        fetcher=lambda url: fetch_result(200, url),
        check_dns=False,
    )

    assert result.score == 0
    assert any("regulated vendor_categories" in item for item in result.escalations)
    assert any("legal_name contains" in item for item in result.escalations)


def test_source_accessibility_passes_public_web_metadata_source(tmp_path, monkeypatch):
    source = {
        "schema_version": "0.1.0",
        "source_id": "example-privacy",
        "vendor_id": "example",
        "source_type": "privacy_notice",
        "title_native": "Example Privacy Notice",
        "source_url": "https://example.com/privacy",
        "source_language": "en",
        "source_authority_class": "vendor_published",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": "2026-05-22T00:00:00Z",
            "observer": "agent",
            "confidence": "high",
        },
        "not_advice": True,
    }
    path = tmp_path / "data/vendors/example/sources/example-privacy.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / "domain-blocklist.yaml").write_text("blocked_domain_classes: {}\n", encoding="utf-8")

    monkeypatch.setattr(automation_rules, "ROOT", tmp_path)

    result = automation_rules.source_accessibility(
        ["data/vendors/example/sources/example-privacy.yaml"],
        fetcher=lambda url: fetch_result(200, url),
    )

    assert result.score == 1
    assert result.escalations == []


def test_entity_mention_exact_match_suggests_agent_provenance(tmp_path, monkeypatch):
    mention = {
        "schema_version": "0.1.0",
        "mention_id": "stripe-llc-mention",
        "vendor_id": "stripe",
        "observed_name": "Stripe, Inc.",
        "observed_role": "processor",
        "appears_in_source_id": "stripe-subprocessors",
        "observed_at": "2026-05-22T00:00:00Z",
        "assertion_source": "vendor_published",
        "resolution": {"status": "unresolved"},
        "not_advice": True,
    }
    path = tmp_path / "data/vendors/stripe/entity_mentions/stripe-llc-mention.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(mention), encoding="utf-8")

    def fake_records(kind):
        if kind == "legal_entity":
            return [
                {
                    "entity_id": "stripe-inc",
                    "vendor_id": "stripe",
                    "legal_name": "Stripe, Inc.",
                    "catalog_status": "canonical",
                    "verification_source_ids": ["stripe-registry"],
                }
            ]
        if kind == "source":
            return [{"source_id": "stripe-subprocessors"}]
        return []

    monkeypatch.setattr(automation_rules, "ROOT", tmp_path)
    monkeypatch.setattr(automation_rules, "records_for", fake_records)

    result = automation_rules.entity_resolution_rules(
        ["data/vendors/stripe/entity_mentions/stripe-llc-mention.yaml"]
    )

    assert result.score == 1
    suggestion = result.details["suggested_matches"][0]["resolution"]
    assert suggestion["match_method"] == "legal_name_exact"
    assert suggestion["matched_by"] == "agent"
    assert suggestion["match_confidence"] == "high"


def test_legal_entity_promotion_requires_public_authority_source(tmp_path, monkeypatch):
    entity = {
        "schema_version": "0.1.0",
        "entity_id": "example-pte",
        "vendor_id": "example",
        "legal_name": "Example Pte Ltd",
        "jurisdiction": "SG",
        "verification_source_ids": ["example-registry"],
        "catalog_status": "stub",
        "not_advice": True,
    }
    path = tmp_path / "data/vendors/example/legal_entities/example-pte.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(entity), encoding="utf-8")

    def fake_records(kind):
        if kind == "vendor":
            return [{"vendor_id": "example", "display_name": "Example"}]
        if kind == "source":
            return [
                {
                    "source_id": "example-registry",
                    "source_authority_class": "public_registry",
                    "source_url": "https://registry.example/entity",
                }
            ]
        return []

    monkeypatch.setattr(automation_rules, "ROOT", tmp_path)
    monkeypatch.setattr(automation_rules, "records_for", fake_records)

    result = automation_rules.legal_entity_promotion_rules(
        ["data/vendors/example/legal_entities/example-pte.yaml"],
        fetcher=lambda url: fetch_result(200, url),
    )

    assert result.score == 0
    assert any("legal_name differs significantly" in item for item in result.escalations)


def test_rule_set_f_observation_classification_detects_change_and_gating():
    previous = {"hashes": {"normalized_text_sha256": "sha256:" + "a" * 64}}

    assert (
        classify_rule_set_f_result(
            base_result="ok",
            http_status=200,
            source_url="https://example.com/privacy",
            final_url="https://example.com/privacy",
            normalized_text_sha256="sha256:" + "b" * 64,
            previous_observation=previous,
        )
        == "content_changed"
    )
    assert (
        classify_rule_set_f_result(
            base_result="ok",
            http_status=403,
            source_url="https://example.com/privacy",
            final_url="https://example.com/privacy",
            normalized_text_sha256="sha256:" + "b" * 64,
            previous_observation=previous,
        )
        == "auth_required"
    )


def test_weighted_review_summary_labels_escalation(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"score": 1, "warnings": [], "escalations": [], "failures": []}), encoding="utf-8")
    second.write_text(json.dumps({"score": 0, "warnings": [], "escalations": ["needs review"], "failures": []}), encoding="utf-8")

    summary = automation_rules.weighted_review([first, second])

    assert summary["total_score"] == 1
    assert summary["label"] == "openva:needs-human-review"
