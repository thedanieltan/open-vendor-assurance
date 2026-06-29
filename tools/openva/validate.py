from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.advisory_wording import load_prohibited_terms as load_shared_prohibited_terms
from tools.openva.advisory_wording import prohibited_terms_in_text
from tools.openva.indexes import build_indexes, check_generated_current, records_for
from tools.openva.pack import verify_pack_integrity
from tools.openva.paths import relative_repo_path
from tools.openva.schema_registry import build_openva_validator
from tools.openva.url_safety import validate_url_safety

ROOT = Path(__file__).resolve().parents[2]
PACK_READER_PATH = ROOT / "adapters/python/openva_pack_reader"

SCHEMA_MAP = {
    "vendor": ROOT / "schemas/openva/vendor-public-profile.schema.json",
    "source": ROOT / "schemas/openva/source-reference.schema.json",
    "artifact": ROOT / "schemas/openva/artifact-reference.schema.json",
    "observation": ROOT / "schemas/openva/observation.schema.json",
    "change": ROOT / "schemas/openva/change-event.schema.json",
    "legal_entity": ROOT / "schemas/openva/legal-entity.schema.json",
    "entity_mention": ROOT / "schemas/openva/entity-mention.schema.json",
    "field_provenance": ROOT / "schemas/openva/field-provenance.schema.json",
    "candidate_source": ROOT / "schemas/openva/candidate-source.schema.json",
    "unavailable_source": ROOT / "schemas/openva/unavailable-source.schema.json",
    "assurance": ROOT / "schemas/openva/assurance-record.schema.json",
    "assurance_observation": ROOT / "schemas/openva/assurance-observation.schema.json",
    "assurance_change": ROOT / "schemas/openva/assurance-change-event.schema.json",
    "pack": ROOT / "schemas/openva/openva-pack.schema.json",
}
ADAPTER_NORMALIZED_RECORD_SCHEMA = ROOT / "schemas/openva/adapter-normalized-record.schema.json"

FIXTURE_GLOBS = {
    "vendor": ["examples/vendors/*/vendor.yaml", "data/vendors/*/vendor.yaml"],
    "source": ["examples/vendors/*/sources/*.yaml", "data/vendors/*/sources/*.yaml"],
    "artifact": ["examples/vendors/*/artifacts/*.yaml", "data/vendors/*/artifacts/*.yaml"],
    "observation": ["examples/vendors/*/observations/*.yaml", "data/vendors/*/observations/*.yaml"],
    "change": ["examples/vendors/*/changes/*.yaml", "data/vendors/*/changes/*.yaml"],
    "legal_entity": ["examples/vendors/*/legal_entities/*.yaml", "data/vendors/*/legal_entities/*.yaml"],
    "entity_mention": ["examples/vendors/*/entity_mentions/*.yaml", "data/vendors/*/entity_mentions/*.yaml"],
    "field_provenance": ["examples/vendors/*/provenance/*.yaml", "data/vendors/*/provenance/*.yaml"],
    "candidate_source": ["examples/vendors/*/candidate_sources/*.yaml", "data/vendors/*/candidate_sources/*.yaml"],
    "unavailable_source": ["examples/vendors/*/unavailable_sources/*.yaml", "data/vendors/*/unavailable_sources/*.yaml"],
    "assurance": ["examples/vendors/*/assurances/*.yaml", "data/vendors/*/assurances/*.yaml"],
    "assurance_observation": [
        "examples/vendors/*/assurance_observations/*.yaml",
        "data/vendors/*/assurance_observations/*.yaml",
    ],
    "assurance_change": [
        "examples/vendors/*/assurance_changes/*.yaml",
        "data/vendors/*/assurance_changes/*.yaml",
    ],
}

RECORD_TEXT_FILE_GLOBS = ["examples/**/*.yaml", "data/**/*.yaml"]
ALLOWED_PROHIBITED_CONTEXTS = ("not a real vendor record", "fixture for schema validation only")
RAW_CONTENT_DIR_NAMES = {"raw", "raw-documents", "snapshots", "screenshots", "extracted-text"}

