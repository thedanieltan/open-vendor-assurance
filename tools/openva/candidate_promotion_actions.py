from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import yaml

from tools.openva.advisory_wording import prohibited_terms_in_text
from tools.openva.catalog_lifecycle import change_event
from tools.openva.indexes import build_indexes
from tools.openva.machine_decisions import append_decisions, load_decisions
from tools.openva.materialization_envelope import verify_envelope
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION, STRICT_GROWTH_PROMOTION_ACTION
from tools.openva.source_discovery import source_type_role
from tools.openva.source_verification import ROOT, display_path
from tools.openva.strict_growth_redirects import canonical_clean_reasons, redirect_metrics_for_actions
from tools.openva.url_safety import validate_url_safety

HASH_TBD = "sha256:TBD"

# WP36: machine materialization writes machine_provisional vendors (not active),
# each backed by a machine decision record with separation of duties.
DISCOVERY_BOT = "catalog-growth-discovery"
DECIDING_BOT = "strict-growth-materializer"
DEFAULT_NOT_BEFORE_DELAY_HOURS = 48


def not_before_delay_hours() -> int:
    path = ROOT / "config" / "machine-evidence-thresholds.yaml"
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return DEFAULT_NOT_BEFORE_DELAY_HOURS
    return int((config.get("materialization") or {}).get("not_before_delay_hours", DEFAULT_NOT_BEFORE_DELAY_HOURS))


def materialization_threshold_config() -> dict[str, Any]:
    path = ROOT / "config" / "machine-evidence-thresholds.yaml"
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    materialization = config.get("materialization") or {}
    return materialization if isinstance(materialization, dict) else {}


def retrieval_independence(attempts: list[Any], min_runs: int, min_modes: int) -> tuple[int, int, bool]:
    """Two agreeing retrievals are independent only across distinct workflow
    runs OR distinct retrieval modes. Same-run, same-mode retries are one
    observation. IP/geography is deliberately not a dimension.
    """
    runs = {str(a.get("workflow_run_id")) for a in attempts if isinstance(a, dict) and a.get("workflow_run_id")}
    modes = {str(a.get("retrieval_mode")) for a in attempts if isinstance(a, dict) and a.get("retrieval_mode")}
    distinct_runs, distinct_modes = len(runs), len(modes)
    return distinct_runs, distinct_modes, (distinct_runs >= min_runs or distinct_modes >= min_modes)


def build_retrieval_claim(
    *,
    required: int,
    observed: int,
    agreeing: bool,
    evidence_ids: list[Any],
    final_url: Any,
    candidate_url: Any,
    http_status: Any,
    min_distinct_workflow_runs: int,
    min_distinct_retrieval_modes: int,
    distinct_workflow_runs: int,
    distinct_retrieval_modes: int,
    independent: bool,
) -> dict[str, Any]:
    """Single authority for the retrieval claim shape, used by the evaluator and
    re-used by the automerge digest cross-check so the digest can never drift.
    """
    return {
        "required": required,
        "observed": observed,
        "agreeing": agreeing,
        "evidence_ids": evidence_ids,
        "final_url": final_url,
        "candidate_url": candidate_url,
        "http_status": http_status,
        "min_distinct_workflow_runs": min_distinct_workflow_runs,
        "min_distinct_retrieval_modes": min_distinct_retrieval_modes,
        "distinct_workflow_runs": distinct_workflow_runs,
        "distinct_retrieval_modes": distinct_retrieval_modes,
        "independent": independent,
    }


