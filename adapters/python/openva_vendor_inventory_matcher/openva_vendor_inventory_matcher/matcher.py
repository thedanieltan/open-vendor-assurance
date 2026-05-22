from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openva_pack_reader import OpenVAPack

MINIMUM_MATCH_CONFIDENCE = 0.90
AMBIGUITY_MARGIN = 0.05
MATCH_INPUT_COLUMNS = {"domain", "vendor_name", "business_entity_name", "registration_number"}

ENRICHMENT_COLUMNS = [
    "match_status",
    "matched_vendor_id",
    "matched_display_name",
    "match_confidence",
    "match_method",
    "candidate_matches_json",
    "manifest_path",
    "catalog_status",
    "official_domains_json",
    "canonical_source_types_json",
    "candidate_source_types_json",
    "unavailable_source_types_json",
    "missing_core_source_types_json",
    "canonical_sources_available",
    "candidate_sources_available",
    "unavailable_sources_recorded",
    "canonical_sources_json",
    "primary_source_by_type_json",
    "candidate_sources_json",
    "latest_observation_result",
    "latest_observed_at",
    "legal_entity_match_method",
    "legal_entity_resolution_confidence",
    "matched_legal_entity_id",
    "matched_legal_entity_name",
    "legal_entity_jurisdiction",
    "legal_entity_registration_number",
    "legal_entity_registered_address_json",
    "legal_entities_json",
    "candidate_legal_entities_json",
    "record_class",
    "canonical",
    "catalog_tier",
    "review_state",
    "advisory_boundary",
]


@dataclass(frozen=True)
class VendorRecord:
    vendor_id: str
    display_name: str
    legal_name: str
    catalog_status: str
    official_domains: list[str]
    manifest_path: str
    name_keys: frozenset[str]


@dataclass(frozen=True)
class LegalEntityRecord:
    entity_id: str
    vendor_id: str
    legal_name: str
    jurisdiction: str
    registration_number: str
    catalog_status: str
    registered_address: dict[str, Any] | None


@dataclass(frozen=True)
class MatchCandidate:
    vendor: VendorRecord
    confidence: float
    method: str


@dataclass(frozen=True)
class LegalEntityResolution:
    method: str
    confidence: str
    matched_entity: LegalEntityRecord | None
    candidates: list[LegalEntityRecord]


def match_inventory(pack_path: str | Path, input_csv: str | Path, output_csv: str | Path) -> Path:
    pack = OpenVAPack.load(pack_path)
    index = MatcherIndex.from_pack(pack)
    input_path = Path(input_csv)
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8-sig", newline="") as input_handle:
        reader = csv.DictReader(input_handle)
        fieldnames = list(reader.fieldnames or [])
        if not MATCH_INPUT_COLUMNS.intersection(fieldnames):
            raise ValueError("input CSV must include domain, vendor_name, business_entity_name, or registration_number")
        rows = [index.enrich_row(row) for row in reader]

    output_columns = [*fieldnames, *[column for column in ENRICHMENT_COLUMNS if column not in fieldnames]]
    with output_path.open("w", encoding="utf-8", newline="") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=output_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output_path


