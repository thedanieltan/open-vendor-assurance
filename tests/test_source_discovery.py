import json
from pathlib import Path

import yaml

from tools.openva.source_discovery import (
    build_discovery_report,
    build_vendor_candidate_discovery_report,
    candidate_source_id,
    discover_for_vendor,
)
from tools.openva.source_verification import FetchResult


def fetcher_for(matches: dict[str, str]):
    def fetch(url: str) -> FetchResult:
        body = matches.get(url, "not found")
        status = 200 if url in matches else 404
        return FetchResult(
            requested_url=url,
            final_url=url,
            http_status=status,
            content_type="text/html; charset=utf-8",
            content_length=len(body),
            etag=None,
            last_modified=None,
            body_sample=body.encode("utf-8"),
        )

    return fetch


def vendor_record() -> dict:
    return {
        "schema_version": "0.1.0",
        "vendor_id": "example",
        "display_name": "Example",
        "legal_name": "Example Inc.",
        "headquarters_country": "US",
        "official_domains": ["example.com"],
        "public_entrypoints": ["https://www.example.com/privacy", "https://www.example.com/security"],
        "source_policy": {
            "public_sources_only": True,
            "gated_materials_excluded": True,
            "raw_documents_mirrored_by_default": False,
        },
        "status": "active",
    }


def vendor_candidate_report(rows: list[dict]) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_type": "vendor_candidate_discovery_report",
        "vendor_candidates": rows,
    }


def vendor_candidate(vendor_id="candidate-a", domain="candidate-a.example") -> dict:
    return {
        "candidate_vendor_id": vendor_id,
        "display_name_candidate": "Candidate A",
        "official_domain_candidate": domain,
        "coverage_lane": "security",
        "cohort_id": "security-001",
        "source_index_url": f"https://{domain}",
        "requires_review": True,
        "writes_canonical_vendors": False,
        "non_advisory": True,
    }


def write_vendor(root: Path, vendor: dict) -> None:
    path = root / "data/vendors" / vendor["vendor_id"] / "vendor.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(vendor, sort_keys=False), encoding="utf-8")


def test_discovery_finds_candidate_from_official_domain():
    vendor = vendor_record()
    url = "https://www.example.com/legal/data-processing-addendum"

    result = discover_for_vendor(
        vendor,
        root=Path("/tmp/nonexistent-openva-root"),
        fetcher=fetcher_for({url: "Data Processing Addendum processor controller"}),
        source_types=("dpa",),
    )

    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["candidate_url"] == url
    assert result["candidates"][0]["source_type_candidate"] == "dpa"
    assert result["candidates"][0]["requires_review"] is True
    assert result["candidates"][0]["confidence"] == "likely"
    assert result["candidates"][0]["evidence"]["verification_status"] == "ok"
    assert result["unavailable_sources"] == []


def test_discovery_records_homepage_redirect_verification_status():
    vendor = vendor_record()
    url = "https://www.example.com/security"

    def fetch(_url: str) -> FetchResult:
        body = "Security encryption availability vulnerability"
        return FetchResult(
            requested_url=url,
            final_url="https://www.example.com/",
            http_status=200,
            content_type="text/html; charset=utf-8",
            content_length=len(body),
            etag=None,
            last_modified=None,
            body_sample=body.encode("utf-8"),
        )

    result = discover_for_vendor(
        vendor,
        root=Path("/tmp/nonexistent-openva-root"),
        fetcher=fetch,
        source_types=("security_page",),
    )

    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["evidence"]["verification_status"] == "homepage_or_generic_redirect"
    assert result["observations"][0]["verification_status"] == "homepage_or_generic_redirect"


