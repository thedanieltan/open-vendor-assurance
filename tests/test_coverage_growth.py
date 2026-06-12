import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from tools.openva.contribution_intake import ADVISORY_RE
from tools.openva.coverage_growth import (
    DOCTRINE,
    QUEUE_CLASSES,
    build_coverage_growth_report,
    high_priority_categories,
    load_targets_config,
    render_markdown,
)
from tools.openva.observation_ledger import load_sla_config

NOW = datetime(2026, 6, 12, 6, 0, 0, tzinfo=UTC)
GENERATED_AT = "2026-06-12T06:00:00Z"

REPO_TARGETS = load_targets_config(Path("config/coverage-targets.yaml"))
REPO_SLA = load_sla_config(Path("config/observation-sla.yaml"))

TARGETS = {
    "schema_version": "0.1.0",
    "required_source_types": ["trust_center", "dpa", "subprocessors_list"],
    "source_type_criticality": {"dpa": 3, "subprocessors_list": 3, "trust_center": 2},
    "staleness_weights": {"fresh": 0, "unknown": 1, "stale": 2, "expired": 3},
    "prevalence_weight": 2,
    "categories": {
        "cloud": {
            "weight": 5,
            "taxonomy_tags": ["cloud_infrastructure"],
            "priority_vendors": [
                {"vendor_id": "example-cloud", "name": "Example Cloud"},
                {"vendor_id": "missing-cloud", "name": "Missing Cloud"},
            ],
        },
        "sme_common_tools": {
            "weight": 3,
            "taxonomy_tags": ["productivity_software"],
            "priority_vendors": [],
        },
    },
}

SLA = {
    "schema_version": "0.1.0",
    "default": {"stale_after_days": 30, "expired_after_days": 90},
    "source_type_overrides": {},
}


