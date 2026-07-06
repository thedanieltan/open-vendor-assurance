from __future__ import annotations

import subprocess

from tools.openva.generated_catalog_pr_risk import (
    GENERATED_CATALOG_TITLE,
    GENERATED_CATALOG_WORK_PACKAGE,
    GeneratedCatalogAutoMergeInput,
    GeneratedCatalogPrRiskClass,
    LATEST_OBSERVATIONS_PATH,
    build_generated_catalog_automerge_input_from_files,
    classify_generated_catalog_pr_risk,
    verify_applied_patch_paths,
    evaluate_generated_catalog_automerge_eligibility,
    is_generated_catalog_pr_low_risk_path,
    is_vendor_catalog_record_path,
    read_paths_file,
)


ALLOWED_GENERATED_CATALOG_PR_PATHS = [
    "data/vendors/guidewire/vendor.yaml",
    "data/vendors/guidewire/sources/guidewire-dpa.yaml",
    "data/vendors/guidewire/artifacts/guidewire-dpa.yaml",
    "data/vendors/guidewire/changes/candidate-promotion-guidewire-dpa.yaml",
    "dist/vendors/guidewire.json",
    "indexes/sources.json",
    "indexes/artifacts.json",
    "indexes/changes.json",
    "indexes/source-coverage.json",
    "indexes/summary.json",
    "indexes/vendor-match-index.json",
    "indexes/vendor-search.json",
    LATEST_OBSERVATIONS_PATH,
    "openva-pack.json",
]


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "openva@example.invalid")
    _git(repo, "config", "user.name", "OpenVA Test")
    (repo / "indexes").mkdir()
    (repo / "indexes" / "sources.json").write_text('{"sources":[]}\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


def _eligible_input(**overrides):
    data = {
        "changed_paths": tuple(ALLOWED_GENERATED_CATALOG_PR_PATHS),
        "pr_body": f"Work-Package: {GENERATED_CATALOG_WORK_PACKAGE}\n\n## Summary\n",
        "head_branch": "agent-candidate-promotion-28738275937",
        "title": GENERATED_CATALOG_TITLE,
        "is_draft": False,
        "mergeable": True,
        "check_conclusions": {
            "validate": "success",
            "catalog-pr-guard": "success",
            "agent-weighted-review": "success",
        },
        "source_preflight_failures": 0,
        "release_gates_passed": True,
        "latest_observations_full_baseline": True,
        "generated_outputs_fresh": True,
        "unresolved_review_threads": 0,
        "selected_action_count": 5,
        "max_selected_action_count": 5,
        "secret_scan_passed": True,
    }
    data.update(overrides)
    return GeneratedCatalogAutoMergeInput(**data)


def test_generated_catalog_pr_risk_allows_bounded_generated_catalog_surface() -> None:
    result = classify_generated_catalog_pr_risk(ALLOWED_GENERATED_CATALOG_PR_PATHS)

    assert result.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK
    assert result.low_risk is True
    assert result.reasons == ()
    assert result.unexpected_paths == ()


def test_generated_catalog_pr_risk_rejects_unexpected_control_plane_and_policy_paths() -> None:
    blocked = [
        ".github/workflows/candidate-promotion-pr.yml",
        "tools/openva/generated_catalog_pr_risk.py",
        "tests/test_generated_catalog_pr_risk.py",
        "config/automerge-policy.yaml",
        "docs/catalog-autonomy-policy.md",
        "maintenance/generated/strict-growth-promotion-plan.json",
        "maintenance/machine-decisions/2026-07.ndjson",
    ]

    result = classify_generated_catalog_pr_risk([*ALLOWED_GENERATED_CATALOG_PR_PATHS, *blocked])

    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.low_risk is False
    assert result.unexpected_paths == tuple(sorted(blocked))
    assert result.reasons == tuple(f"unexpected_path:{path}" for path in sorted(blocked))


def test_latest_observations_allowance_is_exact_not_a_broad_maintenance_glob() -> None:
    assert is_generated_catalog_pr_low_risk_path(LATEST_OBSERVATIONS_PATH)

    near_misses = [
        "maintenance/source-observations/events/2026-07.ndjson",
        "maintenance/source-observations/latest-observations.json.bak",
        "maintenance/source-observations/previous-observations.json",
        "maintenance/source-observations/nested/latest-observations.json",
    ]
    result = classify_generated_catalog_pr_risk(near_misses)

    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.unexpected_paths == tuple(sorted(near_misses))


def test_vendor_catalog_record_surface_is_canonical_and_not_broad_data_vendors() -> None:
    allowed = [
        "data/vendors/acme/vendor.yaml",
        "data/vendors/acme/sources/acme-security.yml",
        "data/vendors/acme/artifacts/acme-security.yaml",
        "data/vendors/acme/changes/acme-security.yaml",
    ]
    rejected = [
        "data/vendors/acme",
        "data/vendors/acme/notes.yaml",
        "data/vendors/acme/sources/nested/acme-security.yaml",
        "data/vendors/acme/private/acme-security.yaml",
        "data/vendors/acme/sources/.yaml",
    ]

    assert [path for path in allowed if not is_vendor_catalog_record_path(path)] == []
    assert [path for path in rejected if is_vendor_catalog_record_path(path)] == []


def test_generated_dist_allowance_is_vendor_json_not_broad_dist_tree() -> None:
    accepted = "dist/vendors/acme.json"
    rejected = [
        "dist/vendors/acme/sources.json",
        "dist/source-health.json",
        "dist/vendors/.json",
    ]

    assert is_generated_catalog_pr_low_risk_path(accepted)
    result = classify_generated_catalog_pr_risk(rejected)
    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.unexpected_paths == tuple(sorted(rejected))


def test_empty_generated_catalog_pr_diff_fails_closed() -> None:
    result = classify_generated_catalog_pr_risk([])

    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert result.reasons == ("no_changed_paths",)


def test_paths_file_reader_accepts_utf8_bom(tmp_path) -> None:
    paths_file = tmp_path / "changed-paths.txt"
    paths_file.write_text(
        "data/vendors/guidewire/sources/guidewire-dpa.yaml\nindexes/sources.json\n",
        encoding="utf-8-sig",
    )

    result = classify_generated_catalog_pr_risk(read_paths_file(str(paths_file)))

    assert result.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK


def test_applied_patch_paths_include_modified_tracked_files(tmp_path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "indexes" / "sources.json").write_text('{"sources":["akur8"]}\n', encoding="utf-8")

    applied = verify_applied_patch_paths(
        ("indexes/sources.json",),
        cwd=str(repo),
    )

    assert applied == ("indexes/sources.json",)


def test_applied_patch_paths_include_untracked_added_files(tmp_path) -> None:
    repo = _init_repo(tmp_path)
    added = repo / "data" / "vendors" / "akur8" / "sources" / "akur8-compliance-page.yaml"
    added.parent.mkdir(parents=True)
    added.write_text("source_id: akur8-compliance-page\n", encoding="utf-8")

    applied = verify_applied_patch_paths(
        ("data/vendors/akur8/sources/akur8-compliance-page.yaml",),
        cwd=str(repo),
    )

    assert applied == ("data/vendors/akur8/sources/akur8-compliance-page.yaml",)


def test_applied_patch_paths_fail_closed_when_expected_added_file_missing(tmp_path) -> None:
    repo = _init_repo(tmp_path)

    try:
        verify_applied_patch_paths(
            ("data/vendors/akur8/sources/akur8-compliance-page.yaml",),
            cwd=str(repo),
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing added file to fail closed")

    assert "missing=['data/vendors/akur8/sources/akur8-compliance-page.yaml']" in message


def test_applied_patch_paths_fail_closed_on_unexpected_added_file(tmp_path) -> None:
    repo = _init_repo(tmp_path)
    added = repo / "data" / "vendors" / "akur8" / "sources" / "akur8-compliance-page.yaml"
    added.parent.mkdir(parents=True)
    added.write_text("source_id: akur8-compliance-page\n", encoding="utf-8")

    try:
        verify_applied_patch_paths(
            ("indexes/sources.json",),
            cwd=str(repo),
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected unexpected added file to fail closed")

    assert "unexpected=['data/vendors/akur8/sources/akur8-compliance-page.yaml']" in message


def test_generated_catalog_automerge_accepts_low_risk_green_generated_pr() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(_eligible_input())

    assert result.eligible is True
    assert result.decision == "MERGE"
    assert result.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK
    assert result.reasons == ()
    assert result.work_package == GENERATED_CATALOG_WORK_PACKAGE


def test_generated_catalog_automerge_builds_safe_input_from_files(tmp_path) -> None:
    paths_file = tmp_path / "changed-files.txt"
    pr_body_file = tmp_path / "pr-body.md"
    metadata_file = tmp_path / "pr-metadata.json"
    checks_file = tmp_path / "pr-checks.json"
    source_preflight_file = tmp_path / "source-preflight-report.json"
    release_gates_file = tmp_path / "release-gates.json"
    review_threads_file = tmp_path / "review-threads.json"
    generated_outputs_file = tmp_path / "generated-outputs-fresh.json"

    paths_file.write_text("\n".join(ALLOWED_GENERATED_CATALOG_PR_PATHS), encoding="utf-8")
    pr_body_file.write_text(
        "\n".join(
            [
                f"Work-Package: {GENERATED_CATALOG_WORK_PACKAGE}",
                "",
                "Promotion actions selected for this PR: `1`",
                "Max promotion actions per generated PR: `5`",
            ]
        ),
        encoding="utf-8",
    )
    metadata_file.write_text(
        '{"title":"Catalog: apply reviewed candidate source promotion","headRefName":"agent-candidate-promotion-1","isDraft":false,"mergeable":"MERGEABLE"}',
        encoding="utf-8",
    )
    checks_file.write_text(
        """
        [
          {"workflow": "validate", "state": "SUCCESS", "bucket": "pass"},
          {"workflow": "catalog-pr-guard", "state": "SUCCESS", "bucket": "pass"},
          {"workflow": "agent-weighted-review", "state": "SUCCESS", "bucket": "pass"}
        ]
        """,
        encoding="utf-8",
    )
    source_preflight_file.write_text('{"failed_count": 0}', encoding="utf-8")
    release_gates_file.write_text(
        '{"decision":"passed","gates":[{"gate_id":"full_baseline_readiness","status":"pass"}]}',
        encoding="utf-8",
    )
    review_threads_file.write_text(
        '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[],"pageInfo":{"hasNextPage":false}}}}}}',
        encoding="utf-8",
    )
    generated_outputs_file.write_text('{"generated_outputs_fresh": true}', encoding="utf-8")

    data = build_generated_catalog_automerge_input_from_files(
        paths_file=str(paths_file),
        pr_body_file=str(pr_body_file),
        metadata_file=str(metadata_file),
        checks_file=str(checks_file),
        source_preflight_report=str(source_preflight_file),
        release_gates_report=str(release_gates_file),
        review_threads_report=str(review_threads_file),
        generated_outputs_fresh_file=str(generated_outputs_file),
    )
    result = evaluate_generated_catalog_automerge_eligibility(data)

    assert result.eligible is True
    assert result.decision == "MERGE"


def test_generated_catalog_automerge_rejects_missing_work_package() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(pr_body="## Summary\n")
    )

    assert result.eligible is False
    assert "invalid_work_package:missing" in result.reasons


def test_generated_catalog_automerge_rejects_high_risk_paths() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(changed_paths=(".github/workflows/agent-automerge.yml",))
    )

    assert result.eligible is False
    assert result.risk_class == GeneratedCatalogPrRiskClass.HIGH_RISK
    assert "unexpected_path:.github/workflows/agent-automerge.yml" in result.reasons


def test_generated_catalog_automerge_rejects_broad_observation_path() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(changed_paths=("maintenance/source-observations/events/2026-07.ndjson",))
    )

    assert result.eligible is False
    assert (
        "unexpected_path:maintenance/source-observations/events/2026-07.ndjson"
        in result.reasons
    )


