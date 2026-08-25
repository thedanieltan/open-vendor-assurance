from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.openva.discovery_cycle import build_bundle_manifest, select_rotating_workset


def candidate(index: int, *, priority: int = 0) -> dict[str, object]:
    return {
        "candidate_vendor_id": f"vendor-{index:02d}",
        "display_name_candidate": f"Vendor {index:02d}",
        "official_domain_candidate": f"vendor-{index:02d}.example",
        "coverage_lane": "test",
        "cohort_id": "test-cohort",
        "priority": priority,
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }


def report(count: int) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "report_type": "vendor_candidate_discovery_report",
        "vendor_candidates": [candidate(index, priority=count - index) for index in range(count)],
    }


def test_rotating_workset_covers_every_candidate_without_first_page_starvation(tmp_path: Path) -> None:
    source = report(11)
    seen: list[str] = []
    for cycle_number in range(1, 4):
        selected = select_rotating_workset(
            source,
            limit=4,
            cycle_number=cycle_number,
            root=tmp_path,
            generated_at="2026-08-26T00:00:00Z",
            source_run_id="123",
        )
        seen.extend(str(row["candidate_vendor_id"]) for row in selected["vendor_candidates"])

    assert len(seen) == 11
    assert len(set(seen)) == 11
    assert set(seen) == {f"vendor-{index:02d}" for index in range(11)}


def test_rotating_workset_wraps_after_last_bucket(tmp_path: Path) -> None:
    source = report(9)
    first = select_rotating_workset(source, limit=4, cycle_number=1, root=tmp_path)
    wrapped = select_rotating_workset(source, limit=4, cycle_number=4, root=tmp_path)
    assert first["vendor_candidates"] == wrapped["vendor_candidates"]
    assert first["summary"]["rotation_bucket_index"] == 0
    assert wrapped["summary"]["rotation_bucket_index"] == 0


def test_rotating_workset_filters_current_catalog_identity(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "data" / "vendors" / "vendor-00"
    vendor_dir.mkdir(parents=True)
    (vendor_dir / "vendor.yaml").write_text(
        yaml.safe_dump(
            {
                "vendor_id": "vendor-00",
                "official_domains": ["vendor-00.example"],
                "public_entrypoints": ["https://vendor-00.example"],
            }
        ),
        encoding="utf-8",
    )

    selected = select_rotating_workset(report(3), limit=10, cycle_number=1, root=tmp_path)
    ids = [row["candidate_vendor_id"] for row in selected["vendor_candidates"]]
    assert ids == ["vendor-01", "vendor-02"]
    assert selected["summary"]["filtered_known_count"] == 1


def test_rotating_workset_rejects_non_positive_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        select_rotating_workset(report(1), limit=0, cycle_number=1, root=tmp_path)
    with pytest.raises(ValueError, match="cycle_number must be positive"):
        select_rotating_workset(report(1), limit=1, cycle_number=0, root=tmp_path)


def test_bundle_manifest_binds_exact_file_bytes(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    eligibility = tmp_path / "eligibility.json"
    plan.write_text(json.dumps({"actions": [1]}, sort_keys=True), encoding="utf-8")
    eligibility.write_text(json.dumps({"summary": {"ready": 1}}, sort_keys=True), encoding="utf-8")

    first = build_bundle_manifest(
        {"plan": plan, "eligibility": eligibility},
        source_run_id="123456",
        source_run_attempt=2,
        source_commit_sha="a" * 40,
        cycle_number=7,
        generated_at="2026-08-26T00:00:00Z",
    )
    second = build_bundle_manifest(
        {"eligibility": eligibility, "plan": plan},
        source_run_id="123456",
        source_run_attempt=2,
        source_commit_sha="a" * 40,
        cycle_number=7,
        generated_at="2026-08-26T00:00:00Z",
    )
    assert first == second
    assert first["bundle_digest"].startswith("sha256:")
    assert first["files"]["plan"]["digest"].startswith("sha256:")

    plan.write_text(json.dumps({"actions": [1, 2]}, sort_keys=True), encoding="utf-8")
    changed = build_bundle_manifest(
        {"plan": plan, "eligibility": eligibility},
        source_run_id="123456",
        source_run_attempt=2,
        source_commit_sha="a" * 40,
        cycle_number=7,
        generated_at="2026-08-26T00:00:00Z",
    )
    assert changed["bundle_digest"] != first["bundle_digest"]
    assert changed["files"]["plan"]["digest"] != first["files"]["plan"]["digest"]
