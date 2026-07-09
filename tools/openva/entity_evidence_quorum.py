"""Evidence-quorum gate for legal-entity registration-number promotion.

This module is intentionally pure and side-effect free. It decides whether a
candidate legal-entity record has enough public evidence to populate or retain a
registration number without routing that single metadata field through a manual
legal-review gate.

The gate is scoped narrowly:

- it may approve a registration number for one legal entity;
- it does not approve a global brand, contracting party, vendor risk outcome,
  procurement decision, KYC/AML result, sanctions result, audit conclusion, or
  legal advice;
- it fails closed whenever the evidence implies multiple plausible entities or a
  contracting/role claim that is not separately source-backed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

OFFICIAL_AUTHORITY_CLASSES = frozenset(
    {
        "public_registry",
        "public_authority",
        "court_or_regulatory_filing",
    }
)

PASS_STATUS = "passed"
FAIL_STATUS = "failed"

REASON_OFFICIAL_SOURCE_MISSING = "official_source_missing"
REASON_CORROBORATING_SOURCE_MISSING = "corroborating_source_missing"
REASON_REGISTRATION_NUMBER_MISSING = "registration_number_missing"
REASON_CONFLICTING_REGISTRATION_NUMBER = "conflicting_registration_number"
REASON_ENTITY_SCOPE_AMBIGUOUS = "entity_scope_ambiguous"
REASON_CONTRACTING_SCOPE_UNSUPPORTED = "contracting_scope_unsupported"
REASON_VERIFICATION_SOURCE_MISSING = "verification_source_missing"


@dataclass(frozen=True)
class EntityEvidenceQuorumDecision:
    """Deterministic outcome for one scoped legal-entity evidence check."""

    status: str
    official_source_ids: tuple[str, ...] = field(default_factory=tuple)
    corroborating_source_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.status == PASS_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "official_source_ids": list(self.official_source_ids),
            "corroborating_source_ids": list(self.corroborating_source_ids),
            "reason_codes": list(self.reason_codes),
        }


def evaluate_entity_evidence_quorum(
    legal_entity: dict[str, Any],
    sources: Iterable[dict[str, Any]],
    *,
    require_supported_contracting_scope: bool = True,
) -> EntityEvidenceQuorumDecision:
    """Evaluate whether one legal entity passes the registration-number quorum.

    Required evidence:

    1. a registration number on the legal entity;
    2. at least one verification source id that resolves to an official
       entity-anchored public authority/registry source;
    3. at least one distinct corroborating public source that supports the same
       entity, the same registration number, or the entity-to-vendor relationship;
    4. no conflicting registration number evidence;
    5. no unsupported contracting-jurisdiction claim, when that check is enabled.

    The function accepts plain dictionaries so it can run before or after schema
    validation and can be reused by catalog bots, validators, and promotion
    planners without importing YAML loaders or touching the filesystem.
    """
    entity_id = _string(legal_entity.get("entity_id"))
    vendor_id = _string(legal_entity.get("vendor_id"))
    registration_number = _normalize_registration_number(legal_entity.get("registration_number"))
    verification_source_ids = tuple(_strings(legal_entity.get("verification_source_ids")))
    source_by_id = {_string(source.get("source_id")): source for source in sources if _string(source.get("source_id"))}

    reasons: list[str] = []
    official_ids: list[str] = []
    corroborating_ids: list[str] = []

    if not registration_number:
        reasons.append(REASON_REGISTRATION_NUMBER_MISSING)

    missing_verification_ids = [source_id for source_id in verification_source_ids if source_id not in source_by_id]
    if missing_verification_ids:
        reasons.append(REASON_VERIFICATION_SOURCE_MISSING)

    for source_id in verification_source_ids:
        source = source_by_id.get(source_id)
        if source is None:
            continue
        if _is_official_entity_source(source, entity_id, vendor_id):
            official_ids.append(source_id)
        if _is_corroborating_source(source, entity_id, vendor_id, registration_number):
            corroborating_ids.append(source_id)

    if not official_ids:
        reasons.append(REASON_OFFICIAL_SOURCE_MISSING)

    # Corroboration must be a second evidence point, not the same official record.
    distinct_corroborating = [source_id for source_id in corroborating_ids if source_id not in set(official_ids)]
    if not distinct_corroborating:
        reasons.append(REASON_CORROBORATING_SOURCE_MISSING)

    if _has_conflicting_registration_number(source_by_id.values(), entity_id, vendor_id, registration_number):
        reasons.append(REASON_CONFLICTING_REGISTRATION_NUMBER)

    if _has_entity_scope_ambiguity(legal_entity, source_by_id.values(), entity_id, vendor_id):
        reasons.append(REASON_ENTITY_SCOPE_AMBIGUOUS)

    if require_supported_contracting_scope and _has_unsupported_contracting_scope(legal_entity, source_by_id):
        reasons.append(REASON_CONTRACTING_SCOPE_UNSUPPORTED)

    unique_reasons = tuple(dict.fromkeys(reasons))
    passed = not unique_reasons
    return EntityEvidenceQuorumDecision(
        status=PASS_STATUS if passed else FAIL_STATUS,
        official_source_ids=tuple(dict.fromkeys(official_ids)),
        corroborating_source_ids=tuple(dict.fromkeys(distinct_corroborating)),
        reason_codes=unique_reasons,
    )


def _is_official_entity_source(source: dict[str, Any], entity_id: str, vendor_id: str) -> bool:
    authority_class = _string(source.get("source_authority_class"))
    if authority_class not in OFFICIAL_AUTHORITY_CLASSES:
        return False
    return _source_scopes_to_entity(source, entity_id, vendor_id)


def _is_corroborating_source(
    source: dict[str, Any],
    entity_id: str,
    vendor_id: str,
    registration_number: str,
) -> bool:
    if not _source_scopes_to_entity(source, entity_id, vendor_id):
        return False
    numbers = _source_registration_numbers(source)
    if numbers:
        return registration_number in numbers
    # A source can corroborate the entity-to-vendor relationship even when the
    # registry source remains the authority for the number itself.
    return bool(entity_id and _string(source.get("entity_id")) == entity_id)


def _source_scopes_to_entity(source: dict[str, Any], entity_id: str, vendor_id: str) -> bool:
    source_entity_id = _string(source.get("entity_id"))
    source_vendor_id = _string(source.get("vendor_id"))
    if entity_id and source_entity_id:
        return source_entity_id == entity_id
    if vendor_id and source_vendor_id:
        return source_vendor_id == vendor_id
    return False


def _has_conflicting_registration_number(
    sources: Iterable[dict[str, Any]],
    entity_id: str,
    vendor_id: str,
    expected: str,
) -> bool:
    if not expected:
        return False
    for source in sources:
        if not _source_scopes_to_entity(source, entity_id, vendor_id):
            continue
        numbers = _source_registration_numbers(source)
        if numbers and any(number != expected for number in numbers):
            return True
    return False


def _has_entity_scope_ambiguity(
    legal_entity: dict[str, Any],
    sources: Iterable[dict[str, Any]],
    entity_id: str,
    vendor_id: str,
) -> bool:
    # The gate may verify one scoped entity. It fails closed if the candidate or
    # its sources explicitly flag multiple plausible group entities.
    ambiguity_markers = (
        legal_entity.get("entity_scope_ambiguous"),
        legal_entity.get("multiple_plausible_entities"),
        legal_entity.get("ambiguous_global_brand"),
    )
    if any(bool(value) for value in ambiguity_markers):
        return True
    for source in sources:
        if not _source_scopes_to_entity(source, entity_id, vendor_id):
            continue
        if any(bool(source.get(key)) for key in ("entity_scope_ambiguous", "multiple_plausible_entities")):
            return True
    return False


def _has_unsupported_contracting_scope(
    legal_entity: dict[str, Any], source_by_id: dict[str, dict[str, Any]]) -> bool:
    for scope in legal_entity.get("contracting_jurisdictions") or []:
        if not isinstance(scope, dict):
            return True
        source_id = _string(scope.get("source_id"))
        source_ids = list(_strings(scope.get("source_ids")))
        if source_id:
            source_ids.append(source_id)
        if not source_ids:
            return True
        if any(source_id not in source_by_id for source_id in source_ids):
            return True
    return False


def _source_registration_numbers(source: dict[str, Any]) -> set[str]:
    numbers: set[str] = set()
    for key in (
        "registration_number",
        "company_number",
        "entity_number",
        "identifier",
    ):
        value = _normalize_registration_number(source.get(key))
        if value:
            numbers.add(value)
    identifiers = source.get("identifiers") or source.get("registration_numbers") or []
    if isinstance(identifiers, dict):
        iterable = identifiers.values()
    elif isinstance(identifiers, Iterable) and not isinstance(identifiers, str):
        iterable = identifiers
    else:
        iterable = []
    for value in iterable:
        number = _normalize_registration_number(value)
        if number:
            numbers.add(number)
    return numbers


def _normalize_registration_number(value: Any) -> str:
    return "".join(str(value or "").strip().upper().split())


def _string(value: Any) -> str:
    return str(value or "").strip()


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_string(value)] if _string(value) else []
    if isinstance(value, Iterable):
        return [_string(item) for item in value if _string(item)]
    return []
