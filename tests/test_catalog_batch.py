from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva import catalog_batch


def sample_manifest() -> dict:
    return {
        "schema_version": "0.1.0",
        "batch_id": "p25-test-batch",
        "operation": "create",
        "collected_at": "2026-05-14T00:00:00Z",
        "observer": "human",
        "vendors": [
            {
                "vendor_id": "sample-vendor",
                "display_name": "Sample Vendor",
                "legal_name": "Sample Vendor, Inc.",
                "headquarters_country": "US",
                "regions_served": ["global"],
                "official_domains": ["sample.example"],
                "public_entrypoints": ["https://sample.example/trust"],
                "vendor_categories": ["enterprise_software"],
                "sources": [
                    {
                        "source_id": "sample-vendor-trust",
                        "source_type": "trust_center",
                        "title_native": "Sample Vendor Trust Center",
                        "title_en": "Sample Vendor Trust Center",
                        "source_url": "https://sample.example/trust",
                        "source_language": "en",
                        "summary_native": "Public Sample Vendor page describing trust information.",
                        "summary_en": "Public Sample Vendor page describing trust information.",
                        "artifact": {
                            "artifact_id": "sample-vendor-trust",
                            "artifact_type": "trust_center",
                        },
                    },
                    {
                        "source_id": "sample-vendor-dpa",
                        "source_type": "dpa",
                        "title_native": "Sample Vendor DPA",
                        "title_en": "Sample Vendor DPA",
                        "source_url": "https://sample.example/dpa",
                        "source_language": "en",
                        "summary_native": "Public Sample Vendor DPA metadata reference.",
                        "summary_en": "Public Sample Vendor DPA metadata reference.",
                        "artifact": {
                            "artifact_id": "sample-vendor-dpa",
                            "artifact_type": "dpa",
                        },
                    },
                ],
            }
        ],
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_catalog_batch_generates_vendor_sources_artifacts_and_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_batch, "ROOT", tmp_path)
    manifest_path = tmp_path / "batch.yaml"
    write_manifest(manifest_path, sample_manifest())

    assert catalog_batch.generate_catalog_batch(manifest_path) == 0

    vendor_path = tmp_path / "data/vendors/sample-vendor/vendor.yaml"
    source_path = tmp_path / "data/vendors/sample-vendor/sources/sample-vendor-trust.yaml"
    artifact_path = tmp_path / "data/vendors/sample-vendor/artifacts/sample-vendor-trust.yaml"
    change_path = tmp_path / "data/vendors/sample-vendor/changes/p25-test-batch-sample-vendor-trust.yaml"
    second_source_path = tmp_path / "data/vendors/sample-vendor/sources/sample-vendor-dpa.yaml"

    assert vendor_path.exists()
    assert source_path.exists()
    assert artifact_path.exists()
    assert change_path.exists()
    assert second_source_path.exists()

    vendor = load_yaml(vendor_path)
    source = load_yaml(source_path)
    artifact = load_yaml(artifact_path)
    change = load_yaml(change_path)

    assert vendor["source_policy"] == {
        "public_sources_only": True,
        "gated_materials_excluded": True,
        "raw_documents_mirrored_by_default": False,
    }
    assert source["access_class"] == "public_web"
    assert source["rights_class"] == "metadata_only"
    assert source["not_advice"] is True
    assert artifact["hashes"]["raw_sha256"] == "sha256:TBD"
    assert artifact["storage"]["raw_document_stored"] is False
    assert artifact["not_advice"] is True
    assert change["change_type"] == "created"
    assert change["not_advice"] is True


def test_catalog_batch_rejects_existing_record_without_force(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_batch, "ROOT", tmp_path)
    manifest = sample_manifest()
    manifest_path = tmp_path / "batch.yaml"
    write_manifest(manifest_path, manifest)

    existing = tmp_path / "data/vendors/sample-vendor/vendor.yaml"
    existing.parent.mkdir(parents=True)
    existing.write_text("schema_version: 0.1.0\n", encoding="utf-8")

    assert catalog_batch.generate_catalog_batch(manifest_path) == 1


def test_catalog_batch_rejects_duplicate_source_url(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_batch, "ROOT", tmp_path)
    manifest = sample_manifest()
    second_vendor = dict(manifest["vendors"][0])
    second_vendor["vendor_id"] = "second-vendor"
    second_vendor["display_name"] = "Second Vendor"
    second_vendor["legal_name"] = "Second Vendor, Inc."
    second_vendor["sources"] = [dict(source) for source in second_vendor["sources"]]
    second_vendor["sources"][0]["source_id"] = "second-vendor-trust"
    second_vendor["sources"][0]["artifact"] = dict(second_vendor["sources"][0]["artifact"])
    second_vendor["sources"][0]["artifact"]["artifact_id"] = "second-vendor-trust"
    second_vendor["sources"][1]["source_id"] = "second-vendor-dpa"
    second_vendor["sources"][1]["source_url"] = "https://second.example/dpa"
    second_vendor["sources"][1]["artifact"] = dict(second_vendor["sources"][1]["artifact"])
    second_vendor["sources"][1]["artifact"]["artifact_id"] = "second-vendor-dpa"
    manifest["vendors"].append(second_vendor)

    failures = catalog_batch.validate_manifest_rules(manifest, force=False)

    assert any("duplicate source_url" in failure for failure in failures)


def test_catalog_batch_force_overwrites_existing_record(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_batch, "ROOT", tmp_path)
    manifest_path = tmp_path / "batch.yaml"
    write_manifest(manifest_path, sample_manifest())

    assert catalog_batch.generate_catalog_batch(manifest_path) == 0
    assert catalog_batch.generate_catalog_batch(manifest_path, force=True) == 0

    vendor = load_yaml(tmp_path / "data/vendors/sample-vendor/vendor.yaml")
    assert vendor["vendor_id"] == "sample-vendor"


def test_catalog_batch_refresh_requires_existing_records(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_batch, "ROOT", tmp_path)
    manifest = sample_manifest()
    manifest["operation"] = "refresh"
    manifest_path = tmp_path / "batch.yaml"
    write_manifest(manifest_path, manifest)

    assert catalog_batch.generate_catalog_batch(manifest_path) == 1