def test_discovery_records_unavailable_when_no_candidate_matches():
    vendor = vendor_record()

    result = discover_for_vendor(
        vendor,
        root=Path("/tmp/nonexistent-openva-root"),
        fetcher=fetcher_for({}),
        source_types=("subprocessors_list",),
    )

    assert result["candidates"] == []
    assert len(result["unavailable_sources"]) == 1
    unavailable = result["unavailable_sources"][0]
    assert unavailable["source_type"] == "subprocessors_list"
    assert unavailable["status"] == "not_identified"
    assert unavailable["reason"] == "distinct_public_url_not_identified"
    assert unavailable["not_advice"] is True
    assert unavailable["candidate_urls_checked"]


def test_discovery_skips_existing_canonical_source_type(tmp_path):
    vendor = vendor_record()
    write_vendor(tmp_path, vendor)
    source_dir = tmp_path / "data/vendors/example/sources"
    source_dir.mkdir(parents=True)
    (source_dir / "example-dpa.yaml").write_text(
        "schema_version: 0.1.0\n"
        "source_id: example-dpa\n"
        "vendor_id: example\n"
        "source_type: dpa\n"
        "title_native: Example DPA\n"
        "source_url: https://www.example.com/legal/dpa\n"
        "source_language: en\n"
        "access_class: public_web\n"
        "rights_class: metadata_only\n"
        "provenance:\n"
        "  publisher: vendor\n"
        "  collected_at: '2026-05-16T00:00:00Z'\n"
        "  observer: human\n"
        "  confidence: medium\n"
        "not_advice: true\n",
        encoding="utf-8",
    )

    result = discover_for_vendor(
        vendor,
        root=tmp_path,
        fetcher=fetcher_for(
            {"https://www.example.com/legal/data-processing-addendum": "Data Processing Addendum processor controller"}
        ),
        source_types=("dpa",),
    )

    assert result["candidates"] == []
    assert result["unavailable_sources"] == []


def test_discovery_write_mode_writes_only_candidate_and_unavailable_records(tmp_path):
    vendor = vendor_record()
    write_vendor(tmp_path, vendor)

    report = build_discovery_report(
        root=tmp_path,
        fetcher=fetcher_for(
            {"https://www.example.com/privacy": "Privacy policy personal data"}
        ),
        write=True,
    )

    assert report["posture"]["writes_repository_state"] is True
    assert report["posture"]["writes_canonical_sources"] is False
    assert list((tmp_path / "data/vendors/example/sources").glob("*.yaml")) == []
    assert list((tmp_path / "data/vendors/example/candidate_sources").glob("*.yaml"))
    assert list((tmp_path / "data/vendors/example/unavailable_sources").glob("*.yaml"))


def test_vendor_candidate_mode_discovers_sources_without_writing_catalog(tmp_path):
    url = "https://candidate-a.example/security"
    report = build_vendor_candidate_discovery_report(
        vendor_candidate_report([vendor_candidate()]),
        root=tmp_path,
        fetcher=fetcher_for({url: "Security encryption SOC 2 compliance"}),
        source_types=("security_page",),
    )

    assert report["discovery_context"] == "vendor_candidate_source_discovery"
    assert report["posture"]["writes_repository_state"] is False
    assert report["summary"]["vendor_candidates_checked"] == 1
    assert report["summary"]["candidate_sources_written_or_reported"] == 1
    candidate = report["vendors"][0]["candidates"][0]
    assert candidate["vendor_id"] == "candidate-a"
    assert candidate["candidate_url"] == url
    assert candidate["confidence"] == "likely"


def test_vendor_candidate_mode_respects_vendor_limit(tmp_path):
    report = build_vendor_candidate_discovery_report(
        vendor_candidate_report([
            vendor_candidate("candidate-a", "candidate-a.example"),
            vendor_candidate("candidate-b", "candidate-b.example"),
        ]),
        root=tmp_path,
        fetcher=fetcher_for({}),
        vendor_limit=1,
        source_types=("security_page",),
    )

    assert report["summary"]["vendor_candidates_checked"] == 1
    assert report["vendors"][0]["vendor_id"] == "candidate-a"


