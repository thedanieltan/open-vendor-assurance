import yaml

from tools.openva.candidate_promotion_actions import apply_candidate_promotions


def strict_growth_action(source_type="security_page", page_title="Vendor Marketing Page"):
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
            "candidate_source_id": f"candidate-a-{source_type.replace('_', '-')}-candidate",
            "vendor_id": "candidate-a",
            "source_type_candidate": source_type,
            "candidate_url": f"https://candidate-a.example/{source_type}",
            "confidence": "likely",
            "evidence": {
                "page_title": page_title,
                "matched_terms": ["security", "privacy", "personal data"],
                "final_url": f"https://candidate-a.example/{source_type}",
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


def test_strict_growth_uses_deterministic_source_title_not_page_title(tmp_path):
    report = apply_candidate_promotions(
        {"actions": [strict_growth_action(page_title="Vendor Marketing Claim Page")]},
        root=tmp_path,
    )

    source = yaml.safe_load(
        (tmp_path / "data/vendors/candidate-a/sources/candidate-a-security-page.yaml").read_text(encoding="utf-8")
    )

    assert report["summary"]["canonical_sources_written"] == 1
    assert source["title_native"] == "Security Page"
    assert "Marketing Claim" not in source["title_native"]


def test_reviewed_candidate_uses_deterministic_source_title_not_page_title(tmp_path):
    candidate_path = tmp_path / "data/vendors/example/candidate_sources/example-dpa-candidate.yaml"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "candidate_source_id": "example-dpa-candidate",
                "vendor_id": "example",
                "source_type_candidate": "dpa",
                "candidate_url": "https://example.test/dpa",
                "confidence": "likely",
                "requires_review": True,
                "evidence": {
                    "http_status": 200,
                    "matched_terms": ["data processing"],
                    "page_title": "Vendor Marketing Claim Page",
                },
                "not_advice": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    action = {
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

    apply_candidate_promotions({"actions": [action]}, root=tmp_path)
    source = yaml.safe_load((tmp_path / "data/vendors/example/sources/example-dpa.yaml").read_text(encoding="utf-8"))

    assert source["title_native"] == "Data Processing Addendum"
    assert "Marketing Claim" not in source["title_native"]
