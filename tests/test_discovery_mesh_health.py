from __future__ import annotations

from pathlib import Path

import yaml

from tools.openva.discovery_mesh_health import build_health_report, markdown_report


def write_vendor(root: Path, vendor_id: str, *, status: str = "active") -> None:
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": vendor_id.title(),
                "official_domains": [f"{vendor_id}.example"],
                "catalog_status": status,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def write_source(root: Path, vendor_id: str, source_type: str) -> None:
    path = root / "data" / "vendors" / vendor_id / "sources" / f"{vendor_id}-{source_type}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "source_id": f"{vendor_id}-{source_type}",
                "vendor_id": vendor_id,
                "source_type": source_type,
                "source_url": f"https://{vendor_id}.example/{source_type}",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def source_report() -> dict:
    return {
        "report_type": "source_discovery_report",
        "summary": {"vendors_checked": 2, "vendor_identity_signal_count": 3},
        "source_frontier_reports": [
            {
                "summary": {
                    "pages_attempted": 20,
                    "requests": 24,
                    "locator_signal_count": 8,
                    "delegated_host_count": 2,
                }
            },
            {
                "summary": {
                    "pages_attempted": 10,
                    "requests": 16,
                    "locator_signal_count": 2,
                    "delegated_host_count": 1,
                }
            },
        ],
        "vendors": [
            {
                "vendor_id": "alpha",
                "candidates": [
                    {"source_type_candidate": "dpa"},
                    {"source_type_candidate": "privacy_notice"},
                ],
            },
            {
                "vendor_id": "beta",
                "candidates": [{"source_type_candidate": "dpa"}],
            },
        ],
    }


def breadth_metrics() -> dict:
    return {
        "report_type": "vendor_breadth_provider_metrics",
        "summary": {
            "entity_count": 10,
            "signal_count": 15,
            "observation_count": 15,
            "provider_count": 3,
            "provider_entity_counts": {"directory": 7, "relationship_graph": 3},
            "provider_signal_counts": {"directory": 10, "relationship_graph": 5},
            "source_kind_counts": {"public_directory": 10, "relationship_graph": 5},
            "queue_state_counts": {
                "ready_for_source_discovery": 4,
                "needs_country": 3,
                "needs_domain": 2,
                "already_catalogued": 1,
            },
            "ready_for_source_discovery_count": 4,
            "catalog_vendor_count_cap": None,
        },
    }


def breadth_queue() -> dict:
    return {
        "report_type": "vendor_breadth_resolution_queue",
        "summary": {
            "queue_count": 10,
            "ready_for_source_discovery_count": 4,
            "state_counts": {
                "ready_for_source_discovery": 4,
                "needs_country": 3,
                "needs_domain": 2,
                "already_catalogued": 1,
            },
        },
        "items": [],
    }


def breadth_candidates(count: int = 4) -> dict:
    return {
        "report_type": "vendor_candidate_discovery_report",
        "summary": {"candidate_vendor_count": count, "catalog_vendor_count_cap": None},
        "vendor_candidates": [],
    }


def promotion_plan(action_count: int = 2) -> dict:
    return {
        "actions": [
            {
                "action": "promote_candidate_source_for_review",
                "vendor_id": f"vendor-{index}",
            }
            for index in range(action_count)
        ]
    }


def replenishment_run(changed: list[str] | None = None) -> dict:
    return {
        "report_type": "vendor_breadth_replenishment_run",
        "summary": {
            "input_signal_count": 3,
            "skipped_input_count": 0,
            "changed_outputs": changed or [],
            "unchanged_outputs": [],
        },
    }


