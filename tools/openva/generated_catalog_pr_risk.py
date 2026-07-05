"""Operational risk classification for generated catalog PR diff shapes.

This module classifies PR *change-control* risk only. It does not classify
vendors, sources, compliance posture, security posture, procurement suitability,
or any other advisory property.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Mapping

from tools.openva.paths import normalize_repo_path

LATEST_OBSERVATIONS_PATH = "maintenance/source-observations/latest-observations.json"
GENERATED_CATALOG_WORK_PACKAGE = "WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01"
GENERATED_CATALOG_BRANCH_PREFIX = "agent-candidate-promotion-"
GENERATED_CATALOG_TITLE = "Catalog: apply reviewed candidate source promotion"
REQUIRED_GENERATED_CATALOG_CHECKS = (
    "validate",
    "catalog-pr-guard",
    "agent-weighted-review",
)
DEFAULT_MAX_GENERATED_CATALOG_ACTIONS = 10


class GeneratedCatalogPrRiskClass(StrEnum):
    LOW_RISK = "LOW_RISK"
    HIGH_RISK = "HIGH_RISK"


@dataclass(frozen=True)
class GeneratedCatalogPrRiskResult:
    risk_class: GeneratedCatalogPrRiskClass
    reasons: tuple[str, ...]
    changed_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...]

    @property
    def low_risk(self) -> bool:
        return self.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK


@dataclass(frozen=True)
class GeneratedCatalogAutoMergeInput:
    changed_paths: tuple[str, ...]
    pr_body: str
    head_branch: str
    title: str
    is_draft: bool
    mergeable: bool
    check_conclusions: Mapping[str, str]
    source_preflight_failures: int
    release_gates_passed: bool
    latest_observations_full_baseline: bool
    generated_outputs_fresh: bool
    unresolved_review_threads: int = 0
    selected_action_count: int | None = None
    max_selected_action_count: int = DEFAULT_MAX_GENERATED_CATALOG_ACTIONS
    secret_scan_passed: bool = True


@dataclass(frozen=True)
class GeneratedCatalogAutoMergeEligibilityResult:
    eligible: bool
    decision: str
    risk_class: GeneratedCatalogPrRiskClass
    reasons: tuple[str, ...]
    required_checks: tuple[str, ...]
    missing_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    changed_paths: tuple[str, ...]
    work_package: str | None
    source_preflight_failures: int
    release_gates_passed: bool
    latest_observations_full_baseline: bool

    def to_json_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "decision": self.decision,
            "risk_class": self.risk_class.value,
            "reasons": list(self.reasons),
            "required_checks": list(self.required_checks),
            "missing_checks": list(self.missing_checks),
            "failed_checks": list(self.failed_checks),
            "changed_files": list(self.changed_paths),
            "work_package": self.work_package,
            "source_preflight_failures": self.source_preflight_failures,
            "release_gates_passed": self.release_gates_passed,
            "latest_observations_full_baseline": self.latest_observations_full_baseline,
        }


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def is_vendor_catalog_record_path(path: str) -> bool:
    """Return true for the bounded canonical vendor catalog record surface."""
    normalized = normalize_repo_path(path)
    parts = _parts(normalized)
    if len(parts) == 4:
        return (
            parts[0] == "data"
            and parts[1] == "vendors"
            and bool(parts[2])
            and parts[3] == "vendor.yaml"
        )
    if len(parts) == 5:
        filename = PurePosixPath(parts[4])
        return (
            parts[0] == "data"
            and parts[1] == "vendors"
            and bool(parts[2])
            and parts[3] in {"sources", "artifacts", "changes"}
            and filename.suffix in {".yaml", ".yml"}
            and bool(filename.stem)
        )
    return False


def is_generated_index_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return normalized.startswith("indexes/") and len(normalized) > len("indexes/")


def is_generated_dist_vendor_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    parts = _parts(normalized)
    filename = PurePosixPath(parts[2]) if len(parts) == 3 else PurePosixPath("")
    return (
        len(parts) == 3
        and parts[0] == "dist"
        and parts[1] == "vendors"
        and filename.suffix == ".json"
        and bool(filename.stem)
    )


def is_generated_catalog_pr_low_risk_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return (
        normalized == "openva-pack.json"
        or normalized == LATEST_OBSERVATIONS_PATH
        or is_vendor_catalog_record_path(normalized)
        or is_generated_index_path(normalized)
        or is_generated_dist_vendor_path(normalized)
    )


def classify_generated_catalog_pr_risk(
    changed_paths: list[str] | tuple[str, ...],
) -> GeneratedCatalogPrRiskResult:
    """Classify a generated candidate-promotion catalog PR by changed paths.

    The low-risk class is intentionally narrow: canonical vendor catalog records,
    deterministic generated index/dist outputs, `openva-pack.json`, and the exact
    committed latest-observations baseline. Any other path fails closed to
    HIGH_RISK so later automerge gates can refuse it.
    """
    paths = tuple(sorted({normalize_repo_path(path) for path in changed_paths if normalize_repo_path(path)}))
    if not paths:
        return GeneratedCatalogPrRiskResult(
            GeneratedCatalogPrRiskClass.HIGH_RISK,
            ("no_changed_paths",),
            (),
            (),
        )

    unexpected = tuple(path for path in paths if not is_generated_catalog_pr_low_risk_path(path))
    if unexpected:
        return GeneratedCatalogPrRiskResult(
            GeneratedCatalogPrRiskClass.HIGH_RISK,
            tuple(f"unexpected_path:{path}" for path in unexpected),
            paths,
            unexpected,
        )

    return GeneratedCatalogPrRiskResult(
        GeneratedCatalogPrRiskClass.LOW_RISK,
        (),
        paths,
        (),
    )


def read_paths_file(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig") as handle:
        return [line.strip() for line in handle if line.strip()]


def extract_work_package(pr_body: str) -> str | None:
    for raw_line in pr_body.splitlines():
        line = raw_line.strip()
        if line.startswith("Work-Package:"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def is_generated_candidate_promotion_pr(head_branch: str, title: str) -> bool:
    return (
        head_branch.startswith(GENERATED_CATALOG_BRANCH_PREFIX)
        and title.strip() == GENERATED_CATALOG_TITLE
    )


def _normalize_check_conclusions(checks: Mapping[str, str]) -> dict[str, str]:
    return {str(name): str(conclusion).lower() for name, conclusion in checks.items()}


def _check_status_reasons(
    checks: Mapping[str, str],
    required_checks: tuple[str, ...] = REQUIRED_GENERATED_CATALOG_CHECKS,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    normalized = _normalize_check_conclusions(checks)
    missing = tuple(check for check in required_checks if check not in normalized)
    failed = tuple(
        check
        for check in required_checks
        if check in normalized and normalized[check] != "success"
    )
    reasons = tuple([*(f"missing_check:{check}" for check in missing), *(f"failed_check:{check}" for check in failed)])
    return missing, failed, reasons


def evaluate_generated_catalog_automerge_eligibility(
    data: GeneratedCatalogAutoMergeInput,
) -> GeneratedCatalogAutoMergeEligibilityResult:
    """Return a fail-closed machine auto-merge decision for a generated catalog PR."""
    risk = classify_generated_catalog_pr_risk(data.changed_paths)
    work_package = extract_work_package(data.pr_body)
    missing_checks, failed_checks, check_reasons = _check_status_reasons(data.check_conclusions)
    reasons: list[str] = []

    if not is_generated_candidate_promotion_pr(data.head_branch, data.title):
        reasons.append("not_generated_candidate_promotion_pr")

    if work_package != GENERATED_CATALOG_WORK_PACKAGE:
        reasons.append(f"invalid_work_package:{work_package or 'missing'}")

    if risk.risk_class != GeneratedCatalogPrRiskClass.LOW_RISK:
        reasons.extend(risk.reasons)

    if data.is_draft:
        reasons.append("draft_pr")

    if not data.mergeable:
        reasons.append("not_mergeable")

    if data.unresolved_review_threads:
        reasons.append(f"unresolved_review_threads:{data.unresolved_review_threads}")

    reasons.extend(check_reasons)

    if data.source_preflight_failures != 0:
        reasons.append(f"source_preflight_failures:{data.source_preflight_failures}")

    if not data.release_gates_passed:
        reasons.append("release_gates_not_passed")

    if not data.latest_observations_full_baseline:
        reasons.append("latest_observations_full_baseline_not_passed")

    if not data.generated_outputs_fresh:
        reasons.append("generated_outputs_not_fresh")

    if not data.secret_scan_passed:
        reasons.append("secret_or_signature_material_detected")

    if data.selected_action_count is None:
        reasons.append("selected_action_count_missing")
    elif data.selected_action_count < 1:
        reasons.append(f"selected_action_count_not_positive:{data.selected_action_count}")
    elif data.selected_action_count > data.max_selected_action_count:
        reasons.append(
            f"selected_action_count_exceeded:{data.selected_action_count}>{data.max_selected_action_count}"
        )

    unique_reasons = tuple(dict.fromkeys(reasons))
    eligible = not unique_reasons
    return GeneratedCatalogAutoMergeEligibilityResult(
        eligible=eligible,
        decision="MERGE" if eligible else "DO_NOT_MERGE",
        risk_class=risk.risk_class,
        reasons=unique_reasons,
        required_checks=REQUIRED_GENERATED_CATALOG_CHECKS,
        missing_checks=missing_checks,
        failed_checks=failed_checks,
        changed_paths=risk.changed_paths,
        work_package=work_package,
        source_preflight_failures=data.source_preflight_failures,
        release_gates_passed=data.release_gates_passed,
        latest_observations_full_baseline=data.latest_observations_full_baseline,
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _parse_check(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("checks must use NAME=CONCLUSION")
    name, conclusion = value.split("=", 1)
    name = name.strip()
    conclusion = conclusion.strip()
    if not name or not conclusion:
        raise argparse.ArgumentTypeError("checks must use NAME=CONCLUSION")
    return name, conclusion


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify generated catalog PR diff risk.")
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--automerge-eligibility", action="store_true")
    parser.add_argument("--pr-body-file")
    parser.add_argument("--head-branch", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--draft", type=_parse_bool, default=False)
    parser.add_argument("--mergeable", type=_parse_bool, default=False)
    parser.add_argument("--unresolved-review-threads", type=int, default=0)
    parser.add_argument("--check", action="append", type=_parse_check, default=[])
    parser.add_argument("--source-preflight-failures", type=int, default=0)
    parser.add_argument("--release-gates-passed", type=_parse_bool, default=False)
    parser.add_argument("--latest-observations-full-baseline", type=_parse_bool, default=False)
    parser.add_argument("--generated-outputs-fresh", type=_parse_bool, default=False)
    parser.add_argument("--selected-action-count", type=int)
    parser.add_argument("--max-selected-action-count", type=int, default=DEFAULT_MAX_GENERATED_CATALOG_ACTIONS)
    parser.add_argument("--secret-scan-passed", type=_parse_bool, default=True)
    parser.add_argument("--out-json")
    args = parser.parse_args(argv)

    paths = read_paths_file(args.paths_file)
    if args.automerge_eligibility:
        if not args.pr_body_file:
            parser.error("--pr-body-file is required with --automerge-eligibility")
        with open(args.pr_body_file, encoding="utf-8-sig") as handle:
            pr_body = handle.read()
        result = evaluate_generated_catalog_automerge_eligibility(
            GeneratedCatalogAutoMergeInput(
                changed_paths=tuple(paths),
                pr_body=pr_body,
                head_branch=args.head_branch,
                title=args.title,
                is_draft=args.draft,
                mergeable=args.mergeable,
                check_conclusions=dict(args.check),
                source_preflight_failures=args.source_preflight_failures,
                release_gates_passed=args.release_gates_passed,
                latest_observations_full_baseline=args.latest_observations_full_baseline,
                generated_outputs_fresh=args.generated_outputs_fresh,
                unresolved_review_threads=args.unresolved_review_threads,
                selected_action_count=args.selected_action_count,
                max_selected_action_count=args.max_selected_action_count,
                secret_scan_passed=args.secret_scan_passed,
            )
        )
        payload = result.to_json_dict()
        output = json.dumps(payload, indent=2, sort_keys=True)
        print(output)
        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as handle:
                handle.write(output)
                handle.write("\n")
        return 0 if result.eligible else 1

    result = classify_generated_catalog_pr_risk(paths)
    print(f"risk_class={result.risk_class.value}")
    for reason in result.reasons:
        print(f"reason={reason}")
    for path in result.unexpected_paths:
        print(f"unexpected_path={path}")
    return 0 if result.low_risk else 1


if __name__ == "__main__":
    raise SystemExit(main())
