import json

import yaml

from tools.openva.catalog_guard import (
    validate_catalog_batch_duplicates,
    validate_catalog_generated_outputs,
    validate_catalog_paths,
    validate_changed_source_observations,
    validate_changed_vendor_completeness,
)


def test_catalog_guard_allows_catalog_files():
    failures = validate_catalog_paths(
        [
            "catalog-batches/p26-project-management-saas.yaml",
            "data/vendors/example/vendor.yaml",
            "data/vendors/example/sources/example-source.yaml",
            "indexes/vendors.json",
            "dist/vendors/example.json",
            "openva-pack.json",
            "maintenance/generated/strict-growth-promotion-plan.json",
            "maintenance/generated/strict-growth-eligibility-report.json",
            "maintenance/source-observations/latest-observations.json",
            "maintenance/applied/applied-plans.json",
            "docs/coverage-map.md",
            "docs/vendor-expansion-backlog.md",
        ]
    )

    assert failures == []


def test_catalog_guard_rejects_substrate_files():
    failures = validate_catalog_paths(
        [
            "schemas/openva/source-reference.schema.json",
            "tools/openva/validate.py",
            "tests/test_validate.py",
            ".github/workflows/validate.yml",
            "policy/scope.md",
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "LICENSE",
            ".github/CODEOWNERS",
        ]
    )

    assert len(failures) == 10
    assert all("must not modify" in failure for failure in failures)


def test_catalog_guard_rejects_unknown_docs():
    failures = validate_catalog_paths(["docs/new-policy.md"])

    assert failures == ["docs/new-policy.md: catalog PR path is outside the allowed catalog-agent file set"]


def test_catalog_generated_guard_requires_outputs_for_data_changes():
    failures = validate_catalog_generated_outputs(["data/vendors/example/sources/example.yaml"])

    assert failures == [
        "catalog data changed but generated outputs are absent; run python -m tools.openva.validate build-indexes, then commit openva-pack.json indexes/ dist/"
    ]


def test_catalog_generated_guard_accepts_data_changes_with_outputs():
    failures = validate_catalog_generated_outputs(
        [
            "data/vendors/example/sources/example.yaml",
            "indexes/sources.json",
            "dist/vendors/example.json",
            "openva-pack.json",
        ]
    )

    assert failures == []


def test_changed_source_observation_guard_requires_latest_baseline(tmp_path):
    source_path = tmp_path / "data" / "vendors" / "example" / "sources" / "example-source.yaml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        """
source_id: example-source
vendor_id: example
source_url: https://example.com/legal
""".lstrip(),
        encoding="utf-8",
    )
    latest_path = tmp_path / "maintenance" / "source-observations" / "latest-observations.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(json.dumps({"sources": []}), encoding="utf-8")

    failures = validate_changed_source_observations(["data/vendors/example/sources/example-source.yaml"], root=tmp_path)

    assert failures == [
        "data/vendors/example/sources/example-source.yaml: source_id example-source has no latest-observations baseline; verify the new source(s), run python -m tools.openva.observation_ledger build, install latest-observations.json, then commit maintenance/source-observations/latest-observations.json"
    ]


def test_changed_source_observation_guard_accepts_latest_baseline(tmp_path):
    source_path = tmp_path / "data" / "vendors" / "example" / "sources" / "example-source.yaml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        """
