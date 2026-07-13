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


def test_complete_vendor_accepts_honest_unavailable_core_groups(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
    source(base, "example-status", "status_page")
    for source_type in ("terms_of_service", "security_page", "dpa", "subprocessors_list", "compliance_page"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert report["summary"]["group_cell_count"] == 7
    assert row["privacy_live"] is True
    assert row["live_core_group_count"] == 2
    assert row["group_resolutions"]["terms_of_service"] == "evidenced_unavailable"
    assert row["group_resolutions"]["security_assurance"] == "evidenced_unavailable"
    assert row["complete"] is True


def test_privacy_must_remain_live(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    unavailable(base, "privacy_notice")
    source(base, "example-terms", "terms_of_service")
    source(base, "example-status", "status_page")
    for source_type in ("security_page", "dpa", "subprocessors_list", "compliance_page"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["privacy_notice"] == "unresolved"
    assert row["privacy_live"] is False
    assert "privacy_notice_requires_live_source" in row["completion_failures"]
    assert row["complete"] is False


def test_minimum_two_live_core_groups_is_enforced(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
    for source_type in ("terms_of_service", "security_page", "dpa", "subprocessors_list", "status_page", "compliance_page"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["unresolved_groups"] == []
    assert row["live_core_group_count"] == 1
    assert "minimum_live_core_group_breadth_not_met" in row["completion_failures"]
    assert row["complete"] is False


def test_security_and_compliance_coverage_claims_resolve_groups(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
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
    for source_type in ("terms_of_service", "dpa", "subprocessors_list", "status_page"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["security_assurance"] == "canonical_source_or_claim"
    assert row["group_resolutions"]["compliance"] == "canonical_source_or_claim"
    assert row["live_core_group_count"] == 2
    assert row["complete"] is True


def test_one_current_unavailable_record_resolves_alternative_group(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
    source(base, "example-terms", "terms_of_service")
    for source_type in ("security_page", "dpa", "subprocessors_list", "status_page", "compliance_page"):
        unavailable(base, source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["security_assurance"] == "evidenced_unavailable"
    assert row["group_resolutions"]["compliance"] == "evidenced_unavailable"
    assert row["complete"] is True


def test_due_unavailable_record_does_not_resolve_group(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
    source(base, "example-terms", "terms_of_service")
    unavailable(base, "dpa", next_review_after="2026-07-14")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["vendors"][0]["group_resolutions"]["dpa"] == "unresolved"
