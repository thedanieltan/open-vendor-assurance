from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.openva.vendor_candidate_discovery import build_vendor_candidate_report

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_category_taxonomy(root: Path) -> None:
    # vendor_candidate_discovery resolves config/category-taxonomy.yaml against the
    # SELECTED root (root isolation), so every fixture root must carry the control
    # file; the real taxonomy is copied verbatim so the fixture stays aligned with
    # the actual control surface instead of inventing a divergent minimal shape.
    target = root / "config" / "category-taxonomy.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = REPO_ROOT / "config" / "category-taxonomy.yaml"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def write_queue(root: Path, target: int = 1) -> Path:
    write_category_taxonomy(root)
    queue = root / "maintenance" / "queues" / "catalog-growth-discovery.json"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "queue_type": "catalog_growth_discovery_queue",
                "non_advisory": True,
                "posture": {
                    "network_fetch_performed": False,
                    "writes_repository_state": False,
                    "writes_canonical_sources": False,
                    "creates_candidate_sources": False,
                },
                "limits": {
                    "target_vendor_candidates": target,
                    "max_vendors_per_discovery_run": 5,
                    "max_candidate_sources_per_report": 10,
                    "max_reviewed_actions_per_plan": 5,
                },
                "source_types": ["dpa"],
                "discovery_modes": ["seed_file_vendor_discovery"],
                "cohorts": [
                    {
                        "cohort_id": "fixture-cohort",
                        "coverage_lane": "cloud_platforms",
                        "target_vendor_candidates": 1,
                        "priority": "high",
                        "status": "queued",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return queue


def write_breadth_report(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "generated_at": "2026-07-10T11:00:00Z",
                "report_type": "vendor_candidate_discovery_report",
                "summary": {
                    "candidate_vendor_count": len(rows),
                    "catalog_vendor_count_cap": None,
                },
                "vendor_candidates": rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def breadth_candidate(index: int, *, domain: str | None = None) -> dict:
    return {
        "schema_version": "0.1.0",
        "candidate_vendor_id": f"signal-vendor-{index}",
        "display_name_candidate": f"Signal Vendor {index}",
        "official_domain_candidate": domain or f"signal-vendor-{index}.example",
        "headquarters_country_candidate": "SG",
        "coverage_lane": "signal_mesh",
        "cohort_id": "provider-replenishment",
        "source_index_url": f"https://{domain or f'signal-vendor-{index}.example'}",
        "vendor_category_candidates": [],
        "priority": index,
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }


def write_known_vendor(root: Path, vendor_id: str, domain: str) -> None:
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": vendor_id.title(),
                "official_domains": [domain],
                "previous_domains": [],
                "public_entrypoints": [f"https://{domain}"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_merges_provider_replenished_candidates_with_no_queue_target_cap(tmp_path: Path) -> None:
    queue = write_queue(tmp_path, target=1)
    breadth = tmp_path / "maintenance" / "generated" / "vendor-breadth-candidates.json"
    write_breadth_report(breadth, [breadth_candidate(index) for index in range(1_501)])

    report = build_vendor_candidate_report(
        queue_path=queue,
        root=tmp_path,
        breadth_candidate_path=breadth,
    )

    assert report["summary"]["candidate_vendor_count"] == 1_501
    assert report["summary"]["seed_candidate_count"] == 0
    assert report["summary"]["breadth_candidate_count"] == 1_501
    assert report["summary"]["catalog_vendor_count_cap"] is None
    assert len(report["vendor_candidates"]) == 1_501
    assert report["vendor_candidates"][0]["priority"] == 1_500


def test_breadth_candidates_are_normalized_for_existing_source_discovery(tmp_path: Path) -> None:
    queue = write_queue(tmp_path)
    breadth = tmp_path / "breadth.json"
    candidate = breadth_candidate(1)
    candidate["official_domain_candidate"] = "WWW.Signal-Vendor-1.Example"
    candidate["source_index_url"] = ""
    write_breadth_report(breadth, [candidate])

    report = build_vendor_candidate_report(
        queue_path=queue,
        root=tmp_path,
        breadth_candidate_path=breadth,
    )
    row = report["vendor_candidates"][0]

    assert row["official_domain_candidate"] == "signal-vendor-1.example"
    assert row["source_index_url"] == "https://signal-vendor-1.example"
    assert row["discovery_method"] == "provider_replenishment_mesh"
    assert row["requires_review"] is True
    assert row["writes_canonical_vendors"] is False
    assert row["non_advisory"] is True


def test_skips_breadth_identity_colliding_with_existing_catalog_domain(tmp_path: Path) -> None:
    queue = write_queue(tmp_path)
    write_known_vendor(tmp_path, "known", "known.example")
    breadth = tmp_path / "breadth.json"
    write_breadth_report(breadth, [breadth_candidate(1, domain="known.example")])

    report = build_vendor_candidate_report(
        queue_path=queue,
        root=tmp_path,
        breadth_candidate_path=breadth,
    )

    assert report["summary"]["breadth_candidate_count"] == 0
    assert report["summary"]["known_vendor_count"] == 1
    assert report["vendor_candidates"] == []


def test_deduplicates_breadth_candidates_by_domain(tmp_path: Path) -> None:
    queue = write_queue(tmp_path)
    breadth = tmp_path / "breadth.json"
    first = breadth_candidate(1, domain="shared.example")
    second = breadth_candidate(2, domain="shared.example")
    write_breadth_report(breadth, [first, second])

    report = build_vendor_candidate_report(
        queue_path=queue,
        root=tmp_path,
        breadth_candidate_path=breadth,
    )

    assert report["summary"]["breadth_candidate_count"] == 1
    assert len(report["vendor_candidates"]) == 1


def test_invalid_breadth_rows_fail_closed_without_blocking_valid_rows(tmp_path: Path) -> None:
    queue = write_queue(tmp_path)
    breadth = tmp_path / "breadth.json"
    invalid = breadth_candidate(1)
    invalid["headquarters_country_candidate"] = None
    invalid["requires_review"] = False
    write_breadth_report(breadth, [invalid, breadth_candidate(2)])

    report = build_vendor_candidate_report(
        queue_path=queue,
        root=tmp_path,
        breadth_candidate_path=breadth,
    )

    assert report["summary"]["invalid_breadth_candidate_count"] == 1
    assert report["summary"]["breadth_candidate_count"] == 1
    assert report["vendor_candidates"][0]["candidate_vendor_id"] == "signal-vendor-2"


def test_missing_breadth_projection_preserves_seed_only_behavior(tmp_path: Path) -> None:
    queue = write_queue(tmp_path)

    report = build_vendor_candidate_report(
        queue_path=queue,
        root=tmp_path,
        breadth_candidate_path=tmp_path / "does-not-exist.json",
    )

    assert report["summary"]["candidate_vendor_count"] == 0
    assert report["summary"]["breadth_candidate_count"] == 0
    assert report["summary"]["invalid_breadth_candidate_count"] == 0