VALID_ACCESS_RIGHTS = {
    "public_web": {"metadata_only", "public_link_only", "snapshot_forbidden", "snapshot_allowed"},
    "public_pdf": {"metadata_only", "public_link_only", "snapshot_forbidden", "snapshot_allowed"},
    "public_doc_portal": {"metadata_only", "public_link_only", "snapshot_forbidden"},
    "public_landing_gated_docs": {"metadata_only", "public_link_only", "gated_excluded"},
    "excluded_non_public": {"gated_excluded"},
}

ENTITY_ANCHORED_AUTHORITY_CLASSES = {"public_registry", "public_authority", "court_or_regulatory_filing"}


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_adapter_record(record: dict[str, Any], *, label: str = "adapter-normalized-record") -> list[str]:
    """Validate a normalized adapter output record against the public adapter schema."""
    schema = load_json(ADAPTER_NORMALIZED_RECORD_SCHEMA)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    failures: list[str] = []
    for error in sorted(validator.iter_errors(record), key=lambda err: list(err.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        failures.append(f"{label}: {location}: {error.message}")
    return failures


def iter_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def validate_schema(kind: str) -> list[str]:
    schema = load_json(SCHEMA_MAP[kind])
    if kind.startswith("assurance"):
        validator = build_openva_validator(SCHEMA_MAP[kind])
    else:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    failures: list[str] = []

    if kind == "pack":
        pack_path = ROOT / "openva-pack.json"
        paths = [pack_path] if pack_path.exists() else []
    else:
        paths = iter_paths(FIXTURE_GLOBS[kind])

    for path in paths:
        data = load_json(path) if path.suffix == ".json" else load_yaml(path)
        errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            failures.append(f"{path}: {location}: {error.message}")

    return failures


def validate_adapter_outputs() -> list[str]:
    if str(PACK_READER_PATH) not in sys.path:
        sys.path.insert(0, str(PACK_READER_PATH))

    from openva_pack_reader import OpenVAPack  # noqa: PLC0415

    pack = OpenVAPack.load(ROOT)
    failures: list[str] = []
    record_groups: list[tuple[str, list[dict[str, Any]]]] = [
        ("vendors", pack.vendors()),
        ("canonical_sources", pack.canonical_sources()),
        ("artifacts", pack.artifacts()),
        ("observations", pack.observations()),
        ("changes", pack.changes()),
        ("legal_entities", pack.legal_entities()),
        ("candidate_sources", pack.candidate_sources()),
        ("unavailable_sources", pack.unavailable_sources()),
    ]
    coverage = pack.source_coverage().get("vendor_coverage", [])
    if isinstance(coverage, list):
        record_groups.append(("source_coverage.vendor_coverage", [row for row in coverage if isinstance(row, dict)]))

    for group_name, records in record_groups:
        for index, record in enumerate(records):
            failures.extend(validate_adapter_record(record, label=f"{group_name}[{index}]"))
    return failures


def records_for_optional_kind(kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in iter_paths(FIXTURE_GLOBS[kind]):
        record = load_yaml(path)
        if isinstance(record, dict):
            record["_openva_path"] = relative_repo_path(path, ROOT)
            records.append(record)
    return records


def validate_cross_references() -> list[str]:
    failures: list[str] = []
    vendors = {record["vendor_id"] for record in records_for("vendor")}
    source_records = records_for("source")
    sources = {record["source_id"] for record in source_records}
    sources_by_id = {record["source_id"]: record for record in source_records}
    artifacts = {record["artifact_id"] for record in records_for("artifact")}
    legal_entities = {record["entity_id"]: record for record in records_for("legal_entity")}
    entity_mentions = {record["mention_id"]: record for record in records_for("entity_mention")}
    field_provenance = records_for_optional_kind("field_provenance")

    for source in source_records:
        if source["vendor_id"] not in vendors:
            failures.append(f"{source['_openva_path']}: unknown vendor_id {source['vendor_id']}")
        entity_id = source.get("entity_id")
        if entity_id and entity_id not in legal_entities:
            failures.append(f"{source['_openva_path']}: unknown entity_id {entity_id}")
        for index, claim in enumerate(source.get("coverage_claims", []) or []):
            if not isinstance(claim, dict):
                continue
            target_source_id = claim.get("target_source_id")
            if target_source_id:
                target = sources_by_id.get(str(target_source_id))
                if not target:
                    failures.append(f"{source['_openva_path']}: coverage_claims[{index}].target_source_id {target_source_id} must reference an existing source")
                elif target.get("vendor_id") != source.get("vendor_id"):
                    failures.append(f"{source['_openva_path']}: coverage_claims[{index}].target_source_id {target_source_id} must match source vendor_id")

    for artifact in records_for("artifact"):
        if artifact["vendor_id"] not in vendors:
            failures.append(f"{artifact['_openva_path']}: unknown vendor_id {artifact['vendor_id']}")
        if artifact["source_id"] not in sources:
            failures.append(f"{artifact['_openva_path']}: unknown source_id {artifact['source_id']}")

    for observation in records_for("observation"):
        if observation["vendor_id"] not in vendors:
            failures.append(f"{observation['_openva_path']}: unknown vendor_id {observation['vendor_id']}")
        if observation["source_id"] not in sources:
            failures.append(f"{observation['_openva_path']}: unknown source_id {observation['source_id']}")
        artifact_id = observation.get("artifact_id")
        if artifact_id and artifact_id not in artifacts:
            failures.append(f"{observation['_openva_path']}: unknown artifact_id {artifact_id}")

    for change in records_for("change"):
        if change["vendor_id"] not in vendors:
            failures.append(f"{change['_openva_path']}: unknown vendor_id {change['vendor_id']}")
        if change["source_id"] not in sources:
            failures.append(f"{change['_openva_path']}: unknown source_id {change['source_id']}")
        artifact_id = change.get("artifact_id")
        if artifact_id and artifact_id not in artifacts:
            failures.append(f"{change['_openva_path']}: unknown artifact_id {artifact_id}")

    for legal_entity in records_for("legal_entity"):
        path = legal_entity["_openva_path"]
        entity_id = legal_entity["entity_id"]
        if legal_entity["vendor_id"] not in vendors:
            failures.append(f"{path}: unknown vendor_id {legal_entity['vendor_id']}")
        parent_entity_id = legal_entity.get("parent_entity_id")
        if parent_entity_id and parent_entity_id not in legal_entities:
            failures.append(f"{path}: unknown parent_entity_id {parent_entity_id}")
        for source_id in legal_entity.get("verification_source_ids", []):
            source = sources_by_id.get(source_id)
            if not source:
                failures.append(f"{path}: unknown verification_source_id {source_id}")
            elif source.get("vendor_id") != legal_entity["vendor_id"] and source.get("entity_id") != entity_id:
                failures.append(f"{path}: verification_source_id {source_id} must match vendor_id or entity_id")
        registered_address = legal_entity.get("registered_address")
        if isinstance(registered_address, dict):
            for source_id in registered_address.get("source_ids", []):
                source = sources_by_id.get(source_id)
                if not source:
                    failures.append(f"{path}: unknown registered_address source_id {source_id}")
                elif source.get("vendor_id") != legal_entity["vendor_id"] and source.get("entity_id") != entity_id:
                    failures.append(f"{path}: registered_address source_id {source_id} must match vendor_id or entity_id")
        for former_name in legal_entity.get("former_legal_names", []):
            for source_id in former_name.get("source_ids", []):
                source = sources_by_id.get(source_id)
                if not source:
                    failures.append(f"{path}: unknown former_legal_names source_id {source_id}")
                elif source.get("vendor_id") != legal_entity["vendor_id"] and source.get("entity_id") != entity_id:
                    failures.append(f"{path}: former_legal_names source_id {source_id} must match vendor_id or entity_id")
        for mapping in legal_entity.get("contracting_jurisdictions", []):
            source_id = mapping.get("source_id")
            source = sources_by_id.get(source_id)
            if not source:
                failures.append(f"{path}: unknown contracting_jurisdictions source_id {source_id}")
            elif source.get("vendor_id") != legal_entity["vendor_id"] and source.get("entity_id") != entity_id:
                failures.append(f"{path}: contracting_jurisdictions source_id {source_id} must match vendor_id or entity_id")
        for event in legal_entity.get("lifecycle_events", []):
            for related_key in ("successor_entity_ids", "predecessor_entity_ids"):
                for related_entity_id in event.get(related_key, []):
                    if related_entity_id not in legal_entities:
                        failures.append(f"{path}: unknown {related_key} entry {related_entity_id}")
            for source_id in event.get("source_ids", []):
                source = sources_by_id.get(source_id)
                if not source:
                    failures.append(f"{path}: unknown lifecycle_events source_id {source_id}")
                elif source.get("vendor_id") != legal_entity["vendor_id"] and source.get("entity_id") != entity_id:
                    failures.append(f"{path}: lifecycle_events source_id {source_id} must match vendor_id or entity_id")

    for mention in records_for("entity_mention"):
        path = mention["_openva_path"]
        if mention["vendor_id"] not in vendors:
            failures.append(f"{path}: unknown vendor_id {mention['vendor_id']}")
        source = sources_by_id.get(mention["appears_in_source_id"])
        if not source:
            failures.append(f"{path}: unknown appears_in_source_id {mention['appears_in_source_id']}")
        elif source.get("vendor_id") != mention["vendor_id"]:
            failures.append(f"{path}: appears_in_source_id {mention['appears_in_source_id']} must match mention vendor_id")
        resolution = mention.get("resolution", {})
        matched_entity_id = resolution.get("matched_entity_id")
        if matched_entity_id and matched_entity_id not in legal_entities:
            failures.append(f"{path}: unknown matched_entity_id {matched_entity_id}")
        for source_id in resolution.get("match_source_ids", []) or []:
            if source_id not in sources:
                failures.append(f"{path}: unknown match_source_id {source_id}")

    for provenance in field_provenance:
        path = provenance["_openva_path"]
        if provenance["vendor_id"] not in vendors:
            failures.append(f"{path}: unknown vendor_id {provenance['vendor_id']}")
        source_id = provenance.get("source_id")
        if source_id and source_id not in sources:
            failures.append(f"{path}: unknown source_id {source_id}")
        elif source_id and sources_by_id[source_id].get("vendor_id") != provenance["vendor_id"]:
            failures.append(f"{path}: source_id {source_id} must match provenance vendor_id")
        source_url = provenance.get("source_url")
        if source_id and source_url and sources_by_id.get(source_id, {}).get("source_url") != source_url:
            failures.append(f"{path}: source_url must match referenced source_id {source_id}")

    for vendor in records_for("vendor"):
        for mention_id in vendor.get("observed_entity_mention_ids", []):
            mention = entity_mentions.get(mention_id)
            if not mention:
                failures.append(f"{vendor['_openva_path']}: unknown observed_entity_mention_id {mention_id}")
            elif mention.get("vendor_id") != vendor["vendor_id"]:
                failures.append(f"{vendor['_openva_path']}: observed_entity_mention_id {mention_id} must match vendor_id")

    for candidate in records_for_optional_kind("candidate_source"):
        if candidate["vendor_id"] not in vendors:
            failures.append(f"{candidate['_openva_path']}: unknown vendor_id {candidate['vendor_id']}")

    for unavailable in records_for_optional_kind("unavailable_source"):
        if unavailable["vendor_id"] not in vendors:
            failures.append(f"{unavailable['_openva_path']}: unknown vendor_id {unavailable['vendor_id']}")
        for related_vendor_id in unavailable.get("related_vendor_ids", []):
            if related_vendor_id not in vendors:
                failures.append(f"{unavailable['_openva_path']}: unknown related_vendor_id {related_vendor_id}")

    return failures


def domain_matches(host: str, official_domains: list[str]) -> bool:
    host = host.lower().removeprefix("www.")
    for domain in official_domains:
        domain = domain.lower().removeprefix("www.")
        if host == domain or host.endswith("." + domain):
            return True
    return False


def load_official_publisher_exceptions() -> set[tuple[str, str]]:
    path = ROOT / "config/official-publisher-exceptions.yaml"
    if not path.exists():
        return set()
    config = load_yaml(path) or {}
    exceptions = set()
    for item in config.get("exceptions", []):
        vendor_id = str(item.get("vendor_id", ""))
        domain = str(item.get("domain", "")).lower().removeprefix("www.")
        if vendor_id and domain:
            exceptions.add((vendor_id, domain))
    return exceptions


def load_region_tags() -> set[str]:
    path = ROOT / "config/region-taxonomy.yaml"
    config = load_yaml(path) or {}
    country_markets = config.get("country_markets", {}) or {}
    regional_markets = config.get("regional_markets", {}) or {}
    return {str(tag) for tag in [*country_markets.keys(), *regional_markets.keys()]}


def load_vendor_category_tags() -> set[str]:
    path = ROOT / "config/category-taxonomy.yaml"
    config = load_yaml(path) or {}
    categories = config.get("vendor_categories", {}) or {}
    return {str(tag) for tag in categories.keys()}


def source_domain_allowed(vendor_id: str, host: str, official_domains: list[str], exceptions: set[tuple[str, str]]) -> bool:
    normalized = host.lower().removeprefix("www.")
    if domain_matches(normalized, official_domains):
        return True
    return any(vendor_id == allowed_vendor and (normalized == domain or normalized.endswith("." + domain)) for allowed_vendor, domain in exceptions)


def validate_access_rights(path: str, record: dict[str, Any]) -> list[str]:
    access_class = record.get("access_class")
    rights_class = record.get("rights_class")
    allowed = VALID_ACCESS_RIGHTS.get(access_class, set())
    if rights_class not in allowed:
        return [f"{path}: rights_class {rights_class} is not allowed for access_class {access_class}"]
    return []


def validate_coverage_claims(
    path: str,
    source: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
    prohibited_terms: list[str],
) -> list[str]:
    failures: list[str] = []
    seen_roles: set[str] = set()
    claims = source.get("coverage_claims", []) or []
    if not isinstance(claims, list):
        return failures

    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        role = str(claim.get("role") or "")
        if role in seen_roles:
            failures.append(f"{path}: duplicate coverage_claims role {role}")
        if role:
            seen_roles.add(role)

        for term in prohibited_terms_in_text(claim.get("evidence"), prohibited_terms):
            failures.append(f"{path}: coverage_claims[{index}].evidence prohibited advisory wording detected: {term}")

        coverage_type = claim.get("coverage_type")
        target_url = claim.get("target_url")
        target_source_id = claim.get("target_source_id")
        if coverage_type == "links_to" and not (target_url or target_source_id):
            failures.append(f"{path}: coverage_claims[{index}] links_to requires target_url or target_source_id")
        if target_source_id:
            target = sources_by_id.get(str(target_source_id))
            if not target:
                failures.append(f"{path}: coverage_claims[{index}].target_source_id {target_source_id} must reference an existing source")
            elif target.get("vendor_id") != source.get("vendor_id"):
                failures.append(f"{path}: coverage_claims[{index}].target_source_id {target_source_id} must match source vendor_id")

    return failures


def validate_region_tags(path: str, field: str, values: list[str], allowed_tags: set[str]) -> list[str]:
    failures: list[str] = []
    for value in values:
        if value != value.lower():
            failures.append(f"{path}: {field} tag {value} must be lowercase")
        if value not in allowed_tags:
            failures.append(f"{path}: {field} tag {value} is not defined in config/region-taxonomy.yaml")
    return failures


def validate_vendor_category_tags(path: str, values: list[str], allowed_tags: set[str]) -> list[str]:
    failures: list[str] = []
    for value in values:
        if value not in allowed_tags:
            failures.append(
                f"{path}: vendor_categories tag {value} is not defined in config/category-taxonomy.yaml"
            )
    return failures


def validate_unavailable_truth_state(path: str, unavailable: dict[str, Any], sources_by_id: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    truth_state = unavailable.get("truth_state")
    original_source = unavailable.get("original_source")
    truth_state_status = unavailable.get("truth_state_status")

    if truth_state == "reviewed_no_replacement_available":
        if not str(unavailable.get("reviewed_artifact_path", "")).startswith("maintenance/reviewed/"):
            failures.append(f"{path}: reviewed_artifact_path must be under maintenance/reviewed/")
        if not str(unavailable.get("validation_report_path", "")).startswith("maintenance/reviewed/"):
            failures.append(f"{path}: validation_report_path must be under maintenance/reviewed/")
        if unavailable.get("reviewed_by") == "agent":
            failures.append(f"{path}: reviewed_no_replacement_available must be reviewed by human or hybrid, not agent")
        if truth_state_status != "superseded" and unavailable.get("superseded_by_source_id"):
            failures.append(f"{path}: current reviewed_no_replacement_available must not set superseded_by_source_id unless truth_state_status is superseded")
        if isinstance(original_source, dict):
            source_id = original_source.get("source_id")
            source = sources_by_id.get(source_id)
            if not source:
                failures.append(f"{path}: original_source.source_id {source_id} must reference an existing source")
            else:
                if source.get("vendor_id") != unavailable.get("vendor_id"):
                    failures.append(f"{path}: original_source.source_id {source_id} must match unavailable source vendor_id")
                if source.get("source_type") != original_source.get("source_type"):
                    failures.append(f"{path}: original_source.source_type must match referenced source_id {source_id}")
                if source.get("source_url") != original_source.get("source_url"):
                    failures.append(f"{path}: original_source.source_url must match referenced source_id {source_id}")
        if truth_state_status in {"stale", "expired"} and not unavailable.get("reviewer_note"):
            failures.append(f"{path}: stale or expired no-replacement state requires reviewer_note")

    if truth_state_status == "superseded":
        superseded_by = unavailable.get("superseded_by_source_id")
        source = sources_by_id.get(superseded_by)
        if not source:
            failures.append(f"{path}: superseded_by_source_id {superseded_by} must reference an existing source")
        elif source.get("vendor_id") != unavailable.get("vendor_id"):
            failures.append(f"{path}: superseded_by_source_id {superseded_by} must match unavailable source vendor_id")

    return failures


def validate_optional_source_ledgers(vendors: dict[str, dict[str, Any]], exceptions: set[tuple[str, str]]) -> list[str]:
    failures: list[str] = []
    seen_candidates: dict[str, str] = {}
    seen_unavailable: dict[tuple[str, str], str] = {}
    sources_by_id = {source["source_id"]: source for source in records_for("source")}

    for candidate in records_for_optional_kind("candidate_source"):
        path = candidate["_openva_path"]
        if path.startswith("data/"):
            expected_path = f"data/vendors/{candidate['vendor_id']}/candidate_sources/{candidate['candidate_source_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: candidate_source_id/vendor_id do not match canonical path {expected_path}")

        url = candidate["candidate_url"].rstrip("/")
        failures.extend(f"{path}: candidate_url: {failure}" for failure in validate_url_safety(candidate["candidate_url"]))
        if url in seen_candidates:
            failures.append(f"{path}: duplicate candidate_url also used by {seen_candidates[url]}")
        seen_candidates[url] = path

        parsed = urlparse(candidate["candidate_url"])
        vendor = vendors.get(candidate["vendor_id"])
        if vendor and parsed.hostname and not source_domain_allowed(candidate["vendor_id"], parsed.hostname, vendor["official_domains"], exceptions):
            failures.append(f"{path}: candidate host {parsed.hostname} is not within official_domains or official publisher exceptions for {candidate['vendor_id']}")

    for unavailable in records_for_optional_kind("unavailable_source"):
        path = unavailable["_openva_path"]
        if path.startswith("data/"):
            expected_path = f"data/vendors/{unavailable['vendor_id']}/unavailable_sources/{unavailable['unavailable_source_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: unavailable_source_id/vendor_id do not match canonical path {expected_path}")

        key = (unavailable["vendor_id"], unavailable["source_type"])
        if key in seen_unavailable:
            failures.append(f"{path}: duplicate unavailable source_type for vendor also used by {seen_unavailable[key]}")
        seen_unavailable[key] = path

        for candidate_url in unavailable.get("candidate_urls_checked", []):
            failures.extend(f"{path}: candidate_urls_checked: {failure}" for failure in validate_url_safety(candidate_url))
        failures.extend(validate_unavailable_truth_state(path, unavailable, sources_by_id))

    return failures


def validate_quality_gates() -> list[str]:
    failures: list[str] = []
    vendors = {record["vendor_id"]: record for record in records_for("vendor")}
    legal_entities = {record["entity_id"]: record for record in records_for("legal_entity")}
    source_records = records_for("source")
    sources_by_id = {source["source_id"]: source for source in source_records}
    seen_urls: dict[tuple[str, str], str] = {}
    exceptions = load_official_publisher_exceptions()
    region_tags = load_region_tags()
    vendor_category_tags = load_vendor_category_tags()
    prohibited_terms = load_prohibited_terms()

    for vendor_id, vendor in vendors.items():
        expected_path = f"data/vendors/{vendor_id}/vendor.yaml"
        if vendor["_openva_path"].startswith("data/") and vendor["_openva_path"] != expected_path:
            failures.append(f"{vendor['_openva_path']}: vendor_id does not match canonical path {expected_path}")
        failures.extend(validate_region_tags(vendor["_openva_path"], "regions_served", vendor.get("regions_served", []), region_tags))
        failures.extend(
            validate_vendor_category_tags(
                vendor["_openva_path"],
                vendor.get("vendor_categories", []),
                vendor_category_tags,
            )
        )

    for source in source_records:
        path = source["_openva_path"]
        failures.extend(validate_access_rights(path, source))
        failures.extend(f"{path}: source_url: {failure}" for failure in validate_url_safety(source["source_url"]))
        failures.extend(validate_coverage_claims(path, source, sources_by_id, prohibited_terms))
        if source.get("source_authority_class") in ENTITY_ANCHORED_AUTHORITY_CLASSES and not source.get("entity_id"):
            failures.append(f"{path}: entity_id is required for {source['source_authority_class']} sources")
        if path.startswith("data/"):
            expected_path = f"data/vendors/{source['vendor_id']}/sources/{source['source_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: source_id/vendor_id do not match canonical path {expected_path}")

        url = source["source_url"].rstrip("/")
        key = (str(source["vendor_id"]), url)
        if key in seen_urls:
            failures.append(f"{path}: duplicate source_url for vendor {source['vendor_id']}: {url}")
        seen_urls[key] = path

        parsed = urlparse(source["source_url"])
        vendor = vendors.get(source["vendor_id"])
        authority_class = source.get("source_authority_class", "vendor_published")
        if (
            authority_class in {"vendor_published", "vendor_legal_terms"}
            and vendor
            and parsed.hostname
            and not source_domain_allowed(source["vendor_id"], parsed.hostname, vendor["official_domains"], exceptions)
        ):
            failures.append(f"{path}: source host {parsed.hostname} is not within official_domains or official publisher exceptions for {source['vendor_id']}")

    for artifact in records_for("artifact"):
        path = artifact["_openva_path"]
        failures.extend(validate_access_rights(path, artifact))
        failures.extend(validate_region_tags(path, "region_scope", artifact.get("region_scope", []), region_tags))
        failures.extend(f"{path}: canonical_url: {failure}" for failure in validate_url_safety(artifact["canonical_url"]))
        entity_scope = artifact.get("entity_scope") or {}
        for entity_id in entity_scope.get("entity_ids", []) or []:
            if entity_id not in legal_entities:
                failures.append(f"{path}: unknown entity_scope entity_id {entity_id}")
        if path.startswith("data/"):
            expected_path = f"data/vendors/{artifact['vendor_id']}/artifacts/{artifact['artifact_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: artifact_id/vendor_id do not match canonical path {expected_path}")

    for legal_entity in records_for("legal_entity"):
        path = legal_entity["_openva_path"]
        if path.startswith("data/"):
            expected_path = f"data/vendors/{legal_entity['vendor_id']}/legal_entities/{legal_entity['entity_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: entity_id/vendor_id do not match canonical path {expected_path}")

    for mention in records_for("entity_mention"):
        path = mention["_openva_path"]
        if path.startswith("data/"):
            expected_path = f"data/vendors/{mention['vendor_id']}/entity_mentions/{mention['mention_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: mention_id/vendor_id do not match canonical path {expected_path}")

    for provenance in records_for_optional_kind("field_provenance"):
        path = provenance["_openva_path"]
        if path.startswith("data/"):
            expected_path = f"data/vendors/{provenance['vendor_id']}/provenance/{provenance['provenance_id']}.yaml"
            if path != expected_path:
                failures.append(f"{path}: provenance_id/vendor_id do not match canonical path {expected_path}")

    failures.extend(validate_optional_source_ledgers(vendors, exceptions))

    for path in ROOT.glob("**/*"):
        if path.is_dir() and path.name in RAW_CONTENT_DIR_NAMES:
            failures.append(f"{relative_repo_path(path, ROOT)}: raw content directory is not allowed by default")

    return failures


