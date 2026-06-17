"""Pydantic request/response models for the zero-install /v1 enrichment API.

All response models are read-only projections of the immutable catalogue pack loaded
at startup. Every catalogue-data response carries a ``snapshot`` identity object and
``not_advice: true``. Nothing here persists, submits, or mutates catalogue state.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

IDENTITY_FIELDS = ("vendor_name", "domain", "business_entity_name", "registration_number")


class Snapshot(BaseModel):
    """Provenance identity of the catalogue pack the response was served from."""

    profile_id: str
    schema_version: str
    generated_at: str
    vendor_count: int
    source_count: int
    snapshot_digest: str = Field(description="Deterministic content digest of the loaded pack, prefixed sha256:. Not a git commit SHA.")
    catalog_commit_sha: str | None = Field(default=None, description="Deployment-supplied 40-char lowercase hex commit SHA, or null when unavailable.")


class Guarantees(BaseModel):
    public_sources_only: bool
    metadata_first: bool
    non_advisory: bool
    raw_documents_mirrored_by_default: bool


class CatalogMetaResponse(BaseModel):
    snapshot: Snapshot
    guarantees: Guarantees
    not_advice: bool = True


class SourceModel(BaseModel):
    """A canonical public source reference, projected from the loaded pack.

    Observation fields are derived only from the loaded observations index and are null
    when no deterministic observation exists. No live URL check is performed."""

    source_id: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    access_class: str | None = None
    source_language: str | None = None
    catalog_status: str | None = None
    record_class: str | None = None
    canonical: bool | None = None
    catalog_tier: str | None = None
    review_state: str | None = None
    advisory_boundary: str | None = None
    last_observed_at: str | None = None
    latest_observation_status: str | None = None


class MatchCandidateModel(BaseModel):
    vendor_id: str | None = None
    display_name: str | None = None
    match_confidence: float | None = None
    match_method: str | None = None


class MatchResultModel(BaseModel):
    status: str = Field(description="One of matched, ambiguous, no_match. Ambiguous is never collapsed into matched.")
    method: str | None = None
    confidence: float | None = None
    vendor_id: str | None = None
    display_name: str | None = None
    candidates: list[MatchCandidateModel] = Field(default_factory=list)


class MatchInput(BaseModel):
    """A single vendor identity. At least one field must be non-empty."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vendor_name": "Stripe",
                "domain": "stripe.com",
                "business_entity_name": None,
                "registration_number": None,
            }
        }
    )

    vendor_name: str | None = None
    domain: str | None = None
    business_entity_name: str | None = None
    registration_number: str | None = None

    @model_validator(mode="after")
    def _require_identity(self) -> "MatchInput":
        if not any((getattr(self, name) or "").strip() for name in IDENTITY_FIELDS):
            raise ValueError("at least one of vendor_name, domain, business_entity_name, registration_number is required")
        return self


class MatchResponse(BaseModel):
    input: MatchInput
    match: MatchResultModel
    snapshot: Snapshot
    not_advice: bool = True


class VendorDetailResponse(BaseModel):
    vendor: dict[str, Any]
    canonical_sources: list[SourceModel]
    snapshot: Snapshot
    not_advice: bool = True


class VendorSourcesResponse(BaseModel):
    vendor_id: str
    sources: list[SourceModel]
    source_types_requested: list[str]
    snapshot: Snapshot
    not_advice: bool = True


def _normalize_row_id(value: Any) -> str | int | None:
    # row_id may be string or integer only (not bool/float); preserve as supplied.
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ValueError("row_id must be a string or integer")
    if isinstance(value, int):
        return value
    raise ValueError("row_id must be a string or integer")


class EnrichVendorItem(MatchInput):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "row_id": "12",
                "vendor_name": "Stripe",
                "domain": "stripe.com",
                "business_entity_name": None,
                "registration_number": None,
            }
        }
    )

    row_id: str | int | None = None

    @model_validator(mode="before")
    @classmethod
    def _check_row_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and "row_id" in data:
            data = dict(data)
            data["row_id"] = _normalize_row_id(data["row_id"])
        return data


class EnrichRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vendors": [
                    {"row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com"}
                ],
                "source_types": [
                    "dpa",
                    "subprocessors_list",
                    "privacy_notice",
                    "security_page",
                    "trust_center",
                    "compliance_page",
                ],
            }
        }
    )

    vendors: list[EnrichVendorItem] = Field(min_length=1, description="Bounded by OPENVA_MAX_ROWS. Processed in input order; duplicates preserved.")
    source_types: list[str] | None = Field(default=None, description="Optional. Omitted means all canonical source types.")


class SpreadsheetProjection(BaseModel):
    """Stable server-side column mapping shared by Google Sheets, Excel and Word."""

    openva_match_status: str
    openva_vendor_id: str | None = None
    openva_vendor_name: str | None = None
    openva_dpa: str | None = None
    openva_subprocessors: str | None = None
    openva_privacy_notice: str | None = None
    openva_security: str | None = None
    openva_trust_center: str | None = None
    openva_compliance: str | None = None
    openva_last_observed_at: str | None = None
    openva_snapshot_digest: str | None = None
    openva_notes: str = ""


class EnrichResultModel(BaseModel):
    row_id: str | int | None = None
    input: MatchInput
    match: MatchResultModel
    sources: list[SourceModel] = Field(default_factory=list)
    primary_source_by_type: dict[str, SourceModel] = Field(default_factory=dict)
    source_urls_by_type: dict[str, list[str]] = Field(default_factory=dict)
    spreadsheet: SpreadsheetProjection
    notes: list[str] = Field(default_factory=list)
    not_advice: bool = True


class EnrichResponse(BaseModel):
    results: list[EnrichResultModel]
    snapshot: Snapshot
    not_advice: bool = True