class MatcherIndex:
    def __init__(
        self,
        vendors: list[VendorRecord],
        coverage_by_vendor: dict[str, dict[str, Any]],
        canonical_sources_by_vendor: dict[str, list[dict[str, Any]]],
        candidate_sources_by_vendor: dict[str, list[dict[str, Any]]],
        latest_observations_by_vendor: dict[str, dict[str, Any]],
        legal_entities: list[LegalEntityRecord],
        contracting_resolution_by_key: dict[tuple[str, str], dict[str, Any]],
    ):
        self.vendors = vendors
        self.vendors_by_id = {vendor.vendor_id: vendor for vendor in vendors}
        self.coverage_by_vendor = coverage_by_vendor
        self.canonical_sources_by_vendor = canonical_sources_by_vendor
        self.candidate_sources_by_vendor = candidate_sources_by_vendor
        self.latest_observations_by_vendor = latest_observations_by_vendor
        self.legal_entities_by_vendor = group_legal_entities_by_vendor(legal_entities)
        self.legal_entities_by_registration = group_legal_entities_by_registration(legal_entities)
        self.legal_entities_by_id = {entity.entity_id: entity for entity in legal_entities}
        self.contracting_resolution_by_key = contracting_resolution_by_key

    @classmethod
    def from_pack(cls, pack: OpenVAPack) -> "MatcherIndex":
        vendors = [vendor_record(row) for row in pack.vendor_search()]
        coverage = pack.source_coverage().get("vendor_coverage", [])
        coverage_by_vendor = {
            row["vendor_id"]: row for row in coverage if isinstance(row, dict) and isinstance(row.get("vendor_id"), str)
        }
        return cls(
            vendors=vendors,
            coverage_by_vendor=coverage_by_vendor,
            canonical_sources_by_vendor=group_sources(pack.canonical_sources(), "vendor_id"),
            candidate_sources_by_vendor=group_sources(pack.candidate_sources(), "vendor_id"),
            latest_observations_by_vendor=latest_observations(pack.observations()),
            legal_entities=[legal_entity_record(row) for row in pack_rows(pack, "legal_entities")],
            contracting_resolution_by_key=contracting_resolution_by_key(pack),
        )

    def enrich_row(self, input_row: dict[str, str]) -> dict[str, str]:
        candidates = self.match_candidates(input_row)
        selected = select_match(candidates)
        entity_resolution = self.resolve_legal_entity(input_row, selected.vendor if selected else None)
        if selected is None and entity_resolution.matched_entity is not None:
            vendor = self.vendors_by_id.get(entity_resolution.matched_entity.vendor_id)
            if vendor is not None:
                selected = MatchCandidate(vendor, 1.00, "registration_number_exact")
        output = dict(input_row)
        output.update(base_annotation())

        if selected is None and candidates:
            output.update(match_fields("ambiguous", None, candidates))
        elif selected is None:
            output.update(match_fields("no_match", None, []))
        else:
            output.update(match_fields("matched", selected, candidates or [selected]))
            output.update(enrichment_fields(selected.vendor, self))
        output.update(legal_entity_fields(entity_resolution, selected.vendor if selected else None, self))
        return output

    def match_candidates(self, input_row: dict[str, str]) -> list[MatchCandidate]:
        domain = normalize_domain(input_row.get("domain", ""))
        name = normalize_name(input_row.get("vendor_name", "")) or normalize_name(input_row.get("business_entity_name", ""))
        candidates: dict[str, MatchCandidate] = {}
        for vendor in self.vendors:
            candidate = candidate_for_vendor(vendor, domain, name)
            if candidate and candidate.confidence >= MINIMUM_MATCH_CONFIDENCE:
                current = candidates.get(vendor.vendor_id)
                if current is None or candidate.confidence > current.confidence:
                    candidates[vendor.vendor_id] = candidate
        return sorted(candidates.values(), key=lambda item: (-item.confidence, item.vendor.vendor_id))

    def resolve_legal_entity(
        self,
        input_row: dict[str, str],
        selected_vendor: VendorRecord | None,
    ) -> LegalEntityResolution:
        registration_number = normalize_registration_number(input_row.get("registration_number", ""))
        jurisdiction = normalize_jurisdiction(input_row.get("jurisdiction", ""))
        if registration_number:
            matches = self.legal_entities_by_registration.get(registration_number, [])
            if jurisdiction:
                matches = [entity for entity in matches if entity.jurisdiction == jurisdiction]
            if len(matches) == 1:
                return LegalEntityResolution("registration_number_exact", "matched", matches[0], matches)
            if len(matches) > 1:
                return LegalEntityResolution("registration_number_exact", "ambiguous", None, sorted_legal_entities(matches))

        if selected_vendor is not None and jurisdiction:
            resolution = self.contracting_resolution_by_key.get((selected_vendor.vendor_id, jurisdiction))
            if resolution is not None:
                candidate_ids = list_value(resolution.get("candidate_entity_ids"))
                candidates = sorted_legal_entities(
                    [
                        self.legal_entities_by_id[entity_id]
                        for entity_id in candidate_ids
                        if isinstance(entity_id, str) and entity_id in self.legal_entities_by_id
                    ]
                )
                resolved_entity_id = resolution.get("resolved_entity_id")
                matched_entity = self.legal_entities_by_id.get(resolved_entity_id) if isinstance(resolved_entity_id, str) else None
                if matched_entity is not None and matched_entity not in candidates:
                    candidates = sorted_legal_entities([matched_entity, *candidates])
                status = scalar(resolution.get("resolution_status"))
                confidence = "ambiguous" if status == "ambiguous" else "candidate"
                return LegalEntityResolution("jurisdiction_resolution_index", confidence, matched_entity, candidates)

        return LegalEntityResolution("unresolved", "unresolved", None, [])


