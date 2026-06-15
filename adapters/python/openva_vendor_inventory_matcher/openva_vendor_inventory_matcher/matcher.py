from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from openva_pack_reader import OpenVAPack

from openva_vendor_inventory_matcher.core import (
    LegalEntityRecord,
    LegalEntityResolution,
    MatchCandidate,
    VendorRecord,
    classify,
    group_legal_entities_by_registration,
    group_legal_entities_by_vendor,
    legal_entity_record,
    list_value,
    match_candidates,
    normalize_domain,
    normalize_jurisdiction,
    normalize_name,
    resolve_legal_entity,
    scalar,
    select_match,
    sorted_legal_entities,
    vendor_record,
)

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
    """CSV/pack glue around the shared matching core."""

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
        domain = normalize_domain(input_row.get("domain", ""))
        name = normalize_name(input_row.get("vendor_name", "")) or normalize_name(input_row.get("business_entity_name", ""))
        candidates = match_candidates(self.vendors, domain, name)
        selected = select_match(candidates)
        entity_resolution = self.resolve_legal_entity(input_row, selected.vendor if selected else None)
        if selected is None and entity_resolution.matched_entity is not None:
            vendor = self.vendors_by_id.get(entity_resolution.matched_entity.vendor_id)
            if vendor is not None:
                selected = MatchCandidate(vendor, 1.00, "registration_number_exact")
        output = dict(input_row)
        output.update(base_annotation())

        status = classify(candidates, selected)
        if selected is None:
            output.update(match_fields(status, None, candidates))
        else:
            output.update(match_fields(status, selected, candidates or [selected]))
            output.update(enrichment_fields(selected.vendor, self))
        output.update(legal_entity_fields(entity_resolution, selected.vendor if selected else None, self))
        return output

    def resolve_legal_entity(
        self,
        input_row: dict[str, str],
        selected_vendor: VendorRecord | None,
    ) -> LegalEntityResolution:
        return resolve_legal_entity(
            input_row,
            selected_vendor,
            by_registration=self.legal_entities_by_registration,
            by_id=self.legal_entities_by_id,
            contracting_by_key=self.contracting_resolution_by_key,
        )


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


def bool_cell(value: bool) -> str:
    return "true" if value else "false"


def confidence_cell(value: float) -> str:
    return f"{value:.2f}"


def json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
