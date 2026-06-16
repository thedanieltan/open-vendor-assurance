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


def fetch_ok(url, final_url=None, status=200, body=None):
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


def discovery_offdomain(domain, source_type, fetcher, observed_at):
    return vr.DiscoveryResult(
        candidate_url=f"https://cdn.other.example/{source_type}",
        final_url=f"https://cdn.other.example/{source_type}",
        http_status=200,
        content_type="text/html",
        verification_status="ok",
        matched_terms=["privacy", "personal data"],
        observed_at=observed_at,
        on_vendor_domain=False,
    )


def discovery_none(domain, source_type, fetcher, observed_at):
    return None


def durable_emitter(tmp_path):
    return vr.SessionEmitter(vr.CatalogQueueIngress(tmp_path))


def resolve(request, catalog, tmp_path=None, **kwargs):
    if tmp_path is not None:
        kwargs.setdefault("emitter", durable_emitter(tmp_path))
    return vr.resolve_vendor_sources(request, catalog=catalog, **kwargs)


# 1. Existing vendor with current source.
def test_existing_vendor_current_source():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok", "2026-06-01T00:00:00Z")]},
    )
    url = "https://examplecloud.com/privacy"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, fetcher=fetcher_map({url: fetch_ok(url)}), discovery=discovery_none, now=fixed_now,
    )
    source = result.sources[0]
    assert result.resolution_status == vr.RESULT_CATALOG_CURRENT
    assert source.status == vr.RESULT_CATALOG_CURRENT
    assert source.origin == "catalog"
    assert source.catalog_membership == "canonical"
    assert source.catalog_status == vr.LIFECYCLE_CATALOGUED
    assert vr.validate_result(result.to_response()) == []


# 2. Existing vendor with stale source: catalogue membership is independent of health.
def test_existing_vendor_stale_source_cached():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/dpa", "stale", "2026-01-01T00:00:00Z")]},
    )
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "cached"},
        catalog, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert source.live_checked is False
    # A stale source is still a canonical, catalogued record.
    assert source.catalog_membership == "canonical"
    assert source.catalog_status == vr.LIFECYCLE_CATALOGUED


# 3. Existing vendor with redirected (on-authority) replacement.
def test_existing_vendor_redirected_replacement(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok", "2026-06-01T00:00:00Z")]},
    )
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
    )
    source = result.sources[0]
    assert result.resolution_status == vr.RESULT_CATALOG_REFRESHED
    assert source.status == vr.RESULT_CATALOG_REFRESHED
    assert source.source_url == new
    assert source.previous_source_url == old
    assert source.origin == "live_discovery"
    assert source.catalog_membership == "none"
    assert source.catalog_status == vr.LIFECYCLE_PROCESSING
    assert vr.validate_result(result.to_response()) == []


# 4. Existing vendor with missing source type (independent coverage_gap candidate).
def test_existing_vendor_missing_source_type(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok")]},
    )
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_found, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_NEWLY_DISCOVERED
    assert source.catalog_status == vr.LIFECYCLE_PROCESSING
    assert len(result.candidate_updates) == 1
    assert result.candidate_updates[0]["candidate_origin"] == "coverage_gap"


