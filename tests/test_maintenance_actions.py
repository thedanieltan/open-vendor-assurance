from pathlib import Path

import yaml

from tools.openva.maintenance_actions import apply_maintenance_plan, build_maintenance_plan


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def source_record() -> dict:
    return {
        "schema_version": "0.1.0",
        "source_id": "example-dpa",
        "vendor_id": "example",
        "source_type": "dpa",
        "title_native": "Example DPA",
        "source_url": "https://example.com/legal/data-processing-addendum",
        "source_language": "en",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": "2026-05-16T00:00:00Z",
            "observer": "human",
            "confidence": "low",
        },
        "not_advice": True,
    }


def artifact_record() -> dict:
    return {
        "schema_version": "0.1.0",
        "artifact_id": "example-dpa",
        "vendor_id": "example",
        "source_id": "example-dpa",
        "artifact_type": "dpa",
        "title_native": "Example DPA",
        "canonical_url": "https://example.com/legal/data-processing-addendum",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "region_scope": ["global"],
        "product_scope": ["Example services"],
        "not_advice": True,
    }


def change_record() -> dict:
    return {
        "schema_version": "0.1.0",
        "change_id": "example-dpa-added",
        "vendor_id": "example",
        "source_id": "example-dpa",
        "artifact_id": "example-dpa",
        "change_type": "source_added",
        "observed_at": "2026-05-16T00:00:00Z",
        "summary": "Metadata-only source added.",
        "not_advice": True,
    }


def promotion_plan(action_name: str = "cleanup_source_for_review") -> dict:
    return {
        "actions": [
            {
                "action": action_name,
                "reason": "Existing canonical source appears likely inferred.",
                "vendor_id": "example",
                "source_id": "example-dpa",
                "source_type": "dpa",
                "source_url": "https://example.com/legal/data-processing-addendum",
                "path": "data/vendors/example/sources/example-dpa.yaml",
                "verification": {
                    "verification_status": "suspect_inferred_url",
                    "http_status": 200,
                    "final_url": "https://example.com/legal/data-processing-addendum",
                },
                "requires_human_review": True,
                "non_advisory": True,
            }
        ]
    }


def seed_source_graph(root: Path) -> None:
    write_yaml(root / "data/vendors/example/sources/example-dpa.yaml", source_record())
    write_yaml(root / "data/vendors/example/artifacts/example-dpa.yaml", artifact_record())
    write_yaml(root / "data/vendors/example/changes/example-dpa-added.yaml", change_record())


def test_maintenance_plan_includes_source_artifact_change_and_unavailable_write(tmp_path):
    seed_source_graph(tmp_path)

    report = build_maintenance_plan(promotion_plan(), root=tmp_path)

    assert report["posture"]["writes_repository_state"] is False
    assert report["summary"]["cleanup_actions_selected"] == 1
    planned = {(item["action"], item["path"]) for item in report["file_actions"]}
    assert ("delete", "data/vendors/example/sources/example-dpa.yaml") in planned
    assert ("delete", "data/vendors/example/artifacts/example-dpa.yaml") in planned
    assert ("delete", "data/vendors/example/changes/example-dpa-added.yaml") in planned
    assert ("write", "data/vendors/example/unavailable_sources/example-dpa.yaml") in planned


def test_apply_maintenance_plan_removes_dependencies_and_writes_unavailable(tmp_path, monkeypatch):
    seed_source_graph(tmp_path)

    called = {"build_indexes": False}

    def fake_build_indexes() -> int:
        called["build_indexes"] = True
        return 0

    monkeypatch.setattr("tools.openva.maintenance_actions.build_indexes", fake_build_indexes)

    report = apply_maintenance_plan(promotion_plan(), root=tmp_path)

    assert report["posture"]["writes_repository_state"] is True
    assert report["summary"]["file_actions_applied"] == 4
    assert not (tmp_path / "data/vendors/example/sources/example-dpa.yaml").exists()
    assert not (tmp_path / "data/vendors/example/artifacts/example-dpa.yaml").exists()
    assert not (tmp_path / "data/vendors/example/changes/example-dpa-added.yaml").exists()
    unavailable = yaml.safe_load((tmp_path / "data/vendors/example/unavailable_sources/example-dpa.yaml").read_text())
    assert unavailable["vendor_id"] == "example"
    assert unavailable["source_type"] == "dpa"
    assert unavailable["status"] == "not_identified"
    assert unavailable["not_advice"] is True
    assert called["build_indexes"] is True


def test_maintenance_actions_ignore_non_cleanup_actions(tmp_path):
    seed_source_graph(tmp_path)
    plan = promotion_plan("promote_candidate_for_review")

    report = build_maintenance_plan(plan, root=tmp_path)

    assert report["summary"]["cleanup_actions_selected"] == 0
    assert report["file_actions"] == []


def test_maintenance_plan_reports_missing_source_path(tmp_path):
    report = build_maintenance_plan(promotion_plan(), root=tmp_path)

    assert report["summary"]["skipped_actions"] == 1
    assert report["file_actions"][0]["action"] == "missing"