def vendor_record(row: dict[str, Any]) -> VendorRecord:
    vendor_id = scalar(row.get("vendor_id"))
    display_name = scalar(row.get("display_name"))
    legal_name = scalar(row.get("legal_name"))
    domains = [domain for domain in [normalize_domain(value) for value in row.get("official_domains", [])] if domain]
    name_keys = {normalize_name(value) for value in [vendor_id, display_name, legal_name, vendor_id.replace("-", " ")]}
    name_keys.add(strip_legal_suffixes(legal_name))
    return VendorRecord(
        vendor_id=vendor_id,
        display_name=display_name,
        legal_name=legal_name,
        catalog_status=scalar(row.get("catalog_status", row.get("status"))),
        official_domains=domains,
        manifest_path=scalar(row.get("manifest_path")),
        name_keys=frozenset(key for key in name_keys if key),
    )


def legal_entity_record(row: dict[str, Any]) -> LegalEntityRecord:
    registered_address = row.get("registered_address")
    return LegalEntityRecord(
        entity_id=scalar(row.get("entity_id")),
        vendor_id=scalar(row.get("vendor_id")),
        legal_name=scalar(row.get("legal_name")),
        jurisdiction=normalize_jurisdiction(row.get("jurisdiction", "")),
        registration_number=scalar(row.get("registration_number")),
        catalog_status=scalar(row.get("catalog_status")),
        registered_address=registered_address if isinstance(registered_address, dict) else None,
    )


def candidate_for_vendor(vendor: VendorRecord, domain: str, name: str) -> MatchCandidate | None:
    if domain:
        for official_domain in vendor.official_domains:
            if domain == official_domain:
                return MatchCandidate(vendor, 1.00, "domain_exact")
        for official_domain in vendor.official_domains:
            if domain.endswith(f".{official_domain}"):
                return MatchCandidate(vendor, 0.95, "domain_subdomain")
    if name and name in vendor.name_keys:
        return MatchCandidate(vendor, 0.90, "name_exact")
    return None


def select_match(candidates: list[MatchCandidate]) -> MatchCandidate | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    first, second = candidates[0], candidates[1]
    if first.confidence == second.confidence or first.confidence - second.confidence < AMBIGUITY_MARGIN:
        return None
    return first


def match_fields(status: str, selected: MatchCandidate | None, candidates: list[MatchCandidate]) -> dict[str, str]:
    return {
        "match_status": status,
        "matched_vendor_id": selected.vendor.vendor_id if selected else "",
        "matched_display_name": selected.vendor.display_name if selected else "",
        "match_confidence": confidence_cell(selected.confidence) if selected else "",
        "match_method": selected.method if selected else "",
        "candidate_matches_json": json_cell([candidate_json(candidate) for candidate in candidates]),
    }