def write_vendor(tmp_path: Path, vendor_id: str, categories: list[str]) -> None:
    vendor_dir = tmp_path / "data" / "vendors" / vendor_id
    vendor_dir.mkdir(parents=True, exist_ok=True)
    (vendor_dir / "vendor.yaml").write_text(
        yaml.safe_dump(
            {
                "vendor_id": vendor_id,
                "display_name": vendor_id.replace("-", " ").title(),
                "official_domains": [f"{vendor_id}.example"],
                "vendor_categories": categories,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def write_source(
    tmp_path: Path,
    vendor_id: str,
    source_type: str,
    *,
    machine_readable: bool | None = None,
    confidence_class: str | None = None,
) -> str:
    source_id = f"{vendor_id}-{source_type.replace('_', '-')}"
    source_dir = tmp_path / "data" / "vendors" / vendor_id / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_type": source_type,
        "source_url": f"https://{vendor_id}.example/{source_type}",
    }
    if machine_readable is not None:
        record["retrieval"] = {"method": "html_page", "machine_readable": machine_readable}
    if confidence_class:
        record["canonical_confidence"] = {"class": confidence_class}
    (source_dir / f"{source_id}.yaml").write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return source_id


def write_candidate(tmp_path: Path, vendor_id: str, name: str) -> None:
    candidate_dir = tmp_path / "data" / "vendors" / vendor_id / "candidate_sources"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / f"{name}.yaml").write_text(
        yaml.safe_dump({"vendor_id": vendor_id, "candidate_source_id": name}, sort_keys=False),
        encoding="utf-8",
    )


def make_repo(tmp_path: Path) -> Path:
    # example-cloud: cloud category, on the wishlist, has dpa + trust_center,
    # missing subprocessors_list.
    write_vendor(tmp_path, "example-cloud", ["cloud_infrastructure"])
    write_source(tmp_path, "example-cloud", "dpa", machine_readable=False)
    write_source(tmp_path, "example-cloud", "trust_center", machine_readable=True)
    write_candidate(tmp_path, "example-cloud", "example-cloud-candidate-1")
    # example-tools: low-priority category, complete required set.
    write_vendor(tmp_path, "example-tools", ["productivity_software"])
    for source_type in ("trust_center", "dpa", "subprocessors_list"):
        write_source(tmp_path, "example-tools", source_type, machine_readable=True)
    # example-uncategorized: no priority category, ambiguous source.
    write_vendor(tmp_path, "example-uncategorized", [])
    write_source(tmp_path, "example-uncategorized", "privacy_notice", confidence_class="ambiguous")
    return tmp_path


def run_artifact(observed_at: str, *, health: str = "reachable") -> dict:
    return {
        "sources": [
            {
                "source_id": "example-cloud-dpa",
                "vendor_id": "example-cloud",
                "observed_at": observed_at,
                "source_health_status": health,
            }
        ]
    }


def build(tmp_path: Path, **kwargs) -> dict:
    return build_coverage_growth_report(
        root=tmp_path,
        targets=TARGETS,
        sla_config=SLA,
        now=NOW,
        generated_at=GENERATED_AT,
        ledger_dir=tmp_path / "maintenance" / "source-observations" / "events",
        **kwargs,
    )


def queue_rows(report: dict, queue_class: str) -> list[dict]:
    return [row for row in report["growth_queue"] if row["queue_class"] == queue_class]


def test_repo_targets_config_maps_to_real_taxonomy_and_schema():
    taxonomy = yaml.safe_load(Path("config/category-taxonomy.yaml").read_text(encoding="utf-8"))
    taxonomy_tags = set(taxonomy["vendor_categories"].keys())
    schema = json.loads(Path("schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))
    source_types = set(schema["properties"]["source_type"]["enum"])

    for name, spec in REPO_TARGETS["categories"].items():
        for tag in spec["taxonomy_tags"]:
            assert tag in taxonomy_tags, (name, tag)
        assert isinstance(spec.get("priority_vendors"), list), name
    for required in REPO_TARGETS["required_source_types"]:
        assert required in source_types, required
        assert required in REPO_TARGETS["source_type_criticality"], required
    assert "status_page" in source_types
    assert set(REPO_TARGETS["staleness_weights"]) == {"fresh", "unknown", "stale", "expired"}


def test_high_priority_categories_are_explicit_weight_threshold():
    assert high_priority_categories(TARGETS) == ["cloud"]
    repo_high = high_priority_categories(REPO_TARGETS)
    assert all(int(REPO_TARGETS["categories"][name]["weight"]) >= 5 for name in repo_high)
    assert repo_high  # at least one explicit high-priority category


def test_vendor_count_and_completeness_by_category(tmp_path):
    report = build(make_repo(tmp_path))

    assert report["vendor_count_by_category"] == {"cloud": 1, "sme_common_tools": 1, "uncategorized": 1}
    cloud = report["source_completeness_by_category"]["cloud"]
    assert cloud["vendor_count"] == 1
    assert cloud["complete_vendors"] == 0
    assert cloud["by_source_type"]["subprocessors_list"]["vendors_with_source"] == 0
    assert cloud["by_source_type"]["dpa"]["ratio"] == 1.0
    tools = report["source_completeness_by_category"]["sme_common_tools"]
    assert tools["complete_vendors"] == 1


def test_named_gap_sections_list_missing_vendors(tmp_path):
    report = build(make_repo(tmp_path))

    missing_subs = {row["vendor_id"] for row in report["missing_subprocessor_sources"]}
    assert "example-cloud" in missing_subs
    assert "example-tools" not in missing_subs
    missing_dpa = {row["vendor_id"] for row in report["missing_dpa_sources"]}
    assert "example-uncategorized" in missing_dpa
    missing_tc = {row["vendor_id"] for row in report["missing_trust_centers"]}
    assert "example-uncategorized" in missing_tc


def test_missing_vendor_queue_from_wishlist(tmp_path):
    report = build(make_repo(tmp_path))
    rows = queue_rows(report, "missing_vendor")

    assert [row["vendor_id"] for row in rows] == ["missing-cloud"]
    row = rows[0]
    assert row["priority"] == 5 + 0 + 2 + 0
    assert row["route"] == "candidate_submission"
    assert report["top_missing_vendors"]["cloud"][0]["vendor_id"] == "missing-cloud"


def test_missing_source_type_queue_and_priority_breakdown(tmp_path):
    report = build(make_repo(tmp_path))
    rows = queue_rows(report, "missing_source_type")
    by_key = {(row["vendor_id"], row["source_type"]): row for row in rows}

    row = by_key[("example-cloud", "subprocessors_list")]
    # weight 5 + criticality 3 + prevalence 2 (wishlist) + staleness 0
    assert row["priority"] == 10
    assert row["priority_breakdown"] == {
        "category_weight": 5,
        "missing_source_criticality": 3,
        "business_prevalence": 2,
        "staleness": 0,
    }
    assert ("example-tools", "dpa") not in by_key  # complete vendor emits nothing


def test_high_priority_vendor_queue_only_for_weight_five_categories(tmp_path):
    report = build(make_repo(tmp_path))
    rows = queue_rows(report, "high_priority_vendor")

    assert [row["vendor_id"] for row in rows] == ["example-cloud"]
    assert rows[0]["priority"] == 5 + 3 + 2 + 0


def test_stale_source_queue_uses_run_artifact_freshness(tmp_path):
    make_repo(tmp_path)
    report = build(tmp_path, latest_observations=run_artifact("2026-04-01T00:00:00Z"))

    assert report["observation_input"] == "run_artifact"
    stale = {row["source_id"]: row for row in report["stale_high_priority_sources"]}
    # dpa observed 72 days ago -> stale; trust_center never observed -> unknown.
    assert stale["example-cloud-dpa"]["freshness_status"] == "stale"
    assert stale["example-cloud-trust-center"]["freshness_status"] == "unknown"

    rows = {row["source_id"]: row for row in queue_rows(report, "stale_source")}
    assert rows["example-cloud-dpa"]["priority"] == 5 + 3 + 2 + 2
    assert rows["example-cloud-trust-center"]["priority"] == 5 + 2 + 2 + 1


def test_fresh_run_artifact_suppresses_stale_rows(tmp_path):
    make_repo(tmp_path)
    report = build(tmp_path, latest_observations=run_artifact("2026-06-10T00:00:00Z"))

    stale_ids = {row["source_id"] for row in report["stale_high_priority_sources"]}
    assert "example-cloud-dpa" not in stale_ids


def test_freshness_report_input_takes_precedence(tmp_path):
    make_repo(tmp_path)
    freshness = {
        "sources": [
            {"source_id": "example-cloud-dpa", "freshness": {"status": "expired"}},
        ]
    }
    report = build(
        tmp_path,
        latest_observations=run_artifact("2026-06-10T00:00:00Z"),
        freshness_report=freshness,
    )
    stale = {row["source_id"]: row for row in report["stale_high_priority_sources"]}
    assert stale["example-cloud-dpa"]["freshness_status"] == "expired"


def test_no_observation_input_marks_none_and_unknown(tmp_path):
    report = build(make_repo(tmp_path))

    assert report["observation_input"] == "none"
    statuses = {row["source_id"]: row["freshness_status"] for row in report["stale_high_priority_sources"]}
    assert set(statuses.values()) == {"unknown"}


def test_ambiguous_source_queue(tmp_path):
    make_repo(tmp_path)
    report = build(tmp_path, latest_observations=run_artifact("2026-06-10T00:00:00Z", health="gated"))
    rows = {row["source_id"]: row for row in queue_rows(report, "ambiguous_source")}

    assert rows["example-uncategorized-privacy-notice"]["reason"] == "canonical confidence ambiguous"
    assert rows["example-cloud-dpa"]["reason"] == "latest observed health gated"


def test_machine_readable_queue_and_coverage_counts(tmp_path):
    report = build(make_repo(tmp_path))
    rows = {row["source_id"]: row for row in queue_rows(report, "machine_readable_surface_needed")}

    assert "example-cloud-dpa" in rows  # machine_readable false
    assert "example-cloud-trust-center" not in rows  # machine_readable true
    coverage = report["machine_readable_coverage"]["cloud"]
    assert coverage["dpa"] == {"machine_readable": 0, "not_machine_readable": 1, "unknown": 0}
    assert coverage["trust_center"] == {"machine_readable": 1, "not_machine_readable": 0, "unknown": 0}


def test_candidate_backlog_by_category(tmp_path):
    report = build(make_repo(tmp_path))
    assert report["candidate_backlog_by_category"] == {
        "cloud": 1,
        "sme_common_tools": 0,
        "uncategorized": 0,
    }


def test_report_is_deterministic_and_queue_sorted(tmp_path):
    make_repo(tmp_path)
    first = build(tmp_path, latest_observations=run_artifact("2026-04-01T00:00:00Z"))
    second = build(tmp_path, latest_observations=run_artifact("2026-04-01T00:00:00Z"))

    assert first == second
    priorities = [row["priority"] for row in first["growth_queue"]]
    assert priorities == sorted(priorities, reverse=True)
    for row in first["growth_queue"]:
        assert row["queue_class"] in QUEUE_CLASSES
        breakdown = row["priority_breakdown"]
        assert row["priority"] == sum(breakdown.values())
        assert row["route"] == "candidate_submission"


def test_report_carries_doctrine_and_no_advisory_vocabulary(tmp_path):
    report = build(make_repo(tmp_path))

    assert report["doctrine"] == DOCTRINE
    assert "not raw URL count" in report["doctrine"]
    assert report["not_advice"] is True
    assert report["posture"]["catalog_mutation_performed"] is False
    assert report["posture"]["network_fetch_performed"] is False
    text = json.dumps(report) + render_markdown(report)
    assert not ADVISORY_RE.search(text), ADVISORY_RE.search(text)
    for forbidden in ("risk_score", "vendor_risk", "compliance_score"):
        assert forbidden not in text


def test_workflow_downloads_freshness_and_stays_read_only():
    path = Path(".github/workflows/coverage-audit.yml")
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    triggers = workflow.get("on") or workflow.get(True) or {}

    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert set(triggers.keys()) == {"workflow_dispatch", "schedule"}
    assert "tools.openva.coverage_growth build" in text
    assert "source-health-artifacts/observation-ledger/latest-observations.json" in text
    assert "source-health-artifacts/observation-ledger/source-freshness-report.json" in text
    assert "reports/coverage-growth-report.json" in text
    assert "reports/coverage-growth-queue.csv" in text
    assert "peter-evans/create-pull-request" not in text
    assert "git push" not in text
    assert "contents: write" not in text


def test_coverage_growth_doc_states_boundaries():
    text = Path("docs/coverage-growth.md").read_text(encoding="utf-8")

    assert "not raw URL count" in text or "not by raw URL count" in text
    assert "candidate" in text
    assert "no crawling" in text
    assert "no compliance scoring" in text
    assert "weight >= 5" in text or "weight ≥ 5" in text
    assert "observation_input" in text
    assert "docs/coverage-growth.md" in Path("docs/index.md").read_text(encoding="utf-8")


def test_real_catalog_build_reconciles_with_repo(tmp_path):
    report = build_coverage_growth_report(
        targets=REPO_TARGETS,
        sla_config=REPO_SLA,
        now=NOW,
        generated_at=GENERATED_AT,
    )
    catalog_vendor_count = len(list(Path("data/vendors").glob("*/vendor.yaml")))
    assert report["summary"]["vendor_count"] == catalog_vendor_count
    assert report["summary"]["growth_queue_count"] == len(report["growth_queue"])
    assert report["observation_input"] in {"run_artifact", "committed_events_fallback", "none"}
