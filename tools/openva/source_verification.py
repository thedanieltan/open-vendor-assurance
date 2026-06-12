from __future__ import annotations

import argparse
import json
import re
import ssl
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

from tools.openva.hash import sha256_bytes, sha256_normalized_text
from tools.openva.paths import display_path as normalized_display_path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "source-verification-report.json"
USER_AGENT = "OpenVA-SourceVerifier/0.1 (+https://github.com/thedanieltan/open-vendor-assurance)"
MAX_SAMPLE_BYTES = 131_072

SOURCE_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dpa": (
        "data processing",
        "data processing addendum",
        "data processing agreement",
        "dpa",
        "processor",
        "controller",
    ),
    "subprocessors_list": (
        "subprocessor",
        "sub-processors",
        "sub-processor",
        "sub processors",
        "third party processors",
        "service providers",
    ),
    "privacy_notice": (
        "privacy",
        "personal data",
        "personal information",
        "privacy policy",
        "privacy notice",
    ),
    "security_page": (
        "security",
        "encryption",
        "availability",
        "vulnerability",
        "incident",
        "trust",
    ),
    "compliance_page": (
        "compliance",
        "certification",
        "soc",
        "iso",
        "audit",
        "trust",
    ),
    "kyc_aml_statement": (
        "kyc",
        "aml",
        "anti-money laundering",
        "know your customer",
        "sanctions",
    ),
}

BOT_PROTECTION_HINTS = (
    "captcha",
    "cloudflare",
    "checking your browser",
    "verify you are human",
    "attention required",
    "access denied",
    "bot protection",
    "security check",
)

LOGIN_GATE_HINTS = (
    "login",
    "log in",
    "sign in",
    "signin",
    "customer portal",
    "trust portal",
    "request access",
    "authentication required",
    "credentials required",
)

SOFT_NOT_FOUND_TITLE_PREFIXES = (
    "404",
    "404 error",
    "page not found",
    "not found",
)

SOFT_NOT_FOUND_BODY_HINTS = (
    "404 error",
    "there's nothing here",
    "there’s nothing here",
    "page not found",
    "the page you are looking for",
    "we can't find that page",
    "we can’t find that page",
    "this page does not exist",
)

SUSPECT_TEMPLATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"/legal/data-processing-addendum/?$",
        r"/data-processing-addendum/?$",
        r"/legal/dpa/?$",
        r"/dpa/?$",
        r"/legal/subprocessors/?$",
        r"/subprocessors/?$",
        r"/legal/sub-processors/?$",
        r"/security#compliance$",
        r"/security/#compliance$",
        r"/security/compliance/?$",
        r"/trust/?$",
        r"/trustcenter/compliance/?$",
    )
)


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    http_status: int | None
    content_type: str | None
    content_length: int | None
    etag: str | None
    last_modified: str | None
    body_sample: bytes
    error: str | None = None


def display_path(path: Path, root: Path = ROOT) -> str:
    return normalized_display_path(path, root)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{display_path(path)}: expected YAML mapping")
    return data


def source_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "data" / "vendors").glob("*/sources/*.yaml"))


def load_source_path_file(path: Path, root: Path = ROOT) -> list[Path]:
    rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    selected: list[Path] = []
    for row in rows:
        if not row or row.startswith("#"):
            continue
        candidate = Path(row)
        if not candidate.is_absolute():
            candidate = root / candidate
        selected.append(candidate)
    return sorted(selected)


def select_source_shard(paths: list[Path], shard_count: int | None, shard_index: int | None) -> list[Path]:
    if shard_count is None and shard_index is None:
        return paths
    if shard_count is None or shard_index is None:
        raise ValueError("--shard-count and --shard-index must be provided together")
    if shard_count <= 0:
        raise ValueError("--shard-count must be positive")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("--shard-index must be >= 0 and < --shard-count")
    return [path for offset, path in enumerate(paths) if offset % shard_count == shard_index]


def normalize_text(data: bytes, content_type: str | None) -> str:
    if not data:
        return ""
    if content_type and "pdf" in content_type.lower():
        return ""
    text = data.decode("utf-8", errors="ignore")
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def title_from_sample(data: bytes, content_type: str | None) -> str | None:
    if content_type and "pdf" in content_type.lower():
        return None
    raw = data.decode("utf-8", errors="ignore")
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def lower_sample(result: FetchResult) -> str:
    title = title_from_sample(result.body_sample, result.content_type) or ""
    body = normalize_text(result.body_sample, result.content_type)
    final_url = result.final_url or ""
    return " ".join([title, body, final_url]).lower()


def looks_like_bot_challenge(result: FetchResult) -> bool:
    sample = lower_sample(result)
    return any(hint in sample for hint in BOT_PROTECTION_HINTS)


def looks_like_login_gate(result: FetchResult) -> bool:
    sample = lower_sample(result)
    return any(hint in sample for hint in LOGIN_GATE_HINTS)


