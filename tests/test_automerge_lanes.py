from __future__ import annotations

from tools.openva.automerge_lanes import (
    AUTOMERGE_GENERATED,
    AUTOMERGE_MACHINE_CANONICAL,
    AUTOMERGE_OBSERVATION,
    eligible_for_lane,
    load_policy,
)


def test_policy_is_report_only_and_limits_machine_canonical_records():
    policy = load_policy()
    assert policy["mode"] == "enforce"
    assert policy["machine_canonical"]["max_source_records_per_pr"] == 50


def test_generated_lane_accepts_only_generated_paths():
    result = eligible_for_lane(["openva-pack.json", "indexes/vendors.json"], [AUTOMERGE_GENERATED])
    assert result.eligible is True
    assert result.lane == AUTOMERGE_GENERATED
    assert result.report_only is False


def test_generated_lane_rejects_source_data_change():
    result = eligible_for_lane(["data/vendors/stripe.yaml", "indexes/vendors.json"], [AUTOMERGE_GENERATED])
    assert result.eligible is False
    assert "non_generated_path:data/vendors/stripe.yaml" in result.reasons


def test_observation_lane_accepts_observation_artifacts_and_generated_outputs():
    result = eligible_for_lane(["observations/stripe.json", "indexes/observations.json"], [AUTOMERGE_OBSERVATION])
    assert result.eligible is True
    assert result.lane == AUTOMERGE_OBSERVATION


def test_machine_canonical_lane_accepts_catalog_source_paths_and_indexes():
    result = eligible_for_lane(
        ["data/vendors/stripe.yaml", "openva-pack.json", "indexes/sources.json"],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is True
    assert result.lane == AUTOMERGE_MACHINE_CANONICAL


def test_machine_canonical_lane_rejects_workflow_changes():
    result = eligible_for_lane(
        [".github/workflows/agent-automerge.yml", "data/vendors/stripe.yaml"],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is False
    assert "sensitive_path:.github/workflows/agent-automerge.yml" in result.reasons


def test_machine_canonical_lane_rejects_more_than_fifty_vendor_source_records():
    paths = [f"data/vendors/vendor-{index}.yaml" for index in range(51)]
    result = eligible_for_lane(paths, [AUTOMERGE_MACHINE_CANONICAL])
    assert result.eligible is False
    assert "machine_canonical_record_limit_exceeded:51>50" in result.reasons


def test_no_automerge_label_requires_human_review():
    result = eligible_for_lane(["data/vendors/stripe.yaml"], [])
    assert result.eligible is False
    assert result.lane == "needs-human-review"
    assert "no_automerge_label" in result.reasons


def test_enforce_mode_cli_returns_nonzero_for_ineligible_lane(tmp_path):
    from tools.openva.automerge_lanes import main

    paths = tmp_path / "paths.txt"
    paths.write_text("data/vendors/stripe.yaml\n", encoding="utf-8")

    assert main(["--paths-file", str(paths), "--labels", ""]) == 1


def test_report_only_flag_keeps_cli_non_blocking(tmp_path):
    from tools.openva.automerge_lanes import main

    paths = tmp_path / "paths.txt"
    paths.write_text("data/vendors/stripe.yaml\n", encoding="utf-8")

    assert main(["--paths-file", str(paths), "--labels", "", "--report-only"]) == 0
