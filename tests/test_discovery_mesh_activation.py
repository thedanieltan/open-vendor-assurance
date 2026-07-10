from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.openva.discovery_mesh_activation import (
    IntakeValidationError,
    build_vendor_promotion_plans,
    validate_changed_paths,
    validate_intake,
)
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION


def reviewed_action(vendor_id: str, candidate_id: str, source_type: str = "dpa") -> dict:
    return {
        "action": REVIEWED_CANDIDATE_PROMOTION_ACTION,
        "reason": "Verified candidate requires reviewed promotion.",
        "vendor_id": vendor_id,
        "source_type": source_type,
        "candidate_source_id": candidate_id,
        "candidate_url": f"https://{vendor_id}.example/{source_type}",
        "path": f"data/vendors/{vendor_id}/candidate_sources/{candidate_id}.yaml",
        "evidence": {
            "confidence": "likely",
            "http_status": 200,
            "matched_terms": [source_type],
            "page_title": source_type.title(),
        },
        "requires_human_review": True,
        "writes_canonical_sources": False,
        "non_advisory": True,
    }


def write_vendor(root: Path, vendor_id: str) -> None:
    path = root / "data" / "vendors" / vendor_id / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "vendor_id": vendor_id,
                "display_name": vendor_id.title(),
                "official_domains": [f"{vendor_id}.example"],
                "public_entrypoints": [f"https://{vendor_id}.example"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def write_candidate(root: Path, vendor_id: str, candidate_id: str, *, external: bool = False) -> Path:
    host = "unattested.example" if external else f"{vendor_id}.example"
    url = f"https://{host}/dpa"
    path = root / "data" / "vendors" / vendor_id / "candidate_sources" / f"{candidate_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "candidate_source_id": candidate_id,
                "vendor_id": vendor_id,
                "source_type_candidate": "dpa",
                "candidate_url": url,
                "requested_url": url,
                "observed_final_url": url,
                "canonical_candidate_url": url,
                "candidate_status": "selected",
                "selection_run_id": "2026-07-10T10:00:00Z",
                "superseded_by_candidate_id": None,
                "evidence_digest": "sha256:test",
                "discovery_method": "html_link_graph",
                "confidence": "likely",
                "requires_review": True,
                "discovered_at": "2026-07-10T10:00:00Z",
                "discovered_by": "agent",
                "evidence": {
                    "page_title": "Data Processing Addendum",
                    "matched_terms": ["data processing"],
                    "final_url": url,
                    "http_status": 200,
                    "content_type": "text/html",
                    "semantic_status": "strong",
                    "verification_status": "ok",
                    "soft_404_detected": False,
                },
                "notes": "Candidate only.",
                "not_advice": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def write_plan(root: Path, run_token: str, vendor_id: str, actions: list[dict]) -> Path:
    path = root / "maintenance" / "reviewed" / "discovery-mesh" / run_token / f"{vendor_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "generated_at": "2026-07-10T10:00:00Z",
                "report_type": "candidate_promotion_plan_proposal",
                "source_plan_path": "mesh-plan.raw.json",
                "discovery_mesh_run_token": run_token,
                "batch_index": 1,
                "vendor_id": vendor_id,
                "posture": {
                    "network_fetch_performed": False,
                    "writes_repository_state": False,
                    "writes_canonical_vendors": False,
                    "writes_canonical_sources": False,
                    "requires_existing_candidate_records": True,
                    "non_advisory": True,
                },
                "summary": {
                    "action_count": len(actions),
                    "vendor_count": 1,
                    "action_types": {REVIEWED_CANDIDATE_PROMOTION_ACTION: len(actions)},
                },
                "actions": actions,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_builds_one_plan_per_vendor_without_vendor_or_action_cap(tmp_path: Path) -> None:
    actions = [
        reviewed_action(f"vendor-{index:04d}", f"vendor-{index:04d}-dpa")
        for index in range(1_250)
    ]

    paths, manifest = build_vendor_promotion_plans(
        {"actions": actions},
        source_plan_path="mesh-promotion-plan.raw.json",
        run_token="run-123",
        output_root=tmp_path / "maintenance" / "reviewed" / "discovery-mesh",
    )

    assert len(paths) == 1_250
    assert manifest["summary"]["vendor_plan_count"] == 1_250
    assert manifest["summary"]["reviewed_action_count"] == 1_250
    assert manifest["summary"]["vendor_count_cap"] is None
    assert manifest["summary"]["action_count_cap"] is None
    assert all(json.loads(path.read_text(encoding="utf-8"))["summary"]["vendor_count"] == 1 for path in paths)


def test_groups_multiple_source_actions_for_the_same_vendor(tmp_path: Path) -> None:
    plan = {
        "actions": [
            reviewed_action("alpha", "alpha-dpa", "dpa"),
            reviewed_action("alpha", "alpha-privacy", "privacy_notice"),
            reviewed_action("beta", "beta-dpa", "dpa"),
        ]
    }

    paths, manifest = build_vendor_promotion_plans(
        plan,
        source_plan_path="raw.json",
        run_token="run-1",
        output_root=tmp_path / "plans",
    )

    assert manifest["summary"]["vendor_plan_count"] == 2
    alpha = next(json.loads(path.read_text(encoding="utf-8")) for path in paths if path.stem == "alpha")
    assert alpha["summary"]["action_count"] == 2
    assert {action["source_type"] for action in alpha["actions"]} == {"dpa", "privacy_notice"}


def test_changed_path_guard_rejects_canonical_and_unrelated_paths() -> None:
    with pytest.raises(IntakeValidationError, match="out-of-scope"):
        validate_changed_paths(
            [
                "data/vendors/alpha/candidate_sources/alpha-dpa.yaml",
                "data/vendors/alpha/sources/alpha-dpa.yaml",
                "maintenance/reviewed/discovery-mesh/run-1/alpha.json",
            ]
        )


def test_validates_complete_official_domain_intake(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    candidate = write_candidate(tmp_path, "alpha", "alpha-dpa")
    plan = write_plan(tmp_path, "run-1", "alpha", [reviewed_action("alpha", "alpha-dpa")])

    report = validate_intake(
        tmp_path,
        [candidate.relative_to(tmp_path).as_posix(), plan.relative_to(tmp_path).as_posix()],
    )

    assert report["valid"] is True
    assert report["summary"] == {
        "changed_path_count": 2,
        "candidate_count": 1,
        "plan_count": 1,
        "referenced_candidate_count": 1,
    }
    assert report["posture"]["canonical_mutation_authority_unchanged"] is True


def test_rejects_unattested_external_candidate_host(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    candidate = write_candidate(tmp_path, "alpha", "alpha-dpa", external=True)
    plan = write_plan(tmp_path, "run-1", "alpha", [reviewed_action("alpha", "alpha-dpa")])

    with pytest.raises(IntakeValidationError, match="not on an official vendor domain"):
        validate_intake(
            tmp_path,
            [candidate.relative_to(tmp_path).as_posix(), plan.relative_to(tmp_path).as_posix()],
        )


def test_rejects_candidate_not_referenced_by_same_intake(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    candidate = write_candidate(tmp_path, "alpha", "alpha-dpa")
    other = write_candidate(tmp_path, "alpha", "alpha-privacy")
    plan = write_plan(tmp_path, "run-1", "alpha", [reviewed_action("alpha", "alpha-dpa")])

    with pytest.raises(IntakeValidationError, match="not referenced"):
        validate_intake(
            tmp_path,
            [
                candidate.relative_to(tmp_path).as_posix(),
                other.relative_to(tmp_path).as_posix(),
                plan.relative_to(tmp_path).as_posix(),
            ],
        )


def test_rejects_multi_vendor_plan(tmp_path: Path) -> None:
    write_vendor(tmp_path, "alpha")
    write_vendor(tmp_path, "beta")
    alpha = write_candidate(tmp_path, "alpha", "alpha-dpa")
    beta = write_candidate(tmp_path, "beta", "beta-dpa")
    plan = write_plan(
        tmp_path,
        "run-1",
        "alpha",
        [reviewed_action("alpha", "alpha-dpa"), reviewed_action("beta", "beta-dpa")],
    )

    with pytest.raises(IntakeValidationError, match="exactly one vendor"):
        validate_intake(
            tmp_path,
            [
                alpha.relative_to(tmp_path).as_posix(),
                beta.relative_to(tmp_path).as_posix(),
                plan.relative_to(tmp_path).as_posix(),
            ],
        )
