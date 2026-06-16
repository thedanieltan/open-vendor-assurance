"""Tests for the unified vendor resolution model (resolve-on-use)."""

from __future__ import annotations

import json
import subprocess
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


def git_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "tester"], check=True)
    return path


def committed_emitter(tmp_path):
    """An emitter whose candidates are committed to git (GitHub-durable)."""
    return vr.SessionEmitter(vr.CatalogQueueIngress(git_repo(tmp_path), commit=True))


def resolve(request, catalog, emitter=None, **kwargs):
    if emitter is not None:
        kwargs["emitter"] = emitter
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
        catalog, emitter=committed_emitter(tmp_path),
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
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
        catalog, emitter=committed_emitter(tmp_path), discovery=discovery_found, now=fixed_now,
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
        catalog, emitter=committed_emitter(tmp_path), discovery=discovery_found, now=fixed_now,
    )
    assert result.resolution_status == vr.RESULT_NEWLY_DISCOVERED
    assert all(s.status == vr.RESULT_NEWLY_DISCOVERED for s in result.sources)
    assert len(result.candidate_updates) == 1
    assert result.candidate_updates[0]["candidate_origin"] == "catalog_discovery"


# 6. Missing vendor with no sources found.
def test_missing_vendor_no_sources_found(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "Ghost", "domain": "ghost.example"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, emitter=committed_emitter(tmp_path), discovery=discovery_none, now=fixed_now,
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


# 8. Candidate already in processing (durable+committed, idempotent across calls).
def test_candidate_already_in_processing(tmp_path):
    emitter = committed_emitter(tmp_path)
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")])
    request = {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"}
    vr.resolve_vendor_sources(request, catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now)
    second = vr.resolve_vendor_sources(request, catalog=catalog, discovery=discovery_found, emitter=emitter, now=fixed_now)
    queue_files = list((tmp_path / "maintenance" / "candidates").glob("*.json"))
    assert len(queue_files) == 1
    assert len(emitter.candidate_updates) == 1
    assert second.candidate_updates[0]["committed"] is True
    assert second.sources[0].catalog_status == vr.LIFECYCLE_PROCESSING


# 9. Duplicate requests remain idempotent (durable queue holds one record).
def test_duplicate_requests_idempotent(tmp_path):
    catalog = make_catalog([vendor_row("examplecloud", "examplecloud.com")])
    inv = vr.resolve_inventory(
        [{"vendor_name": "NewVendor", "domain": "newvendor.com"}, {"vendor_name": "NewVendor", "domain": "newvendor.com"}],
        ["privacy_notice"], catalog=catalog, discovery=discovery_found,
        ingress=vr.CatalogQueueIngress(git_repo(tmp_path), commit=True), now=fixed_now,
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
        catalog, emitter=committed_emitter(tmp_path),
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
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
        catalog, emitter=committed_emitter(tmp_path),
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
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
        catalog, emitter=vr.SessionEmitter(vr.CatalogQueueIngress(tmp_path)),
        fetcher=fetcher_map({old: fetch_ok(old, final_url=new)}), discovery=discovery_none, now=fixed_now,
    )
    assert catalog.sources_for("examplecloud")[0].source_url == old
    assert not (tmp_path / "data").exists()
    assert list((tmp_path / "maintenance" / "candidates").glob("*.json"))


# 18. Candidates route through the existing evaluator and durable ingress.
def test_candidates_route_through_existing_evaluator(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, emitter=vr.SessionEmitter(vr.CatalogQueueIngress(tmp_path)), discovery=discovery_found, now=fixed_now,
    )
    queue_file = next((tmp_path / "maintenance" / "candidates").glob("*.json"))
    record = json.loads(queue_file.read_text())
    assert candidate_record.validate_candidate(record) == []
    assert record["eligibility_state"] in candidate_record.ELIGIBILITY_STATES
    assert record["candidate_origin"] in candidate_record.CANDIDATE_ORIGINS
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
        catalog, emitter=committed_emitter(tmp_path), discovery=discovery_found, now=fixed_now,
    ).to_response()
    assert vr.validate_result(response) == []
    assert response["candidate_updates"][0]["committed"] is True


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
        catalog, emitter=committed_emitter(tmp_path),
        fetcher=fetcher_map({old: fetch_ok(old, final_url=home)}), discovery=discovery_none, now=fixed_now,
    )
    assert result.sources[0].status == vr.RESULT_VERIFICATION_INCONCLUSIVE


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
        catalog, emitter=committed_emitter(tmp_path),
        fetcher=fetcher_map({old: fetch_ok(old, final_url=away)}), discovery=discovery_none, now=fixed_now,
    )
    assert result.sources[0].status == vr.RESULT_VERIFICATION_INCONCLUSIVE


