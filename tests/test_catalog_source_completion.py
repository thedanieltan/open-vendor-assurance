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


def unavailable(base: Path, source_type: str, next_review_after: str) -> None:
    write_yaml(
        base / "unavailable_sources" / f"{source_type}.yaml",
        {
            "unavailable_source_id": f"{base.name}-{source_type}",
            "vendor_id": base.name,
            "source_type": source_type,
            "status": "not_identified",
            "next_review_after": next_review_after,
        },
    )


def test_canonical_alternative_resolves_group(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    for source_type in ("privacy_notice", "dpa", "subprocessors_list", "trust_center", "certification_reference"):
        source(base, f"example-{source_type}", source_type)
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["summary"]["complete_vendor_count"] == 1
    assert report["summary"]["unresolved_group_count"] == 0


def test_coverage_claim_resolves_additional_role(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    source(base, "example-privacy", "privacy_notice")
    source(base, "example-dpa", "dpa")
    source(base, "example-subprocessors", "subprocessors_list")
    source(
        base,
        "example-trust",
        "trust_center",
        claims=[
            {
                "role": "compliance_page",
                "coverage_type": "contains",
                "evidence": "The trust center contains the vendor's public compliance material.",
            }
        ],
    )
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["security"] == "canonical_source_or_claim"
    assert row["group_resolutions"]["compliance"] == "canonical_source_or_claim"
    assert row["complete"] is True


def test_all_alternatives_must_be_evidenced_unavailable(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    for source_type in ("privacy_notice", "dpa", "subprocessors_list"):
        source(base, f"example-{source_type}", source_type)
    unavailable(base, "security_page", "2026-10-12")
    unavailable(base, "compliance_page", "2026-10-12")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["security"] == "unresolved"
    assert row["group_resolutions"]["compliance"] == "unresolved"
    unavailable(base, "trust_center", "2026-10-12")
    unavailable(base, "certification_reference", "2026-10-12")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    row = report["vendors"][0]
    assert row["group_resolutions"]["security"] == "evidenced_unavailable"
    assert row["group_resolutions"]["compliance"] == "evidenced_unavailable"
    assert row["complete"] is True


def test_due_unavailable_record_does_not_resolve_group(tmp_path: Path) -> None:
    base = vendor(tmp_path)
    unavailable(base, "privacy_notice", "2026-07-14")
    report = build_report(tmp_path, today=date(2026, 7, 14), generated_at="2026-07-14T00:00:00Z")
    assert report["vendors"][0]["group_resolutions"]["privacy_notice"] == "unresolved"
