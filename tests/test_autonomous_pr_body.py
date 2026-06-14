"""WP40C Issue 13: autonomous catalog PR bodies are machine evidence, no checklist."""

from __future__ import annotations

from tools.openva import autonomous_pr_body as apb
from tools.openva.advisory_wording import load_prohibited_terms, prohibited_terms_in_text


def _candidate():
    return {
        "candidate_origin": "human_submission",
        "candidate_id": "cand-human-submission-issue-501",
        "evidence_digest": "sha256:" + "a" * 64,
        "decision_reasons": ["usable_assurance_sources=2"],
    }


def _decision():
    return {
        "decision_id": "acme-materialize",
        "deciding_bot": "strict-growth-materializer",
        "discovery_bot": "catalog-growth-discovery",
        "not_before": "2026-06-16T00:00:00Z",
        "candidate_digest": "sha256:" + "a" * 64,
        "reversal": {"method": "remove", "reference": "revert-acme-materialize"},
    }


def _body():
    return apb.from_candidate_and_decision(
        _candidate(), _decision(),
        automerge_lane="automerge:machine-provisional",
        changed_paths=["data/vendors/acme/vendor.yaml", "maintenance/machine-decisions/2026-06.ndjson"],
        release_gate_status="pass",
    )


def test_body_contains_all_required_machine_evidence():
    text = apb.render(_body())
    for needle in (
        "Candidate origin", "`human_submission`",
        "Candidate ID", "`cand-human-submission-issue-501`",
        "Decision ID", "`acme-materialize`",
        "Evidence digest", "sha256:",
        "Separation of duty", "Release gate", "`pass`",
        "Not before", "`2026-06-16T00:00:00Z`",
        "Automerge lane", "`automerge:machine-provisional`",
        "Reversal reference", "`revert-acme-materialize`",
        "Machine-proven conditions", "usable_assurance_sources=2",
        "Changed paths", "`data/vendors/acme/vendor.yaml`",
    ):
        assert needle in text, needle


def test_body_has_no_human_checklist():
    text = apb.render(_body())
    assert not apb.contains_human_checklist(text)


def test_separation_of_duty_pass_and_fail():
    ok = apb.render(_body())
    assert "**pass**" in ok
    bad = _decision()
    bad["discovery_bot"] = bad["deciding_bot"]
    body = apb.from_candidate_and_decision(
        _candidate(), bad, automerge_lane="x", changed_paths=[], release_gate_status="pass"
    )
    assert "**FAIL**" in apb.render(body)


def test_body_is_non_advisory():
    text = apb.render(_body())
    assert prohibited_terms_in_text(text, load_prohibited_terms()) == []


def test_body_is_deterministic():
    assert apb.render(_body()) == apb.render(_body())
    assert apb.render(_body()).startswith(apb.BODY_MARKER)