# 23. A rejected candidate is never reported as processing toward the catalogue.
def test_rejected_candidate_not_processing(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "Loopback", "domain": "localhost"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, emitter=committed_emitter(tmp_path), discovery=discovery_found, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert source.catalog_status == vr.LIFECYCLE_REJECTED
    update = result.candidate_updates[0]
    assert update["lifecycle_state"] == vr.LIFECYCLE_REJECTED
    assert update["eligibility_state"] == "rejected_unsafe_url"


# 24. A deferred candidate is verification_inconclusive with the URL exposed only
#     as an unverified candidate_url (not the resolved source_url).
def test_deferred_candidate_is_inconclusive_with_candidate_url(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = resolve(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog, emitter=committed_emitter(tmp_path), discovery=discovery_offdomain, now=fixed_now,
    )
    source = result.sources[0]
    assert source.status == vr.RESULT_VERIFICATION_INCONCLUSIVE
    assert source.catalog_status == vr.LIFECYCLE_DEFERRED
    assert source.source_url is None
    assert source.candidate_url == "https://cdn.other.example/privacy_notice"


# 25. Non-durable (read-only) ingress never claims processing.
def test_non_durable_ingress_does_not_claim_processing():
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    result = vr.resolve_vendor_sources(
        {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog, discovery=discovery_found, now=fixed_now,  # default RecordingIngress
    )
    assert result.sources[0].catalog_status == vr.LIFECYCLE_PENDING
    update = result.candidate_updates[0]
    assert update["persisted"] is False
    assert update["committed"] is False


# 26 (blocker 1). A persisted-but-uncommitted candidate stays pending_ingress;
#                 only a committed candidate is candidate_processing.
def test_uncommitted_candidate_is_pending_committed_is_processing(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    req = {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"}

    uncommitted = resolve(req, catalog, emitter=vr.SessionEmitter(vr.CatalogQueueIngress(tmp_path / "wt")), discovery=discovery_found, now=fixed_now)
    assert (tmp_path / "wt" / "maintenance" / "candidates").exists()
    assert uncommitted.sources[0].catalog_status == vr.LIFECYCLE_PENDING
    assert uncommitted.candidate_updates[0]["persisted"] is True
    assert uncommitted.candidate_updates[0]["committed"] is False

    committed = resolve(req, catalog, emitter=committed_emitter(tmp_path / "repo"), discovery=discovery_found, now=fixed_now)
    assert committed.sources[0].catalog_status == vr.LIFECYCLE_PROCESSING
    assert committed.candidate_updates[0]["committed"] is True


# 27 (blocker 2). The default fetcher is the SSRF-safe one: it refuses
#                 loopback/private/link-local targets without fetching them.
def test_default_fetcher_rejects_ssrf():
    fetcher = vr.default_fetcher_factory(["example.com"])
    for url in ("http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1/"):
        result = fetcher(url)
        assert result.http_status is None
        assert result.error


# 27b (blocker 2). The resolver builds the per-vendor fetcher via the factory,
#                  bound to the vendor's official domain.
def test_resolver_binds_safe_fetcher_to_official_domain():
    catalog = make_catalog(
        [vendor_row("examplecloud", "examplecloud.com")],
        {"examplecloud": [vr.CatalogSource("examplecloud-privacy", "privacy_notice", "https://examplecloud.com/privacy", "ok")]},
    )
    calls = []

    def spy_factory(domains):
        calls.append(list(domains))
        return fetcher_map({"https://examplecloud.com/privacy": fetch_ok("https://examplecloud.com/privacy")})

    vr.resolve_vendor_sources(
        {"vendor": {"domain": "examplecloud.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"},
        catalog=catalog, fetcher_factory=spy_factory, discovery=discovery_none, now=fixed_now,
    )
    assert calls == [["examplecloud.com"]]


# 28 (blocker 4). Expanded discovery merges into the persisted candidate;
#                 newly discovered sources are never silently discarded.
def test_aggregate_candidate_merges_expanded_sources(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    ingress = vr.CatalogQueueIngress(tmp_path)
    base = {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "freshness_mode": "verify"}

    # First request discovers only privacy_notice.
    resolve({**base, "required_source_types": ["privacy_notice"]}, catalog,
            emitter=vr.SessionEmitter(ingress), discovery=discovery_found, now=fixed_now)
    # A later request (separate session, same queue) discovers an extra type.
    second = resolve({**base, "required_source_types": ["privacy_notice", "dpa"]}, catalog,
                     emitter=vr.SessionEmitter(ingress), discovery=discovery_found, now=fixed_now)

    queue_file = next((tmp_path / "maintenance" / "candidates").glob("*.json"))
    record = json.loads(queue_file.read_text())
    types = sorted(s["source_type_candidate"] for s in record["source_candidates"])
    assert types == ["dpa", "privacy_notice"]  # nothing discarded
    # The response reflects the authoritative persisted (merged) record.
    assert candidate_record.validate_candidate(record) == []
    assert len(second.candidate_updates) == 1


# 29 (blocker 4). The persisted record is authoritative across sessions.
def test_persisted_record_is_authoritative(tmp_path):
    catalog = make_catalog([vendor_row("stripe", "stripe.com")])
    ingress = vr.CatalogQueueIngress(tmp_path)
    req = {"vendor": {"vendor_name": "NewVendor", "domain": "newvendor.com"}, "required_source_types": ["privacy_notice"], "freshness_mode": "verify"}
    first = resolve(req, catalog, emitter=vr.SessionEmitter(ingress), discovery=discovery_found, now=fixed_now)
    again = resolve(req, catalog, emitter=vr.SessionEmitter(ingress), discovery=discovery_found, now=fixed_now)
    cid_first = first.candidate_updates[0]["candidate_id"]
    cid_again = again.candidate_updates[0]["candidate_id"]
    assert cid_first == cid_again
    assert again.candidate_updates[0]["persisted"] is True
