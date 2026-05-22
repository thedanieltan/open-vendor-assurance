from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.contribution_promotion_materializer import materialize_queue


def machine_source() -> dict:
    return {
        "schema_version": "0.1.0",
        "source_id": "stripe-dpa",
        "vendor_id": "stripe",
        "source_type": "dpa",
        "title_native": "Stripe Data Processing Addendum",
        "title_en": "Stripe Data Processing Addendum",
        "source_url": "https://stripe.com/legal/dpa",
        "source_language": "en",
        "source_authority_class": "vendor_published",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "catalog_tier": "machine_validated",
        "review_state": "auto_validated",
        "advisory_boundary": "non_advisory",
        "summary_native": None,
        "summary_en": None,
        "provenance": {
            "publisher": "vendor",
            "collected_at": "2026-05-23T00:00:00Z",
            "observer": "agent",
            "confidence": "high",
        },
        "not_advice": True,
    }


def queue(source: dict | None = None) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_type": "contribution_promotion_queue",
        "machine_validated_promotions": [
            {
                "vendor_id": "stripe",
                "source_type": "dpa",
                "candidate_url": "https://stripe.com/legal/dpa",
                "source": source or machine_source(),
            }
        ],
    }


def test_materializer_dry_run_reports_written_path_without_writing(tmp_path):
    result = materialize_queue(queue(), root=tmp_path, apply=False)

    assert result.written == ("data/vendors/stripe/sources/stripe-dpa.yaml",)
    assert not (tmp_path / "data/vendors/stripe/sources/stripe-dpa.yaml").exists()


def test_materializer_apply_writes_machine_validated_source_yaml(tmp_path):
    result = materialize_queue(queue(), root=tmp_path, apply=True)
    path = tmp_path / "data/vendors/stripe/sources/stripe-dpa.yaml"

    assert result.written == ("data/vendors/stripe/sources/stripe-dpa.yaml",)
    assert path.exists()
    source = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert source["catalog_tier"] == "machine_validated"
    assert source["review_state"] == "auto_validated"
    assert source["advisory_boundary"] == "non_advisory"
    assert source["not_advice"] is True


def test_materializer_skips_existing_identical_source(tmp_path):
    path = tmp_path / "data/vendors/stripe/sources/stripe-dpa.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(machine_source(), sort_keys=False), encoding="utf-8")

    result = materialize_queue(queue(), root=tmp_path, apply=True)

    assert result.written == ()
    assert result.skipped_existing == ("data/vendors/stripe/sources/stripe-dpa.yaml",)
    assert result.conflicts == ()


def test_materializer_reports_conflict_without_overwrite(tmp_path):
    path = tmp_path / "data/vendors/stripe/sources/stripe-dpa.yaml"
    path.parent.mkdir(parents=True)
    existing = {**machine_source(), "source_url": "https://stripe.com/old-dpa"}
    path.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")

    result = materialize_queue(queue(), root=tmp_path, apply=True)

    assert result.written == ()
    assert result.conflicts == ("data/vendors/stripe/sources/stripe-dpa.yaml",)


def test_materializer_can_overwrite_conflict_when_explicit(tmp_path):
    path = tmp_path / "data/vendors/stripe/sources/stripe-dpa.yaml"
    path.parent.mkdir(parents=True)
    existing = {**machine_source(), "source_url": "https://stripe.com/old-dpa"}
    path.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")

    result = materialize_queue(queue(), root=tmp_path, apply=True, overwrite=True)
    source = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert result.written == ("data/vendors/stripe/sources/stripe-dpa.yaml",)
    assert source["source_url"] == "https://stripe.com/legal/dpa"


def test_materializer_rejects_non_machine_validated_source(tmp_path):
    source = {**machine_source(), "catalog_tier": "human_reviewed"}
    result = materialize_queue(queue(source), root=tmp_path, apply=True)

    assert result.written == ()
    assert result.invalid_items
    assert "source catalog_tier must be machine_validated" in result.invalid_items[0]


def test_materializer_report_shape_is_json_serializable(tmp_path):
    result = materialize_queue(queue(), root=tmp_path, apply=False)
    encoded = json.dumps(result.as_dict(), sort_keys=True)

    assert "writes_canonical_source_files" in encoded
    assert "auto_merge" in encoded
