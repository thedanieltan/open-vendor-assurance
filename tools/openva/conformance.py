from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.indexes import EXPORT_PROFILE_ID, EXPORT_SCHEMA_VERSION, ROOT
from tools.openva.pack import REQUIRED_INDEX_KEYS, REQUIRED_REGISTRY_OUTPUT_KEYS, verify_export_contract
from tools.openva.url_safety import validate_url_safety

PACK_FILENAME = "openva-pack.json"
COUNT_INDEX_KEYS = ["vendors", "sources", "artifacts", "observations", "changes", "legal_entities", "entity_mentions"]
SUMMARY_COUNT_MAP = {
    "vendor": "vendors",
    "source": "sources",
    "artifact": "artifacts",
    "observation": "observations",
    "change": "changes",
    "legal_entity": "legal_entities",
    "entity_mention": "entity_mentions",
}
RESOLUTION_STATUSES = {"resolved", "candidate", "ambiguous", "brand_only_fallback"}
AMBIGUITY_REASONS = {"multiple_candidates", "source_too_broad", "no_public_source", "jurisdiction_overlap"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_pack_schema() -> dict[str, Any]:
    return load_json(ROOT / "schemas/openva/openva-pack.schema.json")


def load_prohibited_terms() -> list[str]:
    config_path = ROOT / "config/prohibited-claims.yaml"
    if not config_path.exists():
        return []
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return [str(term).lower() for term in config.get("prohibited_terms", [])]


def is_relative_pack_path(rel_path: str) -> bool:
    path = Path(rel_path)
    return not path.is_absolute() and ".." not in path.parts


def validate_schema(pack: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(load_pack_schema(), format_checker=FormatChecker())
    failures: list[str] = []
    for error in sorted(validator.iter_errors(pack), key=lambda err: list(err.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        failures.append(f"openva-pack.json: {location}: {error.message}")
    return failures


def validate_index_counts(indexes: dict[str, Any], loaded_indexes: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in COUNT_INDEX_KEYS:
        index = loaded_indexes.get(key)
        if not isinstance(index, dict):
            continue
        items = index.get("items")
        count = index.get("count")
        if not isinstance(items, list):
            failures.append(f"{indexes.get(key, key)}: items must be a list")
            continue
        if count != len(items):
            failures.append(f"{indexes.get(key, key)}: count {count} does not match item count {len(items)}")

    summary = loaded_indexes.get("summary")
    if isinstance(summary, dict):
        counts = summary.get("counts", {})
        for summary_key, index_key in SUMMARY_COUNT_MAP.items():
            index = loaded_indexes.get(index_key)
            if not isinstance(index, dict):
                continue
            expected = index.get("count")
            actual = counts.get(summary_key)
            if actual != expected:
                failures.append(
                    f"{indexes.get('summary', 'summary')}: count for {summary_key} {actual} does not match {index_key} count {expected}"
                )
    return failures


def validate_guarantees(pack: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    guarantees = pack.get("guarantees", {})
    for guarantee in ["public_sources_only", "metadata_first", "non_advisory"]:
        if guarantees.get(guarantee) is not True:
            failures.append(f"openva-pack.json: guarantee {guarantee} must be true")
    if guarantees.get("raw_documents_mirrored_by_default") is not False:
        failures.append("openva-pack.json: raw_documents_mirrored_by_default must be false")
    return failures


def validate_registry_outputs(pack: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    registry_outputs = pack.get("registry_outputs")
    if not isinstance(registry_outputs, dict):
        return ["openva-pack.json: registry_outputs must be an object"]
    missing_keys = sorted(REQUIRED_REGISTRY_OUTPUT_KEYS - set(registry_outputs))
    extra_keys = sorted(set(registry_outputs) - REQUIRED_REGISTRY_OUTPUT_KEYS)
    if missing_keys:
        failures.append(f"openva-pack.json: missing registry output keys {missing_keys}")
    if extra_keys:
        failures.append(f"openva-pack.json: unexpected registry output keys {extra_keys}")
    if registry_outputs.get("vendor_manifests") != "dist/vendors/{vendor_id}.json":
        failures.append("openva-pack.json: registry_outputs.vendor_manifests must be dist/vendors/{vendor_id}.json")
    return failures


def validate_source_urls(loaded_indexes: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    sources = loaded_indexes.get("sources", {})
    if isinstance(sources, dict):
        for item in sources.get("items", []):
            source_id = item.get("source_id", "<unknown-source>")
            source_url = item.get("source_url")
            if isinstance(source_url, str):
                for failure in validate_url_safety(source_url):
                    failures.append(f"sources:{source_id}: source_url: {failure}")

    artifacts = loaded_indexes.get("artifacts", {})
    if isinstance(artifacts, dict):
        for item in artifacts.get("items", []):
            artifact_id = item.get("artifact_id", "<unknown-artifact>")
            canonical_url = item.get("canonical_url")
            if isinstance(canonical_url, str):
                for failure in validate_url_safety(canonical_url):
                    failures.append(f"artifacts:{artifact_id}: canonical_url: {failure}")
    return failures


def validate_observation_records(loaded_indexes: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    observations = loaded_indexes.get("observations", {})
    if not isinstance(observations, dict):
        return failures

    for item in observations.get("items", []):
        observation_id = item.get("observation_id", "<unknown-observation>")
        result = item.get("result")
        hashes = item.get("hashes", {})
        storage = item.get("storage", {})
        if result != "ok":
            if hashes.get("raw_sha256") != "sha256:TBD":
                failures.append(f"observations:{observation_id}: non-ok result must not include raw_sha256")
            if hashes.get("normalized_text_sha256") != "sha256:TBD":
                failures.append(f"observations:{observation_id}: non-ok result must not include normalized_text_sha256")
        if storage.get("raw_document_stored") is not False:
            failures.append(f"observations:{observation_id}: raw_document_stored must be false")
    return failures


def validate_contracting_entity_resolution(loaded_indexes: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    resolution = loaded_indexes.get("contracting_entity_resolution", {})
    if not isinstance(resolution, dict):
        return failures

    for item in resolution.get("items", []):
        vendor_id = item.get("vendor_id", "<unknown-vendor>")
        jurisdiction = item.get("jurisdiction", "<unknown-jurisdiction>")
        location = f"contracting_entity_resolution:{vendor_id}:{jurisdiction}"
        status = item.get("resolution_status")
        if status not in RESOLUTION_STATUSES:
            failures.append(f"{location}: unknown resolution_status {status}")
        if status == "brand_only_fallback" and item.get("resolved_entity_id") is not None:
            failures.append(f"{location}: brand_only_fallback must not include resolved_entity_id")
        if status == "resolved" and not item.get("resolved_entity_id"):
            failures.append(f"{location}: resolved status must include resolved_entity_id")
        for reason in item.get("ambiguity_reasons", []) or []:
            if reason not in AMBIGUITY_REASONS:
                failures.append(f"{location}: unknown ambiguity_reason {reason}")
    return failures


def validate_non_advisory_text(pack: dict[str, Any], loaded_indexes: dict[str, Any]) -> list[str]:
    terms = load_prohibited_terms()
    if not terms:
        return []

    text = json.dumps({"pack": pack, "indexes": loaded_indexes}, ensure_ascii=False).lower()
    failures: list[str] = []
    for term in terms:
        pattern = r"(?<![a-z0-9-])" + re.escape(term) + r"(?![a-z0-9-])"
        if re.search(pattern, text):
            failures.append(f"fixture pack: prohibited advisory wording detected: {term}")
    return failures


def validate_pack_dir(pack_dir: Path) -> list[str]:
    failures: list[str] = []
    pack_path = pack_dir / PACK_FILENAME
    if not pack_path.exists():
        return [f"{pack_path}: missing openva-pack.json"]

    try:
        pack = load_json(pack_path)
    except json.JSONDecodeError as error:
        return [f"{pack_path}: invalid JSON: {error}"]

    failures.extend(validate_schema(pack))
    failures.extend(verify_export_contract(pack))

    if pack.get("profileId") != EXPORT_PROFILE_ID:
        failures.append(f"openva-pack.json: profileId must be {EXPORT_PROFILE_ID}")
    if pack.get("schemaVersion") != EXPORT_SCHEMA_VERSION:
        failures.append(f"openva-pack.json: schemaVersion must be {EXPORT_SCHEMA_VERSION}")

    indexes = pack.get("indexes")
    if not isinstance(indexes, dict):
        return [*failures, "openva-pack.json: indexes must be an object"]

    missing_keys = sorted(REQUIRED_INDEX_KEYS - set(indexes))
    extra_keys = sorted(set(indexes) - REQUIRED_INDEX_KEYS)
    if missing_keys:
        failures.append(f"openva-pack.json: missing index keys {missing_keys}")
    if extra_keys:
        failures.append(f"openva-pack.json: unexpected index keys {extra_keys}")

    loaded_indexes: dict[str, Any] = {}
    for key, rel_path in indexes.items():
        if not isinstance(rel_path, str):
            failures.append(f"openva-pack.json: index path for {key} must be a string")
            continue
        if not is_relative_pack_path(rel_path):
            failures.append(f"openva-pack.json: index path for {key} escapes pack root: {rel_path}")
            continue
        path = pack_dir / rel_path
        if not path.exists():
            failures.append(f"openva-pack.json: index path for {key} does not exist: {rel_path}")
            continue
        if not path.is_file():
            failures.append(f"openva-pack.json: index path for {key} is not a file: {rel_path}")
            continue
        try:
            loaded_indexes[key] = load_json(path)
        except json.JSONDecodeError as error:
            failures.append(f"{rel_path}: invalid JSON: {error}")

    failures.extend(validate_index_counts(indexes, loaded_indexes))
    failures.extend(validate_registry_outputs(pack))
    failures.extend(validate_guarantees(pack))
    failures.extend(validate_source_urls(loaded_indexes))
    failures.extend(validate_observation_records(loaded_indexes))
    failures.extend(validate_contracting_entity_resolution(loaded_indexes))
    failures.extend(validate_non_advisory_text(pack, loaded_indexes))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-conformance")
    parser.add_argument("pack_dir", help="Path to a fixture pack directory containing openva-pack.json")
    args = parser.parse_args()

    pack_dir = Path(args.pack_dir)
    failures = validate_pack_dir(pack_dir)
    if failures:
        for failure in failures:
            print(failure)
        print(f"Consumer conformance failed: {len(failures)} issue(s).")
        return 1

    print("Consumer conformance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
