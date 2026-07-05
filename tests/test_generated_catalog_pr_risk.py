from __future__ import annotations

from tools.openva.generated_catalog_pr_risk import (
    GeneratedCatalogPrRiskClass,
    LATEST_OBSERVATIONS_PATH,
    classify_generated_catalog_pr_risk,
    is_generated_catalog_pr_low_risk_path,
    is_vendor_catalog_record_path,
    read_paths_file,
)


ALLOWED_GENERATED_CATALOG_PR_PATHS = [
    "data/vendors/guidewire/vendor.yaml",
    "data/vendors/guidewire/sources/guidewire-dpa.yaml",
    "data/vendors/guidewire/artifacts/guidewire-dpa.yaml",
    "data/vendors/guidewire/changes/candidate-promotion-guidewire-dpa.yaml",
    "dist/vendors/guidewire.json",
    "indexes/sources.json",
    "indexes/artifacts.json",
    "indexes/changes.json",
    "indexes/source-coverage.json",
    "indexes/summary.json",
    "indexes/vendor-match-index.json",
    "indexes/vendor-search.json",
    LATEST_OBSERVATIONS_PATH,
    "openva-pack.json",
]


def test_generated_catalog_pr_risk_allows_bounded_generated_catalog_surface() -> None:
    result = classify_generated_catalog_pr_risk(ALLOWED_GENERATED_CATALOG_PR_PATHS)

    assert result.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK
    assert result.low_risk is True
    assert result.reasons == ()
    assert result.unexpected_paths == ()


def test_generated_catalog_pr_risk_rejects_unexpected_control_plane_and_policy_paths() -> None:
    blocked = [
        ".github/workflows/candidate-promotion-pr.yml",
        "tools/openva/generated_catalog_pr_risk.py",
        "tests/test_generated_catalog_pr_risk.py",
        "config/automerge-policy.yaml",
        "docs/catalog-autonomy-policy.md",
        "maintenance/generated/strict-growth-promotion-plan.json",
        "maintenance/machine-decisions/2026-07.ndjson",
    ]

    result = classify_generated_catalog_pr_risk([*ALLOWED_GENERATED_CATALOG_PR_PATHS, *blocked])

    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.low_risk is False
    assert result.unexpected_paths == tuple(sorted(blocked))
    assert result.reasons == tuple(f"unexpected_path:{path}" for path in sorted(blocked))


def test_latest_observations_allowance_is_exact_not_a_broad_maintenance_glob() -> None:
    assert is_generated_catalog_pr_low_risk_path(LATEST_OBSERVATIONS_PATH)

    near_misses = [
        "maintenance/source-observations/events/2026-07.ndjson",
        "maintenance/source-observations/latest-observations.json.bak",
        "maintenance/source-observations/previous-observations.json",
        "maintenance/source-observations/nested/latest-observations.json",
    ]
    result = classify_generated_catalog_pr_risk(near_misses)

    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.unexpected_paths == tuple(sorted(near_misses))


def test_vendor_catalog_record_surface_is_canonical_and_not_broad_data_vendors() -> None:
    allowed = [
        "data/vendors/acme/vendor.yaml",
        "data/vendors/acme/sources/acme-security.yml",
        "data/vendors/acme/artifacts/acme-security.yaml",
        "data/vendors/acme/changes/acme-security.yaml",
    ]
    rejected = [
        "data/vendors/acme",
        "data/vendors/acme/notes.yaml",
        "data/vendors/acme/sources/nested/acme-security.yaml",
        "data/vendors/acme/private/acme-security.yaml",
        "data/vendors/acme/sources/.yaml",
    ]

    assert [path for path in allowed if not is_vendor_catalog_record_path(path)] == []
    assert [path for path in rejected if is_vendor_catalog_record_path(path)] == []


def test_generated_dist_allowance_is_vendor_json_not_broad_dist_tree() -> None:
    accepted = "dist/vendors/acme.json"
    rejected = [
        "dist/vendors/acme/sources.json",
        "dist/source-health.json",
        "dist/vendors/.json",
    ]

    assert is_generated_catalog_pr_low_risk_path(accepted)
    result = classify_generated_catalog_pr_risk(rejected)
    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.unexpected_paths == tuple(sorted(rejected))


def test_empty_generated_catalog_pr_diff_fails_closed() -> None:
    result = classify_generated_catalog_pr_risk([])

    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.reasons == ("no_changed_paths",)


def test_paths_file_reader_accepts_utf8_bom(tmp_path) -> None:
    paths_file = tmp_path / "changed-paths.txt"
    paths_file.write_text(
        "data/vendors/guidewire/sources/guidewire-dpa.yaml\nindexes/sources.json\n",
        encoding="utf-8-sig",
    )

    result = classify_generated_catalog_pr_risk(read_paths_file(str(paths_file)))

    assert result.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK
