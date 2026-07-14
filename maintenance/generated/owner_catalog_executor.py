from __future__ import annotations

import base64
import lzma
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
generated = ROOT / "maintenance" / "generated"
source_part = generated / "owner-catalog-source.b85"
candidate_part = generated / "owner-catalog-candidates.b85"
candidate_path = generated / "owner-catalog-candidates.tsv"
source = lzma.decompress(base64.b85decode(source_part.read_text(encoding="utf-8"))).decode("utf-8")
candidate_path.write_bytes(lzma.decompress(base64.b85decode(candidate_part.read_text(encoding="utf-8"))))

DISALLOWED_MARKERS = (
    "/blog",
    "blog.",
    "/news",
    "/press",
    "/media",
    "/event",
    "/webinar",
    "/resource",
    "/customer",
    "/case-stud",
    "/success-stor",
    "/stories",
)

SOURCE_MARKERS: dict[str, tuple[str, ...]] = {
    "privacy_notice": (
        "privacy",
        "privacidad",
        "privacidade",
        "confidentialit",
        "datenschutz",
        "개인정보",
        "個人情報",
        "隐私",
        "隱私",
        "gizlilik",
    ),
    "security_page": (
        "security",
        "secure",
        "cyber",
        "trust",
        "seguridad",
        "segurança",
        "securite",
        "sécurité",
        "sicherheit",
        "セキュリティ",
        "보안",
        "安全",
        "güvenlik",
    ),
    "terms_of_service": (
        "terms",
        "conditions",
        "legal",
        "termos",
        "condiciones",
        "nutzungsbeding",
        "利用規約",
        "이용약관",
        "şart",
        "koşul",
    ),
    "trust_center": ("trust",),
    "dpa": (
        "dpa",
        "data-processing",
        "data_processing",
        "processing-agreement",
        "processing_addendum",
        "data processing",
    ),
    "subprocessors_list": (
        "subprocessor",
        "sub-process",
        "sous-trait",
        "subencarg",
    ),
    "compliance_page": (
        "compliance",
        "conform",
        "cumplimiento",
        "conformidade",
        "certif",
        "iso-",
        "iso ",
        "soc-",
        "soc ",
        "준수",
    ),
    "certification_reference": (
        "certif",
        "iso-",
        "iso ",
        "soc-",
        "soc ",
        "attestation",
    ),
    "status_page": ("status", "uptime", "service health"),
    "government_request_policy": (
        "government-request",
        "government request",
        "law-enforcement",
        "law enforcement",
    ),
    "transparency_report": ("transparency",),
    "ai_terms": (
        "ai-terms",
        "ai terms",
        "artificial-intelligence",
        "artificial intelligence",
        "generative-ai",
        "generative ai",
    ),
    "kyc_statement": ("kyc", "know-your-customer", "know your customer"),
    "aml_statement": ("aml", "anti-money-laundering", "anti money laundering"),
}