def load_prohibited_terms() -> list[str]:
    return load_shared_prohibited_terms(ROOT / "config/prohibited-claims.yaml")


def check_prohibited_language() -> list[str]:
    terms = load_prohibited_terms()
    failures: list[str] = []

    for path in iter_paths(RECORD_TEXT_FILE_GLOBS):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        if any(context in lower for context in ALLOWED_PROHIBITED_CONTEXTS):
            continue
        for term in prohibited_terms_in_text(lower, terms):
            failures.append(f"{path}: prohibited advisory wording detected: {term}")

    return failures


def validate_machine_decisions() -> list[str]:
    # WP36: committed machine decision records (append-only NDJSON, validated
    # outside SCHEMA_MAP because the store is NDJSON, not per-record YAML).
    from tools.openva.machine_decisions import validate_committed

    return [f"machine-decision: {reason}" for reason in validate_committed()]


def validate_all() -> int:
    failures: list[str] = []
    for kind in SCHEMA_MAP:
        failures.extend(validate_schema(kind))
    failures.extend(validate_cross_references())
    failures.extend(validate_quality_gates())
    failures.extend(verify_pack_integrity())
    failures.extend(validate_adapter_outputs())
    failures.extend(check_prohibited_language())
    failures.extend(validate_machine_decisions())
    failures.extend(check_generated_current())

    if failures:
        for failure in failures:
            print(failure)
        print(f"Validation failed: {len(failures)} issue(s).")
        return 1

    print("OpenVA validation passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva")
    parser.add_argument("command", choices=["validate", "build-indexes"])
    args = parser.parse_args()

    if args.command == "validate":
        return validate_all()
    if args.command == "build-indexes":
        return build_indexes()

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
