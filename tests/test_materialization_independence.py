"""Tier A: materialization retrieval-independence semantics.

Two agreeing retrievals only corroborate when they come from distinct workflow
runs OR distinct retrieval modes. Same-run, same-mode retries are one
observation. The threshold stays two and is not weakened; IP/geography is not a
dimension.
"""

import pytest

from tools.openva.candidate_promotion_actions import (
    materialization_threshold_results,
    retrieval_independence,
    validate_materialization_thresholds,
)


def _action(attempts: list[dict]) -> dict:
    return {
        "vendor": {
            "candidate_vendor_id": "acme",
            "official_domain_candidate": "acme.example",
        },
        "source": {
            "candidate_url": "https://acme.example/security",
            "evidence": {
                "matched_terms": ["security"],
                "final_url": "https://acme.example/security",
                "http_status": 200,
                "name_supported_by_official_domain_metadata": True,
                "retrieval_attempts": {"observed": len(attempts), "agreeing": True, "attempts": attempts},
                "source_host_authority": "vendor_controlled",
                "adversarial_review": "clean",
                "evidence_fresh": True,
            },
        },
    }


DIFFERENT_RUNS = [
    {"workflow_run_id": "run-1", "retrieval_mode": "direct_http"},
    {"workflow_run_id": "run-2", "retrieval_mode": "direct_http"},
]
DIFFERENT_MODES = [
    {"workflow_run_id": "run-1", "retrieval_mode": "direct_http"},
    {"workflow_run_id": "run-1", "retrieval_mode": "render_lane"},
]
SAME_RUN_SAME_MODE = [
    {"workflow_run_id": "run-1", "retrieval_mode": "direct_http"},
    {"workflow_run_id": "run-1", "retrieval_mode": "direct_http"},
]
NO_IDENTITY = [{}, {}]  # fabricated attempts with neither run nor mode identity


def test_unit_independence_rule():
    assert retrieval_independence(DIFFERENT_RUNS, 2, 2) == (2, 1, True)
    assert retrieval_independence(DIFFERENT_MODES, 2, 2) == (1, 2, True)
    assert retrieval_independence(SAME_RUN_SAME_MODE, 2, 2) == (1, 1, False)
    assert retrieval_independence(NO_IDENTITY, 2, 2) == (0, 0, False)


def test_two_same_run_retries_count_as_one_and_fail_closed():
    with pytest.raises(ValueError, match="retrieval_attempts_independence=fail"):
        validate_materialization_thresholds(_action(SAME_RUN_SAME_MODE))


def test_missing_run_and_mode_identity_fails_closed():
    with pytest.raises(ValueError, match="retrieval_attempts_independence=fail"):
        validate_materialization_thresholds(_action(NO_IDENTITY))


def test_two_distinct_runs_satisfy_independence():
    validate_materialization_thresholds(_action(DIFFERENT_RUNS))  # does not raise
    results = materialization_threshold_results(_action(DIFFERENT_RUNS))
    assert results["retrieval_attempts"]["independent"] is True


def test_two_distinct_modes_satisfy_independence():
    validate_materialization_thresholds(_action(DIFFERENT_MODES))  # does not raise


def test_threshold_remains_two_and_is_not_weakened():
    results = materialization_threshold_results(_action(DIFFERENT_RUNS))
    assert results["retrieval_attempts"]["required"] == 2
    # A single attempt never satisfies the count threshold even if "independent".
    one = [{"workflow_run_id": "run-1", "retrieval_mode": "direct_http"}]
    with pytest.raises(ValueError, match="retrieval_attempts=fail"):
        validate_materialization_thresholds(_action(one))
