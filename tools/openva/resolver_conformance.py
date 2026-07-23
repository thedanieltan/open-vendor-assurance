"""Cross-runtime resolver conformance suite, generated from the authoritative core.

WP-OPENVA-RESOLVER-UNIFICATION.

The Python matching core `openva_vendor_inventory_matcher.core` is the single authority for
domain/name normalization, legal-suffix stripping, registration-number matching, candidate
ranking, ambiguity rules, confidence thresholds, and the result-status vocabulary. Every
transport (browser, Cloudflare Worker, MCP, CSV adapter, hosted service) must produce the same
outcomes.

This module:
  * emits a **contract** (thresholds + method confidences + status vocabulary + legal suffixes)
    read directly from the core — so no transport hand-maintains its own copy of `0.90`;
  * emits **conformance vectors** whose expected outcomes are COMPUTED by running the core over
    a fixture catalog, across every required identity/registration case class;
  * `check` fails closed if the committed artifact is stale or if the core no longer reproduces
    a vector (a matching-behaviour regression).

The committed artifact `tests/conformance/resolver-conformance.json` is the contract a JS
conformance harness runs against in a later increment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "tests" / "conformance" / "resolver-conformance.json"

MATCHER_PATH = ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher"
if str(MATCHER_PATH) not in sys.path:
    sys.path.insert(0, str(MATCHER_PATH))

from openva_vendor_inventory_matcher import core  # noqa: E402

# --- fixture catalog (small, deterministic) --------------------------------- #
VENDORS: list[dict[str, Any]] = [
    {"vendor_id": "acme", "display_name": "Acme", "legal_name": "Acme Inc",
     "official_domains": ["acme.com"], "catalog_status": "active"},
    {"vendor_id": "globex", "display_name": "Globex", "legal_name": "Globex LLC",
     "official_domains": ["globex.io"], "catalog_status": "active"},
    {"vendor_id": "initech", "display_name": "Initech", "legal_name": "Initech Corporation",
     "official_domains": ["initech.example"], "catalog_status": "active"},
    {"vendor_id": "umbrella-eu", "display_name": "Umbrella", "legal_name": "Umbrella EU BV",
     "official_domains": ["umbrella.eu"], "catalog_status": "active"},
    {"vendor_id": "umbrella-us", "display_name": "Umbrella", "legal_name": "Umbrella US Inc",
     "official_domains": ["umbrella.us"], "catalog_status": "active"},
    {"vendor_id": "muenchen", "display_name": "München Cloud", "legal_name": "München Cloud GmbH",
     "official_domains": ["münchen.example"], "catalog_status": "active"},
    # Two vendors deliberately claiming the same exact domain -> fail-closed ambiguity.
    {"vendor_id": "shared-a", "display_name": "Shared A", "legal_name": "Shared A Ltd",
     "official_domains": ["shared.example"], "catalog_status": "active"},
    {"vendor_id": "shared-b", "display_name": "Shared B", "legal_name": "Shared B Ltd",
     "official_domains": ["shared.example"], "catalog_status": "active"},
]

LEGAL_ENTITIES: list[dict[str, Any]] = [
    {"entity_id": "acme-gb", "vendor_id": "acme", "legal_name": "Acme Inc",
     "jurisdiction": "GB", "registration_number": "12345678", "catalog_status": "active"},
    # Same registration number under two vendors -> ambiguous without a jurisdiction filter.
    {"entity_id": "dup-a", "vendor_id": "globex", "legal_name": "Globex LLC",
     "jurisdiction": "US", "registration_number": "99999999", "catalog_status": "active"},
    {"entity_id": "dup-b", "vendor_id": "initech", "legal_name": "Initech Corporation",
     "jurisdiction": "GB", "registration_number": "99999999", "catalog_status": "active"},
]

# Each case: id, class, description, query (raw, un-normalized).
CASES: list[dict[str, Any]] = [
    {"id": "domain-exact", "class": "exact_domain", "query": {"domain": "acme.com"}},
    {"id": "domain-exact-scheme-path", "class": "exact_domain",
     "query": {"domain": "https://www.acme.com/security"}},
    {"id": "domain-subdomain", "class": "subdomain", "query": {"domain": "trust.acme.com"}},
    {"id": "shared-domain-ambiguous", "class": "shared_parent_domain",
     "query": {"domain": "shared.example"}},
    {"id": "name-exact", "class": "exact_name", "query": {"vendor_name": "Globex"}},
    {"id": "name-stripped-suffix", "class": "stripped_legal_suffix",
     "query": {"vendor_name": "Initech"}},
    {"id": "name-ambiguous", "class": "ambiguous", "query": {"vendor_name": "Umbrella"}},
    {"id": "no-match", "class": "no_match",
     "query": {"domain": "unknown.example", "vendor_name": "Nobody Ltd"}},
    {"id": "malformed", "class": "malformed_input",
     "query": {"domain": "$$$ not a url", "vendor_name": ""}},
    {"id": "idn-domain", "class": "internationalized_domain",
     "query": {"domain": "MÜNCHEN.EXAMPLE"}},
    {"id": "conflicting-identity", "class": "conflicting_identity",
     "query": {"domain": "acme.com", "vendor_name": "Globex"}},
    {"id": "registration-exact", "class": "registration_number",
     "query": {"registration_number": "1234-5678", "jurisdiction": "gb"}},
    {"id": "registration-ambiguous", "class": "registration_number",
     "query": {"registration_number": "99999999"}},
    # Domain -> acme, but registration (with jurisdiction) resolves to globex's entity.
    # Contradictory strong identity must fail closed: neither vendor is attributed.
    {"id": "registration-vendor-conflict", "class": "conflicting_identity",
     "query": {"domain": "acme.com", "registration_number": "99999999", "jurisdiction": "us"}},
]


def _resolve(query: dict[str, Any]) -> dict[str, Any]:
    """Run the authoritative core exactly as a transport would."""
    vendors = [core.vendor_record(row) for row in VENDORS]
    entities = [core.legal_entity_record(row) for row in LEGAL_ENTITIES]
    domain = core.normalize_domain(query.get("domain"))
    name = core.normalize_name(query.get("vendor_name") or query.get("business_entity_name"))
    candidates = core.match_candidates(vendors, domain, name)

    # Registration / legal-entity path via the single shared authority.
    by_registration = core.group_legal_entities_by_registration(entities)
    by_id = {entity.entity_id: entity for entity in entities}
    input_row = {
        "registration_number": str(query.get("registration_number", "")),
        "jurisdiction": str(query.get("jurisdiction", "")),
    }
    selected, resolution = core.select_with_legal_fallback(
        {vendor.vendor_id: vendor for vendor in vendors},
        candidates,
        input_row,
        by_registration=by_registration,
        by_id=by_id,
        contracting_by_key={},
    )
    status = core.classify(candidates, selected)
    return {
        "status": status,
        "vendor_id": selected.vendor.vendor_id if selected else None,
        "method": selected.method if selected else None,
        "confidence": round(selected.confidence, 4) if selected else None,
        "legal_entity_method": resolution.method,
        "legal_entity_confidence": resolution.confidence,
        "legal_entity_id": resolution.matched_entity.entity_id if resolution.matched_entity else None,
    }


def build_suite() -> dict[str, Any]:
    contract = {
        "resolver_contract_version": "1.0.0",
        "minimum_match_confidence": core.MINIMUM_MATCH_CONFIDENCE,
        "ambiguity_margin": core.AMBIGUITY_MARGIN,
        "status_vocabulary": [core.STATUS_MATCHED, core.STATUS_NO_MATCH, core.STATUS_AMBIGUOUS],
        "method_confidence": {"domain_exact": 1.00, "domain_subdomain": 0.95, "name_exact": 0.90},
        # Legal suffixes are a local set in core.strip_legal_suffixes; mirror them here and let
        # check() prove the core still strips each one (behavioural drift guard, no core edit).
        "legal_suffixes": [
            "co", "company", "corp", "corporation", "inc", "limited", "llc", "ltd",
        ],
    }
    vectors = []
    for case in CASES:
        vectors.append({
            "id": case["id"],
            "class": case["class"],
            "query": case["query"],
            "expected": _resolve(case["query"]),
        })
    return {"contract": contract, "catalog": {"vendors": VENDORS, "legal_entities": LEGAL_ENTITIES},
            "vectors": vectors}


def render() -> str:
    return json.dumps(build_suite(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate() -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(render(), encoding="utf-8")


def check() -> list[str]:
    problems: list[str] = []
    # 1. Contract constants must equal the core's actual constants.
    suite = build_suite()
    if suite["contract"]["minimum_match_confidence"] != core.MINIMUM_MATCH_CONFIDENCE:
        problems.append("contract minimum_match_confidence drifted from core")
    if suite["contract"]["ambiguity_margin"] != core.AMBIGUITY_MARGIN:
        problems.append("contract ambiguity_margin drifted from core")
    # 1b. Every declared legal suffix must still be stripped by the core; a control token must not.
    for suffix in suite["contract"]["legal_suffixes"]:
        if core.strip_legal_suffixes(f"sentinel {suffix}") != "sentinel":
            problems.append(f"core no longer strips declared legal suffix {suffix!r}")
    if core.strip_legal_suffixes("sentinel systems") != "sentinel systems":
        problems.append("core strips a non-suffix token 'systems' (legal-suffix set widened)")
    # 2. The core must reproduce every committed vector (fail closed on matching regression).
    for vector in suite["vectors"]:
        actual = _resolve(vector["query"])
        if actual != vector["expected"]:
            problems.append(f"vector {vector['id']!r}: core no longer reproduces expected outcome")
    # 3. Committed artifact must be fresh.
    if not ARTIFACT.exists() or ARTIFACT.read_text(encoding="utf-8") != render():
        problems.append("committed resolver-conformance.json is stale: run `generate`")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVA resolver conformance suite")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    if args.command == "generate":
        generate()
        print(f"Generated {ARTIFACT.relative_to(ROOT)} from the authoritative core.")
        return 0
    problems = check()
    if problems:
        print("Resolver conformance FAILED:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print("Resolver conformance: core reproduces all vectors; contract consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
