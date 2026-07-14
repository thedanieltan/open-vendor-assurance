import json

from tools.openva.catalog_guard import (
    validate_catalog_batch_duplicates,
    validate_catalog_generated_outputs,
    validate_catalog_paths,
    validate_catalog_pr,
    validate_changed_source_observations,
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
    assert validate_catalog_paths(["docs/new-policy.md"]) == [
        "docs/new-policy.md: catalog PR path is outside the allowed catalog-agent file set"
    ]


def test_catalog_generated_guard_requires_outputs_for_data_changes():
    assert validate_catalog_generated_outputs(
        ["data/vendors/example/sources/example.yaml"]
    ) == [
        "catalog data changed but generated outputs are absent; run python -m tools.openva.validate build-indexes, then commit openva-pack.json indexes/ dist/"
    ]


def test_catalog_generated_guard_accepts_data_changes_with_outputs():
    assert validate_catalog_generated_outputs(
        [
            "data/vendors/example/sources/example.yaml",
            "indexes/sources.json",
            "dist/vendors/example.json",
            "openva-pack.json",
        ]
    ) == []


def test_changed_source_observation_guard_requires_latest_baseline(tmp_path):
    source_path = tmp_path / "data/vendors/example/sources/example-source.yaml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "source_id: example-source\nvendor_id: example\nsource_url: https://example.com/legal\n",
        encoding="utf-8",
    )
    latest_path = tmp_path / "maintenance/source-observations/latest-observations.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(json.dumps({"sources": []}), encoding="utf-8")
    assert validate_changed_source_observations(
        ["data/vendors/example/sources/example-source.yaml"], root=tmp_path
    ) == [
        "data/vendors/example/sources/example-source.yaml: source_id example-source has no latest-observations baseline; verify the new source(s), run python -m tools.openva.observation_ledger build, install latest-observations.json, then commit maintenance/source-observations/latest-observations.json"
    ]


def test_changed_source_observation_guard_accepts_latest_baseline(tmp_path):
    source_path = tmp_path / "data/vendors/example/sources/example-source.yaml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "source_id: example-source\nvendor_id: example\nsource_url: https://example.com/legal\n",
        encoding="utf-8",
    )
    latest_path = tmp_path / "maintenance/source-observations/latest-observations.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(
        json.dumps({"sources": [{"source_id": "example-source"}]}),
        encoding="utf-8",
    )
    assert validate_changed_source_observations(
        ["data/vendors/example/sources/example-source.yaml"], root=tmp_path
    ) == []


def test_catalog_guard_does_not_require_predefined_source_categories(tmp_path):
    vendor_path = tmp_path / "data/vendors/example/vendor.yaml"
    source_path = tmp_path / "data/vendors/example/sources/example-security.yaml"
    vendor_path.parent.mkdir(parents=True)
    source_path.parent.mkdir(parents=True)
    vendor_path.write_text("vendor_id: example\n", encoding="utf-8")
    source_path.write_text(
        "source_id: example-security\nvendor_id: example\nsource_type: security_page\nsource_url: https://example.com/security\n",
        encoding="utf-8",
    )
    latest_path = tmp_path / "maintenance/source-observations/latest-observations.json"
    latest_path.parent.mkdir(parents=True)
    latest_path.write_text(
        json.dumps({"sources": [{"source_id": "example-security"}]}),
        encoding="utf-8",
    )
    assert validate_catalog_pr(
        [
            "data/vendors/example/vendor.yaml",
            "data/vendors/example/sources/example-security.yaml",
            "indexes/vendors.json",
        ],
        root=tmp_path,
    ) == []


def test_catalog_batch_guard_rejects_duplicate_vendor_id_in_manifest(tmp_path):
    batch_path = tmp_path / "catalog-batches/example.yaml"
    batch_path.parent.mkdir(parents=True)
    batch_path.write_text(
        "vendors:\n  - vendor_id: duplicate\n  - vendor_id: duplicate\n",
        encoding="utf-8",
    )
    assert validate_catalog_batch_duplicates(
        ["catalog-batches/example.yaml"], root=tmp_path
    ) == ["catalog-batches/example.yaml: duplicate: duplicate vendor_id in batch manifest"]


def test_catalog_batch_guard_rejects_vendor_id_already_in_catalog(tmp_path):
    batch_path = tmp_path / "catalog-batches/example.yaml"
    batch_path.parent.mkdir(parents=True)
    batch_path.write_text("vendors:\n  - vendor_id: existing-vendor\n", encoding="utf-8")
    existing_vendor_path = tmp_path / "data/vendors/existing-vendor/vendor.yaml"
    existing_vendor_path.parent.mkdir(parents=True)
    existing_vendor_path.write_text("vendor_id: existing-vendor\n", encoding="utf-8")
    assert validate_catalog_batch_duplicates(
        ["catalog-batches/example.yaml"], root=tmp_path
    ) == [
        "catalog-batches/example.yaml: existing-vendor: vendor_id already exists at data/vendors/existing-vendor/vendor.yaml"
    ]
