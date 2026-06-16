from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from tools.openva.advisory_wording import prohibited_terms_in_text
from tools.openva.catalog_lifecycle import change_event
from tools.openva.indexes import build_indexes
from tools.openva.machine_decisions import append_decisions, load_decisions
from tools.openva.materialization_envelope import verify_envelope
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.promotion_planner import REVIEWED_CANDIDATE_PROMOTION_ACTION, STRICT_GROWTH_PROMOTION_ACTION
from tools.openva.source_verification import ROOT, display_path
from tools.openva.strict_growth_redirects import canonical_clean_reasons, redirect_metrics_for_actions

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


def apply_reviewed_candidate(action: dict[str, Any], root: Path) -> list[dict[str, str]]:
    validate_action(action)
    c_path = candidate_path(action, root)
    candidate = load_yaml(c_path)
    validate_candidate(candidate, action)
    record = source_from_candidate(candidate, action)
    s_path = root / "data" / "vendors" / record["vendor_id"] / "sources" / f"{record['source_id']}.yaml"
    a_path = root / "data" / "vendors" / record["vendor_id"] / "artifacts" / f"{record['source_id']}.yaml"
    c_path_out = root / "data" / "vendors" / record["vendor_id"] / "changes" / f"candidate-promotion-{record['source_id']}.yaml"
    if s_path.exists():
        raise ValueError("canonical source already exists")
    if a_path.exists():
        raise ValueError("canonical artifact already exists")
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
    ]


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
            applied.extend(apply_reviewed_candidate(action, root))

    if root.resolve() == ROOT.resolve():
        build_indexes()
    redirect_metrics = redirect_metrics_for_actions(actions)
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
            **redirect_metrics,
        },
        "file_actions": applied,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-candidate-promotion-actions")
    parser.add_argument("command", choices={"apply"})
    parser.add_argument("--promotion-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "candidate-promotion-report.json")
    args = parser.parse_args()
    report = apply_candidate_promotions(load_json(args.promotion_plan))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
