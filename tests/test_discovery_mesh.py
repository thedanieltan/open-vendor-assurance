from __future__ import annotations

from tools.openva.discovery_mesh import (
    CrawlLimits,
    aggregate_identity_signals,
    build_discovery_plan,
    classify_locator,
    discover_source_frontier,
    extract_relationship_identity_signals,
    vendor_identity_signal,
)
from tools.openva.source_verification import FetchResult


def fetched(url: str, body: str, *, final_url: str | None = None, status: int = 200) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=final_url or url,
        http_status=status,
        content_type="text/html; charset=utf-8",
        content_length=len(body.encode("utf-8")),
        etag=None,
        last_modified=None,
        body_sample=body.encode("utf-8"),
        error=None,
    )


def missing(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        http_status=404,
        content_type="text/html",
        content_length=0,
        etag=None,
        last_modified=None,
        body_sample=b"",
        error=None,
    )


def mapping_fetcher(mapping: dict[str, FetchResult]):
    def fetch(url: str) -> FetchResult:
        return mapping.get(url, missing(url))

    return fetch


def test_multilingual_locator_classifier_recognizes_non_english_sources() -> None:
    japanese = classify_locator(url="https://example.jp/legal", anchor_text="プライバシーポリシー")
    german = classify_locator(
        url="https://example.de/recht/auftragsverarbeitung",
        anchor_text="Vereinbarung zur Auftragsverarbeitung",
    )
    korean = classify_locator(url="https://example.kr/trust", anchor_text="신뢰 센터")

    assert japanese[0]["source_type"] == "privacy_notice"
    assert german[0]["source_type"] == "dpa"
    assert korean[0]["source_type"] == "trust_center"


def test_source_frontier_crawls_all_official_domains_and_depth_two() -> None:
    vendor = {
        "vendor_id": "example",
        "official_domains": ["example.com", "example.eu"],
        "public_entrypoints": [],
    }
    mapping = {
        "https://example.com/": fetched(
            "https://example.com/",
            '<html><a href="/legal">Legal and privacy</a></html>',
        ),
        "https://www.example.com/": missing("https://www.example.com/"),
        "https://example.eu/": fetched(
            "https://example.eu/",
            '<html><a href="/datenschutz">Datenschutzerklärung</a></html>',
        ),
        "https://www.example.eu/": missing("https://www.example.eu/"),
        "https://example.com/legal": fetched(
            "https://example.com/legal",
            '<html><a href="/legal/data-processing-addendum">Data Processing Addendum</a></html>',
        ),
        "https://example.com/legal/data-processing-addendum": fetched(
            "https://example.com/legal/data-processing-addendum",
            "<html><title>Data Processing Addendum</title></html>",
        ),
        "https://example.eu/datenschutz": fetched(
            "https://example.eu/datenschutz",
            "<html><title>Datenschutzerklärung</title></html>",
        ),
    }

    report = discover_source_frontier(
        vendor,
        mapping_fetcher(mapping),
        limits=CrawlLimits(max_pages=100, max_total_requests=100),
        discovered_at="2026-07-10T08:00:00Z",
    )

    urls = {row["candidate_url"] for row in report["source_locator_signals"]}
    source_types = {row["source_type_candidate"] for row in report["source_locator_signals"]}
    assert report["summary"]["official_domain_count"] == 2
    assert "https://example.com/legal/data-processing-addendum" in urls
    assert "https://example.eu/datenschutz" in urls
    assert "dpa" in source_types
    assert "privacy_notice" in source_types
    assert report["summary"]["pages_attempted"] >= 6


def test_external_trust_center_is_emitted_as_first_party_attested_delegate() -> None:
    vendor = {"vendor_id": "example", "official_domains": ["example.com"]}
    mapping = {
        "https://example.com/": fetched(
            "https://example.com/",
            '<html><a href="https://trust.assurance-host.test/example">Trust Center</a></html>',
        ),
        "https://www.example.com/": missing("https://www.example.com/"),
    }

    report = discover_source_frontier(
        vendor,
        mapping_fetcher(mapping),
        discovered_at="2026-07-10T08:00:00Z",
    )

    delegated = [
        row
        for row in report["source_locator_signals"]
        if row["authority_state"] == "first_party_attested_delegate"
    ]
    assert delegated
    assert delegated[0]["candidate_url"] == "https://trust.assurance-host.test/example"
    assert delegated[0]["requires_verification"] is True
    assert report["summary"]["delegated_host_count"] == 1