# 5. Missing vendor with sources discovered -> ONE aggregate candidate.
def test_missing_vendor_sources_discovered_aggregated(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice", "security_page"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_found, now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_NEWLY_DISCOVERED
    assert all(s.status == vr.RESULT_NEWLY_DISCOVERED for s in result.sources)
    # New vendor materialises from one candidate carrying its full discovery set.
    assert len(result.candidate_updates) == 1
    assert result.candidate_updates[0]["candidate_origin"] == "catalog_discovery"


# 6. Missing vendor with no sources found.
def test_missing_vendor_no_sources_found(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "Ghost", "domain": "ghost.example"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_none, now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_NOT_FOUND
    assert result.sources[0].status == vr.RESULT_NOT_FOUND
    assert result.candidate_updates == []


# 7. Ambiguous vendor identity.
def test_identity_ambiguous():
    catalog = make_catalog(
        [vendor_row("acme-one", "acme.example", "Acme"), vendor_row("acme-two", "acme-two.example", "Acme")]
    )
    result = resolve(
        {"vendor": {"vendor_name": "Acme"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_IDENTITY_AMBIGUOUS
    assert set(result.identity_candidates) == {"acme-one", "acme-two"}
    assert vr.validate_result(result.to_response()) == []


# 8. Candidate already in processing (durable, idempotent across calls).
def test_candidate_already_in_processing(tmp_path):
    emitter = durable_emitter(tmp_path)
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")])
    request = {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"}
    vr.resolve_vendor_sources(request, catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now)
    vr.resolve_vendor_sources(request, catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now)
    queue_files = list((tmp_path / "maintenance" / "candidates").glob("*.json"))
    assert len(queue_files) == 1
    assert len(emitter.candidate_updates) == 1


# 9. Duplicate requests remain idempotent (durable queue holds one record).
def test_duplicate_requests_idempotent(tmp_path):
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")])
    inv = vr.resolve_inventory(
        [{"vendor_name": "NewVendor", "domain": "newvendor.com"}, {"vendor_name": "NewVendor", "domain": "newvendor.com"}],
        ["privacy_notice"], catalog=catalog, discovery=discovery_found,
        ingress=vr.CatalogQueueIngress(tmp_path), now=fixed_now,
    )
    assert len(inv["candidate_updates"]) == 1
    assert len(list((tmp_path / "maintenance" / "candidates").glob("*.json"))) == 1


# 10 + 11. Proposed history supersedes old URL and preserves the reference.
def test_history_supersedes_and_preserves_reference(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa-old", "dpa", "https://examplecloud.com/old-dpa", "ok", "2026-06-10T12:00:00Z")]},
    )
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
    )
    history = result.sources[0].proposed_source_history
    assert history["current_source"]["url"] == new
    prev = history["previous_sources"][0]
    assert prev["url"] == old
    assert prev["status"] == "superseded"
    assert prev["last_observed_at"] == "2026-06-10T12:00:00Z"
    assert prev["superseded_by"] == history["current_source"]["source_id"]


# 12. No historical document content is stored.
def test_no_historical_document_content(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok")]},
    )
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
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
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "cached"},
        catalog, now=fixed_now,
    )
    source = result.sources[0]
    assert source.live_checked is False
    assert source.checked_at == "2026-06-01T00:00:00Z"
    assert source.checked_at != FIXED_NOW


# 14. Verify mode records current observation time.
def test_verify_mode_records_observation_time():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok")]},
    )
    url = "https://examplecloud.com/privacy"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, fetcher=fetcher_map({url: fetch_ok(url)}), discovery=discovery_none, now=fixed_now,
    )
    source = result.sources[0]
    assert source.live_checked is True
    assert source.checked_at == FIXED_NOW


# 15. Human CSV export includes result state.
def test_csv_export_includes_result_state(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok", "2026-06-01T00:00:00Z")]},
    )
    inv = vr.resolve_inventory(
        [{"vendor_name": "ExampleCloud", "domain": "examplecloud.com"}],
        ["privacy_notice"], catalog=catalog, freshness_mode="cached",
        ingress=vr.CatalogQueueIngress(tmp_path), now=fixed_now,
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
    response = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, fetcher=fetcher_map({url: fetch_ok(url)}), discovery=discovery_none, now=fixed_now,
    ).to_response()
    assert response["freshness_mode"] == "verify"
    assert response["snapshot"]["catalog_commit_sha"] == "abc123"
    source = response["sources"][0]
    assert source["origin"] == "catalog"
    assert source["catalog_membership"] == "canonical"
    assert source["live_checked"] is True
    assert source["checked_at"] == FIXED_NOW
    assert source["catalog_status"] == vr.LIFECYCLE_CATALOGUED


# 17. Live resolution does not write canonical data; durable ingress is isolated.
def test_live_resolution_does_not_mutate_catalog(tmp_path):
    sources = {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok")]}
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")], sources)
    old = "https://examplecloud.com/old-dpa"
    new = "https://examplecloud.com/legal/dpa"
    resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
    )
    # Catalogue view unchanged; the only write is into the candidate queue.
    assert catalog.sources_for("examplecloud")[0].source_url == old
    assert not (tmp_path / "data").exists()
    assert list((tmp_path / "maintenance" / "candidates").glob("*.json"))


# 18. Candidates route through the existing evaluator and durable ingress.
def test_candidates_route_through_existing_evaluator(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    emitter = durable_emitter(tmp_path)
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now,
    )
    # The durably enqueued record is a valid candidate with evaluator-decided state.
    queue_file = next((tmp_path / "maintenance" / "candidates").glob("*.json"))
    record = json.loads(queue_file.read_text())
    assert candidate_record.validate_candidate(record) == []
    assert record["eligibility_state"] in candidate_record.ELIGIBILITY_STATES
    assert record["candidate_origin"] in candidate_record.CANDIDATE_ORIGINS
    # Live discovery never claims canonical status; only the lifecycle can.
    for source in result.sources:
        if source.origin == "live_discovery":
            assert source.catalog_status != vr.LIFECYCLE_CATALOGUED


# 19. Invalid or unsafe URLs fail closed.
def test_unsafe_url_fails_closed():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "http://localhost/dpa", "ok")]},
    )

    def exploding_fetcher(url):
        raise AssertionError("unsafe URL must never be fetched")

    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, fetcher=exploding_fetcher, discovery=discovery_none, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert "unsafe_url_not_fetched" in source.reasons