def test_discovery_ranks_strong_candidate_after_weak_first_hit():
    vendor = vendor_record()
    weak = "https://www.example.com/legal/data-processing-addendum"
    strong = "https://www.example.com/data-processing-addendum"

    result = discover_for_vendor(
        vendor,
        root=Path("/tmp/nonexistent-openva-root"),
        fetcher=fetcher_for(
            {
                weak: "processor",
                strong: "Data Processing Addendum processor controller",
            }
        ),
        source_types=("dpa",),
        max_urls_per_type=2,
    )

    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["candidate_url"] == strong
    assert candidate["confidence"] == "likely"
    assert candidate["selection"]["rank_reason"] == "strong_same_authority_canonical_url"
    assert candidate["selection"]["alternative_candidate_count"] == 1
    assert not candidate["candidate_source_id"].endswith("-candidate")
    assert len(result["observations"]) == 2


def test_due_unavailable_source_type_is_rediscovered(tmp_path):
    vendor = vendor_record()
    write_vendor(tmp_path, vendor)
    unavailable_dir = tmp_path / "data/vendors/example/unavailable_sources"
    unavailable_dir.mkdir(parents=True, exist_ok=True)
    (unavailable_dir / "example-dpa.yaml").write_text(
        "schema_version: 0.1.0\n"
        "unavailable_source_id: example-dpa\n"
        "vendor_id: example\n"
        "source_type: dpa\n"
        "status: not_identified\n"
        "next_review_after: '2000-01-01'\n"
        "not_advice: true\n",
        encoding="utf-8",
    )

    result = discover_for_vendor(
        vendor,
        root=tmp_path,
        fetcher=fetcher_for(
            {"https://www.example.com/legal/data-processing-addendum": "Data Processing Addendum processor controller"}
        ),
        source_types=("dpa",),
        max_urls_per_type=1,
    )

    assert len(result["candidates"]) == 1
    assert result["unavailable_sources"] == []


def test_registry_discovers_trust_center_and_status_page():
    vendor = vendor_record()
    result = discover_for_vendor(
        vendor,
        root=Path("/tmp/nonexistent-openva-root"),
        fetcher=fetcher_for(
            {
                "https://www.example.com/trust": "Trust center security compliance privacy",
                "https://status.example.com": "Status uptime incident operational availability",
            }
        ),
        source_types=("trust_center", "status_page"),
        max_urls_per_type=20,
    )

    found = {candidate["source_type_candidate"]: candidate for candidate in result["candidates"]}
    assert found["trust_center"]["candidate_url"] == "https://www.example.com/trust"
    assert found["status_page"]["candidate_url"] == "https://status.example.com"


def test_write_discovery_outputs_appends_discovery_event_ledger(tmp_path):
    vendor = vendor_record()
    write_vendor(tmp_path, vendor)
    discovery = discover_for_vendor(
        vendor,
        root=tmp_path,
        fetcher=fetcher_for({"https://www.example.com/security": "Security encryption availability vulnerability"}),
        source_types=("security_page",),
        max_urls_per_type=1,
    )

    from tools.openva.discovery_ledger import append_events
    from tools.openva.source_discovery import write_discovery_outputs

    write_discovery_outputs(discovery, root=tmp_path)
    assert not (tmp_path / "maintenance/discovery-events").exists()

    append_events(discovery["discovery_events"], tmp_path / "maintenance/discovery-events")
    event_files = sorted((tmp_path / "maintenance/discovery-events").glob("*.ndjson"))
    assert len(event_files) == 1
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines()]
    assert events[0]["candidate_id"] == discovery["candidates"][0]["candidate_source_id"]
    assert events[0]["evidence_digest"].startswith("sha256:")
    assert events[0]["discovery_event_id"]


def test_candidate_source_id_normalizes_equivalent_urls():
    first = candidate_source_id("example", "privacy_notice", "HTTPS://Example.TEST:443/privacy/?utm_source=x#top")
    second = candidate_source_id("example", "privacy_notice", "https://example.test/privacy")

    assert first == second