def enrichment_fields(vendor: VendorRecord, index: MatcherIndex) -> dict[str, str]:
    coverage = index.coverage_by_vendor.get(vendor.vendor_id, {})
    canonical_source_types = list_value(coverage.get("canonical_source_types"))
    candidate_source_types = list_value(coverage.get("candidate_source_types"))
    unavailable_source_types = list_value(coverage.get("unavailable_source_types"))
    missing_core_source_types = list_value(coverage.get("missing_core_source_types"))
    canonical_sources = [canonical_source_json(row) for row in index.canonical_sources_by_vendor.get(vendor.vendor_id, [])]
    candidate_sources = [candidate_source_json(row) for row in index.candidate_sources_by_vendor.get(vendor.vendor_id, [])]
    observation = index.latest_observations_by_vendor.get(vendor.vendor_id, {})
    return {
        "manifest_path": vendor.manifest_path,
        "catalog_status": vendor.catalog_status,
        "official_domains_json": json_cell(vendor.official_domains),
        "canonical_source_types_json": json_cell(canonical_source_types),
        "candidate_source_types_json": json_cell(candidate_source_types),
        "unavailable_source_types_json": json_cell(unavailable_source_types),
        "missing_core_source_types_json": json_cell(missing_core_source_types),
        "canonical_sources_available": bool_cell(bool(canonical_source_types)),
        "candidate_sources_available": bool_cell(bool(candidate_source_types)),
        "unavailable_sources_recorded": bool_cell(bool(unavailable_source_types)),
        "canonical_sources_json": json_cell(canonical_sources),
        "primary_source_by_type_json": json_cell(primary_source_by_type(canonical_sources)),
        "candidate_sources_json": json_cell(candidate_sources),
        "latest_observation_result": scalar(observation.get("result")),
        "latest_observed_at": scalar(observation.get("observed_at")),
    }


def legal_entity_fields(
    resolution: LegalEntityResolution,
    selected_vendor: VendorRecord | None,
    index: MatcherIndex,
) -> dict[str, str]:
    matched_entity = resolution.matched_entity
    vendor_entities = index.legal_entities_by_vendor.get(selected_vendor.vendor_id, []) if selected_vendor else []
    candidates = resolution.candidates
    if not candidates and resolution.confidence == "unresolved":
        candidates = []
    return {
        "legal_entity_match_method": resolution.method,
        "legal_entity_resolution_confidence": resolution.confidence,
        "matched_legal_entity_id": matched_entity.entity_id if matched_entity else "",
        "matched_legal_entity_name": matched_entity.legal_name if matched_entity else "",
        "legal_entity_jurisdiction": matched_entity.jurisdiction if matched_entity else "",
        "legal_entity_registration_number": matched_entity.registration_number if matched_entity else "",
        "legal_entity_registered_address_json": json_cell(matched_entity.registered_address if matched_entity else None),
        "legal_entities_json": json_cell([legal_entity_json(entity) for entity in vendor_entities]),
        "candidate_legal_entities_json": json_cell([legal_entity_json(entity) for entity in candidates]),
    }


def base_annotation() -> dict[str, str]:
    return {
        "record_class": "inventory_match",
        "canonical": "false",
        "catalog_tier": "human_reviewed",
        "review_state": "human_reviewed",
        "advisory_boundary": "non_advisory",
    }


def candidate_json(candidate: MatchCandidate) -> dict[str, Any]:
    return {
        "vendor_id": candidate.vendor.vendor_id,
        "display_name": candidate.vendor.display_name,
        "match_confidence": candidate.confidence,
        "match_method": candidate.method,
    }


def canonical_source_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": scalar(row.get("source_id")),
        "source_type": scalar(row.get("source_type")),
        "source_url": scalar(row.get("source_url")),
        "title_en": scalar(row.get("title_en")),
        "effective_or_published_at": scalar(row.get("effective_or_published_at")),
        "record_class": "canonical",
        "canonical": True,
        "catalog_tier": "human_reviewed",
        "review_state": "human_reviewed",
        "advisory_boundary": "non_advisory",
    }


def primary_source_by_type(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        source_type = source.get("source_type", "")
        if source_type:
            by_type[source_type].append(source)
    return {
        source_type: sorted(
            typed_sources,
            key=lambda item: (
                item.get("effective_or_published_at", "") == "",
                reverse_date_key(item.get("effective_or_published_at", "")),
                item.get("source_id", ""),
            ),
        )[0]
        for source_type, typed_sources in sorted(by_type.items())
    }


def reverse_date_key(value: str) -> str:
    return "".join(chr(255 - ord(character)) for character in value)


def candidate_source_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_source_id": scalar(row.get("candidate_source_id")),
        "source_type_candidate": scalar(row.get("source_type_candidate")),
        "candidate_url": scalar(row.get("candidate_url")),
        "confidence": scalar(row.get("confidence")),
        "record_class": "candidate",
        "canonical": False,
        "catalog_tier": "discovery",
        "review_state": "human_review_required",
        "advisory_boundary": "non_advisory",
    }


