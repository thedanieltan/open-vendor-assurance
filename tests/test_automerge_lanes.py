from __future__ import annotations

from tools.openva.automerge_lanes import (
    AUTOMERGE_CANDIDATE_INTAKE,
    AUTOMERGE_GENERATED,
    AUTOMERGE_MACHINE_CANONICAL,
    AUTOMERGE_OBSERVATION,
    eligible_for_lane,
    is_candidate_intake_path,
    load_policy,
)


def test_policy_is_report_only_and_limits_machine_canonical_records():
    policy = load_policy()
    assert policy["mode"] == "enforce"
    assert policy["machine_canonical"]["max_source_records_per_pr"] == 50
    assert policy["source_repair"]["max_source_records_per_pr"] == 10
    assert policy["lanes"]["p0_source_repair"]["label"] == "automerge:p0-source-repair"
    assert policy["lanes"]["p0_source_repair"]["required_labels"] == ["source-refinement"]


def test_generated_lane_accepts_only_generated_paths():
    result = eligible_for_lane(["openva-pack.json", "indexes/vendors.json"], [AUTOMERGE_GENERATED])
    assert result.eligible is True
    assert result.lane == AUTOMERGE_GENERATED
    assert result.report_only is False


def test_generated_lane_rejects_source_data_change():
    result = eligible_for_lane(["data/vendors/stripe.yaml", "indexes/vendors.json"], [AUTOMERGE_GENERATED])
    assert result.eligible is False
    assert "non_generated_path:data/vendors/stripe.yaml" in result.reasons


def test_observation_lane_accepts_committed_ledger_events_and_generated_outputs():
    result = eligible_for_lane(
        ["maintenance/source-observations/events/2026-06.ndjson", "indexes/observations.json"],
        [AUTOMERGE_OBSERVATION],
    )
    assert result.eligible is True
    assert result.lane == AUTOMERGE_OBSERVATION


def test_observation_lane_rejects_non_ledger_path():
    result = eligible_for_lane(["observations/stripe.json"], [AUTOMERGE_OBSERVATION])
    assert result.eligible is False


def test_machine_canonical_lane_accepts_only_canonical_source_paths_and_indexes():
    result = eligible_for_lane(
        [
            "data/vendors/stripe/sources/stripe-dpa.yaml",
            "openva-pack.json",
            "indexes/sources.json",
        ],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is True
    assert result.lane == AUTOMERGE_MACHINE_CANONICAL


def test_machine_canonical_lane_rejects_workflow_changes():
    result = eligible_for_lane(
        [".github/workflows/agent-automerge.yml", "data/vendors/stripe/sources/stripe-dpa.yaml"],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is False
    assert "sensitive_path:.github/workflows/agent-automerge.yml" in result.reasons


def test_machine_canonical_lane_rejects_more_than_fifty_vendor_source_records():
    paths = [
        f"data/vendors/vendor-{index}/sources/vendor-{index}-dpa.yaml"
        for index in range(51)
    ]
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


def test_machine_canonical_lane_rejects_vendor_profile_changes():
    result = eligible_for_lane(
        ["data/vendors/stripe/vendor.yaml", "indexes/vendors.json"],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is False
    assert "non_machine_canonical_path:data/vendors/stripe/vendor.yaml" in result.reasons


def test_machine_canonical_lane_rejects_unavailable_source_changes():
    result = eligible_for_lane(
        ["data/vendors/stripe/unavailable_sources/stripe-dpa.yaml", "indexes/sources.json"],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is False
    assert (
        "non_machine_canonical_path:data/vendors/stripe/unavailable_sources/stripe-dpa.yaml"
        in result.reasons
    )


def test_machine_canonical_lane_rejects_catalog_batch_inputs():
    result = eligible_for_lane(
        ["catalog-batches/intake/batch.yaml", "indexes/sources.json"],
        [AUTOMERGE_MACHINE_CANONICAL],
    )
    assert result.eligible is False
    assert "non_machine_canonical_path:catalog-batches/intake/batch.yaml" in result.reasons


def test_candidate_intake_lane_accepts_only_candidate_staging_json():
    result = eligible_for_lane(
        ["maintenance/candidates/cand-catalog-discovery-stripe.json"],
        [AUTOMERGE_CANDIDATE_INTAKE],
    )
    assert result.eligible is True
    assert result.lane == AUTOMERGE_CANDIDATE_INTAKE
    assert result.report_only is False


def test_candidate_intake_lane_has_no_generated_escape_hatch():
    # Unlike the observation lane, a candidate-intake PR must not carry generated
    # or canonical drift.
    result = eligible_for_lane(
        ["maintenance/candidates/cand-x.json", "indexes/sources.json"],
        [AUTOMERGE_CANDIDATE_INTAKE],
    )
    assert result.eligible is False
    assert "non_candidate_intake_path:indexes/sources.json" in result.reasons


def test_candidate_intake_lane_rejects_canonical_data_change():
    result = eligible_for_lane(
        ["maintenance/candidates/cand-x.json", "data/vendors/stripe/sources/a.yaml"],
        [AUTOMERGE_CANDIDATE_INTAKE],
    )
    assert result.eligible is False
    assert "non_candidate_intake_path:data/vendors/stripe/sources/a.yaml" in result.reasons


def test_candidate_intake_lane_blocks_workflow_via_sensitive_precheck():
    result = eligible_for_lane(
        ["maintenance/candidates/cand-x.json", ".github/workflows/foo.yml"],
        [AUTOMERGE_CANDIDATE_INTAKE],
    )
    assert result.eligible is False
    assert result.lane == "needs-human-review"
    assert "sensitive_path:.github/workflows/foo.yml" in result.reasons


def test_candidate_intake_path_is_single_level_json_only():
    assert is_candidate_intake_path("maintenance/candidates/cand-x.json") is True
    # nested (would be a silent no-op for the consumer glob) is rejected
    assert is_candidate_intake_path("maintenance/candidates/sub/cand-x.json") is False
    # wrong suffix / non-json staging artifacts are rejected
    assert is_candidate_intake_path("maintenance/candidates/README.md") is False
    assert is_candidate_intake_path("maintenance/candidates/cand-x.JSON") is False
    assert is_candidate_intake_path("maintenance/candidates/") is False


def test_candidate_intake_lane_rejects_nested_candidate_path():
    result = eligible_for_lane(
        ["maintenance/candidates/sub/cand-x.json"],
        [AUTOMERGE_CANDIDATE_INTAKE],
    )
    assert result.eligible is False
    assert "non_candidate_intake_path:maintenance/candidates/sub/cand-x.json" in result.reasons


def test_policy_declares_candidate_intake_lane():
    policy = load_policy()
    lane = policy["lanes"]["candidate_intake"]
    assert lane["label"] == "automerge:candidate-intake"
    assert lane["required_labels"] == ["candidate-intake"]
    # WP-OPENVA-CANDIDATE-ACTIVATION-01: execution-wired now that the producer
    # PR-open workflow and the consuming agent-automerge merge job both exist.
    assert lane["execution_wired"] is True
