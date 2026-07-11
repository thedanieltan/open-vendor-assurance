from __future__ import annotations

import json
from pathlib import Path

from tools.openva.vendor_candidate_discovery import build_vendor_candidate_report

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_breadth_projection_is_resolved_against_selected_root(tmp_path: Path) -> None:
    # The taxonomy control file is resolved against the SELECTED root too, so the
    # isolated fixture root carries a verbatim copy of the real control surface.
    taxonomy = tmp_path / "config" / "category-taxonomy.yaml"
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.write_text(
        (REPO_ROOT / "config" / "category-taxonomy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    queue = tmp_path / "maintenance" / "queues" / "catalog-growth-discovery.json"
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
                    "target_vendor_candidates": 1,
                    "max_vendors_per_discovery_run": 1,
                    "max_candidate_sources_per_report": 1,
                    "max_reviewed_actions_per_plan": 1,
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
            }
        ),
        encoding="utf-8",
    )
    projection = tmp_path / "maintenance" / "generated" / "vendor-breadth-candidates.json"
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text(
        json.dumps(
            {
                "report_type": "vendor_candidate_discovery_report",
                "vendor_candidates": [
                    {
                        "candidate_vendor_id": "isolated-vendor",
                        "display_name_candidate": "Isolated Vendor",
                        "official_domain_candidate": "isolated.example",
                        "headquarters_country_candidate": "SG",
                        "requires_review": True,
                        "writes_canonical_vendors": False,
                        "non_advisory": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_vendor_candidate_report(queue_path=queue, root=tmp_path)

    assert [row["candidate_vendor_id"] for row in report["vendor_candidates"]] == ["isolated-vendor"]