def materialization_threshold_results(action: dict[str, Any]) -> dict[str, Any]:
    config = materialization_threshold_config()
    vendor = action.get("vendor", {}) or {}
    source = action.get("source", {}) or {}
    evidence = source.get("evidence", {}) or {}
    retrieval = evidence.get("retrieval_attempts") or {}
    if not isinstance(retrieval, dict):
        retrieval = {}
    independence_config = config.get("retrieval_independence") or {}
    min_runs = int(independence_config.get("min_distinct_workflow_runs", 2))
    min_modes = int(independence_config.get("min_distinct_retrieval_modes", 2))
    attempts = retrieval.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
    observed_retrievals = len(attempts) if attempts else int(retrieval.get("observed") or evidence.get("retrieval_attempt_count") or 0)
    agreeing_retrievals = bool(retrieval.get("agreeing") or evidence.get("retrieval_attempts_agree") is True)
    distinct_runs, distinct_modes, independent = retrieval_independence(attempts, min_runs, min_modes)
    duplicate_score = float(vendor.get("duplicate_collision_score", evidence.get("duplicate_collision_score", 0.0)))
    retrieval_evidence_ids = retrieval.get("evidence_ids") or evidence.get("retrieval_evidence_ids") or []
    if not isinstance(retrieval_evidence_ids, list):
        retrieval_evidence_ids = []
    if attempts and not retrieval_evidence_ids:
        retrieval_evidence_ids = [
            f"retrieval-{idx + 1}:{attempt.get('workflow_run_id')}:{attempt.get('retrieval_mode')}"
            for idx, attempt in enumerate(attempts)
            if isinstance(attempt, dict)
        ]
    elif observed_retrievals and not retrieval_evidence_ids:
        retrieval_evidence_ids = [
            f"retrieval-{idx + 1}:{evidence.get('final_url') or source.get('candidate_url') or 'unknown'}"
            for idx in range(observed_retrievals)
        ]
    duplicate_evidence_ids = evidence.get("duplicate_collision_evidence_ids") or []
    if not isinstance(duplicate_evidence_ids, list):
        duplicate_evidence_ids = []
    if not duplicate_evidence_ids:
        duplicate_evidence_ids = [
            "duplicate-collision:"
            + str(vendor.get("candidate_vendor_id") or "")
            + ":"
            + str(vendor.get("official_domain_candidate") or "")
        ]
    retrieval_claim = build_retrieval_claim(
        required=int(config.get("min_agreeing_retrieval_attempts", 2)),
        observed=observed_retrievals,
        agreeing=agreeing_retrievals,
        evidence_ids=retrieval_evidence_ids,
        final_url=evidence.get("final_url"),
        candidate_url=source.get("candidate_url"),
        http_status=evidence.get("http_status"),
        min_distinct_workflow_runs=min_runs,
        min_distinct_retrieval_modes=min_modes,
        distinct_workflow_runs=distinct_runs,
        distinct_retrieval_modes=distinct_modes,
        independent=independent,
    )
    duplicate_claim = {
        "maximum": float(config.get("max_duplicate_collision_score", 0.0)),
        "observed": duplicate_score,
        "evidence_ids": duplicate_evidence_ids,
        "candidate_vendor_id": vendor.get("candidate_vendor_id"),
        "official_domain": vendor.get("official_domain_candidate"),
    }
    return {
        "official_entrypoint": "pass" if vendor.get("official_domain_candidate") else "fail",
        "name_supported_by_official_metadata": (
            "pass" if evidence.get("name_supported_by_official_domain_metadata") is True else "fail"
        ),
        "retrieval_attempts": {
            **retrieval_claim,
            "result_digest": sha256_bytes(canonical_json(retrieval_claim)),
        },
        "duplicate_collision_score": {
            **duplicate_claim,
            "result_digest": sha256_bytes(canonical_json(duplicate_claim)),
        },
        "source_host_authority": (
            "pass" if evidence.get("source_host_authority") in {"vendor_controlled", "same_domain"} else "fail"
        ),
        "adversarial_review": "pass" if evidence.get("adversarial_review") == "clean" else "fail",
        "evidence_freshness": "pass" if evidence.get("evidence_fresh") is True else "fail",
    }


def validate_materialization_thresholds(action: dict[str, Any]) -> None:
    results = materialization_threshold_results(action)
    failures: list[str] = []
    for key in (
        "official_entrypoint",
        "name_supported_by_official_metadata",
        "source_host_authority",
        "adversarial_review",
        "evidence_freshness",
    ):
        if results.get(key) != "pass":
            failures.append(f"{key}=fail")
    retrieval = results["retrieval_attempts"]
    if retrieval["observed"] < retrieval["required"] or retrieval["agreeing"] is not True:
        failures.append("retrieval_attempts=fail")
    if retrieval.get("independent") is not True:
        failures.append("retrieval_attempts_independence=fail")
    duplicate = results["duplicate_collision_score"]
    if duplicate["observed"] > duplicate["maximum"]:
        failures.append("duplicate_collision_score=fail")
    if failures:
        raise ValueError("strict growth materialization thresholds failed: " + ", ".join(failures))


def validate_materialization_envelope(action: dict[str, Any], root: Path) -> None:
    envelope = action.get("materialization_envelope")
    if not isinstance(envelope, dict):
        raise ValueError("strict growth materialization envelope missing")
    reasons = verify_envelope(action, envelope, root=root)
    if reasons:
        raise ValueError("strict growth materialization envelope invalid: " + ", ".join(reasons))


