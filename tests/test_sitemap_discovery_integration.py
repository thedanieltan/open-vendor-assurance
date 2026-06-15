"""Tier A: sitemap discovery wired into the live scheduled controller.

Proves the full chain the scheduled workflow runs: enabled queue -> bounded
sitemap inspection (zero-weight locator events) -> ORDINARY candidate
verification of each locator -> the EXISTING eligibility classifier ->
eligible/deferred/rejected outcome. Plus the acceptance invariant: a
sitemap-discovered locator cannot, by itself, satisfy materialization gates;
deterministic vendor rotation; idempotent re-runs; and that the scheduled
workflow actually invokes the real command and surfaces its counts.
"""

import json
from pathlib import Path

import pytest
import yaml

from tools.openva.candidate_promotion_actions import validate_materialization_thresholds
from tools.openva.catalog_growth_discovery_queue import (
    QUEUE_PATH,
    SITEMAP_DISCOVERY_MODE,
    main,
    run_sitemap_discovery_command,
    run_sitemap_source_discovery,
    sitemap_discovery_enabled,
)
from tools.openva.discovery_ledger import validate_event
from tools.openva.sitemap_discovery import FetchResult
from tools.openva.source_verification import FetchResult as VerifyFetchResult

VENDOR = {"vendor_id": "vendor", "official_domains": ["vendor.example"]}
RUN = {"discovery_run_id": "run-1", "discovered_at": "2026-06-15T00:00:00Z"}
WORKFLOW = Path(".github/workflows/catalog-growth-discovery.yml")

# A real DPA page: two source-type keywords -> strong semantic match -> a
# confident candidate the eligibility classifier marks strict_promote_ready.
DPA_PAGE = (
    b"<html><head><title>Data Processing Agreement</title></head><body>"
    b"This Data Processing Agreement governs the processor and controller "
    b"relationship for all data processing.</body></html>"
)


def _sitemap_body(*urls: str) -> bytes:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'.encode()


def _sitemap_fetcher(mapping):
    """A SafeFetcher-shaped fetcher serving robots/sitemaps (no network)."""

    def fetch(url):
        spec = mapping.get(url)
        if spec is None:
            return FetchResult(status=404, final_url=url, body=b"")
        return FetchResult(status=200, final_url=url, body=spec)

    return fetch


def _verify_fetcher(pages):
    """An ordinary candidate-verification fetcher serving page bodies."""

    def fetch(url):
        body = pages.get(url)
        if body is None:
            return VerifyFetchResult(
                requested_url=url, final_url=url, http_status=404, content_type="text/html",
                content_length=0, etag=None, last_modified=None, body_sample=b"",
            )
        return VerifyFetchResult(
            requested_url=url, final_url=url, http_status=200, content_type="text/html",
            content_length=len(body), etag=None, last_modified=None, body_sample=body,
        )

    return fetch


def _queue(modes):
    return {"discovery_modes": modes, "limits": {"max_vendors_per_discovery_run": 5}}


def _committed_queue_at(tmp_path):
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(queue), encoding="utf-8")
    return path


# --- per-vendor discovery records --------------------------------------------


def test_enabled_mode_returns_per_vendor_records_with_normalized_events():
    queue = _queue([SITEMAP_DISCOVERY_MODE])
    assert sitemap_discovery_enabled(queue)
    fetcher = _sitemap_fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/trust", "https://vendor.example/security/dpa",
    )})
    records = run_sitemap_source_discovery(queue, [VENDOR], fetcher, **RUN)

    assert len(records) == 1
    record = records[0]
    assert record["vendor_id"] == "vendor"
    assert record["robots_parser"] == "openva-robots.v3"  # corrected evaluator used
    assert "https://vendor.example/trust" in record["locators"]
    assert record["events"], "the enabled mode must produce zero-weight events"
    for event in record["events"]:
        assert validate_event(event) == []  # normalized: valid under the ledger
        assert event["origin"] == "sitemap"
        assert event["classification"] == "unverified_candidate"
        assert "promotion_weight:none" in event["reason_codes"]


def test_disabled_mode_runs_nothing():
    assert run_sitemap_source_discovery(_queue(["seed_file_vendor_discovery"]), [VENDOR], _sitemap_fetcher({}), **RUN) == []


def test_sitemap_locator_alone_cannot_satisfy_materialization():
    # A sitemap candidate is a locator with no retrieval evidence. Feeding it as
    # a materialization action fails closed (no agreeing independent retrievals).
    queue = _queue([SITEMAP_DISCOVERY_MODE])
    fetcher = _sitemap_fetcher({"https://vendor.example/sitemap.xml": _sitemap_body("https://vendor.example/trust")})
    records = run_sitemap_source_discovery(queue, [VENDOR], fetcher, **RUN)
    locator = records[0]["locators"][0]

    action = {
        "vendor": {"candidate_vendor_id": "vendor", "official_domain_candidate": "vendor.example"},
        "source": {
            "candidate_url": locator,
            "evidence": {  # locator only: no matched_terms, no agreeing independent retrievals
                "final_url": locator,
                "name_supported_by_official_domain_metadata": True,
                "source_host_authority": "vendor_controlled",
                "adversarial_review": "clean",
                "evidence_fresh": True,
            },
        },
    }
    with pytest.raises(ValueError) as exc:
        validate_materialization_thresholds(action)
    assert "retrieval_attempts" in str(exc.value)


