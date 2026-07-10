"""Provider-driven vendor breadth replenishment for the OpenVA discovery mesh.

The source crawler can only deepen vendors it already knows. This module supplies
new vendor identities from three independent signal families:

* privacy-preserving resolver demand events;
* public ecosystem or marketplace directory rows;
* subprocessor and other first-party relationship observations emitted by the
  discovery mesh.

Signals are normalized into an append-safe entity ledger, deduplicated against
the current catalog, assigned an identity-resolution state, and projected into a
``vendor_candidate_discovery_report`` for the existing source discovery and
strict admission pipeline. Signals are never catalog facts and this module never
writes canonical vendor or source records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from tools.openva.discovery_mesh import aggregate_identity_signals, slugify
from tools.openva.source_verification import ROOT, display_path

SCHEMA_VERSION = "0.1.0"
POLICY_VERSION = "vendor-breadth-mesh.v1"

RESOLVER_GAP_STATUSES = {
    "not_found",
    "identity_ambiguous",
    "verification_inconclusive",
}

NON_VENDOR_HOSTS = {
    "apps.apple.com",
    "chrome.google.com",
    "docs.google.com",
    "drive.google.com",
    "facebook.com",
    "github.com",
    "instagram.com",
    "linkedin.com",
    "marketplace.atlassian.com",
    "play.google.com",
    "slack.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

GENERIC_NAMES = {
    "about",
    "contact",
    "details",
    "documentation",
    "download",
    "home",
    "learn more",
    "legal",
    "privacy",
    "privacy policy",
    "read more",
    "security",
    "status",
    "terms",
    "trust center",
    "website",
}

COUNTRY_ALIASES = {
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "belgium": "BE",
    "brazil": "BR",
    "bulgaria": "BG",
    "canada": "CA",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "croatia": "HR",
    "cyprus": "CY",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "estonia": "EE",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "greece": "GR",
    "hong kong": "HK",
    "hungary": "HU",
    "iceland": "IS",
    "india": "IN",
    "indonesia": "ID",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "japan": "JP",
    "latvia": "LV",
    "liechtenstein": "LI",
    "lithuania": "LT",
    "luxembourg": "LU",
    "malaysia": "MY",
    "malta": "MT",
    "mexico": "MX",
    "netherlands": "NL",
    "new zealand": "NZ",
    "norway": "NO",
    "philippines": "PH",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "singapore": "SG",
    "slovakia": "SK",
    "slovenia": "SI",
    "south africa": "ZA",
    "south korea": "KR",
    "korea": "KR",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "taiwan": "TW",
    "thailand": "TH",
    "turkey": "TR",
    "türkiye": "TR",
    "ukraine": "UA",
    "united arab emirates": "AE",
    "uae": "AE",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "vietnam": "VN",
}

COUNTRY_TOKEN_PATTERN = re.compile(
    r"(?<![a-z])(" + "|".join(sorted((re.escape(value) for value in COUNTRY_ALIASES), key=len, reverse=True)) + r")(?![a-z])",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: Any) -> str:
    return normalize_space(value)[:300]


def normalize_country(value: Any) -> str | None:
    raw = normalize_space(value)
    if not raw:
        return None
    upper = raw.upper()
    if re.fullmatch(r"[A-Z]{2}", upper):
        return upper
    return COUNTRY_ALIASES.get(raw.casefold())


def infer_country(value: Any) -> str | None:
    text = normalize_space(value)
    if not text:
        return None
    explicit = normalize_country(text)
    if explicit:
        return explicit
    match = COUNTRY_TOKEN_PATTERN.search(text.casefold())
    return COUNTRY_ALIASES.get(match.group(1).casefold()) if match else None


def normalize_domain(value: Any) -> str | None:
    raw = normalize_space(value).lower()
    if not raw:
        return None
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    else:
        raw = raw.split("/", 1)[0].split(":", 1)[0]
    raw = raw.strip(".").removeprefix("www.")
    try:
        raw = raw.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not raw or "." not in raw or len(raw) > 253 or " " in raw:
        return None
    try:
        ipaddress.ip_address(raw)
        return None
    except ValueError:
        pass
    if raw in NON_VENDOR_HOSTS:
        return None
    if not re.fullmatch(r"[a-z0-9.-]+", raw):
        return None
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in raw.split(".")):
        return None
    return raw


def domain_from_url(value: Any) -> str | None:
    return normalize_domain(value)


def is_public_http_url(value: Any) -> bool:
    parsed = urlparse(normalize_space(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def valid_vendor_name(value: Any) -> bool:
    name = normalize_name(value)
    if len(name) < 2 or name.casefold() in GENERIC_NAMES:
        return False
    if len(re.sub(r"[^a-z0-9]", "", name.casefold())) < 2:
        return False
    return True


def stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps([normalize_space(part) for part in parts], ensure_ascii=False, separators=(",", ":"))
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def signal_record(
    *,
    name: str,
    domain: str | None,
    country: str | None,
    provider: str,
    provider_record_id: str,
    source_url: str | None,
    observed_at: str,
    demand_count: int = 1,
    relationship_context: str | None = None,
    source_kind: str,
) -> dict[str, Any] | None:
    clean_name = normalize_name(name)
    clean_domain = normalize_domain(domain)
    clean_country = normalize_country(country) or infer_country(relationship_context)
    if not valid_vendor_name(clean_name):
        return None
    if source_url and not is_public_http_url(source_url):
        source_url = None
    signal_id = stable_id(
        "vbsig-",
        clean_name.casefold(),
        clean_domain or "",
        provider,
        provider_record_id,
        source_url or "",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_id": signal_id,
        "signal_type": "vendor_identity",
        "source_kind": source_kind,
        "candidate_vendor_id": slugify(clean_domain.split(".")[0] if clean_domain else clean_name),
        "display_name_observed": clean_name,
        "domain_observed": clean_domain,
        "country_observed": clean_country,
        "provider": normalize_space(provider),
        "provider_record_id": normalize_space(provider_record_id),
        "source_url": source_url,
        "relationship_context": normalize_space(relationship_context)[:1_000] or None,
        "observed_at": observed_at,
        "demand_count": max(1, int(demand_count)),
        "identity_state": "country_and_domain_observed" if clean_domain and clean_country else (
            "domain_observed" if clean_domain else "unresolved"
        ),
        "admission_weight": "none",
        "requires_identity_resolution": True,
        "not_advice": True,
    }


def _event_query(event: dict[str, Any]) -> dict[str, Any]:
    query = event.get("query") or event.get("request") or {}
    return query if isinstance(query, dict) else {}


def _event_result(event: dict[str, Any]) -> dict[str, Any]:
    result = event.get("resolution") or event.get("result") or {}
    return result if isinstance(result, dict) else {}


def resolver_demand_signals(events: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            skipped.append({"index": index, "reason": "event_not_object"})
            continue
        query = _event_query(event)
        result = _event_result(event)
        status = normalize_space(
            result.get("resolution_status") or event.get("resolution_status") or event.get("status")
        )
        vendor = result.get("vendor") or {}
        if not isinstance(vendor, dict):
            vendor = {}
        if vendor.get("vendor_id"):
            skipped.append({"index": index, "reason": "resolver_match_already_identified"})
            continue
        if status not in RESOLVER_GAP_STATUSES:
            skipped.append({"index": index, "reason": "status_not_vendor_identity_gap", "status": status})
            continue
        name = (
            query.get("vendor_name")
            or query.get("name")
            or event.get("vendor_name")
            or event.get("name")
            or vendor.get("display_name")
        )
        domain = (
            query.get("domain")
            or query.get("official_domain")
            or event.get("domain")
            or vendor.get("official_domain")
        )
        country = query.get("country") or event.get("country")
        event_id = normalize_space(event.get("event_id") or event.get("request_id") or f"row-{index}")
        signal = signal_record(
            name=str(name or ""),
            domain=str(domain or "") or None,
            country=str(country or "") or None,
            provider="resolver_demand",
            provider_record_id=event_id,
            source_url=None,
            observed_at=normalize_space(event.get("observed_at")) or now_iso(),
            demand_count=int(event.get("demand_count") or 1),
            source_kind="resolver_demand",
        )
        if signal is None:
            skipped.append({"index": index, "reason": "invalid_or_generic_vendor_name"})
            continue
        signals.append(signal)
    return signals, skipped


def directory_signals(
    rows: Iterable[dict[str, Any]],
    *,
    provider: str,
    provider_source_url: str,
    observed_at: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not provider or not is_public_http_url(provider_source_url):
        raise ValueError("directory provider and public provider_source_url are required")
    signals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    observed_at = observed_at or now_iso()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            skipped.append({"index": index, "reason": "row_not_object"})
            continue
        name = row.get("display_name") or row.get("vendor_name") or row.get("name")
        website = row.get("official_domain") or row.get("domain") or row.get("website") or row.get("homepage")
        domain = normalize_domain(website)
        listing_url = row.get("listing_url") or row.get("source_url") or provider_source_url
        record_id = normalize_space(row.get("id") or row.get("slug") or row.get("key") or f"row-{index}")
        signal = signal_record(
            name=str(name or ""),
            domain=domain,
            country=row.get("country") or row.get("headquarters_country"),
            provider=provider,
            provider_record_id=record_id,
            source_url=str(listing_url or provider_source_url),
            observed_at=normalize_space(row.get("observed_at")) or observed_at,
            demand_count=int(row.get("demand_count") or 1),
            relationship_context=row.get("description") or row.get("context"),
            source_kind="public_directory",
        )
        if signal is None:
            skipped.append({"index": index, "reason": "invalid_directory_identity"})
            continue
        signals.append(signal)
    return signals, skipped


def relationship_report_signals(report: dict[str, Any], *, observed_at: str | None = None) -> list[dict[str, Any]]:
    """Convert either raw relationship signals or an aggregate identity report."""

    observed_at = observed_at or normalize_space(report.get("generated_at")) or now_iso()
    output: dict[str, dict[str, Any]] = {}
    raw = report.get("vendor_identity_signals") or report.get("signals") or []
    if isinstance(raw, list):
        for index, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            signal = signal_record(
                name=str(row.get("display_name_observed") or row.get("display_name_candidate") or ""),
                domain=row.get("domain_observed") or row.get("official_domain_candidate"),
                country=row.get("country_observed") or row.get("headquarters_country_candidate"),
                provider=str(row.get("provider") or "relationship_graph"),
                provider_record_id=str(row.get("signal_id") or f"raw-{index}"),
                source_url=row.get("source_url"),
                observed_at=normalize_space(row.get("observed_at")) or observed_at,
                demand_count=int(row.get("demand_count") or 1),
                relationship_context=row.get("relationship_context"),
                source_kind="relationship_graph",
            )
            if signal:
                output[signal["signal_id"]] = signal

    candidates = report.get("vendor_candidates") or []
    if isinstance(candidates, list):
        for index, row in enumerate(candidates):
            if not isinstance(row, dict):
                continue
            providers = row.get("providers") or ["relationship_graph"]
            if not isinstance(providers, list) or not providers:
                providers = ["relationship_graph"]
            source_urls = row.get("source_urls") or [None]
            if not isinstance(source_urls, list) or not source_urls:
                source_urls = [None]
            for provider_index, provider in enumerate(providers):
                signal = signal_record(
                    name=str(row.get("display_name_candidate") or ""),
                    domain=row.get("official_domain_candidate"),
                    country=row.get("headquarters_country_candidate"),
                    provider=str(provider),
                    provider_record_id=f"aggregate-{index}-{provider_index}",
                    source_url=source_urls[min(provider_index, len(source_urls) - 1)],
                    observed_at=observed_at,
                    demand_count=max(1, int(row.get("demand_count") or row.get("signal_count") or 1)),
                    relationship_context=row.get("relationship_context"),
                    source_kind="relationship_graph",
                )
                if signal:
                    output[signal["signal_id"]] = signal
    return sorted(output.values(), key=lambda row: str(row["signal_id"]))


def entity_key(signal: dict[str, Any]) -> str:
    domain = normalize_domain(signal.get("domain_observed"))
    if domain:
        return "domain:" + domain
    return "name:" + normalize_name(signal.get("display_name_observed")).casefold()


def observation_projection(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": str(signal.get("signal_id") or ""),
        "provider": str(signal.get("provider") or ""),
        "provider_record_id": str(signal.get("provider_record_id") or ""),
        "source_kind": str(signal.get("source_kind") or ""),
        "source_url": signal.get("source_url"),
        "observed_at": str(signal.get("observed_at") or ""),
        "demand_count": max(1, int(signal.get("demand_count") or 1)),
        "country_observed": normalize_country(signal.get("country_observed")),
        "relationship_context": normalize_space(signal.get("relationship_context"))[:1_000] or None,
    }


def merge_ledger(existing: dict[str, Any] | None, signals: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entities: dict[str, dict[str, Any]] = {}
    if isinstance(existing, dict):
        for row in existing.get("entities", []) or []:
            if isinstance(row, dict) and row.get("entity_key"):
                entities[str(row["entity_key"])] = json.loads(json.dumps(row))

    for signal in signals:
        if not isinstance(signal, dict) or signal.get("not_advice") is not True:
            continue
        key = entity_key(signal)
        current = entities.get(key)
        if current is None:
            current = {
                "entity_key": key,
                "display_name": normalize_name(signal.get("display_name_observed")),
                "domain": normalize_domain(signal.get("domain_observed")),
                "countries": [],
                "first_seen_at": str(signal.get("observed_at") or now_iso()),
                "last_seen_at": str(signal.get("observed_at") or now_iso()),
                "observations": [],
                "not_advice": True,
            }
            entities[key] = current
        observation = observation_projection(signal)
        by_signal = {
            str(row.get("signal_id") or ""): row
            for row in current.get("observations", []) or []
            if isinstance(row, dict)
        }
        prior = by_signal.get(observation["signal_id"])
        if prior:
            prior["observation_count"] = int(prior.get("observation_count") or 1) + 1
            prior["last_seen_at"] = max(
                str(prior.get("last_seen_at") or prior.get("observed_at") or ""),
                observation["observed_at"],
            )
            prior["demand_count"] = int(prior.get("demand_count") or 1) + observation["demand_count"]
            if observation.get("country_observed"):
                prior["country_observed"] = observation["country_observed"]
        else:
            observation["observation_count"] = 1
            observation["last_seen_at"] = observation["observed_at"]
            current.setdefault("observations", []).append(observation)
        country = normalize_country(signal.get("country_observed"))
        if country and country not in current.setdefault("countries", []):
            current["countries"].append(country)
        current["countries"] = sorted(current["countries"])
        current["last_seen_at"] = max(str(current.get("last_seen_at") or ""), observation["observed_at"])
        if not current.get("domain") and normalize_domain(signal.get("domain_observed")):
            current["domain"] = normalize_domain(signal.get("domain_observed"))
        candidate_name = normalize_name(signal.get("display_name_observed"))
        if candidate_name and len(candidate_name) > len(str(current.get("display_name") or "")):
            current["display_name"] = candidate_name

    rows = []
    for key in sorted(entities):
        row = entities[key]
        row["observations"] = sorted(
            row.get("observations", []) or [],
            key=lambda item: (str(item.get("provider") or ""), str(item.get("signal_id") or "")),
        )
        providers = sorted({str(item.get("provider") or "") for item in row["observations"] if item.get("provider")})
        row["provider_count"] = len(providers)
        row["providers"] = providers
        row["signal_count"] = len(row["observations"])
        row["observation_count"] = sum(int(item.get("observation_count") or 1) for item in row["observations"])
        row["demand_count"] = sum(int(item.get("demand_count") or 1) for item in row["observations"])
        rows.append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "report_type": "vendor_breadth_signal_ledger",
        "policy_version": POLICY_VERSION,
        "summary": {
            "entity_count": len(rows),
            "signal_count": sum(int(row["signal_count"]) for row in rows),
            "observation_count": sum(int(row["observation_count"]) for row in rows),
            "provider_count": len({provider for row in rows for provider in row.get("providers", [])}),
            "catalog_vendor_count_cap": None,
        },
        "entities": rows,
        "posture": {
            "append_safe": True,
            "signals_are_catalog_facts": False,
            "canonical_mutation_performed": False,
            "personal_identifiers_retained": False,
            "non_advisory": True,
        },
    }


def catalog_identity(root: Path = ROOT) -> tuple[set[str], set[str], set[str]]:
    vendor_ids: set[str] = set()
    domains: set[str] = set()
    names: set[str] = set()
    for path in sorted((root / "data" / "vendors").glob("*/vendor.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(value, dict):
            continue
        vendor_ids.add(str(value.get("vendor_id") or path.parent.name))
        for domain in value.get("official_domains", []) or []:
            normalized = normalize_domain(domain)
            if normalized:
                domains.add(normalized)
        for domain in value.get("previous_domains", []) or []:
            normalized = normalize_domain(domain)
            if normalized:
                domains.add(normalized)
        for name in [value.get("display_name"), value.get("legal_name"), *(value.get("display_aliases", []) or [])]:
            normalized = normalize_name(name).casefold()
            if normalized:
                names.add(normalized)
    return vendor_ids, domains, names


def entity_country(entity: dict[str, Any]) -> tuple[str | None, str]:
    countries = sorted({normalize_country(value) for value in entity.get("countries", []) or [] if normalize_country(value)})
    if len(countries) == 1:
        return countries[0], "single_country_observed"
    if len(countries) > 1:
        counts: Counter[str] = Counter()
        for observation in entity.get("observations", []) or []:
            country = normalize_country(observation.get("country_observed"))
            if country:
                counts[country] += int(observation.get("observation_count") or 1)
        if counts:
            best = counts.most_common()
            if len(best) == 1 or best[0][1] > best[1][1]:
                return best[0][0], "country_observation_majority"
        return None, "country_conflict"
    return None, "country_missing"


def queue_and_candidate_report(
    ledger: dict[str, Any],
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    known_ids, known_domains, known_names = catalog_identity(root)
    queue: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for entity in ledger.get("entities", []) or []:
        if not isinstance(entity, dict):
            continue
        name = normalize_name(entity.get("display_name"))
        domain = normalize_domain(entity.get("domain"))
        country, country_reason = entity_country(entity)
        vendor_id = slugify(domain.split(".")[0] if domain else name)
        reasons: list[str] = []
        state = "ready_for_source_discovery"
        if vendor_id in known_ids or (domain and domain in known_domains) or name.casefold() in known_names:
            state = "already_catalogued"
            reasons.append("catalog_identity_collision")
        elif not domain:
            state = "needs_domain"
            reasons.append("official_domain_missing")
        elif not country:
            state = "needs_country"
            reasons.append(country_reason)
        elif not valid_vendor_name(name):
            state = "low_quality_identity"
            reasons.append("vendor_name_invalid_or_generic")

        providers = sorted(str(value) for value in entity.get("providers", []) or [] if value)
        source_urls = sorted(
            {
                str(row.get("source_url"))
                for row in entity.get("observations", []) or []
                if isinstance(row, dict) and row.get("source_url")
            }
        )
        priority = (
            int(entity.get("demand_count") or 0) * 5
            + int(entity.get("provider_count") or 0) * 12
            + int(entity.get("signal_count") or 0) * 2
            + (20 if domain else 0)
            + (20 if country else 0)
        )
        queue_row = {
            "schema_version": SCHEMA_VERSION,
            "queue_id": stable_id("vbq-", entity.get("entity_key")),
            "candidate_vendor_id": vendor_id,
            "display_name_candidate": name,
            "official_domain_candidate": domain,
            "headquarters_country_candidate": country,
            "state": state,
            "reason_codes": reasons,
            "priority": priority,
            "provider_count": int(entity.get("provider_count") or 0),
            "providers": providers,
            "signal_count": int(entity.get("signal_count") or 0),
            "observation_count": int(entity.get("observation_count") or 0),
            "demand_count": int(entity.get("demand_count") or 0),
            "source_urls": source_urls,
            "first_seen_at": entity.get("first_seen_at"),
            "last_seen_at": entity.get("last_seen_at"),
            "requires_review": True,
            "writes_canonical_vendors": False,
            "not_advice": True,
        }
        queue.append(queue_row)
        if state == "ready_for_source_discovery":
            candidates.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "candidate_vendor_id": vendor_id,
                    "display_name_candidate": name,
                    "official_domain_candidate": domain,
                    "headquarters_country_candidate": country,
                    "coverage_lane": "signal_mesh",
                    "cohort_id": "provider-replenishment",
                    "source_index_url": f"https://{domain}",
                    "vendor_category_candidates": [],
                    "signal_count": queue_row["signal_count"],
                    "observation_count": queue_row["observation_count"],
                    "demand_count": queue_row["demand_count"],
                    "independent_provider_count": queue_row["provider_count"],
                    "providers": providers,
                    "source_urls": source_urls,
                    "priority": priority,
                    "requires_review": True,
                    "writes_canonical_vendors": False,
                    "non_advisory": True,
                }
            )

    queue.sort(key=lambda row: (-int(row["priority"]), str(row["candidate_vendor_id"])))
    candidates.sort(key=lambda row: (-int(row["priority"]), str(row["candidate_vendor_id"])))
    state_counts = Counter(str(row["state"]) for row in queue)
    queue_report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "report_type": "vendor_breadth_resolution_queue",
        "policy_version": POLICY_VERSION,
        "summary": {
            "queue_count": len(queue),
            "ready_for_source_discovery_count": len(candidates),
            "state_counts": dict(sorted(state_counts.items())),
            "catalog_vendor_count_cap": None,
        },
        "items": queue,
        "posture": {
            "catalog_mutation_performed": False,
            "identity_resolution_required": True,
            "non_advisory": True,
        },
    }
    candidate_report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "report_type": "vendor_candidate_discovery_report",
        "discovery_context": "vendor_breadth_signal_mesh",
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "writes_canonical_vendors": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "summary": {
            "candidate_vendor_count": len(candidates),
            "known_vendor_count": int(state_counts.get("already_catalogued", 0)),
            "identity_resolution_queue_count": len(queue),
            "catalog_vendor_count_cap": None,
        },
        "vendor_candidates": candidates,
    }
    return queue_report, candidate_report


def provider_metrics(signals: Iterable[dict[str, Any]], skipped: Iterable[dict[str, Any]], queue: dict[str, Any]) -> dict[str, Any]:
    signal_rows = [row for row in signals if isinstance(row, dict)]
    provider_counts = Counter(str(row.get("provider") or "unknown") for row in signal_rows)
    source_kind_counts = Counter(str(row.get("source_kind") or "unknown") for row in signal_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "report_type": "vendor_breadth_provider_metrics",
        "summary": {
            "accepted_signal_count": len(signal_rows),
            "skipped_input_count": len(list(skipped)),
            "provider_counts": dict(sorted(provider_counts.items())),
            "source_kind_counts": dict(sorted(source_kind_counts.items())),
            "ready_for_source_discovery_count": int(
                (queue.get("summary") or {}).get("ready_for_source_discovery_count") or 0
            ),
            "catalog_vendor_count_cap": None,
        },
        "posture": {"non_advisory": True},
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    text = path.read_text(encoding="utf-8")
    if suffix in {".ndjson", ".jsonl"}:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("events", "rows", "items", "vendor_identity_signals"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [value]
    raise ValueError(f"{display_path(path)}: expected JSON object, array, JSONL, NDJSON, or CSV")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{display_path(path)}: expected JSON object")
    return value


def parse_directory_spec(value: str) -> tuple[str, str, Path]:
    parts = value.split("::", 2)
    if len(parts) != 3:
        raise ValueError("directory feed must use provider::public_source_url::path")
    provider, source_url, raw_path = parts
    return provider, source_url, Path(raw_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-vendor-breadth-mesh")
    parser.add_argument("build", nargs="?")
    parser.add_argument("--resolver-events", type=Path)
    parser.add_argument("--directory-feed", action="append", default=[])
    parser.add_argument("--relationship-report", action="append", type=Path, default=[])
    parser.add_argument("--existing-ledger", type=Path)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--queue-output", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--metrics-output", type=Path, required=True)
    args = parser.parse_args(argv)

    signals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if args.resolver_events:
        rows, rejected = resolver_demand_signals(read_rows(args.resolver_events))
        signals.extend(rows)
        skipped.extend(rejected)
    for specification in args.directory_feed:
        provider, source_url, path = parse_directory_spec(specification)
        rows, rejected = directory_signals(
            read_rows(path),
            provider=provider,
            provider_source_url=source_url,
        )
        signals.extend(rows)
        skipped.extend(rejected)
    for path in args.relationship_report:
        signals.extend(relationship_report_signals(load_json(path)))

    existing = load_json(args.existing_ledger) if args.existing_ledger and args.existing_ledger.exists() else None
    ledger = merge_ledger(existing, signals)
    queue, candidates = queue_and_candidate_report(ledger)
    metrics = provider_metrics(signals, skipped, queue)
    for path, payload in (
        (args.ledger_output, ledger),
        (args.queue_output, queue),
        (args.candidate_output, candidates),
        (args.metrics_output, metrics),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**ledger["summary"], **queue["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
