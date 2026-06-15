"""Tier A: sitemap discovery wired into the live scheduled controller.

Proves: the scheduled workflow invokes the real run-sitemap-discovery command;
that command (queue with the mode enabled) -> bounded sitemap inspection ->
normalized discovery event (valid under the existing ledger) -> unified
candidate path. And the acceptance invariant: a sitemap-discovered locator
cannot, by itself, satisfy materialization gates.
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

VENDOR = {"vendor_id": "vendor", "official_domains": ["vendor.example"]}
RUN = {"discovery_run_id": "run-1", "discovered_at": "2026-06-15T00:00:00Z"}
WORKFLOW = Path(".github/workflows/catalog-growth-discovery.yml")


def _sitemap_body(*urls: str) -> bytes:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'.encode()


def _fetcher(mapping):
    def fetch(url):
        spec = mapping.get(url)
        if spec is None:
            return FetchResult(status=404, final_url=url, body=b"")
        return FetchResult(status=200, final_url=url, body=spec)

    return fetch


def _queue(modes):
    return {"discovery_modes": modes, "limits": {"max_vendors_per_discovery_run": 5}}


def test_enabled_mode_runs_sitemap_inspection_and_emits_normalized_candidate_events():
    queue = _queue([SITEMAP_DISCOVERY_MODE])
    assert sitemap_discovery_enabled(queue)
    fetcher = _fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/trust", "https://vendor.example/security/dpa",
    )})
    events = run_sitemap_source_discovery(queue, [VENDOR], fetcher, **RUN)

    assert events, "the enabled mode must actually produce candidate events"
    urls = {e["candidate_url"] for e in events}
    assert "https://vendor.example/trust" in urls  # unified candidate path
    for event in events:
        assert validate_event(event) == []  # normalized: valid under the ledger
        assert event["origin"] == "sitemap"
        assert event["classification"] == "unverified_candidate"
        assert "promotion_weight:none" in event["reason_codes"]


def test_disabled_mode_runs_nothing():
    assert run_sitemap_source_discovery(_queue(["seed_file_vendor_discovery"]), [VENDOR], _fetcher({}), **RUN) == []


def test_sitemap_locator_alone_cannot_satisfy_materialization():
    # A sitemap candidate is a locator with no retrieval evidence. Feeding it as
    # a materialization action fails closed (no agreeing independent retrievals).
    queue = _queue([SITEMAP_DISCOVERY_MODE])
    fetcher = _fetcher({"https://vendor.example/sitemap.xml": _sitemap_body("https://vendor.example/trust")})
    events = run_sitemap_source_discovery(queue, [VENDOR], fetcher, **RUN)
    locator = events[0]["candidate_url"]

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


# --- scheduled-path wiring (blocker 1/5) ------------------------------------


def test_scheduled_workflow_invokes_the_real_sitemap_discovery_command():
    # The scheduled controller must actually call the command, against the
    # committed queue, not merely document an integration.
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = spec["jobs"]["catalog-growth-discovery"]["steps"]
    runs = [step.get("run", "") for step in steps]
    invoking = [
        r for r in runs
        if "catalog_growth_discovery_queue run-sitemap-discovery" in r
    ]
    assert invoking, "the scheduled workflow must invoke run-sitemap-discovery"
    command = invoking[0]
    assert "maintenance/queues/catalog-growth-discovery.json" in command
    assert "--discovery-run-id" in command
    assert "--discovered-at" in command
    assert "--output" in command


def test_committed_queue_has_the_mode_enabled_so_the_command_is_active():
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    assert SITEMAP_DISCOVERY_MODE in queue["discovery_modes"]
    assert sitemap_discovery_enabled(queue)


def test_command_entrypoint_emits_events_through_the_real_code_path(tmp_path):
    # Drive the exact function main() calls, with an injected per-vendor fetcher
    # factory (no network), proving the scheduled entrypoint materializes events
    # and writes the report.
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    out = tmp_path / "events.json"

    fetcher = _fetcher({"https://vendor.example/sitemap.xml": _sitemap_body(
        "https://vendor.example/trust", "https://vendor.example/security/dpa",
    )})

    report = run_sitemap_discovery_command(
        queue_path=queue_path,
        output_path=out,
        discovery_run_id="run-xyz",
        discovered_at="2026-06-15T00:00:00Z",
        vendors=[VENDOR],
        fetcher_factory=lambda domains: fetcher,
    )
    assert report["mode_enabled"] is True
    assert report["event_count"] >= 1
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == report
    assert {e["candidate_url"] for e in on_disk["events"]} >= {"https://vendor.example/trust"}
    for event in on_disk["events"]:
        assert validate_event(event) == []


def test_command_entrypoint_is_a_no_op_and_never_fetches_when_mode_disabled(tmp_path):
    # Remove the sitemap mode from a committed-shaped queue; the command must do
    # no network I/O (the factory would raise if touched) and write an empty
    # report. Also exercised through the real argparse entrypoint.
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