def looks_like_soft_not_found(result: FetchResult) -> bool:
    if result.content_type and "pdf" in result.content_type.lower():
        return False
    title = (title_from_sample(result.body_sample, result.content_type) or "").strip().lower()
    normalized_title = re.sub(r"\s+", " ", title).strip(" -|:")
    if any(
        normalized_title == hint or normalized_title.startswith(f"{hint} ")
        for hint in SOFT_NOT_FOUND_TITLE_PREFIXES
    ):
        return True
    body_prefix = normalize_text(result.body_sample, result.content_type)[:1500]
    if any(hint in body_prefix for hint in SOFT_NOT_FOUND_BODY_HINTS):
        return True
    return False


def semantic_match(source_type: str | None, text: str, content_type: str | None) -> dict[str, Any]:
    if content_type and "pdf" in content_type.lower():
        return {
            "status": "not_evaluated_pdf_sample",
            "matched_terms": [],
        }
    keywords = SOURCE_TYPE_KEYWORDS.get(str(source_type or ""), ())
    if not keywords:
        return {
            "status": "not_evaluated_unknown_source_type",
            "matched_terms": [],
        }
    matched = [keyword for keyword in keywords if keyword in text]
    if len(matched) >= 2:
        status = "strong"
    elif len(matched) == 1:
        status = "weak"
    else:
        status = "mismatch"
    return {"status": status, "matched_terms": matched}


def looks_like_homepage_redirect(source: dict[str, Any], final_url: str) -> bool:
    requested = str(source.get("source_url") or "").rstrip("/")
    final = final_url.rstrip("/")
    if requested == final:
        return False
    parsed = urlparse(final)
    if parsed.path in {"", "/"}:
        return True
    source_type = str(source.get("source_type") or "")
    if source_type in {"dpa", "subprocessors_list"} and parsed.path in {"/legal", "/privacy", "/security"}:
        return True
    return False


def has_suspect_template_path(url: str) -> bool:
    parsed = urlparse(url)
    path_and_fragment = parsed.path
    if parsed.fragment:
        path_and_fragment = f"{path_and_fragment}#{parsed.fragment}"
    return any(pattern.search(path_and_fragment) for pattern in SUSPECT_TEMPLATE_PATTERNS)


def fetch_url(url: str, timeout: float = 10.0) -> FetchResult:
    context = ssl.create_default_context()
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read(MAX_SAMPLE_BYTES)
            return FetchResult(
                requested_url=url,
                final_url=response.geturl(),
                http_status=response.status,
                content_type=response.headers.get("content-type"),
                content_length=_int_or_none(response.headers.get("content-length")),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                body_sample=body,
            )
    except HTTPError as exc:
        body = exc.read(MAX_SAMPLE_BYTES) if exc.fp else b""
        return FetchResult(
            requested_url=url,
            final_url=exc.geturl(),
            http_status=exc.code,
            content_type=exc.headers.get("content-type") if exc.headers else None,
            content_length=_int_or_none(exc.headers.get("content-length")) if exc.headers else None,
            etag=exc.headers.get("etag") if exc.headers else None,
            last_modified=exc.headers.get("last-modified") if exc.headers else None,
            body_sample=body,
            error=f"http_error:{exc.code}",
        )
    except (TimeoutError, URLError, OSError) as exc:
        return FetchResult(
            requested_url=url,
            final_url=url,
            http_status=None,
            content_type=None,
            content_length=None,
            etag=None,
            last_modified=None,
            body_sample=b"",
            error=type(exc).__name__,
        )


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def classify_status(source: dict[str, Any], result: FetchResult, semantic: dict[str, Any]) -> str:
    status = result.http_status
    if status is None:
        return "unreachable"
    if status == 401:
        return "gated_or_login_required"
    if status == 403:
        if looks_like_bot_challenge(result):
            return "bot_protected"
        if looks_like_login_gate(result):
            return "gated_or_login_required"
        return "forbidden_unknown"
    if status == 429:
        return "rate_limited"
    if status == 404:
        return "not_found"
    if status == 410:
        return "gone"
    if status >= 500:
        return "server_error"
    if status >= 400:
        return "client_error"
    if looks_like_soft_not_found(result):
        return "soft_not_found"
    if looks_like_homepage_redirect(source, result.final_url):
        return "homepage_or_generic_redirect"
    if semantic.get("status") == "mismatch":
        return "possible_mismatch"
    if has_suspect_template_path(str(source.get("source_url") or "")) and semantic.get("status") in {"weak", "mismatch"}:
        return "suspect_inferred_url"
    if result.final_url.rstrip("/") != str(source.get("source_url") or "").rstrip("/"):
        return "redirected"
    return "ok"


