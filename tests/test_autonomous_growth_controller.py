"""WP40A Issue 3: scheduled autonomous growth controller decides one cycle.

Updated for WP-OPENVA-CANDIDATE-ACTIVATION-01: the controller now binds the
selected candidate (recomputes eligibility + identity from the persisted record)
before authorising a cycle, so candidates are full schema-valid records, not
eligibility-state stubs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tools.openva import autonomous_growth_controller as agc
from tools.openva import candidate_record as cr

NOW = datetime(2026, 6, 14, tzinfo=UTC)
LANE = "catalog_growth_promotion"


def _live_state(**overrides):
    state = {
        "lane_id": LANE,
        "state_source": "github_live",
        "open_prs": [],
        "recent_bot_prs": {"day_count": 0, "week_count": 0},
        "pause": {"active": False},
        "evidence": {"generated_at": "2026-06-14T00:00:00Z"},
    }
    state.update(overrides)
    return state


def _candidate(ref, *, on_domain=True, created_at="2026-06-10T00:00:00Z", country="US"):
    """A full, schema-valid candidate record the controller can recompute."""
    identity = {
        "vendor_id_candidate": ref,
        "vendor_name": ref.replace("-", " ").title(),
        "official_domain": f"{ref}.example",
        "headquarters_country": country,
    }
    sources = [
        {
            "candidate_url": f"https://{ref}.example/dpa",
            "final_url": f"https://{ref}.example/dpa",
            "http_status": 200,
            "source_type_candidate": "dpa",
            "access_state": "public_reachable",
            "source_role": "primary_assurance",
            "on_vendor_domain": on_domain,
        }
    ]
    evidence = [{"candidate_url": f"https://{ref}.example/dpa", "verification_result": "ok", "observed_at": created_at}]
    state, reasons = cr.evaluate_eligibility(identity, sources, is_new_vendor=True)
    record = cr.build_candidate(
        candidate_origin="catalog_discovery",
        origin_reference=ref,
        vendor_identity_candidate=identity,
        source_candidates=sources,
        evidence_references=evidence,
        discovery_component="vendor-resolution:catalog_discovery",
        created_at=created_at,
        eligibility_state=state,
        decision_reasons=reasons,
    )
    record["candidate_path"] = f"maintenance/candidates/{record['candidate_id']}.json"
    return record


def test_authorises_one_cycle_with_one_candidate():
    candidate = _candidate("cand-a")
    result = agc.decide_cycle(_live_state(), [candidate], now=NOW)
    assert result["proceed"] is True
    assert result["max_vendors_this_cycle"] == 1
    assert result["selected_candidate_id"] == candidate["candidate_id"]
    binding = result["selected_candidate"]
    assert binding["candidate_id"] == candidate["candidate_id"]
    assert binding["candidate_path"] == candidate["candidate_path"]
    assert binding["selected_vendor"] == "cand-a"
    assert binding["content_digest"].startswith("sha256:")


def test_selects_oldest_eligible_deterministically():
    cands = [
        _candidate("cand-new", created_at="2026-06-12T00:00:00Z"),
        _candidate("cand-old", created_at="2026-06-01T00:00:00Z"),
        _candidate("cand-mid", created_at="2026-06-05T00:00:00Z"),
    ]
    result = agc.decide_cycle(_live_state(), cands, now=NOW)
    oldest = next(c for c in cands if c["origin_reference"] == "cand-old")
    assert result["selected_candidate_id"] == oldest["candidate_id"]
    assert result["selected_candidate"]["selected_vendor"] == "cand-old"


def test_never_more_than_one_vendor_per_cycle():
    cands = [_candidate(f"cand-{i}") for i in range(5)]
    result = agc.decide_cycle(_live_state(), cands, now=NOW)
    assert result["max_vendors_this_cycle"] == 1


def test_fallback_state_blocks_growth():
    result = agc.decide_cycle(_live_state(fallback_state=True), [_candidate("cand-a")], now=NOW)
    assert result["proceed"] is False
    assert result["state_authoritative"] is False


def test_hold_blocks_growth():
    result = agc.decide_cycle(_live_state(pause={"active": True}), [_candidate("cand-a")], now=NOW)
    assert result["proceed"] is False
    assert result["queue_decision"] == "pause"


def test_reserved_capacity_yields_to_integrity_work():
    result = agc.decide_cycle(
        _live_state(open_prs=[]), [_candidate("cand-a")], now=NOW,
        pending_integrity_work=True, total_pr_budget=3, open_prs_total=2,
    )
    assert result["proceed"] is False
    assert result["reason"] == "reserved_capacity_held_for_integrity_work"


def test_no_eligible_candidate_defers():
    # An off-domain candidate recomputes to deferred, never eligible.
    result = agc.decide_cycle(_live_state(), [_candidate("cand-a", on_domain=False)], now=NOW)
    assert result["proceed"] is False
    assert result["reason"] == "no_eligible_candidate"


def test_eligibility_mismatch_fails_closed():
    # A forged candidate: off-domain (truly deferred) but stamped "eligible".
    candidate = _candidate("cand-forged", on_domain=False)
    candidate["eligibility_state"] = "eligible"
    result = agc.decide_cycle(_live_state(), [candidate], now=NOW)
    assert result["proceed"] is False
    assert result["reason"] == "candidate_eligibility_mismatch"
    assert result["selected_candidate"] is None
    assert result.get("candidate_mismatch_reasons")
