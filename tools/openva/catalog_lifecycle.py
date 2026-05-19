from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "0.1.0"
HASH_TBD = "sha256:TBD"


def change_event(
    *,
    change_id: str,
    vendor_id: str,
    source_id: str,
    artifact_id: str | None,
    change_type: str,
    detected_at: str,
    summary: str,
    catalog_change_significance: str = "unknown",
    materiality: str | None = None,
    review_state: str = "proposed",
) -> dict[str, Any]:
    significance = materiality or catalog_change_significance
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": change_id,
        "vendor_id": vendor_id,
        "source_id": source_id,
        "artifact_id": artifact_id,
        "change_type": change_type,
        "detected_at": detected_at,
        "from_hash": HASH_TBD,
        "to_hash": HASH_TBD,
        "catalog_change_significance": significance,
        "materiality": significance,
        "review_state": review_state,
        "summary": summary,
        "not_advice": True,
    }


def lifecycle_change_type(operation: str) -> str:
    if operation == "create":
        return "created"
    if operation == "refresh":
        return "updated"
    if operation == "deprecate":
        return "metadata_changed"
    raise ValueError(f"unsupported catalog lifecycle operation: {operation}")
