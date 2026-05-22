from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AUTOMERGE_GENERATED = "automerge:generated"
AUTOMERGE_OBSERVATION = "automerge:observation"
AUTOMERGE_MACHINE_CANONICAL = "automerge:machine-canonical"

DEFAULT_MAX_MACHINE_CANONICAL_RECORDS = 50

SENSITIVE_EXACT = {
    "CODEOWNERS",
    ".github/CODEOWNERS",
    "LICENSE",
    "SECURITY.md",
    "GOVERNANCE.md",
    "MAINTAINERS.md",
    "docs/catalog-autonomy-policy.md",
}

SENSITIVE_PREFIXES = (
    ".github/workflows/",
    "schemas/",
    "tools/openva/validate.py",
    "tools/openva/automation_rules.py",
)

GENERATED_EXACT = {
    "openva-pack.json",
    "release-artifacts.json",
}

GENERATED_PREFIXES = (
    "indexes/",
    "dist/",
    "release-downloads/",
)

OBSERVATION_PREFIXES = (
    "observations/",
    "reports/observations/",
    "site/dist/data/feed/",
)

MACHINE_CANONICAL_EXACT = {"openva-pack.json"}
MACHINE_CANONICAL_PREFIXES = ("data/vendors/", "indexes/", "catalog-batches/")


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    lane: str
    reasons: tuple[str, ...]
    report_only: bool = True


def load_policy(path: str | Path = "config/automerge-policy.yaml") -> dict[str, Any]:
    policy_path = Path(path)
    if not policy_path.exists():
        return {
            "mode": "report_only",
            "machine_canonical": {
                "max_source_records_per_pr": DEFAULT_MAX_MACHINE_CANONICAL_RECORDS
            },
        }
    return yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}


def policy_report_only(policy: dict[str, Any]) -> bool:
    return policy.get("mode", "report_only") != "enforce"


def machine_canonical_limit(policy: dict[str, Any]) -> int:
    return int(
        policy.get("machine_canonical", {}).get(
            "max_source_records_per_pr", DEFAULT_MAX_MACHINE_CANONICAL_RECORDS
        )
    )


def is_sensitive_path(path: str) -> bool:
    return path in SENSITIVE_EXACT or any(path.startswith(prefix) for prefix in SENSITIVE_PREFIXES)


def is_generated_path(path: str) -> bool:
    return path in GENERATED_EXACT or any(path.startswith(prefix) for prefix in GENERATED_PREFIXES)


def is_observation_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in OBSERVATION_PREFIXES)


def is_machine_canonical_path(path: str) -> bool:
    return path in MACHINE_CANONICAL_EXACT or any(
        path.startswith(prefix) for prefix in MACHINE_CANONICAL_PREFIXES
    )


def machine_canonical_record_count(paths: list[str]) -> int:
    return sum(1 for path in paths if path.startswith("data/vendors/"))


def eligible_for_lane(
    changed_paths: list[str],
    labels: list[str],
    policy: dict[str, Any] | None = None,
) -> EligibilityResult:
    policy = policy or load_policy()
    report_only = policy_report_only(policy)
    clean_labels = {label.strip() for label in labels if label.strip()}
    paths = [path.strip() for path in changed_paths if path.strip()]

    if not paths:
        return EligibilityResult(False, "none", ("no_changed_paths",), report_only)

    sensitive = [path for path in paths if is_sensitive_path(path)]
    if sensitive:
        return EligibilityResult(
            False,
            "needs-human-review",
            tuple(f"sensitive_path:{path}" for path in sensitive),
            report_only,
        )

    if AUTOMERGE_GENERATED in clean_labels:
        bad = [path for path in paths if not is_generated_path(path)]
        if bad:
            return EligibilityResult(
                False,
                AUTOMERGE_GENERATED,
                tuple(f"non_generated_path:{path}" for path in bad),
                report_only,
            )
        return EligibilityResult(True, AUTOMERGE_GENERATED, (), report_only)

    if AUTOMERGE_OBSERVATION in clean_labels:
        bad = [path for path in paths if not (is_observation_path(path) or is_generated_path(path))]
        if bad:
            return EligibilityResult(
                False,
                AUTOMERGE_OBSERVATION,
                tuple(f"non_observation_path:{path}" for path in bad),
                report_only,
            )
        return EligibilityResult(True, AUTOMERGE_OBSERVATION, (), report_only)

    if AUTOMERGE_MACHINE_CANONICAL in clean_labels:
        bad = [path for path in paths if not is_machine_canonical_path(path)]
        if bad:
            return EligibilityResult(
                False,
                AUTOMERGE_MACHINE_CANONICAL,
                tuple(f"non_machine_canonical_path:{path}" for path in bad),
                report_only,
            )
        count = machine_canonical_record_count(paths)
        limit = machine_canonical_limit(policy)
        if count > limit:
            return EligibilityResult(
                False,
                AUTOMERGE_MACHINE_CANONICAL,
                (f"machine_canonical_record_limit_exceeded:{count}>{limit}",),
                report_only,
            )
        return EligibilityResult(True, AUTOMERGE_MACHINE_CANONICAL, (), report_only)

    return EligibilityResult(False, "needs-human-review", ("no_automerge_label",), report_only)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check OpenVA agent auto-merge lane eligibility.")
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--labels", default="")
    parser.add_argument("--policy", default="config/automerge-policy.yaml")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)

    paths = open(args.paths_file, encoding="utf-8").read().splitlines()
    labels = [label for label in args.labels.split(",") if label]
    policy = load_policy(args.policy)
    result = eligible_for_lane(paths, labels, policy)

    print(f"eligible={str(result.eligible).lower()}")
    print(f"lane={result.lane}")
    print(f"report_only={str(result.report_only or args.report_only).lower()}")
    print(f"mode={policy.get('mode', 'report_only')}")
    print(f"max_machine_canonical_records_per_pr={machine_canonical_limit(policy)}")
    for reason in result.reasons:
        print(f"reason={reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
