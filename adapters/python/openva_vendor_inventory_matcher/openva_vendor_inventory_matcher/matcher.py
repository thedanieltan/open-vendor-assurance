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
MATCH_INPUT_COLUMNS = {"domain", "vendor_name", "business_entity_name"}

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
    "record_class",
    "canonical",
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
class MatchCandidate:
    vendor: VendorRecord
    confidence: float
    method: str


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
            raise ValueError("input CSV must include domain, vendor_name, or business_entity_name")
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
    ):
        self.vendors = vendors
        self.coverage_by_vendor = coverage_by_vendor
        self.canonical_sources_by_vendor = canonical_sources_by_vendor
        self.candidate_sources_by_vendor = candidate_sources_by_vendor
        self.latest_observations_by_vendor = latest_observations_by_vendor

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
        )

    def enrich_row(self, input_row: dict[str, str]) -> dict[str, str]:
        candidates = self.match_candidates(input_row)
        selected = select_match(candidates)
        output = dict(input_row)
        output.update(base_annotation())

        if selected is None and candidates:
            output.update(match_fields("ambiguous", None, candidates))
        elif selected is None:
            output.update(match_fields("no_match", None, []))
        else:
            output.update(match_fields("matched", selected, candidates))
            output.update(enrichment_fields(selected.vendor, self))
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


def base_annotation() -> dict[str, str]:
    return {
        "record_class": "inventory_match",
        "canonical": "false",
        "advisory_boundary": "non_advisory",
    }


def candidate_json(candidate: MatchCandidate) -> dict[str, Any]:
    return {
        "vendor_id": candidate.vendor.vendor_id,
        "display_name": candidate.vendor.display_name,
        "match_confidence": candidate.confidence,
        "match_method": candidate.method,
    }


def canonical_source_json(row: dict[str, Any]) -> dict[str, str]:
    return {
        "source_id": scalar(row.get("source_id")),
        "source_type": scalar(row.get("source_type")),
        "source_url": scalar(row.get("source_url")),
        "title_en": scalar(row.get("title_en")),
        "effective_or_published_at": scalar(row.get("effective_or_published_at")),
    }


def primary_source_by_type(sources: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
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


def candidate_source_json(row: dict[str, Any]) -> dict[str, str]:
    return {
        "candidate_source_id": scalar(row.get("candidate_source_id")),
        "source_type_candidate": scalar(row.get("source_type_candidate")),
        "candidate_url": scalar(row.get("candidate_url")),
        "confidence": scalar(row.get("confidence")),
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
