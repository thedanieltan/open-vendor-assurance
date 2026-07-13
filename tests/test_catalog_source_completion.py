from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from tools.openva.catalog_source_completion import build_report


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def vendor(root: Path, vendor_id: str = "example") -> Path:
    base = root / "data" / "vendors" / vendor_id
    write_yaml(base / "vendor.yaml", {"vendor_id": vendor_id, "display_name": "Example"})
    return base


def source(base: Path, source_id: str, source_type: str, *, claims: list[dict] | None = None) -> None:
    record = {"source_id": source_id, "vendor_id": base.name, "source_type": source_type}
    if claims:
        record["coverage_claims"] = claims
    write_yaml(base / "sources" / f"{source_id}.yaml", record)


def unavailable(base: Path, source_type: str, next_review_after: str = "2026-10-12") -> None:
    slug = source_type.replace("_", "-")
    write_yaml(
        base / "unavailable_sources" / f"{base.name}-{slug}.yaml",
        {
            "unavailable_source_id": f"{base.name}-{slug}",
            "vendor_id": base.name,
            "source_type": source_type,
            "status": "not_identified",
            "reviewed_at": "2026-07-14T00:00:00Z",
            "next_review_after": next_review_after,
        },
    )


def complete_live_foundation(base: Path) -> None:
    source(base, "example-privacy", "privacy_notice")
    source(base, "example-terms", "terms_of_service")
    source(base, "example-trust", "trust_center")


def test_current_main_contract_can_complete_vendor(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    complete_live_foundation(base)
    unavailable(base, "dpa")
    unavailable(base, "subprocessors_list")
    unavailable(base, "status_page")
    unavailable(base, "compliance_page")
    unavailable(base, "certification_reference")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["summary"]["group_cell_count"] == 7
    assert report["summary"]["complete_vendor_count"] == 1
    assert report["summary"]["unresolved_group_count"] == 0


def test_live_required_groups_do_not_accept_unavailable_records(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    unavailable(base, "privacy_notice")
    unavailable(base, "terms_of_service")
    unavailable(base, "security_page")
    unavailable(base, "trust_center")
    unavailable(base, "compliance_page")
    for source_type in ("dpa", "subprocessors_list", "status_page", "certification_reference"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["privacy_notice"] == "unresolved"
    assert row["group_resolutions"]["terms_of_service"] == "unresolved"
    assert row["group_resolutions"]["security_assurance"] == "unresolved"
    assert row["group_resolutions"]["compliance"] == "evidenced_unavailable"
    assert row["complete"] is False


def test_security_and_compliance_coverage_claims_resolve_groups(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
    source(base, "example-terms", "terms_of_service")
    source(
        base,
        "example-security",
        "security_page",
        claims=[
            {
                "role": "compliance_page",
                "coverage_type": "contains",
                "evidence": "The official security page contains the vendor's public compliance material.",
            }
        ],
    )
    for source_type in ("dpa", "subprocessors_list", "status_page"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["security_assurance"] == "canonical_source_or_claim"
    assert row["group_resolutions"]["compliance"] == "canonical_source_or_claim"
    assert row["complete"] is True


def test_compliance_unavailable_requires_all_alternatives(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    complete_live_foundation(base)
    for source_type in ("dpa", "subprocessors_list", "status_page"):
        unavailable(base, source_type)
    unavailable(base, "compliance_page")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["vendors"][0]["group_resolutions"]["compliance"] == "unresolved"
    unavailable(base, "certification_reference")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["vendors"][0]["group_resolutions"]["compliance"] == "evidenced_unavailable"


def test_due_unavailable_record_does_not_resolve_optional_group(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    complete_live_foundation(base)
    unavailable(base, "dpa", next_review_after="2026-07-14")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["vendors"][0]["group_resolutions"]["dpa"] == "unresolved"