def legal_entity_json(entity: LegalEntityRecord) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "vendor_id": entity.vendor_id,
        "legal_name": entity.legal_name,
        "jurisdiction": entity.jurisdiction,
        "registration_number": entity.registration_number,
        "catalog_status": entity.catalog_status,
        "registered_address": entity.registered_address,
    }


def pack_rows(pack: OpenVAPack, method_name: str) -> list[dict[str, Any]]:
    method = getattr(pack, method_name, None)
    if not callable(method):
        return []
    rows = method()
    return rows if isinstance(rows, list) else []


def contracting_resolution_by_key(pack: OpenVAPack) -> dict[tuple[str, str], dict[str, Any]]:
    method = getattr(pack, "contracting_entity_resolution", None)
    if not callable(method):
        return {}
    index = method()
    rows = index.get("items", []) if isinstance(index, dict) else []
    return {
        (str(row["vendor_id"]), normalize_jurisdiction(row.get("jurisdiction", ""))): row
        for row in rows
        if isinstance(row, dict) and row.get("vendor_id") and row.get("jurisdiction")
    }


def group_sources(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if isinstance(value, str):
            grouped[value].append(row)
    for value in grouped.values():
        value.sort(key=lambda item: scalar(item.get("source_id", item.get("candidate_source_id"))))
    return dict(grouped)


def group_legal_entities_by_vendor(rows: list[LegalEntityRecord]) -> dict[str, list[LegalEntityRecord]]:
    grouped: dict[str, list[LegalEntityRecord]] = defaultdict(list)
    for row in rows:
        grouped[row.vendor_id].append(row)
    return {vendor_id: sorted_legal_entities(items) for vendor_id, items in grouped.items()}


def group_legal_entities_by_registration(rows: list[LegalEntityRecord]) -> dict[str, list[LegalEntityRecord]]:
    grouped: dict[str, list[LegalEntityRecord]] = defaultdict(list)
    for row in rows:
        registration_number = normalize_registration_number(row.registration_number)
        if registration_number:
            grouped[registration_number].append(row)
    return {registration_number: sorted_legal_entities(items) for registration_number, items in grouped.items()}


def sorted_legal_entities(rows: list[LegalEntityRecord]) -> list[LegalEntityRecord]:
    return sorted(rows, key=lambda row: (row.vendor_id, row.jurisdiction, row.entity_id))


def latest_observations(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        vendor_id = row.get("vendor_id")
        if not isinstance(vendor_id, str):
            continue
        current = latest.get(vendor_id)
        if current is None or scalar(row.get("observed_at")) > scalar(current.get("observed_at")):
            latest[vendor_id] = row
    return latest


def normalize_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        parsed = urlsplit(raw)
        domain = parsed.netloc
    else:
        domain = re.split(r"[/#?]", raw, maxsplit=1)[0]
    domain = domain.rsplit("@", maxsplit=1)[-1]
    if ":" in domain and domain.count(":") == 1:
        domain = domain.split(":", maxsplit=1)[0]
    domain = domain.strip().rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def normalize_jurisdiction(value: str | None) -> str:
    return (value or "").strip().upper()


def normalize_name(value: str | None) -> str:
    raw = (value or "").strip().lower()
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return " ".join(raw.split())


def strip_legal_suffixes(value: str | None) -> str:
    tokens = normalize_name(value).split()
    suffixes = {"inc", "llc", "ltd", "limited", "corp", "corporation", "company", "co"}
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def normalize_registration_number(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value or "").upper()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def bool_cell(value: bool) -> str:
    return "true" if value else "false"


def confidence_cell(value: float) -> str:
    return f"{value:.2f}"


def json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