def test_health_report_separates_catalog_discovery_breadth_and_promotion(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    write_vendor(tmp_path, "beta", status="machine_provisional")
    write_vendor(tmp_path, "gamma")
    write_source(tmp_path, "alpha", "dpa")
    write_source(tmp_path, "alpha", "privacy_notice")
    write_source(tmp_path, "beta", "security_page")

    report = build_health_report(
        root=tmp_path,
        source_discovery_report=source_report(),
        breadth_metrics=breadth_metrics(),
        breadth_queue=breadth_queue(),
        breadth_candidates=breadth_candidates(),
        promotion_plan=promotion_plan(),
        replenishment_run=replenishment_run(["ledger", "queue"]),
        generated_at="2026-07-10T12:00:00Z",
    )

    assert report["status"] == "healthy"
    assert report["catalog"]["vendor_count"] == 3
    assert report["catalog"]["active_vendor_count"] == 2
    assert report["catalog"]["machine_provisional_vendor_count"] == 1
    assert report["catalog"]["source_count"] == 3
    assert report["catalog"]["vendors_with_any_source_pct"] == 66.667
    assert report["source_discovery"]["requests"] == 40
    assert report["source_discovery"]["locator_signal_count"] == 10
    assert report["source_discovery"]["verified_candidate_count"] == 3
    assert report["efficiency"]["locator_signals_per_request"] == 0.25
    assert report["efficiency"]["verified_candidates_per_request"] == 0.075
    assert report["efficiency"]["viable_promotions_per_verified_candidate"] == 0.666667
    assert report["vendor_breadth"]["ready_for_source_discovery_count"] == 4
    assert report["vendor_breadth"]["unresolved_identity_count"] == 5
    assert report["promotion"]["viable_action_count"] == 2
    assert report["intake"]["intake_needed"] is True
    assert report["success_metrics"]["catalog_vendor_count_cap"] is None
    assert report["posture"]["vendor_risk_scoring_performed"] is False


def test_health_report_identifies_true_noop_run(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    report_data = source_report()
    report_data["vendors"] = []
    report_data["summary"]["vendors_checked"] = 1
    report_data["source_frontier_reports"] = [
        {
            "summary": {
                "pages_attempted": 1,
                "requests": 1,
                "locator_signal_count": 1,
                "delegated_host_count": 0,
            }
        }
    ]

    report = build_health_report(
        root=tmp_path,
        source_discovery_report=report_data,
        breadth_metrics=breadth_metrics(),
        breadth_queue=breadth_queue(),
        breadth_candidates=breadth_candidates(),
        promotion_plan=promotion_plan(0),
        replenishment_run=replenishment_run([]),
    )

    assert report["intake"] == {
        "intake_needed": False,
        "no_op_run": True,
        "reason": "no_viable_source_promotions_and_breadth_state_unchanged",
    }


def test_health_report_flags_missing_metrics_and_zero_locator_yield(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    report_data = source_report()
    report_data["source_frontier_reports"] = [
        {
            "summary": {
                "pages_attempted": 10,
                "requests": 20,
                "locator_signal_count": 0,
                "delegated_host_count": 0,
            }
        }
    ]
    report_data["vendors"] = []

    report = build_health_report(
        root=tmp_path,
        source_discovery_report=report_data,
        breadth_metrics=None,
        breadth_queue=None,
        breadth_candidates=None,
        promotion_plan=promotion_plan(0),
        replenishment_run=replenishment_run([]),
    )

    assert report["status"] == "attention"
    assert "requests_without_locator_signals" in report["reason_codes"]
    assert "breadth_metrics_unavailable" in report["reason_codes"]


def test_health_report_flags_projection_mismatch(tmp_path: Path) -> None:
    report = build_health_report(
        root=tmp_path,
        source_discovery_report=source_report(),
        breadth_metrics=breadth_metrics(),
        breadth_queue=breadth_queue(),
        breadth_candidates=breadth_candidates(3),
        promotion_plan=promotion_plan(0),
        replenishment_run=replenishment_run([]),
    )

    assert report["status"] == "attention"
    assert "breadth_candidate_projection_count_mismatch" in report["reason_codes"]


def test_markdown_exposes_load_bearing_success_metrics(tmp_path: Path) -> None:
    report = build_health_report(
        root=tmp_path,
        source_discovery_report=source_report(),
        breadth_metrics=breadth_metrics(),
        breadth_queue=breadth_queue(),
        breadth_candidates=breadth_candidates(),
        promotion_plan=promotion_plan(1),
        replenishment_run=replenishment_run(["candidates"]),
    )

    text = markdown_report(report)

    assert "# Discovery Mesh Health" in text
    assert "Locator signals per request" in text
    assert "Verified candidates per request" in text
    assert "Viable promotions per verified candidate" in text
    assert "Unresolved identities retained" in text
    assert "Catalog vendor cap: `none`" in text
    assert "does not score vendors" in text
