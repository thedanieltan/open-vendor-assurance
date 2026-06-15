import copy
import json
from datetime import UTC, datetime

from tools.openva.materialization_envelope import build_envelope, verify_envelope


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def strict_growth_action(source_type="security_page"):
    return {
        "action": "strict_catalog_growth_promotion",
        "vendor": {
            "candidate_vendor_id": "candidate-a",
            "display_name_candidate": "Candidate A",
            "official_domain_candidate": "candidate-a.example",
        },
        "source": {
            "candidate_source_id": f"candidate-a-{source_type}-a1b2c3d4",
            "vendor_id": "candidate-a",
            "source_type_candidate": source_type,
            "candidate_url": f"https://candidate-a.example/{source_type}",
            "confidence": "likely",
            "evidence": {
                "final_url": f"https://candidate-a.example/{source_type}",
                "http_status": 200,
                "matched_terms": ["security"],
            },
        },
    }


def artifact_paths(root):
    paths = {
        "vendor_candidate_report": root / "vendor-candidate-discovery-report.json",
        "source_discovery_report": root / "source-discovery-report.json",
        "eligibility_report": root / "catalog-growth-eligibility-report.json",
    }
    for name, path in paths.items():
        write_json(path, {"report": name})
    return paths


def materialization_envelope(action, root):
    return build_envelope(
        action,
        root=root,
        artifact_paths=artifact_paths(root),
        discovery_run_id="run-1",
        workflow_run_id="100",
        workflow_attempt=1,
        source_commit_sha="a" * 40,
        base_sha="a" * 40,
        generated_at="2026-06-15T00:00:00Z",
    )


def test_valid_materialization_envelope_verifies(tmp_path):
    action = strict_growth_action()
    envelope = materialization_envelope(action, tmp_path)

    assert verify_envelope(action, envelope, root=tmp_path, now=datetime(2026, 6, 15, 1, tzinfo=UTC)) == []


def test_tampered_artifact_digest_fails(tmp_path):
    action = strict_growth_action()
    envelope = materialization_envelope(action, tmp_path)
    write_json(tmp_path / "source-discovery-report.json", {"report": "tampered"})

    reasons = verify_envelope(action, envelope, root=tmp_path, now=datetime(2026, 6, 15, 1, tzinfo=UTC))

    assert "envelope_artifact_digest_mismatch:source_discovery_report" in reasons


def test_candidate_digest_mismatch_fails(tmp_path):
    action = strict_growth_action()
    envelope = materialization_envelope(action, tmp_path)
    mutated = copy.deepcopy(action)
    mutated["vendor"]["display_name_candidate"] = "Candidate B"

    reasons = verify_envelope(mutated, envelope, root=tmp_path, now=datetime(2026, 6, 15, 1, tzinfo=UTC))

    assert "envelope_candidate_digest_mismatch" in reasons


def test_expired_materialization_envelope_fails(tmp_path):
    action = strict_growth_action()
    envelope = materialization_envelope(action, tmp_path)

    reasons = verify_envelope(action, envelope, root=tmp_path, now=datetime(2026, 6, 16, 0, tzinfo=UTC))

    assert "envelope_expired" in reasons


def test_status_page_cannot_materialize_vendor(tmp_path):
    action = strict_growth_action(source_type="status_page")
    envelope = materialization_envelope(action, tmp_path)

    reasons = verify_envelope(action, envelope, root=tmp_path, now=datetime(2026, 6, 15, 1, tzinfo=UTC))

    assert "envelope_source_type_not_materialization:status_page" in reasons