def materialization_decision(action: dict[str, Any], vendor_id: str, decision_id: str, now: datetime) -> dict[str, Any]:
    """Build the append-only machine decision record for a provisional vendor.

    Separation of duties: the deciding bot differs from the discovery bot.
    """
    not_before = now + timedelta(hours=not_before_delay_hours())
    source = action.get("source", {}) or {}
    evidence = source.get("evidence", {}) or {}
    candidate_digest = sha256_bytes(canonical_json(action))
    envelope = action.get("materialization_envelope")
    envelope_digest = sha256_bytes(canonical_json(envelope)) if isinstance(envelope, dict) else None
    return {
        "schema_version": "0.1.0",
        "decision_id": decision_id,
        "decision_type": "vendor_materialization",
        "subject_type": "vendor",
        "subject_id": vendor_id,
        "subject_lineage_id": vendor_id,
        "supersedes_decision_id": None,
        "reapplies_after_rollback_id": None,
        "decision": "materialize_provisional",
        "deciding_bot": DECIDING_BOT,
        "supporting_bots": [],
        "discovery_bot": DISCOVERY_BOT,
        "evidence": {
            "official_domain": str((action.get("vendor", {}) or {}).get("official_domain_candidate") or ""),
            "candidate_source_id": str(source.get("candidate_source_id") or ""),
            "source_type": str(source.get("source_type_candidate") or ""),
            "candidate_url": str(source.get("candidate_url") or ""),
            "http_status": evidence.get("http_status"),
            "matched_terms": evidence.get("matched_terms") or [],
            "final_url": evidence.get("final_url"),
            "name_supported_by_official_domain_metadata": evidence.get(
                "name_supported_by_official_domain_metadata"
            ),
            "source_host_authority": evidence.get("source_host_authority"),
            "adversarial_review": evidence.get("adversarial_review"),
            "evidence_fresh": evidence.get("evidence_fresh"),
            "materialization_envelope_digest": envelope_digest,
        },
        "counter_evidence": [],
        "thresholds": {
            "required_score": 1.0,
            "actual_score": 1.0,
            "results": materialization_threshold_results(action),
        },
        "source_queue_reference": str(
            (action.get("vendor", {}) or {}).get("cohort_id")
            or (action.get("vendor", {}) or {}).get("coverage_lane")
            or "strict_growth"
        ),
        "candidate_digest": candidate_digest,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "not_before": not_before.isoformat().replace("+00:00", "Z"),
        "reversal": {
            "method": "remove",
            "reference": f"Revert the materialization PR for {vendor_id}; see decision {decision_id}.",
            "reversal_decision_id": None,
        },
        "not_advice": True,
    }
CONFIDENCE_MAP = {
    "likely": "high",
    "possible": "medium",
    "candidate": "low",
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return data


def source_id(vendor_id: str, source_type: str) -> str:
    return f"{vendor_id}-{source_type.replace('_', '-')}"


def artifact_type(source_type: str) -> str:
    if source_type == "other_public_source":
        return "other_public_artifact"
    return source_type


def candidate_path(action: dict[str, Any], root: Path) -> Path:
    if action.get("path"):
        return root / str(action["path"])
    return root / "data" / "vendors" / str(action["vendor_id"]) / "candidate_sources" / f"{action['candidate_source_id']}.yaml"


def normalize_source_url_for_comparison(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return raw
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if not scheme or not host:
        return raw
    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{netloc}:{port}"
    path = quote(unquote(parsed.path or ""), safe="/:@!$&'()*+,;=")
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def canonical_sources_for_vendor(root: Path, vendor_id: str) -> list[tuple[Path, dict[str, Any]]]:
    sources: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "data" / "vendors" / vendor_id / "sources").glob("*.yaml")):
        try:
            sources.append((path, load_yaml(path)))
        except Exception:
            continue
    return sources


def reviewed_skip_entry(action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": action,
        "vendor_id": str(action.get("vendor_id") or result.get("vendor_id") or ""),
        "candidate_source_id": str(action.get("candidate_source_id") or result.get("candidate_source_id") or ""),
        "source_type": str(action.get("source_type") or result.get("source_type") or ""),
        "candidate_url": str(action.get("candidate_url") or result.get("candidate_url") or ""),
        "normalized_candidate_url": result.get("normalized_candidate_url"),
        "candidate_path": result.get("candidate_path"),
        "target_source_path": result.get("target_source_path"),
        "reason_codes": sorted(set(result.get("reason_codes") or [])),
    }


