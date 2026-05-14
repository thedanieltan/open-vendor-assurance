from __future__ import annotations

import argparse
import socket
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.hash import sha256_bytes, sha256_normalized_text
from tools.openva.indexes import ROOT, records_for
from tools.openva.url_safety import validate_url_safety

USER_AGENT = "open-vendor-assurance-observer/0.1 (+metadata-only; public sources only)"
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 20
PILOT_CONFIG = ROOT / "config" / "observation-pilot.yaml"

BOT_PROTECTED_STATUS_CODES = {401, 403, 407, 429}
AMBIGUOUS_RESULTS = {"bot_protected", "size_limited", "fetch_failed", "quarantined"}

BLOCKED_HINTS = (
    "login",
    "sign in",
    "signin",
    "access denied",
    "forbidden",
    "captcha",
    "verify you are human",
    "customer portal",
    "trust portal",
    "request access",
    "cloudflare",
    "checking your browser",
    "attention required",
)

RESULT_NOTES = {
    "ok": "Fetched public source successfully. Raw content not stored; hashes computed from fetched response.",
    "not_modified": "Source was not modified according to conditional request metadata. Raw content not stored.",
    "moved": "Source appears to have moved. Maintainer review required before changing canonical source metadata.",
    "access_changed": "Source access behavior changed. Maintainer review required before writing this observation.",
    "bot_protected": "Transparent public-source fetch encountered bot protection, access controls, or challenge-like content. OpenVA does not bypass these controls and does not compute hashes.",
    "size_limited": "Public response exceeded OpenVA's observation byte limit. Partial content is not stored or hashed.",
    "fetch_failed": "Fetch failed for a non-classified network, timeout, HTTP, or transport reason. Maintainer review required before relying on this result.",
    "quarantined": "Source URL or redirect target failed URL-safety checks. No fetch output is trusted or hashed.",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_observation_id(source_id: str, observed_at: str) -> str:
    date = observed_at[:10]
    return f"{source_id}-{date}"


def is_ambiguous_result(result: str) -> bool:
    return result in AMBIGUOUS_RESULTS


def result_note(result: str) -> str:
    return RESULT_NOTES.get(
        result,
        "Observation result is not recognised by the current taxonomy. Maintainer review required.",
    )


def load_pilot_source_ids() -> set[str]:
    if not PILOT_CONFIG.exists():
        raise FileNotFoundError(f"{PILOT_CONFIG.relative_to(ROOT)} is missing")
    config = yaml.safe_load(PILOT_CONFIG.read_text(encoding="utf-8")) or {}
    source_ids = config.get("sources", [])
    if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
        raise ValueError("config/observation-pilot.yaml: sources must be a list of source_id strings")
    return set(source_ids)


def select_sources(*, pilot_only: bool) -> list[dict[str, Any]]:
    sources = [source for source in records_for("source") if not source["_openva_path"].startswith("examples/")]
    if not pilot_only:
        return sources

    pilot_ids = load_pilot_source_ids()
    available_ids = {source["source_id"] for source in sources}
    missing_ids = sorted(pilot_ids - available_ids)
    if missing_ids:
        missing = ", ".join(missing_ids)
        raise ValueError(f"config/observation-pilot.yaml references unknown source_id(s): {missing}")
    return [source for source in sources if source["source_id"] in pilot_ids]


def fetch_public(url: str) -> tuple[str, int | None, str | None, bytes]:
    if validate_url_safety(url):
        return "quarantined", None, None, b""

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(response.status)
            final_url = response.geturl()
            if validate_url_safety(final_url):
                return "quarantined", status, final_url, b""
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return "size_limited", status, final_url, b""
            return "ok", status, final_url, data
    except urllib.error.HTTPError as error:
        status = int(error.code)
        if status in BOT_PROTECTED_STATUS_CODES:
            return "bot_protected", status, url, b""
        return "fetch_failed", status, url, b""
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        return "fetch_failed", None, url, b""


def looks_blocked(data: bytes) -> bool:
    text = data[:50_000].decode("utf-8", errors="ignore").lower()
    return any(hint in text for hint in BLOCKED_HINTS)


def observation_for_source(source: dict[str, Any]) -> dict[str, Any]:
    observed_at = now_iso()
    source_id = source["source_id"]
    result, http_status, final_url, data = fetch_public(source["source_url"])

    if result == "ok" and looks_blocked(data):
        result = "bot_protected"
        data = b""

    if result == "ok":
        raw_hash = sha256_bytes(data)
        text_hash = sha256_normalized_text(data)
    else:
        raw_hash = "sha256:TBD"
        text_hash = "sha256:TBD"

    return {
        "schema_version": "0.1.0",
        "observation_id": safe_observation_id(source_id, observed_at),
        "vendor_id": source["vendor_id"],
        "source_id": source_id,
        "artifact_id": None,
        "observed_at": observed_at,
        "result": result,
        "http_status": http_status,
        "final_url": final_url,
        "access_class": source["access_class"],
        "hashes": {
            "raw_sha256": raw_hash,
            "normalized_text_sha256": text_hash,
            "etag": None,
            "last_modified": None,
        },
        "storage": {
            "raw_document_stored": False,
            "extracted_text_stored": False,
            "screenshot_stored": False,
        },
        "notes": result_note(result),
    }


def write_observation(observation: dict[str, Any]) -> Path:
    vendor_id = observation["vendor_id"]
    observation_id = observation["observation_id"]
    path = ROOT / "data" / "vendors" / vendor_id / "observations" / f"{observation_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(observation, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def summarize_observations(observations: list[dict[str, Any]], *, dry_run: bool, skipped: int = 0) -> None:
    counts = Counter(observation["result"] for observation in observations)
    print("OpenVA observation summary")
    print(f"mode: {'dry-run' if dry_run else 'write'}")
    print(f"sources: {len(observations)}")
    for result in sorted(counts):
        print(f"{result}: {counts[result]}")
    if skipped:
        print(f"skipped_ambiguous_writes: {skipped}")

    if observations:
        print("\nResults by source:")
        for observation in observations:
            status = observation["http_status"] if observation["http_status"] is not None else "-"
            print(
                f"- {observation['source_id']}: {observation['result']} "
                f"(http={status}, final_url={observation['final_url'] or '-'})"
            )


def observe_sources(dry_run: bool, *, pilot_only: bool, allow_ambiguous_write: bool = False, emit_yaml: bool = False) -> int:
    observations = [observation_for_source(source) for source in select_sources(pilot_only=pilot_only)]

    if dry_run:
        summarize_observations(observations, dry_run=True)
        if emit_yaml:
            print("\n---")
            print(yaml.safe_dump(observations, sort_keys=False, allow_unicode=True))
        return 0

    created = []
    skipped = 0
    for observation in observations:
        if is_ambiguous_result(observation["result"]) and not allow_ambiguous_write:
            skipped += 1
            continue
        created.append(write_observation(observation))

    summarize_observations(observations, dry_run=False, skipped=skipped)
    if created:
        print("\nWritten observations:")
        for path in created:
            print(path.relative_to(ROOT))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-observe")
    parser.add_argument("command", choices=["observe-all", "observe-pilot"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-ambiguous-write",
        action="store_true",
        help="Write ambiguous observations such as bot_protected, size_limited, fetch_failed, or quarantined.",
    )
    parser.add_argument(
        "--emit-yaml",
        action="store_true",
        help="In dry-run mode, print raw observation YAML after the compact summary.",
    )
    args = parser.parse_args()

    if args.command == "observe-all":
        return observe_sources(
            dry_run=args.dry_run,
            pilot_only=False,
            allow_ambiguous_write=args.allow_ambiguous_write,
            emit_yaml=args.emit_yaml,
        )
    if args.command == "observe-pilot":
        return observe_sources(
            dry_run=args.dry_run,
            pilot_only=True,
            allow_ambiguous_write=args.allow_ambiguous_write,
            emit_yaml=args.emit_yaml,
        )

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
