"""Tier A: content-blocked coverage reporting.

Operational metadata only: it quantifies where vendors or sources are blocked by
access barriers, so outreach and (future) render work can be prioritized by a
human — it is NOT a vendor catalog status, NOT a mutation authority, and carries
no scoring, ranking, queue ordering, or recommendations. It is a pure,
deterministic function of committed candidate/discovery/source records, so the
output is reproducible. It emits identifiers only — never raw page text,
snippets, document metadata, or inferred gated claims.

Category boundaries:
- identity_anchored_vendor_candidates: official identity anchor passed; no
  catalog admission implied.
- locator_verified_content_blocked: STRONG authority provenance AND blocked/gated
  access. Sitemap-only discovery (no strong authority) cannot qualify.
- bot_protected_candidate_sources: access_state bot_protected from the classifier.
- gated_candidate_sources: declared or observed gating only — never robots
  suppression.
- public_landing_gated_docs: the public landing page was actually retrieved and
  classified (committed access_class public_landing_gated_docs).
- client_render_suspected: deterministic public-page indicators suggest client
  rendering may be required. No renderer exists in Tier A; this is not a
  prediction that rendering will succeed, and it carries no promotion weight.
- delegation_unproven: off-domain locator without a strong authority basis.

Robots suppression is policy metadata and never appears here as gated, blocked,
or unavailable. Sitemap entries remain unverified candidates even when relevant.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT
from tools.openva.source_authority import establishes_authority, is_on_official_domain

REPORT_TYPE = "content_blocked_coverage"
SCHEMA_VERSION = "0.1.0"
CATEGORIES = (
    "identity_anchored_vendor_candidates",
    "locator_verified_content_blocked",
    "bot_protected_candidate_sources",
    "gated_candidate_sources",
    "public_landing_gated_docs",
    "client_render_suspected",
    "delegation_unproven",
)
# Declared or observed gating, excluding bot_protected (its own category) and
# excluding robots suppression (policy, never recorded as gating).
GATED_ACCESS = {"declared_gated", "gated_or_auth_required"}
BLOCKED_ACCESS = {"bot_protected", "declared_gated", "gated_or_auth_required"}


def build_blocked_coverage_report(
    *,
    candidates: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    official_domains_by_vendor: dict[str, list[str]],
    discovery_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    buckets: dict[str, set[str]] = {category: set() for category in CATEGORIES}

    for candidate in candidates:
        identity = candidate.get("vendor_identity_candidate", {}) or {}
        vendor_id = identity.get("vendor_id_candidate")
        official_domain = identity.get("official_domain")
        # Identity anchor passed: an official domain is anchored and identity was
        # not rejected as a collision. No catalog admission is implied.
        if vendor_id and official_domain and candidate.get("eligibility_state") != "rejected_identity_collision":
            buckets["identity_anchored_vendor_candidates"].add(str(vendor_id))

        official_domains = official_domains_by_vendor.get(str(vendor_id), [])
        if not official_domains and official_domain:
            official_domains = [official_domain]

        for source in candidate.get("source_candidates", []) or []:
            url = source.get("candidate_url")
            if not url:
                continue
            access = source.get("access_state")
            authority = source.get("authority")
            strong = establishes_authority(authority)

            if access == "bot_protected":
                buckets["bot_protected_candidate_sources"].add(url)
            if access in GATED_ACCESS:
                buckets["gated_candidate_sources"].add(url)
            if strong and access in BLOCKED_ACCESS:
                buckets["locator_verified_content_blocked"].add(url)
            if not is_on_official_domain(url, official_domains) and not strong:
                buckets["delegation_unproven"].add(url)
            if source.get("client_render_suspected") is True or "client_render_suspected" in (source.get("reasons") or []):
                buckets["client_render_suspected"].add(url)

    for source in sources:
        # Retrieved-and-classified public landing page with gated children.
        if source.get("access_class") == "public_landing_gated_docs" and source.get("source_id"):
            buckets["public_landing_gated_docs"].add(str(source["source_id"]))

    return {
        "report_type": REPORT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "not_advice": True,
        # Deterministic identifier lists (deduplicated by identity, not event
        # count). No scores, no ordering by priority/risk, no recommendations.
        "categories": {
            category: {"count": len(buckets[category]), "items": sorted(buckets[category])}
            for category in CATEGORIES
        },
    }


def _load_yaml_records(root: Path, glob: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob(glob)):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            records.append(value)
    return records


def build_report_from_root(root: Path = ROOT) -> dict[str, Any]:
    """Reproducible build from committed records.

    Sources are committed; candidate and discovery records are read when present
    (the candidate pipeline is transient, so the committed catalog typically
    yields the public_landing_gated_docs category only).
    """
    sources = _load_yaml_records(root, "data/vendors/*/sources/*.yaml")
    vendors = _load_yaml_records(root, "data/vendors/*/vendor.yaml")
    official = {
        str(v.get("vendor_id")): [str(d) for d in (v.get("official_domains") or [])]
        for v in vendors
        if v.get("vendor_id")
    }
    candidates = _load_yaml_records(root, "data/vendors/*/candidate_sources/*.yaml")
    return build_blocked_coverage_report(
        candidates=candidates, sources=sources, official_domains_by_vendor=official
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-coverage-blocked")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(build_report_from_root(args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