def reviewed_candidate_viability(action: dict[str, Any], root: Path) -> dict[str, Any]:
    reason_codes: list[str] = []
    vendor_id = str(action.get("vendor_id") or "")
    source_type = str(action.get("source_type") or "")
    candidate_url = str(action.get("candidate_url") or "")
    normalized_url = normalize_source_url_for_comparison(candidate_url)
    result: dict[str, Any] = {
        "viable": False,
        "vendor_id": vendor_id,
        "source_type": source_type,
        "candidate_source_id": str(action.get("candidate_source_id") or ""),
        "candidate_url": candidate_url,
        "normalized_candidate_url": normalized_url,
    }

    try:
        validate_action(action)
    except ValueError:
        reason_codes.append("candidate_action_invalid")

    c_path = candidate_path(action, root)
    result["candidate_path"] = display_path(c_path, root)
    if not c_path.exists():
        reason_codes.append("candidate_source_missing")
        result["reason_codes"] = sorted(set(reason_codes))
        return result

    try:
        candidate = load_yaml(c_path)
    except Exception:
        reason_codes.append("candidate_source_malformed")
        result["reason_codes"] = sorted(set(reason_codes))
        return result

    missing = [
        field
        for field in [
            "candidate_source_id",
            "vendor_id",
            "source_type_candidate",
            "candidate_url",
            "requires_review",
            "evidence",
            "not_advice",
        ]
        if field not in candidate
    ]
    if missing:
        reason_codes.append("candidate_missing_required_fields")

    if vendor_id and not (root / "data" / "vendors" / vendor_id / "vendor.yaml").exists():
        reason_codes.append("vendor_missing")

    if source_type and not source_type_role(source_type, "qualifies_as_promotion_source_role"):
        reason_codes.append("source_type_not_allowed")

    try:
        parsed = urlsplit(candidate_url)
        _port = parsed.port
        if parsed.scheme.lower() != "https":
            reason_codes.append("source_url_not_https")
    except ValueError:
        reason_codes.append("source_url_malformed")
    for _failure in validate_url_safety(candidate_url):
        reason_codes.append("source_url_not_safe")
        break

    expected = {
        "vendor_id": vendor_id,
        "candidate_source_id": str(action.get("candidate_source_id") or ""),
        "source_type_candidate": source_type,
        "candidate_url": candidate_url,
    }
    if any(candidate.get(key) != value for key, value in expected.items()):
        reason_codes.append("candidate_action_mismatch")
    if candidate.get("requires_review") is not True or candidate.get("not_advice") is not True:
        reason_codes.append("candidate_promotion_invariant_failed")
    evidence = candidate.get("evidence", {}) if isinstance(candidate.get("evidence"), dict) else {}
    if evidence.get("http_status") != 200:
        reason_codes.append("candidate_http_status_not_200")
    if not evidence.get("matched_terms"):
        reason_codes.append("candidate_missing_matched_terms")

    advisory_terms: set[str] = set()
    for value in (candidate.get("notes"), evidence.get("page_title")):
        advisory_terms.update(prohibited_terms_in_text(value))
    if advisory_terms:
        reason_codes.append("prohibited_advisory_wording")

    record: dict[str, Any] | None = None
    if not reason_codes:
        try:
            record = source_from_candidate(candidate, action)
        except Exception:
            reason_codes.append("canonical_source_render_failed")

    if record:
        s_path = root / "data" / "vendors" / record["vendor_id"] / "sources" / f"{record['source_id']}.yaml"
        a_path = root / "data" / "vendors" / record["vendor_id"] / "artifacts" / f"{record['source_id']}.yaml"
        c_path_out = root / "data" / "vendors" / record["vendor_id"] / "changes" / f"candidate-promotion-{record['source_id']}.yaml"
        result["target_source_path"] = display_path(s_path, root)
        if s_path.exists():
            reason_codes.append("canonical_source_path_exists")
        if a_path.exists():
            reason_codes.append("canonical_artifact_path_exists")
        if c_path_out.exists():
            reason_codes.append("change_event_path_exists")

    for _path, source in canonical_sources_for_vendor(root, vendor_id):
        if normalize_source_url_for_comparison(source.get("source_url")) == normalized_url:
            reason_codes.append("duplicate_canonical_source_url")
            if str(source.get("source_type") or "") == source_type:
                reason_codes.append("already_represented_by_canonical_source")

    result["reason_codes"] = sorted(set(reason_codes))
    result["viable"] = not result["reason_codes"]
    return result


