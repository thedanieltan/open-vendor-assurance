"""Pydantic request/response models for the zero-install /v1 enrichment API.

All response models are read-only projections of the immutable catalogue pack loaded
at startup. Every catalogue-data response carries a ``snapshot`` identity object and
``not_advice: true``. Nothing here persists, submits, or mutates catalogue state.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

IDENTITY_FIELDS = ("vendor_name", "domain", "business_entity_name", "registration_number")

# Defense-in-depth model bounds (the authoritative protection is the request-byte limit
# enforced at the ASGI boundary). Generous relative to real catalogue values.
MAX_IDENTITY_LEN = 512
MAX_ROW_ID_LEN = 128
MAX_SOURCE_TYPE_LEN = 128
MAX_SOURCE_TYPES = 64
# Hosted verify budget: at most 4 source types per verify row, matching
# hosted-deployment.yaml hosted_verify_limits.max_source_types_per_verify_row.
# This bounds the accepted live-fetch execution budget (>4 source types -> 422).
MAX_VERIFY_SOURCE_TYPES = 4

IdentityField = Annotated[str, Field(max_length=MAX_IDENTITY_LEN)]
SourceTypeField = Annotated[str, Field(max_length=MAX_SOURCE_TYPE_LEN)]


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
    """A single vendor identity. At least one field must be non-empty.

    ``extra="forbid"`` enforces the shared row contract
    (``schemas/openva/agent-enrichment-row.schema.json``, ``additionalProperties: false``)
    on the HTTP surface, so an unknown/undeclared field (e.g. a workspace id or
    spreadsheet id) is rejected with 422 rather than silently ignored — the same
    authority boundary the MCP tool's JSON Schema enforces."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "vendor_name": "Stripe",
                "domain": "stripe.com",
                "business_entity_name": None,
                "registration_number": None,
            }
        },
    )

    vendor_name: IdentityField | None = None
    domain: IdentityField | None = None
    business_entity_name: IdentityField | None = None
    registration_number: IdentityField | None = None

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
    if value is None:
        return value
    if isinstance(value, str):
        if len(value) > MAX_ROW_ID_LEN:
            raise ValueError(f"row_id must be at most {MAX_ROW_ID_LEN} characters")
        return value
    if isinstance(value, bool):
        raise ValueError("row_id must be a string or integer")
    if isinstance(value, int):
        return value
    raise ValueError("row_id must be a string or integer")


class EnrichVendorItem(MatchInput):
    # Inherits extra="forbid" from MatchInput (declared again for clarity), so a row
    # with an undeclared workspace column is rejected, not silently dropped.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "row_id": "12",
                "vendor_name": "Stripe",
                "domain": "stripe.com",
                "business_entity_name": None,
                "registration_number": None,
            }
        },
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
    # extra="forbid" closes the envelope: an undeclared top-level field (e.g. a
    # workspace token) is rejected with 422 rather than silently discarded, matching
    # the MCP request schema's additionalProperties:false and ADR-0004's boundary.
    model_config = ConfigDict(
        extra="forbid",
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
    source_types: list[SourceTypeField] | None = Field(
        default=None,
        max_length=MAX_SOURCE_TYPES,
        description="Optional. Omitted means all canonical source types.",
    )


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


# --- Hosted verify transport models (WP-02A) ---------------------------------
#
# Verify mode takes vendor IDENTITIES only (never a fetch target URL). The SSRF
# boundary is enforced structurally: VerifyRowItem subclasses MatchInput, so it
# inherits the four identity fields, the "at least one identity" validator, and
# extra="forbid". A url/candidate_url/source_url (or any other non-identity field)
# is therefore rejected with 422 before any job is created — the resolver chooses
# what to fetch from the catalogue, never the caller.


class VerifyRowItem(MatchInput):
    # Inherits extra="forbid" + the identity fields + the identity validator from
    # MatchInput. Adds an optional row_id (same contract as EnrichVendorItem). It
    # intentionally declares NO url field: extra="forbid" makes any url/candidate_url/
    # source_url a 422, which is the SSRF boundary — verify takes identities only.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "row_id": "12",
                "vendor_name": "Stripe",
                "domain": "stripe.com",
                "business_entity_name": None,
                "registration_number": None,
            }
        },
    )

    row_id: str | int | None = None

    @model_validator(mode="before")
    @classmethod
    def _check_row_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and "row_id" in data:
            data = dict(data)
            data["row_id"] = _normalize_row_id(data["row_id"])
        return data


class VerifyRequest(BaseModel):
    # extra="forbid" closes the envelope: an undeclared top-level field is rejected
    # with 422 rather than silently discarded, matching the other /v1 surfaces.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "rows": [
                    {"row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com"}
                ],
                "source_types": [
                    "dpa",
                    "subprocessors_list",
                    "privacy_notice",
                    "security_page",
                ],
            }
        },
    )

    rows: list[VerifyRowItem] = Field(
        min_length=1,
        description="Bounded by OPENVA_MAX_VERIFY_ROWS. Identity rows only; no fetch-target URL is accepted.",
    )
    source_types: list[SourceTypeField] | None = Field(
        default=None,
        max_length=MAX_VERIFY_SOURCE_TYPES,
        description="Optional, ≤ 4 (the hosted verify budget). Omitted means the hosted verify default source types.",
    )


class VerifyCreatedResponse(BaseModel):
    """Returned once at job creation. ``job_token`` is the one-time capability and is
    returned HERE ONLY — never on poll, never logged, never stored in plaintext."""

    job_id: str
    job_token: str = Field(description="One-time capability. Sent on poll via Authorization: Bearer only. Not returned again.")
    state: str
    expires_at: str
    snapshot: Snapshot
    not_advice: bool = True


class VerifyStatusResponse(BaseModel):
    """Poll/status projection of a job record.

    MUST NOT include the job_token, the job_token_digest, the submitted request
    content, or the lease fields — only operational status plus the result when
    completed and the generic error_code when failed."""

    job_id: str
    state: str
    row_count: int
    created_at: str
    updated_at: str
    expires_at: str
    result: dict[str, Any] | None = None
    error_code: str | None = None
    snapshot: Snapshot
    not_advice: bool = True