def sample_hashes(result: FetchResult) -> dict[str, str]:
    # Hashes of the fetched 128KB sample, not the full document. Field names
    # carry the "sample" scope so downstream consumers cannot misread them.
    if not result.body_sample:
        return {
            "raw_sample_sha256": "sha256:TBD",
            "normalized_text_sample_sha256": "sha256:TBD",
        }
    raw = sha256_bytes(result.body_sample)
    if result.content_type and "pdf" in result.content_type.lower():
        normalized = "sha256:TBD"
    else:
        normalized = sha256_normalized_text(result.body_sample, result.content_type)
    return {
        "raw_sample_sha256": raw,
        "normalized_text_sample_sha256": normalized,
    }


def verify_source(
    source: dict[str, Any],
    path: Path,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    root: Path = ROOT,
) -> dict[str, Any]:
    url = str(source.get("source_url") or "")
    result = fetcher(url)
    text = normalize_text(result.body_sample, result.content_type)
    semantic = semantic_match(str(source.get("source_type") or ""), text, result.content_type)
    status = classify_status(source, result, semantic)
    hashes = sample_hashes(result)

    return {
        "path": display_path(path, root),
        "vendor_id": source.get("vendor_id"),
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "source_url": url,
        "final_url": result.final_url,
        "http_status": result.http_status,
        "content_type": result.content_type,
        "content_length": result.content_length,
        "etag": result.etag,
        "last_modified": result.last_modified,
        "title_detected": title_from_sample(result.body_sample, result.content_type),
        "fetch_error": result.error,
        "raw_sample_sha256": hashes["raw_sample_sha256"],
        "normalized_text_sample_sha256": hashes["normalized_text_sample_sha256"],
        "semantic_match": semantic,
        "soft_404_detected": status == "soft_not_found",
        "verification_status": status,
        "requires_review": status not in {"ok", "redirected"},
        "non_advisory": True,
    }


def build_source_verification_report(
    root: Path = ROOT,
    fetcher: Callable[[str], FetchResult] = fetch_url,
    limit: int | None = None,
    shard_count: int | None = None,
    shard_index: int | None = None,
    source_path_file: Path | None = None,
) -> dict[str, Any]:
    verifications: list[dict[str, Any]] = []
    failures: list[str] = []
    all_paths = source_paths(root)
    paths = load_source_path_file(source_path_file, root=root) if source_path_file else all_paths
    paths = select_source_shard(paths, shard_count, shard_index)
    if limit is not None:
        paths = paths[:limit]

    for path in paths:
        try:
            source = load_yaml(path)
            verifications.append(verify_source(source, path, fetcher=fetcher, root=root))
        except Exception as exc:  # noqa: BLE001 - report generation should continue per source.
            failures.append(f"{display_path(path, root)}: {type(exc).__name__}: {exc}")

    status_counter = Counter(item["verification_status"] for item in verifications)
    type_counter = Counter(str(item.get("source_type") or "unknown") for item in verifications)
    vendors_by_status: dict[str, set[str]] = defaultdict(set)
    for item in verifications:
        vendor_id = item.get("vendor_id")
        if vendor_id:
            vendors_by_status[item["verification_status"]].add(str(vendor_id))

    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "report_type": "source_verification_report",
        "posture": {
            "network_fetch_performed": True,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "public_sources_only": True,
            "non_advisory": True,
        },
        "scope": {
            "total_source_paths": len(all_paths),
            "candidate_source_paths": len(load_source_path_file(source_path_file, root=root)) if source_path_file else len(all_paths),
            "verified_source_paths": len(paths),
            "source_path_file": display_path(source_path_file, root) if source_path_file else None,
            "limit": limit,
            "shard_count": shard_count,
            "shard_index": shard_index,
            "is_partial": len(paths) != len(all_paths) or source_path_file is not None,
        },
        "summary": {
            "source_count": len(verifications),
            "sources_requiring_review": sum(1 for item in verifications if item["requires_review"]),
            "parse_or_fetch_pipeline_failures": len(failures),
        },
        "breakdowns": {
            "verification_statuses": dict(sorted(status_counter.items())),
            "source_types": dict(sorted(type_counter.items())),
            "vendors_by_status": {
                status: sorted(vendors) for status, vendors in sorted(vendors_by_status.items())
            },
        },
        "failures": failures,
        "sources": verifications,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="openva-source-verification")
    parser.add_argument("command", choices={"verify"})
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--source-path-file", type=Path)
    parser.add_argument("--fail-on-review", action="store_true")
    args = parser.parse_args()

    report = build_source_verification_report(
        limit=args.limit,
        shard_count=args.shard_count,
        shard_index=args.shard_index,
        source_path_file=args.source_path_file,
    )
    write_report(report, args.output)
    print(json.dumps(report["scope"], indent=2, sort_keys=True))
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(json.dumps(report["breakdowns"].get("verification_statuses", {}), indent=2, sort_keys=True))

    if args.fail_on_review and (
        report["summary"]["sources_requiring_review"]
        or report["summary"]["parse_or_fetch_pipeline_failures"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