def filter_reviewed_candidate_plan(
    promotion_plan: dict[str, Any], root: Path = ROOT, max_actions: int | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    viable_actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    considered = 0
    for action in promotion_plan.get("actions", []) or []:
        if action.get("action") != REVIEWED_CANDIDATE_PROMOTION_ACTION:
            continue
        considered += 1
        result = reviewed_candidate_viability(action, root)
        if result["viable"]:
            viable_actions.append(action)
        else:
            skipped.append(reviewed_skip_entry(action, result))

    cap = max_actions or 0
    selected_actions = viable_actions[:cap] if cap else viable_actions
    deferred_due_to_cap = viable_actions[cap:] if cap else []
    reason_counts = Counter(reason for item in skipped for reason in item.get("reason_codes", []))
    deferred_actions = [
        {"action": action, "reason_codes": ["max_promotion_actions_per_pr_exceeded"]}
        for action in deferred_due_to_cap
    ]
    filtered = {
        **promotion_plan,
        "actions": selected_actions,
        "skipped_actions": skipped,
        "deferred_actions": [
            *((promotion_plan.get("deferred_actions") or [])),
            *deferred_actions,
        ],
        "summary": {
            **(promotion_plan.get("summary") or {}),
            "action_count": len(selected_actions),
            "selected_promotion_action_count": len(selected_actions),
            "viability_candidate_actions_considered": considered,
            "viable_action_count": len(selected_actions),
            "viable_before_cap_count": len(viable_actions),
            "selected_after_cap_count": len(selected_actions),
            "deferred_due_to_cap_count": len(deferred_due_to_cap),
            "skipped_action_count": len(skipped),
            "skip_reason_counts": dict(sorted(reason_counts.items())),
            "max_promotion_actions_per_pr": cap,
            "batch_deferred_action_count": len(deferred_due_to_cap),
        },
    }
    report = {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "candidate_promotion_viability_report",
        "summary": {
            "candidate_actions_considered": considered,
            "viable_action_count": len(selected_actions),
            "viable_before_cap_count": len(viable_actions),
            "selected_after_cap_count": len(selected_actions),
            "deferred_due_to_cap_count": len(deferred_due_to_cap),
            "skipped_action_count": len(skipped),
            "skip_reason_counts": dict(sorted(reason_counts.items())),
            "max_promotion_actions_per_pr": cap,
        },
        "viable_actions": [
            {
                "vendor_id": str(action.get("vendor_id") or ""),
                "candidate_source_id": str(action.get("candidate_source_id") or ""),
                "source_type": str(action.get("source_type") or ""),
                "candidate_url": str(action.get("candidate_url") or ""),
            }
            for action in selected_actions
        ],
        "deferred_viable_actions": [
            {
                "vendor_id": str(action.get("vendor_id") or ""),
                "candidate_source_id": str(action.get("candidate_source_id") or ""),
                "source_type": str(action.get("source_type") or ""),
                "candidate_url": str(action.get("candidate_url") or ""),
                "reason_codes": ["max_promotion_actions_per_pr_exceeded"],
            }
            for action in deferred_due_to_cap
        ],
        "skipped_actions": skipped,
    }
    return filtered, report


def build_sitemap_source_plan_from_artifacts(
    discovery_events: dict[str, Any], raw_plan: dict[str, Any], root: Path = ROOT
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replay sitemap-source candidate promotion selection from saved artifacts.

    This intentionally performs no network fetches. It rehydrates the reviewed
    candidate-source records that the live workflow would have written from the
    saved discovery events, then rebuilds the uncapped sitemap-source promotion
    plan from the saved raw planner output.
    """
    from tools.openva.source_discovery import write_discovery_outputs

    vendors = list((discovery_events.get("verification") or {}).get("vendors") or [])
    candidate_ids: list[str] = []
    temporary_paths: list[str] = []
    for vendor in vendors:
        vendor_id = str(vendor.get("vendor_id") or "")
        if not vendor_id:
            continue
        new_candidates: list[dict[str, Any]] = []
        for candidate in vendor.get("candidates") or []:
            candidate_id = str(candidate.get("candidate_source_id") or "")
            if not candidate_id:
                continue
            candidate_ids.append(candidate_id)
            candidate_path = root / "data" / "vendors" / vendor_id / "candidate_sources" / f"{candidate_id}.yaml"
            if not candidate_path.exists():
                new_candidates.append(candidate)
                temporary_paths.append(display_path(candidate_path, root))
        if new_candidates:
            write_discovery_outputs(
                {"vendor_id": vendor_id, "candidates": new_candidates, "unavailable_sources": []},
                root=root,
            )

    sitemap_candidate_ids = set(candidate_ids)
    promote_actions = [
        action
        for action in raw_plan.get("actions", []) or []
        if action.get("action") == REVIEWED_CANDIDATE_PROMOTION_ACTION
        and action.get("candidate_source_id") in sitemap_candidate_ids
    ]
    counts = Counter(action["action"] for action in promote_actions)
    plan = {
        **raw_plan,
        "report_type": "sitemap_source_promotion_plan",
        "inputs": {
            **(raw_plan.get("inputs") or {}),
            "sitemap_source_discovery_report_path": "sitemap-source-discovery-events.json",
            "sitemap_candidate_manifest_path": "sitemap-source-candidate-manifest.json",
            "replay_from_saved_artifacts": True,
        },
        "summary": {
            **(raw_plan.get("summary") or {}),
            "action_count": len(promote_actions),
            "selected_promotion_action_count": len(promote_actions),
            "candidate_source_ids_from_sitemap": len(sitemap_candidate_ids),
            "uncapped_action_count": len(promote_actions),
            "batch_deferred_action_count": 0,
            "viability_filter_pending": True,
            "action_types": dict(sorted(counts.items())),
        },
        "actions": promote_actions,
    }
    manifest = {
        "candidate_source_ids": sorted(sitemap_candidate_ids),
        "temporary_candidate_paths": sorted(set(temporary_paths)),
    }
    return plan, manifest


def validate_action(action: dict[str, Any]) -> None:
    if action.get("action") != REVIEWED_CANDIDATE_PROMOTION_ACTION:
        raise ValueError("unsupported candidate promotion action")
    if action.get("requires_human_review") is not True:
        raise ValueError("candidate promotion action must require review")
    if action.get("writes_canonical_sources") is not False:
        raise ValueError("promotion plan action must be non-mutating")
    if action.get("non_advisory") is not True:
        raise ValueError("candidate promotion action must be non-advisory")
    for field in ["vendor_id", "source_type", "candidate_source_id", "candidate_url"]:
        if not action.get(field):
            raise ValueError(f"candidate promotion action missing {field}")


def validate_strict_growth_action(action: dict[str, Any]) -> None:
    if action.get("action") != STRICT_GROWTH_PROMOTION_ACTION:
        raise ValueError("unsupported strict growth action")
    if action.get("requires_human_review") is not False:
        raise ValueError("strict growth action must be machine-strict, not human-review gated")
    if action.get("writes_canonical_vendors") is not False or action.get("writes_canonical_sources") is not False:
        raise ValueError("strict growth plan must be non-mutating until apply")
    if action.get("strict_machine_candidate") is not True or action.get("non_advisory") is not True:
        raise ValueError("strict growth action must be strict machine non-advisory")
    vendor = action.get("vendor", {}) or {}
    source = action.get("source", {}) or {}
    for field in ["candidate_vendor_id", "display_name_candidate", "official_domain_candidate", "headquarters_country_candidate"]:
        if not vendor.get(field):
            raise ValueError(f"strict growth vendor missing {field}")
    for field in ["source_type_candidate", "candidate_url", "evidence"]:
        if not source.get(field):
            raise ValueError(f"strict growth source missing {field}")
    evidence = source.get("evidence", {}) or {}
    if evidence.get("http_status") != 200:
        raise ValueError("strict growth source requires HTTP 200 evidence")
    if not evidence.get("matched_terms"):
        raise ValueError("strict growth source requires matched terms")
    if not evidence.get("final_url"):
        raise ValueError("strict growth source requires final URL evidence")
    canonical_reasons = canonical_clean_reasons(action)
    if canonical_reasons:
        raise ValueError(f"strict growth source is not redirect canonical-clean: {', '.join(canonical_reasons)}")
    for value in (source.get("title"), source.get("description"), evidence.get("page_title")):
        terms = prohibited_terms_in_text(value)
        if terms:
            raise ValueError(f"strict growth advisory wording detected: {', '.join(terms)}")
    validate_materialization_thresholds(action)


def validate_candidate(candidate: dict[str, Any], action: dict[str, Any]) -> None:
    expected = {
        "vendor_id": action["vendor_id"],
        "candidate_source_id": action["candidate_source_id"],
        "source_type_candidate": action["source_type"],
        "candidate_url": action["candidate_url"],
    }
    for key, value in expected.items():
        if candidate.get(key) != value:
            raise ValueError(f"candidate {key} does not match reviewed action")
    if candidate.get("requires_review") is not True:
        raise ValueError("candidate source must require review")
    if candidate.get("not_advice") is not True:
        raise ValueError("candidate source must be non-advisory")
    evidence = candidate.get("evidence", {}) or {}
    if evidence.get("http_status") != 200:
        raise ValueError("candidate promotion requires HTTP 200 evidence")
    if not evidence.get("matched_terms"):
        raise ValueError("candidate promotion requires matched terms")


def coverage_claims_from(*records: dict[str, Any]) -> list[dict[str, Any]]:
    for record in records:
        claims = record.get("coverage_claims")
        if isinstance(claims, list) and claims:
            return claims
    return []


def source_from_candidate(candidate: dict[str, Any], action: dict[str, Any] | None = None) -> dict[str, Any]:
    vendor_id = str(candidate["vendor_id"])
    source_type = str(candidate["source_type_candidate"])
    evidence = candidate.get("evidence", {}) or {}
    confidence = CONFIDENCE_MAP.get(str(candidate.get("confidence", "candidate")), "low")
    record = {
        "schema_version": "0.1.0",
        "source_id": source_id(vendor_id, source_type),
        "vendor_id": vendor_id,
        "source_type": source_type,
        "source_authority_class": "vendor_published",
        "title_native": str(evidence.get("page_title") or source_type.replace("_", " ").title()),
        "source_url": str(candidate["candidate_url"]),
        "source_language": "en",
        "access_class": "public_web",
        "rights_class": "metadata_only",
        "provenance": {
            "publisher": "vendor",
            "collected_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "observer": "agent",
            "confidence": confidence,
        },
        "not_advice": True,
    }
    claims = coverage_claims_from(action or {}, candidate)
    if claims:
        record["coverage_claims"] = claims
    return record


def vendor_from_strict_growth(action: dict[str, Any], decision_id: str) -> dict[str, Any]:
    vendor = action["vendor"]
    domain = str(vendor["official_domain_candidate"]).lower().removeprefix("www.")
    return {
        "schema_version": "0.1.0",
        "vendor_id": str(vendor["candidate_vendor_id"]),
        "display_name": str(vendor["display_name_candidate"]),
        "legal_name": None,
        "headquarters_country": str(vendor["headquarters_country_candidate"]),
        "regions_served": ["global"],
        "official_domains": [domain],
        "public_entrypoints": [f"https://{domain}"],
        "vendor_categories": vendor.get("vendor_category_candidates") or [],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        # WP36: machine-materialized vendors enter as machine_provisional, never
        # directly active. Promotion to active is WP37 quorum after observation.
        "catalog_status": "machine_provisional",
        "machine_generated": True,
        "machine_decision_id": decision_id,
        "reversal": {
            "method": "remove",
            "reference": f"Revert the materialization PR; see decision {decision_id}.",
            "reversal_decision_id": None,
        },
        "notes": "Machine-provisional catalog growth vendor materialized from public source discovery evidence. Metadata-only; not advisory; reversible.",
        "entity_surface": "global_brand",
        "source_authority_language": "en",
    }


def source_from_strict_growth(action: dict[str, Any]) -> dict[str, Any]:
    vendor = action["vendor"]
    source = action["source"]
    evidence = source.get("evidence", {}) or {}
    candidate = {
        "vendor_id": vendor["candidate_vendor_id"],
        "source_type_candidate": source["source_type_candidate"],
        "candidate_url": evidence.get("final_url") if evidence.get("redirect_reason") == "redirect_canonicalized" else source["candidate_url"],
        "confidence": source.get("confidence", "likely"),
        "evidence": evidence,
        "coverage_claims": source.get("coverage_claims", []),
    }
    return source_from_candidate(candidate, source)


def materialization_decision_id(vendor_id: str, action: dict[str, Any], decisions_dir: Path) -> str:
    digest = sha256_bytes(canonical_json(action)).removeprefix("sha256:")[:12]
    prefix = f"{vendor_id}-materialization-{digest}"
    existing = {
        str(record.get("decision_id") or "")
        for record in load_decisions(decisions_dir)
        if str(record.get("decision_id") or "").startswith(prefix)
    }
    sequence = 1
    while f"{prefix}-{sequence:03d}" in existing:
        sequence += 1
    return f"{prefix}-{sequence:03d}"


def artifact_from_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "artifact_id": str(source["source_id"]),
        "vendor_id": str(source["vendor_id"]),
        "source_id": str(source["source_id"]),
        "artifact_type": artifact_type(str(source["source_type"])),
        "canonical_url": str(source["source_url"]),
        "source_language": str(source["source_language"]),
        "region_scope": [],
        "entity_scope": {"scope_type": "brand_surface", "entity_ids": []},
        "product_scope": [],
        "access_class": str(source["access_class"]),
        "rights_class": str(source["rights_class"]),
        "effective_or_published_at": None,
        "hashes": {
            "raw_sha256": HASH_TBD,
            "normalized_text_sha256": HASH_TBD,
            "hash_method": "metadata_plus_hash_only",
        },
        "storage": {
            "raw_document_stored": False,
            "extracted_text_stored": False,
            "screenshot_stored": False,
        },
        "not_advice": True,
    }


def apply_reviewed_candidate(action: dict[str, Any], root: Path) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    viability = reviewed_candidate_viability(action, root)
    if not viability["viable"]:
        return [], reviewed_skip_entry(action, viability)
    c_path = candidate_path(action, root)
    candidate = load_yaml(c_path)
    validate_candidate(candidate, action)
    record = source_from_candidate(candidate, action)
    s_path = root / "data" / "vendors" / record["vendor_id"] / "sources" / f"{record['source_id']}.yaml"
    a_path = root / "data" / "vendors" / record["vendor_id"] / "artifacts" / f"{record['source_id']}.yaml"
    c_path_out = root / "data" / "vendors" / record["vendor_id"] / "changes" / f"candidate-promotion-{record['source_id']}.yaml"
    write_yaml(s_path, record)
    artifact = artifact_from_source(record)
    write_yaml(a_path, artifact)
    write_yaml(
        c_path_out,
        change_event(
            change_id=f"candidate-promotion-{record['source_id']}",
            vendor_id=str(record["vendor_id"]),
            source_id=str(record["source_id"]),
            artifact_id=str(artifact["artifact_id"]),
            change_type="created",
            detected_at=str(record["provenance"]["collected_at"]),
            summary="Reviewed candidate source promoted to canonical public source metadata.",
        ),
    )
    return [
        {"action": "write", "path": display_path(s_path, root), "candidate_path": display_path(c_path, root)},
        {"action": "write", "path": display_path(a_path, root), "candidate_path": display_path(c_path, root)},
        {"action": "write", "path": display_path(c_path_out, root), "candidate_path": display_path(c_path, root)},
    ], None


def apply_strict_growth(action: dict[str, Any], root: Path, written_vendors: set[str]) -> list[dict[str, str]]:
    validate_strict_growth_action(action)
    validate_materialization_envelope(action, root)
    vendor_id = str(action["vendor"]["candidate_vendor_id"])
    decisions_dir = root / "maintenance" / "machine-decisions"
    decision_id = materialization_decision_id(vendor_id, action, decisions_dir)
    vendor = vendor_from_strict_growth(action, decision_id)
    source = source_from_strict_growth(action)
    artifact = artifact_from_source(source)
    base = root / "data" / "vendors" / vendor_id
    v_path = base / "vendor.yaml"
    s_path = base / "sources" / f"{source['source_id']}.yaml"
    a_path = base / "artifacts" / f"{artifact['artifact_id']}.yaml"
    c_path = base / "changes" / f"strict-growth-{source['source_id']}.yaml"
    for path in (s_path, a_path, c_path):
        if path.exists():
            raise ValueError(f"strict growth target already exists: {display_path(path, root)}")

    file_actions: list[dict[str, str]] = []
    if v_path.exists():
        if vendor_id not in written_vendors:
            raise ValueError(f"strict growth vendor already exists: {display_path(v_path, root)}")
    else:
        # Emit the append-only machine decision record before writing the
        # provisional vendor, so the vendor links a real, committed decision.
        decision = materialization_decision(action, vendor_id, decision_id, datetime.now(UTC))
        decision_files = append_decisions([decision], decisions_dir)
        write_yaml(v_path, vendor)
        written_vendors.add(vendor_id)
        file_actions.append({"action": "write", "path": display_path(v_path, root), "candidate_path": "strict_growth_plan"})
        for decision_file in decision_files:
            file_actions.append({"action": "append", "path": display_path(decision_file, root), "candidate_path": "machine_decision_record"})

    write_yaml(s_path, source)
    write_yaml(a_path, artifact)
    write_yaml(
        c_path,
        change_event(
            change_id=f"strict-growth-{source['source_id']}",
            vendor_id=str(source["vendor_id"]),
            source_id=str(source["source_id"]),
            artifact_id=str(artifact["artifact_id"]),
            change_type="created",
            detected_at=str(source["provenance"]["collected_at"]),
            summary="Strict catalog growth candidate promoted to canonical public source metadata.",
        ),
    )
    file_actions.extend(
        [
            {"action": "write", "path": display_path(s_path, root), "candidate_path": "strict_growth_plan"},
            {"action": "write", "path": display_path(a_path, root), "candidate_path": "strict_growth_plan"},
            {"action": "write", "path": display_path(c_path, root), "candidate_path": "strict_growth_plan"},
        ]
    )
    return file_actions


def apply_candidate_promotions(promotion_plan: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    actions = [
        action for action in promotion_plan.get("actions", []) or []
        if action.get("action") in {REVIEWED_CANDIDATE_PROMOTION_ACTION, STRICT_GROWTH_PROMOTION_ACTION}
    ]
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    strict_growth_written_vendors: set[str] = set()
    for action in actions:
        if action.get("action") == STRICT_GROWTH_PROMOTION_ACTION:
            applied.extend(apply_strict_growth(action, root, strict_growth_written_vendors))
        else:
            file_actions, skip = apply_reviewed_candidate(action, root)
            applied.extend(file_actions)
            if skip:
                skipped.append(skip)

    if root.resolve() == ROOT.resolve():
        build_indexes()
    redirect_metrics = redirect_metrics_for_actions(actions)
    skip_reason_counts = Counter(reason for item in skipped for reason in item.get("reason_codes", []))
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "candidate_promotion_apply_report",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": True,
            "writes_canonical_vendors": True,
            "writes_canonical_sources": True,
            "non_advisory": True,
        },
        "summary": {
            "promotion_actions_seen": len(actions),
            "canonical_vendors_written": sum(1 for item in applied if item["path"].endswith("/vendor.yaml")),
            "canonical_sources_written": sum(1 for item in applied if "/sources/" in item["path"]),
            "canonical_artifacts_written": sum(1 for item in applied if "/artifacts/" in item["path"]),
            "change_events_written": sum(1 for item in applied if "/changes/" in item["path"]),
            "skipped_actions": len(skipped),
            "skip_reason_counts": dict(sorted(skip_reason_counts.items())),
            **redirect_metrics,
        },
        "file_actions": applied,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-candidate-promotion-actions")
    parser.add_argument("command", choices={"apply", "filter-reviewed-plan", "replay-sitemap-source-plan"})
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "candidate-promotion-report.json")
    parser.add_argument("--viability-report", type=Path, default=ROOT / "candidate-promotion-viability-report.json")
    parser.add_argument("--discovery-events", type=Path)
    parser.add_argument("--candidate-manifest", type=Path, default=ROOT / "sitemap-source-candidate-manifest.json")
    parser.add_argument("--max-actions", type=int, default=None)
    args = parser.parse_args()
    if args.max_actions is not None and args.max_actions < 0:
        raise SystemExit("--max-actions must be a non-negative integer")
    if args.command == "filter-reviewed-plan":
        filtered, report = filter_reviewed_candidate_plan(load_json(args.promotion_plan), max_actions=args.max_actions)
        args.output.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.viability_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    elif args.command == "replay-sitemap-source-plan":
        if args.discovery_events is None:
            raise SystemExit("replay-sitemap-source-plan requires --discovery-events")
        plan, manifest = build_sitemap_source_plan_from_artifacts(
            load_json(args.discovery_events), load_json(args.promotion_plan)
        )
        filtered, report = filter_reviewed_candidate_plan(plan, max_actions=args.max_actions)
        args.output.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.viability_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.candidate_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    else:
        report = apply_candidate_promotions(load_json(args.promotion_plan))
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