def test_generated_catalog_automerge_rejects_failed_and_missing_checks() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(
            check_conclusions={
                "validate": "failure",
                "catalog-pr-guard": "success",
            }
        )
    )

    assert result.eligible is False
    assert result.missing_checks == ("agent-weighted-review",)
    assert result.failed_checks == ("validate",)
    assert "missing_check:agent-weighted-review" in result.reasons
    assert "failed_check:validate" in result.reasons


def test_generated_catalog_automerge_rejects_source_preflight_failure() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(source_preflight_failures=1)
    )

    assert result.eligible is False
    assert "source_preflight_failures:1" in result.reasons


def test_generated_catalog_automerge_rejects_release_gate_failure() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(release_gates_passed=False)
    )

    assert result.eligible is False
    assert "release_gates_not_passed" in result.reasons


def test_generated_catalog_automerge_rejects_incomplete_latest_observations_baseline() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(latest_observations_full_baseline=False)
    )

    assert result.eligible is False
    assert "latest_observations_full_baseline_not_passed" in result.reasons


def test_generated_catalog_automerge_rejects_stale_generated_outputs() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(generated_outputs_fresh=False)
    )

    assert result.eligible is False
    assert "generated_outputs_not_fresh" in result.reasons


def test_generated_catalog_automerge_rejects_draft_conflicted_and_threaded_prs() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(is_draft=True, mergeable=False, unresolved_review_threads=2)
    )

    assert result.eligible is False
    assert "draft_pr" in result.reasons
    assert "not_mergeable" in result.reasons
    assert "unresolved_review_threads:2" in result.reasons


def test_generated_catalog_automerge_rejects_wrong_generated_identity() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(head_branch="feature/manual-catalog-change")
    )

    assert result.eligible is False
    assert "not_generated_candidate_promotion_pr" in result.reasons


def test_generated_catalog_automerge_rejects_batch_limit_excess() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(selected_action_count=6, max_selected_action_count=5)
    )

    assert result.eligible is False
    assert "selected_action_count_exceeded:6>5" in result.reasons


def test_generated_catalog_automerge_rejects_missing_selected_action_count() -> None:
    result = evaluate_generated_catalog_automerge_eligibility(
        _eligible_input(selected_action_count=None)
    )

    assert result.eligible is False
    assert "selected_action_count_missing" in result.reasons