# --- item 3: end-to-end through the existing candidate lifecycle -------------


def test_end_to_end_locator_reaches_an_eligible_outcome(tmp_path):
    # scheduled entrypoint -> sitemap event -> ordinary verification -> eligible.
    out = tmp_path / "events.json"
    sitemap = _sitemap_fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/legal/dpa",
    )})
    verify = _verify_fetcher({"https://vendor.example/legal/dpa": DPA_PAGE})

    report = run_sitemap_discovery_command(
        queue_path=_committed_queue_at(tmp_path),
        output_path=out,
        discovery_run_id="run-e2e",
        discovered_at="2026-06-15T00:00:00Z",
        vendors=[VENDOR],
        fetcher_factory=lambda _domains: sitemap,
        verify_fetcher_factory=lambda _domain: verify,
    )
    pv = report["per_vendor"][0]
    assert pv["candidate_count"] == 1  # locator discovered
    assert pv["verified_candidate_count"] == 1  # locator fetched + classified into a candidate
    assert pv["eligibility_outcome"] == "strict_promote_ready"  # eligible outcome
    assert report["verification"]["eligibility_outcomes"] == {"strict_promote_ready": 1}
    assert report["robots_parser"] == "openva-robots.v3"
    assert json.loads(out.read_text(encoding="utf-8")) == report


def test_end_to_end_unmatched_locator_is_rejected(tmp_path):
    # A locator whose page does not verify (404) yields no candidate and a
    # rejected eligibility outcome — never a silent promotion.
    out = tmp_path / "events.json"
    sitemap = _sitemap_fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/legal/dpa",
    )})
    verify = _verify_fetcher({})  # the page 404s through ordinary verification

    report = run_sitemap_discovery_command(
        queue_path=_committed_queue_at(tmp_path),
        output_path=out,
        discovery_run_id="run-e2e",
        discovered_at="2026-06-15T00:00:00Z",
        vendors=[VENDOR],
        fetcher_factory=lambda _domains: sitemap,
        verify_fetcher_factory=lambda _domain: verify,
    )
    pv = report["per_vendor"][0]
    assert pv["candidate_count"] == 1
    assert pv["verified_candidate_count"] == 0
    assert pv["eligibility_outcome"] == "reject_no_public_source"


def test_end_to_end_is_idempotent_across_runs(tmp_path):
    sitemap = _sitemap_fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/legal/dpa",
    )})
    verify = _verify_fetcher({"https://vendor.example/legal/dpa": DPA_PAGE})

    def run(run_id, out_name):
        return run_sitemap_discovery_command(
            queue_path=_committed_queue_at(tmp_path),
            output_path=tmp_path / out_name,
            discovery_run_id=run_id,
            discovered_at="2026-06-15T00:00:00Z",
            vendors=[VENDOR],
            fetcher_factory=lambda _domains: sitemap,
            verify_fetcher_factory=lambda _domain: verify,
        )

    a = run("run-1", "a.json")
    b = run("run-1", "b.json")
    assert a == b  # same inputs -> byte-identical report

    # Locator event identity is content-stable, not run-scoped: a different run id
    # produces the SAME discovery_event_ids (so the committed ledger dedups them).
    c = run("run-2", "c.json")
    assert {e["discovery_event_id"] for e in a["events"]} == {e["discovery_event_id"] for e in c["events"]}


# --- item 4: deterministic vendor rotation -----------------------------------


def _fake_vendors(n):
    return [{"vendor_id": f"v{i:03d}", "official_domains": [f"v{i:03d}.example"]} for i in range(n)]


def _week(iso_week):
    # A discovered_at string in ISO week `iso_week` of 2026 (Monday 00:00Z).
    from datetime import date, timedelta

    monday = date.fromisocalendar(2026, iso_week, 1)
    return f"{monday.isoformat()}T00:00:00Z"


def test_rotation_is_bounded_deterministic_and_covers_every_vendor(tmp_path):
    from tools.openva.catalog_growth_discovery_queue import rotation_shard_count, select_rotation_vendors

    vendors = _fake_vendors(60)
    max_vendors = 25
    shard_count = rotation_shard_count(len(vendors), max_vendors)
    assert shard_count == 3  # ceil(60/25)

    covered: set[str] = set()
    for offset in range(shard_count):
        at = _week(10 + offset)  # consecutive weeks within one year (no year seam)
        selected, meta = select_rotation_vendors(vendors, max_vendors=max_vendors, discovered_at=at)
        assert len(selected) <= max_vendors  # every run is bounded
        # Deterministic: the same cycle selects the same vendors on a rerun.
        selected_again, _ = select_rotation_vendors(vendors, max_vendors=max_vendors, discovered_at=at)
        assert [v["vendor_id"] for v in selected] == [v["vendor_id"] for v in selected_again]
        assert meta["selected_vendor_ids"] == [v["vendor_id"] for v in selected]
        covered.update(meta["selected_vendor_ids"])

    assert covered == {v["vendor_id"] for v in vendors}  # full coverage, no starvation


