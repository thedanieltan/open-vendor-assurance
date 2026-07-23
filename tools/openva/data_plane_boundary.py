"""Discovery/canonical plane boundary guard.

WP-OPENVA-DATA-PLANE-BOUNDARY-01 (four-plane refactor).

The four-plane model separates the **discovery data plane** (rich candidate records: raw
signals, verification attempts, evidence) from the **canonical catalog plane**
(`data/vendors/**` — lean, mutable, latest-branch = truth). The stated objective is that
GitHub stays the governance/publication control plane but is NOT the bulk transport for raw
discovery candidates: the discovery plane belongs in an append-only store addressed by a
deterministic identity, and only compact, qualified promotions cross into the canonical plane.

This module makes that boundary machine-enforced and fails closed on either violation:

  1. **Store-addressability (discovery plane).** Every committed candidate-source record must
     reproduce its own `candidate_source_id` from its deterministic identity
     `(vendor_id, source_type_candidate, canonical_candidate_url)`. If this holds for every
     record, the discovery plane is fully addressable by content-derived identity and can be
     relocated to an external append-only store (SQLite/artifacts/R2) without GitHub as the
     bulk transport. A record whose id does not reproduce is NOT store-addressable and blocks.

  2. **Plane disjointness (canonical plane).** The canonical `source-reference` schema must keep
     `additionalProperties: false` and must never declare a discovery-plane-only bulk field.
     This stops raw discovery signals/evidence from leaking into the canonical catalog plane
     (which would re-couple the planes and re-introduce bulk transport through canonical writes).

The physical relocation of the 1,416 in-tree `candidate_sources/*.yaml` files into the external
store is a separate, infrastructure-gated increment; this guard is its safe precondition — it
proves the plane is store-ready and keeps the boundary from eroding in the meantime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from tools.openva.source_discovery import candidate_source_id

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SOURCE_SCHEMA = ROOT / "schemas" / "openva" / "source-reference.schema.json"

CANDIDATE_RECORD_GLOBS = (
    "data/vendors/*/candidate_sources/*.yaml",
    "examples/vendors/*/candidate_sources/*.yaml",
)

# Field names that belong exclusively to the discovery data plane (raw signals, verification
# attempts, candidate lifecycle). None of these may ever be declared by the canonical catalog
# plane's source-reference schema; if one appears there, the planes have been re-coupled.
DISCOVERY_ONLY_BULK_FIELDS = frozenset(
    {
        "candidate_source_id",
        "candidate_status",
        "candidate_url",
        "requested_url",
        "observed_final_url",
        "canonical_candidate_url",
        "discovery_method",
        "discovered_at",
        "discovered_by",
        "requires_review",
        "evidence",
        "evidence_digest",
        "selection_run_id",
        "source_type_candidate",
        "superseded_by_candidate_id",
    }
)


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def candidate_record_paths() -> list[Path]:
    paths: list[Path] = []
    for pattern in CANDIDATE_RECORD_GLOBS:
        paths.extend(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def check_store_addressability() -> list[str]:
    """Every candidate record must reproduce its deterministic, store-ready identity."""
    problems: list[str] = []
    for path in candidate_record_paths():
        record = _load_yaml(path)
        if not isinstance(record, dict):
            problems.append(f"{path.relative_to(ROOT)}: candidate record is not a mapping")
            continue
        vendor_id = record.get("vendor_id")
        source_type = record.get("source_type_candidate")
        canonical_url = record.get("canonical_candidate_url")
        stored_id = record.get("candidate_source_id")
        if not (vendor_id and source_type and canonical_url and stored_id):
            problems.append(
                f"{path.relative_to(ROOT)}: not store-addressable "
                "(missing vendor_id/source_type_candidate/canonical_candidate_url/candidate_source_id)"
            )
            continue
        expected = candidate_source_id(vendor_id, source_type, canonical_url)
        if expected != stored_id:
            problems.append(
                f"{path.relative_to(ROOT)}: candidate_source_id {stored_id!r} is not reproducible "
                f"from its deterministic identity (expected {expected!r}); not store-addressable"
            )
    return problems


def check_plane_disjointness() -> list[str]:
    """The canonical source-reference schema must not absorb discovery-plane bulk fields."""
    problems: list[str] = []
    schema = json.loads(CANONICAL_SOURCE_SCHEMA.read_text(encoding="utf-8"))
    if schema.get("additionalProperties") is not False:
        problems.append(
            "canonical source-reference schema must keep additionalProperties:false "
            "(open canonical records could absorb discovery-plane bulk)"
        )
    declared = set(schema.get("properties", {}))
    leaked = sorted(declared & DISCOVERY_ONLY_BULK_FIELDS)
    if leaked:
        problems.append(
            "canonical source-reference schema declares discovery-plane-only bulk field(s) "
            f"{leaked}: the discovery data plane has leaked into the canonical catalog plane"
        )
    return problems


def check() -> list[str]:
    return check_store_addressability() + check_plane_disjointness()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVA discovery/canonical plane boundary guard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    parser.parse_args(argv)
    problems = check()
    if problems:
        print("Data-plane boundary FAILED:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print(
        f"Data-plane boundary OK: {len(candidate_record_paths())} discovery records are "
        "store-addressable; canonical plane is disjoint from discovery bulk."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
