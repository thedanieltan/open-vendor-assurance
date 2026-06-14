"""WP40B autonomous source-repair classifier.

Replaces the reviewer-CSV maintenance loop with a deterministic classifier that
maps a source's committed observation history (and any candidate replacement
evidence) to exactly one repair outcome and the autonomous action it implies.

Outcomes and the action each implies:

    temporary_failure       -> bounded_retry        (do not repair yet)
    confirmed_unavailable    -> quarantine           (no safe replacement)
    same_authority_redirect  -> repair_candidate     (needs more evidence)
    safe_replacement         -> autonomous_repair_pr (verified replacement)
    ambiguous_replacement    -> defer                (no human escalation)
    gated                    -> record_access_state_and_quarantine
    bot_protected            -> record_access_state  (never bypassed)
    generic_redirect         -> defer
    cross_authority_unproven -> defer

A replacement is only ``safe_replacement`` when it satisfies *every* guard:
repeated observations, fresh evidence, matching vendor authority, matching
source role, and no duplicate conflict. Anything short of that fails closed to
``defer`` or ``quarantine``; nothing escalates to a human queue.

This module is a pure function of its inputs (observation statuses, failure
counts, and replacement evidence). It never fetches, authenticates, or bypasses
bot protection.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Latest-status buckets, expressed in the shared classify_status vocabulary.
TEMPORARY_STATUSES = {"unreachable", "server_error", "rate_limited", "soft_not_found"}
UNAVAILABLE_STATUSES = {"not_found", "gone"}
GATED_STATUSES = {"gated_or_login_required", "forbidden_unknown"}
BOT_PROTECTED_STATUSES = {"bot_protected"}
GENERIC_REDIRECT_STATUSES = {"homepage_or_generic_redirect"}

OUTCOMES = (
    "temporary_failure",
    "confirmed_unavailable",
    "same_authority_redirect",
    "safe_replacement",
    "ambiguous_replacement",
    "gated",
    "bot_protected",
    "generic_redirect",
    "cross_authority_unproven",
)

ACTIONS = (
    "bounded_retry",
    "quarantine",
    "repair_candidate",
    "autonomous_repair_pr",
    "defer",
    "record_access_state_and_quarantine",
    "record_access_state",
)

# Defaults; live thresholds come from config/machine-evidence-thresholds.yaml
# when the caller supplies them.
DEFAULT_MIN_FAILURES_FOR_CONFIRMED = 3
DEFAULT_MIN_REPLACEMENT_OBSERVATIONS = 2


@dataclass
class Replacement:
    """Candidate replacement evidence for a failing source."""

    final_url: str
    reachable: bool = False
    on_same_authority: bool = False
    source_role_match: bool = False
    duplicate_conflict: bool = False
    repeated_observations: int = 0
    semantic_strong: bool = False
    fresh_evidence: bool = False


@dataclass
class RepairClassification:
    outcome: str
    action: str
    reasons: list[str] = field(default_factory=list)
    reversible: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "action": self.action,
            "reasons": list(self.reasons),
            "reversible": self.reversible,
            "not_advice": True,
        }


def classify_repair(
    *,
    latest_status: str,
    consecutive_failures: int,
    replacement: Replacement | None = None,
    min_failures_for_confirmed: int = DEFAULT_MIN_FAILURES_FOR_CONFIRMED,
    min_replacement_observations: int = DEFAULT_MIN_REPLACEMENT_OBSERVATIONS,
) -> RepairClassification:
    """Classify one failing source into exactly one repair outcome + action."""

    # Access-state facts come first: never bypassed, never fetched-around.
    if latest_status in BOT_PROTECTED_STATUSES:
        return RepairClassification(
            "bot_protected", "record_access_state",
            ["bot_protection_recorded_not_bypassed"],
        )
    if latest_status in GATED_STATUSES:
        # A gated source that is persistently gated is quarantined as an
        # access-state fact; a gated source is never authenticated against.
        action = "record_access_state_and_quarantine" if consecutive_failures >= min_failures_for_confirmed else "record_access_state"
        return RepairClassification("gated", action, ["gated_access_state_recorded"])

    if latest_status in TEMPORARY_STATUSES and consecutive_failures < min_failures_for_confirmed:
        return RepairClassification(
            "temporary_failure", "bounded_retry",
            [f"transient_status_{latest_status}_failures_{consecutive_failures}"],
        )

    # From here the source is persistently failing. A replacement may rescue it.
    if replacement is not None and replacement.reachable:
        return _classify_replacement(replacement, min_replacement_observations)

    if latest_status in GENERIC_REDIRECT_STATUSES:
        return RepairClassification(
            "generic_redirect", "defer",
            ["resolves_to_homepage_or_generic_page_no_replacement"],
        )

    if latest_status in UNAVAILABLE_STATUSES or consecutive_failures >= min_failures_for_confirmed:
        return RepairClassification(
            "confirmed_unavailable", "quarantine",
            [f"persistent_{latest_status}_failures_{consecutive_failures}_no_safe_replacement"],
        )

    # Still failing but not yet confirmed and no replacement: keep retrying.
    return RepairClassification(
        "temporary_failure", "bounded_retry",
        [f"unconfirmed_status_{latest_status}"],
    )


def _classify_replacement(replacement: Replacement, min_observations: int) -> RepairClassification:
    reasons: list[str] = []
    if replacement.duplicate_conflict:
        return RepairClassification(
            "ambiguous_replacement", "defer", ["replacement_duplicate_conflict"],
        )
    if not replacement.on_same_authority:
        return RepairClassification(
            "cross_authority_unproven", "defer", ["replacement_off_vendor_authority_unproven"],
        )
    # Same authority from here.
    if not replacement.source_role_match:
        return RepairClassification(
            "ambiguous_replacement", "defer", ["replacement_source_role_mismatch"],
        )
    has_repeated = replacement.repeated_observations >= min_observations
    if has_repeated and replacement.fresh_evidence and replacement.semantic_strong:
        return RepairClassification(
            "safe_replacement", "autonomous_repair_pr",
            [
                f"same_authority_role_match_observations_{replacement.repeated_observations}",
                "fresh_evidence",
                "semantic_strong",
            ],
        )
    # Same authority + role match but not yet enough proof -> a repair candidate
    # that needs more observations before it becomes a PR.
    reasons.append("same_authority_role_match")
    if not has_repeated:
        reasons.append(f"observations_{replacement.repeated_observations}<min_{min_observations}")
    if not replacement.fresh_evidence:
        reasons.append("evidence_not_fresh")
    if not replacement.semantic_strong:
        reasons.append("semantic_not_strong")
    return RepairClassification("same_authority_redirect", "repair_candidate", reasons)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-source-repair-classifier")
    parser.add_argument("--input", type=Path, required=True, help="JSON with latest_status/consecutive_failures/replacement")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    replacement = None
    if payload.get("replacement"):
        replacement = Replacement(**payload["replacement"])
    result = classify_repair(
        latest_status=payload["latest_status"],
        consecutive_failures=int(payload.get("consecutive_failures", 0)),
        replacement=replacement,
    ).as_dict()
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