def test_rotation_adding_one_vendor_does_not_reshuffle_the_schedule():
    from tools.openva.catalog_growth_discovery_queue import select_rotation_vendors

    base = _fake_vendors(60)
    grown = base + [{"vendor_id": "v999", "official_domains": ["v999.example"]}]
    at = _week(10)
    before, _ = select_rotation_vendors(base, max_vendors=25, discovered_at=at)
    after, _ = select_rotation_vendors(grown, max_vendors=25, discovered_at=at)
    # No existing vendor leaves the selection when one vendor is appended (the
    # shard_count is unchanged at 3, so stride membership is stable).
    before_ids = {v["vendor_id"] for v in before}
    after_ids = {v["vendor_id"] for v in after}
    assert before_ids <= after_ids
    assert after_ids - before_ids <= {"v999"}


# --- scheduled-path wiring + surfacing ---------------------------------------


def test_scheduled_workflow_invokes_the_real_sitemap_discovery_command():
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = spec["jobs"]["catalog-growth-discovery"]["steps"]
    runs = [step.get("run", "") for step in steps]
    invoking = [r for r in runs if "catalog_growth_discovery_queue run-sitemap-discovery" in r]
    assert invoking, "the scheduled workflow must invoke run-sitemap-discovery"
    command = invoking[0]
    assert "maintenance/queues/catalog-growth-discovery.json" in command
    assert "--discovery-run-id" in command
    assert "--discovered-at" in command
    assert "--output" in command


def test_scheduled_workflow_surfaces_sitemap_counts_in_the_issue_body():
    # The discovery counts/outcomes must reach an established operational surface
    # (the generated GitHub issue), not terminate as an unread artifact.
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = spec["jobs"]["catalog-growth-discovery"]["steps"]
    issue_step = next(s for s in steps if s.get("name") == "Prepare discovery issue body")
    body = issue_step["run"]
    assert "sitemap-source-discovery-events.json" in body
    assert "Sitemap source discovery" in body


def test_committed_queue_has_the_mode_enabled_so_the_command_is_active():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    assert SITEMAP_DISCOVERY_MODE in queue["discovery_modes"]
    assert sitemap_discovery_enabled(queue)


def test_command_entrypoint_emits_events_through_the_real_code_path(tmp_path):
    out = tmp_path / "events.json"
    sitemap = _sitemap_fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/trust", "https://vendor.example/security/dpa",
    )})

    report = run_sitemap_discovery_command(
        queue_path=_committed_queue_at(tmp_path),
        output_path=out,
        discovery_run_id="run-xyz",
        discovered_at="2026-06-15T00:00:00Z",
        vendors=[VENDOR],
        fetcher_factory=lambda _domains: sitemap,
        verify_fetcher_factory=lambda _domain: _verify_fetcher({}),  # no network
    )
    assert report["mode_enabled"] is True
    assert report["event_count"] >= 1
    assert json.loads(out.read_text(encoding="utf-8")) == report
    assert {e["candidate_url"] for e in report["events"]} >= {"https://vendor.example/trust"}
    for event in report["events"]:
        assert validate_event(event) == []


def test_command_entrypoint_is_a_no_op_and_never_fetches_when_mode_disabled(tmp_path):
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    queue["discovery_modes"] = [m for m in queue["discovery_modes"] if m != SITEMAP_DISCOVERY_MODE]
    del queue["mode_capabilities"][SITEMAP_DISCOVERY_MODE]
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    out = tmp_path / "events.json"

    def exploding_factory(_domains):
        raise AssertionError("disabled mode must not construct a fetcher")

    report = run_sitemap_discovery_command(
        queue_path=queue_path,
        output_path=out,
        discovery_run_id="run-0",
        discovered_at="2026-06-15T00:00:00Z",
        vendors=[VENDOR],
        fetcher_factory=exploding_factory,
        verify_fetcher_factory=exploding_factory,
    )
    assert report["mode_enabled"] is False
    assert report["event_count"] == 0
    assert json.loads(out.read_text(encoding="utf-8"))["events"] == []

    # Real CLI entrypoint (argparse) over the same disabled queue: still a no-op.
    import sys

    out2 = tmp_path / "events2.json"
    argv = sys.argv
    sys.argv = [
        "prog", "run-sitemap-discovery",
        "--queue", str(queue_path),
        "--output", str(out2),
        "--discovery-run-id", "run-cli",
        "--discovered-at", "2026-06-15T00:00:00Z",
    ]
    try:
        assert main() == 0
    finally:
        sys.argv = argv
    assert json.loads(out2.read_text(encoding="utf-8"))["mode_enabled"] is False