def test_default_crawl_limits_are_growth_oriented_but_bounded() -> None:
    limits = CrawlLimits()
    assert limits.max_pages >= 500
    assert limits.max_total_requests >= limits.max_pages
    assert limits.max_locator_candidates >= 1_000
    assert limits.max_depth == 2


def test_relationship_graph_extracts_vendor_identity_signal() -> None:
    source_url = "https://example.com/legal/subprocessors"
    result = fetched(
        source_url,
        '<html><p>Infrastructure provider <a href="https://cloudco.test/">CloudCo</a></p></html>',
    )

    signals = extract_relationship_identity_signals(
        source_url=source_url,
        result=result,
        observed_at="2026-07-10T08:00:00Z",
    )

    assert len(signals) == 1
    assert signals[0]["display_name_observed"] == "CloudCo"
    assert signals[0]["domain_observed"] == "cloudco.test"
    assert signals[0]["admission_weight"] == "none"


def test_identity_aggregation_retains_unresolved_signals_and_combines_demand() -> None:
    signals = [
        vendor_identity_signal(
            observed_name="Unknown Platform",
            source_url="https://example.com/integrations",
            provider="relationship_graph",
            demand_count=2,
            observed_at="2026-07-10T08:00:00Z",
        ),
        vendor_identity_signal(
            observed_name="Unknown Platform",
            source_url="https://directory.test/vendors/unknown-platform",
            provider="public_directory",
            demand_count=3,
            observed_at="2026-07-10T08:00:00Z",
        ),
    ]

    report = aggregate_identity_signals(signals)

    assert report["summary"]["candidate_count"] == 1
    assert report["summary"]["unresolved_candidate_count"] == 1
    candidate = report["vendor_candidates"][0]
    assert candidate["official_domain_candidate"] is None
    assert candidate["demand_count"] == 5
    assert candidate["independent_provider_count"] == 2
    assert report["posture"]["incomplete_signals_retained"] is True


def test_identity_aggregation_skips_existing_domain_collision() -> None:
    signal = vendor_identity_signal(
        observed_name="CloudCo",
        observed_domain="cloudco.test",
        source_url="https://example.com/subprocessors",
        provider="relationship_graph",
        observed_at="2026-07-10T08:00:00Z",
    )

    report = aggregate_identity_signals([signal], known_domains={"cloudco.test"})

    assert report["summary"]["candidate_count"] == 0
    assert report["skipped"][0]["reason"] == "already_materialized"
    assert report["skipped"][0]["collisions"] == ["official_domain"]


def test_discovery_plan_separates_breadth_depth_and_maintenance_budgets() -> None:
    identity_candidates = [
        {
            "candidate_vendor_id": "new-vendor",
            "priority": 50,
            "display_name_candidate": "New Vendor",
        }
    ]
    coverage_queue = [
        {"queue_class": "missing_vendor", "vendor_id": "wishlist-vendor", "priority": 20},
        {
            "queue_class": "missing_source_type",
            "vendor_id": "known-vendor",
            "source_type": "dpa",
            "priority": 40,
        },
        {
            "queue_class": "stale_source",
            "vendor_id": "known-vendor",
            "source_id": "known-dpa",
            "source_type": "dpa",
            "priority": 30,
        },
    ]

    plan = build_discovery_plan(
        coverage_queue=coverage_queue,
        identity_candidates=identity_candidates,
        max_tasks=100,
    )

    assert plan["budgets"] == {"breadth": 45, "depth": 40, "maintenance": 15}
    assert [row["task_type"] for row in plan["queues"]["breadth"]] == [
        "resolve_vendor_identity",
        "discover_vendor_identity",
    ]
    assert plan["queues"]["depth"][0]["task_type"] == "discover_source_frontier"
    assert plan["queues"]["maintenance"][0]["task_type"] == "recheck_source"
    assert plan["summary"]["planned_task_count"] == 4