def sanitize_vendor(vendor: dict[str, Any] | None) -> dict[str, Any] | None:
    if not vendor:
        return None

    display_name = str(vendor.get("display_name") or vendor.get("vendor_id") or "Vendor")
    cleaned_sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_source in vendor.get("sources") or []:
        source_record = dict(raw_source)
        source_type = str(source_record.get("source_type") or "").strip()
        source_url = str(source_record.get("source_url") or "").strip()
        title = " ".join(
            str(source_record.get(key) or "")
            for key in ("title_en", "title_native", "summary_en", "summary_native")
        )
        haystack = f"{source_url} {title}".lower()

        if not source_url or source_type not in SOURCE_MARKERS:
            continue
        if any(marker in haystack for marker in DISALLOWED_MARKERS):
            continue
        if not any(marker in haystack for marker in SOURCE_MARKERS[source_type]):
            continue

        dedupe_key = (source_type, source_url.rstrip("/").lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        artifact = dict(source_record.get("artifact") or {})
        artifact["region_scope"] = []
        source_record["artifact"] = artifact
        # Preserve source identity and classification while replacing publisher
        # marketing copy with a neutral, deterministic catalog label.
        neutral_title = f"{display_name} {source_type.replace('_', ' ')}"
        source_record["title_en"] = neutral_title
        source_record["title_native"] = neutral_title
        source_record["summary_en"] = None
        source_record["summary_native"] = None
        cleaned_sources.append(source_record)

    if not cleaned_sources:
        return None

    cleaned = dict(vendor)
    cleaned["sources"] = cleaned_sources
    cleaned["regions_served"] = ["global"]
    cleaned["public_entrypoints"] = sorted(
        {str(source_record["source_url"]) for source_record in cleaned_sources}
    )
    return cleaned


source = source.replace(
    'SUPPLEMENTAL_TSV_PATH = ROOT / "maintenance" / "generated" / "owner-catalog-candidates.tsv"\n',
    'SUPPLEMENTAL_TSV_PATH = ROOT / "maintenance" / "generated" / "owner-catalog-candidates.tsv"\n'
    'CACHE_PATH = ROOT / "maintenance" / "generated" / "owner-real-source-expansion-500-cache.json"\n',
)
old_init = '''    candidates = load_candidates()
    accepted: list[dict[str, Any]] = []
    skipped: list[str] = []

    # Process bounded waves and stop as soon as the exact catalog target is met.
'''
new_init = '''    candidates = load_candidates()
    accepted: list[dict[str, Any]] = []
    skipped: list[str] = []
    processed_vendor_ids: set[str] = set()
    existing_vendor_ids = {
        path.parent.name
        for path in (ROOT / "data" / "vendors").glob("*/vendor.yaml")
    }
    candidates = [
        candidate
        for candidate in candidates
        if candidate["vendor_id"] not in existing_vendor_ids
    ]
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        for cached_vendor in cache.get("accepted_vendors") or []:
            vendor_id = str(cached_vendor.get("vendor_id") or "")
            if not vendor_id or vendor_id in existing_vendor_ids:
                continue
            sanitized = sanitize_vendor(cached_vendor)
            if sanitized is None:
                skipped.append(f"{vendor_id}: rejected by conservative source admission")
                continue
            accepted.append(sanitized)
        skipped.extend(str(item) for item in (cache.get("skipped") or []))
        processed_vendor_ids = {
            str(vendor["vendor_id"])
            for vendor in accepted
        }
        candidates = [
            candidate
            for candidate in candidates
            if candidate["vendor_id"] not in processed_vendor_ids
        ]
        if len(accepted) > needed:
            accepted = accepted[:needed]
            processed_vendor_ids = {
                str(vendor["vendor_id"])
                for vendor in accepted
            }
        print(
            f"resuming source discovery with {len(accepted)} conservatively admitted vendors, "
            f"{len(processed_vendor_ids)} retained candidates, and {len(candidates)} candidates eligible for retry",
            flush=True,
        )

    # Process bounded waves and stop as soon as the exact catalog target is met.
'''
old_wave = '''            for future in as_completed(future_map):
                candidate = future_map[future]
                try:
                    vendor = future.result()
                except Exception as exc:
                    skipped.append(f"{candidate['vendor_id']}: {type(exc).__name__}")
                    continue
                if vendor is None:
                    skipped.append(f"{candidate['vendor_id']}: no verified public source")
                    continue
                accepted.append(vendor)
        if len(accepted) >= needed:
            break
'''
new_wave = '''            for future in as_completed(future_map):
                candidate = future_map[future]
                processed_vendor_ids.add(candidate["vendor_id"])
                try:
                    vendor = future.result()
                except Exception as exc:
                    skipped.append(f"{candidate['vendor_id']}: {type(exc).__name__}")
                    continue
                vendor = sanitize_vendor(vendor)
                if vendor is None:
                    skipped.append(f"{candidate['vendor_id']}: no conservatively admitted public source")
                    continue
                accepted.append(vendor)
        if len(accepted) > needed:
            accepted = accepted[:needed]
        CACHE_PATH.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "accepted_vendors": accepted,
                    "processed_vendor_ids": sorted(processed_vendor_ids),
                    "skipped": skipped,
                },
                indent=2,
                sort_keys=True,
            )
            + "\\n",
            encoding="utf-8",
        )
        print(
            f"discovery wave complete: accepted={len(accepted)} processed={len(processed_vendor_ids)}",
            flush=True,
        )
        if len(accepted) >= needed:
            break
'''
if old_init not in source or old_wave not in source:
    raise RuntimeError("resumable-discovery patch markers do not match staged executor")
source = source.replace(old_init, new_init).replace(old_wave, new_wave)
source_part.unlink()
candidate_part.unlink()
exec(
    compile(source, "owner_catalog_executor.py", "exec"),
    {
        "__name__": "__main__",
        "__file__": str(Path(__file__)),
        "sanitize_vendor": sanitize_vendor,
    },
)