source_id: example-source
vendor_id: example
source_url: https://example.com/legal
""".lstrip(),
        encoding="utf-8",
    )
    latest_path = tmp_path / "maintenance" / "source-observations" / "latest-observations.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(json.dumps({"sources": [{"source_id": "example-source"}]}), encoding="utf-8")

    failures = validate_changed_source_observations(["data/vendors/example/sources/example-source.yaml"], root=tmp_path)

    assert failures == []


def write_source(root, vendor_id, source_id, source_type):
    path = root / "data" / "vendors" / vendor_id / "sources" / f"{source_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "source_id": source_id,
                "vendor_id": vendor_id,
                "source_type": source_type,
                "source_url": f"https://example.com/{source_id}",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def write_unavailable(root, vendor_id, source_type):
    path = root / "data" / "vendors" / vendor_id / "unavailable_sources" / f"{vendor_id}-{source_type}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "unavailable_source_id": f"{vendor_id}-{source_type}",
                "vendor_id": vendor_id,
                "source_type": source_type,
                "status": "not_identified",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def write_vendor(root, vendor_id="example"):
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"vendor_id: {vendor_id}\n", encoding="utf-8")


def test_changed_vendor_completeness_requires_live_privacy_and_two_live_groups(tmp_path):
    write_vendor(tmp_path)
    write_unavailable(tmp_path, "example", "privacy_notice")
    write_source(tmp_path, "example", "example-terms", "terms_of_service")
    write_unavailable(tmp_path, "example", "security_page")
    write_unavailable(tmp_path, "example", "dpa")
    write_unavailable(tmp_path, "example", "subprocessors_list")
    write_unavailable(tmp_path, "example", "status_page")

    failures = validate_changed_vendor_completeness(
        ["data/vendors/example/vendor.yaml", "data/vendors/example/sources/example-terms.yaml"],
        root=tmp_path,
    )

    assert failures == [
        "data/vendors/example: incomplete privacy_notice coverage; requires a live canonical public source",
        "data/vendors/example: insufficient live source breadth; requires at least 2 live core assurance groups",
    ]


def test_changed_vendor_completeness_accepts_live_or_unavailable_core_groups(tmp_path):
    write_vendor(tmp_path)
    write_source(tmp_path, "example", "example-privacy", "privacy_notice")
    write_source(tmp_path, "example", "example-terms", "terms_of_service")
    write_source(tmp_path, "example", "example-trust", "trust_center")
    write_unavailable(tmp_path, "example", "dpa")
    write_unavailable(tmp_path, "example", "subprocessors_list")
    write_unavailable(tmp_path, "example", "status_page")

    failures = validate_changed_vendor_completeness(
        ["data/vendors/example/vendor.yaml", "data/vendors/example/sources/example-privacy.yaml"],
        root=tmp_path,
    )

    assert failures == []


def test_changed_vendor_completeness_accepts_unavailable_terms_and_security_with_live_status(tmp_path):
    write_vendor(tmp_path)
    write_source(tmp_path, "example", "example-privacy", "privacy_notice")
    write_source(tmp_path, "example", "example-status", "status_page")
    write_unavailable(tmp_path, "example", "terms_of_service")
    write_unavailable(tmp_path, "example", "security_page")
    write_unavailable(tmp_path, "example", "dpa")
    write_unavailable(tmp_path, "example", "subprocessors_list")

    failures = validate_changed_vendor_completeness(
        ["data/vendors/example/vendor.yaml", "data/vendors/example/sources/example-status.yaml"],
        root=tmp_path,
    )

    assert failures == []


def test_changed_vendor_completeness_ignores_untouched_incomplete_vendor(tmp_path):
    write_vendor(tmp_path, "untouched")

    failures = validate_changed_vendor_completeness(
        ["data/vendors/example/sources/example-privacy.yaml"],
        root=tmp_path,
    )

    assert failures == []


def test_catalog_batch_guard_rejects_duplicate_vendor_id_in_manifest(tmp_path):
    batch_path = tmp_path / "catalog-batches" / "example.yaml"
    batch_path.parent.mkdir(parents=True)
    batch_path.write_text(
        """
vendors:
  - vendor_id: duplicate
  - vendor_id: duplicate
""".lstrip(),
        encoding="utf-8",
    )

    failures = validate_catalog_batch_duplicates(["catalog-batches/example.yaml"], root=tmp_path)

    assert failures == ["catalog-batches/example.yaml: duplicate: duplicate vendor_id in batch manifest"]


def test_catalog_batch_guard_rejects_vendor_id_already_in_catalog(tmp_path):
    batch_path = tmp_path / "catalog-batches" / "example.yaml"
    batch_path.parent.mkdir(parents=True)
    batch_path.write_text(
        """
vendors:
  - vendor_id: existing-vendor
""".lstrip(),
        encoding="utf-8",
    )
    existing_vendor_path = tmp_path / "data" / "vendors" / "existing-vendor" / "vendor.yaml"
    existing_vendor_path.parent.mkdir(parents=True)
    existing_vendor_path.write_text("vendor_id: existing-vendor\n", encoding="utf-8")

    failures = validate_catalog_batch_duplicates(["catalog-batches/example.yaml"], root=tmp_path)

    assert failures == [
        "catalog-batches/example.yaml: existing-vendor: vendor_id already exists at data/vendors/existing-vendor/vendor.yaml"
    ]