# 20. The result schema validates produced responses (round-trip contract).
def test_result_schema_round_trips(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    response = resolve(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice", "dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_found, now=fixed_now,
    ).to_response()
    assert vr.validate_result(response) == []
    assert response["candidate_updates"][0]["durable"] is True


# 21. A generic/homepage redirect is NOT returned as a refreshed source.
def test_generic_redirect_not_refreshed(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok")]},
    )
    old = "https://examplecloud.com/old-dpa"
    home = "https://examplecloud.com/"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, fetcher=fetcher_map({old: fetch_ok(old, final_url=home)}), discovery=discovery_none, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert source.status != vr.RESULT_CATALOG_REFRESHED


# 22. An off-domain redirect is NOT returned as a refreshed source.
def test_offdomain_redirect_not_refreshed(tmp_path):
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-dpa", "dpa", "https://examplecloud.com/old-dpa", "ok")]},
    )
    old = "https://examplecloud.com/old-dpa"
    away = "https://evil.example/dpa"
    result = resolve(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["dpa"], "freshness_mode": "verify"},
        catalog, tmp_path, fetcher=fetcher_map({old: fetch_ok(old, final_url=away)}), discovery=discovery_none, now=fixed_now,
    )
    assert result.sources[0].status == vr.RESULT_VERIFICATION_INCONCLUSIVE


# 23. A rejected candidate is never reported as processing toward the catalogue.
def test_rejected_candidate_not_processing(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    # Unsafe official domain -> evaluator returns rejected_unsafe_url.
    result = resolve(
        {"vendor": {"vendor_name": "Loopback", "domain": "localhost"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_found, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert source.catalog_status == vr.LIFECYCLE_REJECTED
    update = result.candidate_updates[0]
    assert update["lifecycle_state"] == vr.LIFECYCLE_REJECTED
    assert update["eligibility_state"] == "rejected_unsafe_url"


# 24. A deferred candidate keeps its URL but discloses the deferred lifecycle.
def test_deferred_candidate_discloses_lifecycle(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_offdomain, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_NEWLY_DISCOVERED
    assert source.catalog_status == vr.LIFECYCLE_DEFERRED


# 25. Non-durable (read-only) ingress never claims processing.
def test_non_durable_ingress_does_not_claim_processing():
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog, discovery=discovery_found, now=fixed_now,  # default RecordingIngress
    )
    assert result.sources[0].catalog_status == vr.LIFECYCLE_PENDING
    assert result.candidate_updates[0]["durable"] is False


# 26. The durable queue record is readable back with its eligibility state.
def test_durable_queue_record_is_persisted(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    resolve(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, tmp_path, discovery=discovery_found, now=fixed_now,
    )
    queue_file = next((tmp_path / "maintenance" / "candidates").glob("*.json"))
    record = json.loads(queue_file.read_text())
    assert record["eligibility_state"] == "eligible"
    assert record["candidate_origin"] == "catalog_discovery"
    assert record["discovery_component"].startswith("vendor_resolution:")
