from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.openva import candidate_record, vendor_resolution
from tools.openva.source_discovery import source_type_role
from tools.openva.source_verification import ROOT

SCHEMA_VERSION = "0.1.0"
PUBLIC_VERIFICATION = {"ok", "redirected"}
GATED_VERIFICATION = {"gated_or_login_required"}
BOT_PROTECTED_VERIFICATION = {"bot_protected"}


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def normalize_domain(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    return raw.split("/", 1)[0].removeprefix("www.").strip(".")


def on_vendor_domain(url: str, official_domain: str) -> bool:
    host = normalize_domain(url)
    domain = normalize_domain(official_domain)
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def evidence_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def access_state(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    status = str(evidence.get("verification_status") or "")
    http_status = evidence.get("http_status")
    if status in PUBLIC_VERIFICATION and http_status == 200:
        return "public_reachable"
    if status in BOT_PROTECTED_VERIFICATION:
        return "bot_protected"
    if status in GATED_VERIFICATION:
        return "gated_or_auth_required"
    return "fetch_failed"


def source_role(candidate: dict[str, Any]) -> str:
    source_type = str(candidate.get("source_type_candidate") or "")
    if source_type_role(source_type, "qualifies_for_vendor_materialization"):
        return "primary_assurance"
    return "rejected"


def project_source_candidate(
    candidate: dict[str, Any],
    *,
    official_domain: str,
    fallback_observed_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    candidate_url = str(candidate.get("candidate_url") or "")
    final_url = str(evidence.get("final_url") or candidate.get("observed_final_url") or candidate_url)
    observed_at = str(candidate.get("discovered_at") or fallback_observed_at)
    retrieval_method = str(candidate.get("discovery_method") or "scheduled_discovery")[:60]
    digest = str(candidate.get("evidence_digest") or "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        digest = evidence_digest(evidence)
    same_domain = on_vendor_domain(final_url or candidate_url, official_domain)

    authority: dict[str, Any] | None = None
    if same_domain:
        authority = {
            "class": "strong",
            "method": "same_official_domain",
            "source_url": f"https://{normalize_domain(official_domain)}",
            "target_url": final_url or candidate_url,
            "observed_at": observed_at,
            "evidence_digest": digest,
            "note": "Observed through bounded scheduled discovery on the candidate official domain.",
        }

    source = {
        "candidate_url": candidate_url,
        "final_url": final_url or None,
        "redirect_chain": [],
        "http_status": evidence.get("http_status"),
        "content_type": evidence.get("content_type"),
        "source_type_candidate": str(candidate.get("source_type_candidate") or ""),
        "retrieval_method_candidate": retrieval_method,
        "access_state": access_state(candidate),
        "source_role": source_role(candidate),
        "on_vendor_domain": same_domain,
        "duplicate_of": None,
        "evidence_digest": digest,
        "verification_result": str(evidence.get("verification_status") or "unknown")[:60],
        "authority": authority,
        "reasons": [str(value)[:200] for value in (candidate.get("reason_codes") or []) if value],
    }
    evidence_reference = {
        "candidate_url": candidate_url,
        "final_url": final_url or None,
        "http_status": evidence.get("http_status"),
        "content_type": evidence.get("content_type"),
        "redirect_chain": [],
        "source_type_candidate": str(candidate.get("source_type_candidate") or "") or None,
        "retrieval_method_candidate": retrieval_method,
        "verification_result": str(evidence.get("verification_status") or "unknown")[:60],
        "evidence_digest": digest,
        "observed_at": observed_at,
    }
    return source, evidence_reference


def source_rows_by_vendor(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if report.get("report_type") != "source_discovery_report":
        raise ValueError("expected source_discovery_report")
    output: dict[str, dict[str, Any]] = {}
    for row in report.get("vendors", []) or []:
        if not isinstance(row, dict):
            continue
        vendor_id = str(row.get("candidate_vendor_id") or row.get("vendor_id") or "").strip()
        if vendor_id:
            output[vendor_id] = row
    return output


def valid_country(value: Any) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2}", str(value or "").strip()))


def project_discovery_candidates(
    vendor_report: dict[str, Any],
    source_report: dict[str, Any],
    *,
    ingress: Any,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Project scheduled discovery into the one unified candidate lifecycle.

    This is the convergence boundary that was previously deferred. It does not
    write canonical catalog records. Every projected record is evaluated by the
    existing ``SessionEmitter`` and handed to the injected canonical candidate
    ingress, which deterministically merges expanded evidence with any persisted
    record under ``maintenance/candidates``.
    """

    if vendor_report.get("report_type") != "vendor_candidate_discovery_report":
        raise ValueError("expected vendor_candidate_discovery_report")
    source_by_vendor = source_rows_by_vendor(source_report)
    created = created_at or str(source_report.get("generated_at") or vendor_report.get("generated_at") or "")
    if not created:
        raise ValueError("discovery evidence must have a generated_at timestamp")

    emitter = vendor_resolution.SessionEmitter(ingress=ingress)
    state_counts: Counter[str] = Counter()
    outcomes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for vendor in vendor_report.get("vendor_candidates", []) or []:
        if not isinstance(vendor, dict):
            continue
        vendor_id = str(vendor.get("candidate_vendor_id") or "").strip()
        domain = normalize_domain(vendor.get("official_domain_candidate"))
        country = str(vendor.get("headquarters_country_candidate") or "").strip().upper()
        display_name = str(vendor.get("display_name_candidate") or "").strip()
        if not vendor_id or not domain or not display_name:
            skipped.append({"vendor_id": vendor_id, "reason": "identity_incomplete"})
            continue
        # Candidate-bound materialisation deliberately fails closed without an
        # ISO-3166 alpha-2 country. Do not persist a permanently incomplete base
        # record because the canonical merge contract preserves persisted identity.
        if not valid_country(country):
            skipped.append({"vendor_id": vendor_id, "reason": "headquarters_country_not_ready"})
            continue

        source_row = source_by_vendor.get(vendor_id, {})
        projected_sources: list[dict[str, Any]] = []
        evidence_references: list[dict[str, Any]] = []
        for candidate in source_row.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            projected, evidence = project_source_candidate(
                candidate,
                official_domain=domain,
                fallback_observed_at=created,
            )
            projected_sources.append(projected)
            evidence_references.append(evidence)

        result = emitter.emit(
            candidate_origin="catalog_discovery",
            origin_reference=f"{vendor_id}:{domain}",
            discovery_component="discovery-cycle",
            vendor_identity_candidate={
                "vendor_id_candidate": vendor_id,
                "vendor_name": display_name[:200],
                "official_domain": domain,
                "legal_name": None,
                "headquarters_country": country,
                "matches_existing_vendor_id": None,
                "official_domain_unsafe": False,
            },
            source_candidates=projected_sources,
            evidence_references=evidence_references,
            created_at=created,
            is_new_vendor=True,
            identity_collision=False,
        )
        record = result.record
        errors = candidate_record.validate_candidate(record)
        if errors:
            raise ValueError(f"projected candidate {vendor_id} is invalid: {'; '.join(errors)}")
        state = str(record.get("eligibility_state") or "pending")
        state_counts[state] += 1
        outcomes.append(
            {
                "candidate_id": record["candidate_id"],
                "vendor_id": vendor_id,
                "eligibility_state": state,
                "decision_reasons": record.get("decision_reasons", []),
                "source_candidate_count": len(record.get("source_candidates", []) or []),
                "ingress_state": result.outcome.ingress_state,
                "reference": result.outcome.reference,
                "created": result.outcome.enqueued,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "discovery_cycle_candidate_ingress_report",
        "generated_at": created,
        "posture": {
            "writes_candidate_staging": True,
            "writes_canonical_catalog": False,
            "canonical_candidate_writer": "vendor_resolution.CatalogQueueIngress",
            "catalog_mutation_authority": "candidate-promotion-pr.yml",
            "non_advisory": True,
        },
        "summary": {
            "candidate_count": len(outcomes),
            "eligible_count": state_counts.get("eligible", 0),
            "state_counts": dict(sorted(state_counts.items())),
            "skipped_count": len(skipped),
        },
        "candidates": outcomes,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-cycle-ingress")
    parser.add_argument("ingest", choices=["ingest"])
    parser.add_argument("--vendor-candidates", type=Path, required=True)
    parser.add_argument("--source-discovery", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--created-at")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    ingress = vendor_resolution.CatalogQueueIngress(root=root)
    report = project_discovery_candidates(
        load_json(args.vendor_candidates),
        load_json(args.source_discovery),
        ingress=ingress,
        created_at=args.created_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
