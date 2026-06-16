"""Tests for the unified vendor resolution model (resolve-on-use)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.openva import candidate_record, vendor_resolution as vr
from tools.openva.source_verification import FetchResult

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = "2026-06-16T08:30:00Z"


def fixed_now() -> str:
    return FIXED_NOW


def make_catalog(vendor_rows, sources_by_vendor=None):
    return vr.ResolutionCatalog(
        snapshot={"catalog_commit_sha": "abc123", "catalog_generated_at": "1970-01-01T00:00:00Z"},
        vendor_rows=vendor_rows,
        sources_by_vendor=sources_by_vendor or {},
    )


def vendor_row(vendor_id, domain, display=None):
    return {
        "vendor_id": vendor_id,
        "display_name": display or vendor_id.replace("-", " ").title(),
        "legal_name": display or vendor_id,
        "catalog_status": "active",
        "official_domains": [domain],
        "manifest_path": f"dist/vendors/{vendor_id}.json",
    }


def fetch_ok(url, source_type="privacy_notice", final_url=None, status=200, body=None):
    text = body or "privacy policy personal data privacy notice subprocessor data processing security"
    return FetchResult(
        requested_url=url,
        final_url=final_url or url,
        http_status=status,
        content_type="text/html",
        content_length=len(text),
        etag=None,
        last_modified=None,
        body_sample=f"<title>Doc</title>{text}".encode("utf-8"),
    )


def fetcher_map(mapping):
    def _fetch(url):
        if url not in mapping:
            raise AssertionError(f"unexpected fetch of {url}")
        return mapping[url]

    return _fetch


def discovery_found(domain, source_type, fetcher, observed_at):
    return vr.DiscoveryResult(
        candidate_url=f"https://{domain}/{source_type}",
        final_url=f"https://{domain}/{source_type}",
        http_status=200,
        content_type="text/html",
        verification_status="ok",
        matched_terms=["privacy", "personal data"],
        observed_at=observed_at,
        on_vendor_domain=True,
    )


def discovery_none(domain, source_type, fetcher, observed_at):
    return None


# 1. Existing vendor with current source.
def test_existing_vendor_current_source():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok", "2026-06-01T00:00:00Z")]},
    )
    url = "https://examplecloud.com/privacy"
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({url: fetch_ok(url)}),
        discovery=discovery_none,
        now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_CATALOG_CURRENT
    source = result.sources[0]
    assert source.status == vr.RESULT_CATALOG_CURRENT
    assert source.origin == "catalog"
    assert source.catalog_status == vr.RESULT_CATALOGUED
    assert vr.validate_result(result.to_response()) == []


# 2. Existing vendor with stale source (cached mode reports stored state only).
def test_existing_vendor_stale_source_cached():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/dpa", "stale", "2026-01-01T00:00:00Z")]},
    )
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "cached"},
        catalog=catalog,
        now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert source.live_checked is False


# 3. Existing vendor with redirected replacement.
def test_existing_vendor_redirected_replacement():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok", "2026-06-01T00:00:00Z")]},
    )
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}),
        discovery=discovery_none,
        now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_CATALOG_REFRESHED
    source = result.sources[0]
    assert source.status == vr.RESULT_CATALOG_REFRESHED
    assert source.source_url == new
    assert source.previous_source_url == old
    assert source.origin == "live_discovery"
    assert source.catalog_status == vr.RESULT_CANDIDATE_PROCESSING
    assert vr.validate_result(result.to_response()) == []


# 4. Existing vendor with missing source type.
def test_existing_vendor_missing_source_type():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok")]},
    )
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog=catalog,
        discovery=discovery_found,
        now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_NEWLY_DISCOVERED
    assert source.catalog_status == vr.RESULT_CANDIDATE_PROCESSING
    assert len(result.candidates) == 1
    assert result.candidates[0]["candidate_origin"] == "coverage_gap"


# 5. Missing vendor with sources discovered.
def test_missing_vendor_sources_discovered():
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        discovery=discovery_found,
        now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_NEWLY_DISCOVERED
    assert result.sources[0].status == vr.RESULT_NEWLY_DISCOVERED
    assert result.candidates[0]["candidate_origin"] == "catalog_discovery"


# 6. Missing vendor with no sources found.
def test_missing_vendor_no_sources_found():
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "Ghost", "domain": "ghost.example"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        discovery=discovery_none,
        now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_NOT_FOUND
    assert result.sources[0].status == vr.RESULT_NOT_FOUND
    assert result.candidates == []


# 7. Ambiguous vendor identity.
def test_identity_ambiguous():
    catalog = make_catalog(
        [vendor_row("acme-one", "acme.example", "Acme"), vendor_row("acme-two", "acme-two.example", "Acme")]
    )
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "Acme"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_IDENTITY_AMBIGUOUS
    assert set(result.identity_candidates) == {"acme-one", "acme-two"}
    assert vr.validate_result(result.to_response()) == []


# 8. Candidate already in processing.
def test_candidate_already_in_processing():
    emitter = vr.SessionEmitter()
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")])
    request = {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"}
    first = vr.resolve_vendor_sources(request, catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now)
    second = vr.resolve_vendor_sources(request, catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now)
    assert len(emitter.candidates) == 1
    assert first.candidates[0]["candidate_id"] == second.candidates[0]["candidate_id"]


# 9. Duplicate requests remain idempotent.
def test_duplicate_requests_idempotent():
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")])
    inv = vr.resolve_inventory(
        [{"vendor_name": "NewVendor", "domain": "newvendor.com"}, {"vendor_name": "NewVendor", "domain": "newvendor.com"}],
        ["privacy_notice"],
        catalog=catalog,
        discovery=discovery_found,
        now=fixed_now,
    )
    assert len(inv["candidates"]) == 1


# 10 + 11. Old URL superseded; historical source-reference metadata preserved.
def test_history_supersedes_and_preserves_reference():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa-old", "dpa", "https://examplecloud.com/old-dpa", "ok", "2026-06-10T12:00:00Z")]},
    )
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}),
        discovery=discovery_none,
        now=fixed_now,
    )
    history = result.sources[0].history
    assert history["current_source"]["url"] == new
    prev = history["previous_sources"][0]
    assert prev["url"] == old
    assert prev["status"] == "superseded"
    assert prev["last_observed_at"] == "2026-06-10T12:00:00Z"
    assert prev["superseded_by"] == history["current_source"]["source_id"]


# 12. No historical document content is stored.
def test_no_historical_document_content():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok")]},
    )
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}),
        discovery=discovery_none,
        now=fixed_now,
    )
    blob = json.dumps(result.to_response()).lower()
    for forbidden in ("document_content", "extracted_text", "clause", "full_text", "body_text", "raw_document"):
        assert forbidden not in blob


# 13. Cached mode does not claim live verification.
def test_cached_mode_no_live_verification():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok", "2026-06-01T00:00:00Z")]},
    )
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "cached"},
        catalog=catalog,
        now=fixed_now,
    )
    source = result.sources[0]
    assert source.live_checked is False
    assert source.checked_at != FIXED_NOW
    assert source.checked_at == "2026-06-01T00:00:00Z"


# 14. Verify mode records current observation time.
def test_verify_mode_records_observation_time():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok")]},
    )
    url = "https://examplecloud.com/privacy"
    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({url: fetch_ok(url)}),
        discovery=discovery_none,
        now=fixed_now,
    )
    source = result.sources[0]
    assert source.live_checked is True
    assert source.checked_at == FIXED_NOW


# 15. Human CSV export includes result state.
def test_csv_export_includes_result_state():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok", "2026-06-01T00:00:00Z")]},
    )
    inv = vr.resolve_inventory(
        [{"vendor_name": "ExampleCloud", "domain": "examplecloud.com"}],
        ["privacy_notice"],
        catalog=catalog,
        freshness_mode="cached",
        now=fixed_now,
    )
    row = inv["csv_rows"][0]
    assert "result_state" in row
    assert row["result_state"] == vr.RESULT_CATALOG_CURRENT
    assert "result_state" in vr.CSV_COLUMNS


# 16. Agent response includes source origin and freshness status.
def test_agent_response_includes_origin_and_freshness():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok")]},
    )
    url = "https://examplecloud.com/privacy"
    response = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({url: fetch_ok(url)}),
        discovery=discovery_none,
        now=fixed_now,
    ).to_response()
    assert response["freshness_mode"] == "verify"
    assert response["snapshot"]["catalog_commit_sha"] == "abc123"
    source = response["sources"][0]
    assert source["origin"] == "catalog"
    assert source["live_checked"] is True
    assert source["checked_at"] == FIXED_NOW
    assert source["catalog_status"] == vr.RESULT_CATALOGUED


# 17. Live resolution does not write directly to canonical catalogue data.
def test_live_resolution_does_not_mutate_catalog():
    sources = {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok")]}
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")], sources)
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}),
        discovery=discovery_none,
        now=fixed_now,
    )
    # The catalogue view the resolver read is unchanged; replacement lives only
    # as a candidate, never written to canonical data.
    assert catalog.sources_for("examplecloud")[0].source_url == old
    assert not hasattr(catalog, "write")


# 18. Existing autonomous promotion and release gates remain authoritative.
def test_candidates_route_through_existing_evaluator():
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        discovery=discovery_found,
        now=fixed_now,
    )
    candidate = result.candidates[0]
    # Valid candidate record, eligibility decided by the shared evaluator.
    assert candidate_record.validate_candidate(candidate) == []
    assert candidate["eligibility_state"] in candidate_record.ELIGIBILITY_STATES
    assert candidate["candidate_origin"] in candidate_record.CANDIDATE_ORIGINS
    # Live discovery never claims canonical status; only the lifecycle can.
    for source in result.sources:
        if source.origin == "live_discovery":
            assert source.catalog_status != vr.RESULT_CATALOGUED


# 19. Invalid or unsafe URLs fail closed.
def test_unsafe_url_fails_closed():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "http://localhost/dpa", "ok")]},
    )

    def exploding_fetcher(url):
        raise AssertionError("unsafe URL must never be fetched")

    result = vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog=catalog,
        fetcher=exploding_fetcher,
        discovery=discovery_none,
        now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert "unsafe_url_not_fetched" in source.reasons


# 20. The result schema validates produced responses (round-trip contract).
def test_result_schema_round_trips():
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    response = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "Ghost", "domain": "ghost.example"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog,
        discovery=discovery_none,
        now=fixed_now,
    ).to_response()
    assert vr.validate_result(response) == []
    schema = json.loads((ROOT / "schemas" / "openva" / "vendor-resolution-result.schema.json").read_text())
    assert schema["$id"].endswith("vendor-resolution-result.schema.json")
