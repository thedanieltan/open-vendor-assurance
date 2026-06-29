from __future__ import annotations

import inspect
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tools.openva import assurance_projection
from tools.openva.assurance_projection import (
    ASSURANCE_CHANGE_EVENT_OUTPUT_INVALID,
    ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS,
    ASSURANCE_CHANGE_EVENT_TIME_INVALID,
    ASSURANCE_PROJECTION_DATETIME_NAIVE,
    ASSURANCE_PROJECTION_DIFF_INCOMPATIBLE,
    ASSURANCE_PROJECTION_DIFF_INPUT_INVALID,
    ASSURANCE_PROJECTION_DIFF_NON_MONOTONIC,
    AssuranceProjectionError,
    change_event_id_for_manifest,
    diff_assurance_projections,
    event_identity_manifest,
)
from tools.openva.schema_registry import ROOT, build_openva_validator

PROJECTION_ROOT = ROOT / "tests/fixtures/assurance/projection"
CHANGE_EVENT_SCHEMA = ROOT / "schemas/openva/assurance-change-event.schema.json"
SHA256_A = "sha256:" + "a" * 64
SHA256_B = "sha256:" + "b" * 64


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_projection(name: str) -> dict[str, Any]:
    path = PROJECTION_ROOT / "projection-valid" / name / "expectations.json"
    return deepcopy(load_json(path)["expected_projection"])


def noop_projection(name: str) -> dict[str, Any]:
    path = PROJECTION_ROOT / "semantic-no-op-rebuild" / "expectations.json"
    return deepcopy(load_json(path)[name])


def assert_event_valid(event: dict[str, Any]) -> None:
    errors = sorted(
        build_openva_validator(CHANGE_EVENT_SCHEMA).iter_errors(event),
        key=lambda error: list(error.path),
    )
    assert errors == []


def set_instrument(
    projection: dict[str, Any],
    value: str,
    reason: str,
) -> dict[str, Any]:
    projection = deepcopy(projection)
    projection["axes"]["instrument_state"]["value"] = value
    projection["axes"]["instrument_state"]["reason_codes"] = [reason]
    return projection


def set_supersession(
    projection: dict[str, Any],
    value: str,
    reason: str,
    *,
    topology: str | None = None,
) -> dict[str, Any]:
    projection = deepcopy(projection)
    axis = projection["axes"]["supersession_state"]
    axis["value"] = value
    axis["reason_codes"] = [reason]
    if topology is not None:
        axis["topology"] = topology
    if value == "superseded":
        axis["topology"] = topology or "chain_root"
        axis["predecessor_assurance_id"] = None
        axis["successor_assurance_ids"] = ["acme-successor"]
        axis["caused_by"]["assurance_ids"] = [projection["assurance_id"], "acme-successor"]
    else:
        axis["topology"] = topology or "standalone"
        axis["predecessor_assurance_id"] = None
        axis["successor_assurance_ids"] = []
        axis["caused_by"]["assurance_ids"] = [projection["assurance_id"]]
    return projection


def instrument_event(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return next(event for event in events if event["transition"]["axis"] == "instrument_state")


def supersession_event(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return next(event for event in events if event["transition"]["axis"] == "supersession_state")


def diff(
    previous: dict[str, Any] | None,
    new: dict[str, Any],
    detected_at: str = "2026-06-30T00:00:00Z",
) -> tuple[dict[str, Any], ...]:
    return tuple(dict(event) for event in diff_assurance_projections(previous, new, detected_at))


def test_initial_materialization_produces_two_ordered_events() -> None:
    projection = noop_projection("projection_a")

    events = diff(None, projection)

    assert [event["transition"]["axis"] for event in events] == ["instrument_state", "supersession_state"]
    assert [event["transition"]["from"] for event in events] == [None, None]
    assert events[0]["transition"]["to"] == "effective"
    assert events[1]["transition"]["to"] == "current"
    assert events[0]["reason_code"] == "effective_at_within_stated_interval"
    assert events[1]["reason_code"] == "no_explicit_successor_admitted"
    assert events[0]["caused_by"] == {"assurance_ids": ["acme-noop"]}
    assert events[1]["caused_by"] == {"assurance_ids": ["acme-noop"]}
    assert events == diff(None, projection)
    for event in events:
        assert_event_valid(event)
        assert event["change_event_id"].startswith("assurance-change-")


@pytest.mark.parametrize(
    "previous_value,new_value,new_reason",
    [
        ("not_yet_effective", "effective", "effective_at_within_stated_interval"),
        ("effective", "expired", "stated_valid_until_passed"),
        ("not_yet_effective", "historical", "point_in_time_scope"),
        ("temporally_indeterminate", "expired", "stated_valid_until_passed"),
    ],
)
def test_instrument_state_transitions(
    previous_value: str,
    new_value: str,
    new_reason: str,
) -> None:
    base = fixture_projection("active-certification")
    previous = set_instrument(base, previous_value, "effective_at_before_valid_from")
    new = set_instrument(base, new_value, new_reason)

    events = diff(previous, new)

    assert len(events) == 1
    event = events[0]
    assert event["change_type"] == "instrument_state_changed"
    assert event["transition"] == {"axis": "instrument_state", "from": previous_value, "to": new_value}
    assert event["reason_code"] == new_reason
    assert_event_valid(event)


def test_supersession_transition_and_topology_only_noop() -> None:
    base = fixture_projection("active-certification")
    changed = set_supersession(base, "superseded", "explicit_successor_admitted")

    events = diff(base, changed)

    assert len(events) == 1
    event = events[0]
    assert event["change_type"] == "assurance_superseded"
    assert event["transition"] == {"axis": "supersession_state", "from": "current", "to": "superseded"}
    assert event["reason_code"] == "explicit_successor_admitted"
    assert_event_valid(event)

    topology_only = deepcopy(base)
    topology_only["axes"]["supersession_state"]["topology"] = "chain_tip"
    topology_only["axes"]["supersession_state"]["predecessor_assurance_id"] = "acme-predecessor"
    topology_only["axes"]["supersession_state"]["caused_by"]["assurance_ids"] = [
        base["assurance_id"],
        "acme-predecessor",
    ]
    assert diff(base, topology_only) == ()


def test_two_axis_one_axis_and_no_axis_transitions() -> None:
    base = fixture_projection("active-certification")
    instrument_changed = set_instrument(base, "expired", "stated_valid_until_passed")
    supersession_changed = set_supersession(base, "superseded", "explicit_successor_admitted")
    both_changed = set_supersession(instrument_changed, "superseded", "explicit_successor_admitted")

    assert [event["transition"]["axis"] for event in diff(base, both_changed)] == [
        "instrument_state",
        "supersession_state",
    ]
    assert [event["transition"]["axis"] for event in diff(base, instrument_changed)] == ["instrument_state"]
    assert [event["transition"]["axis"] for event in diff(base, supersession_changed)] == ["supersession_state"]
    assert diff(base, deepcopy(base)) == ()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda projection: projection.__setitem__("projected_at", "2026-07-03T00:00:00Z"),
        lambda projection: projection.__setitem__("input_digest", SHA256_A),
        lambda projection: projection.__setitem__(
            "policy",
            {
                "id": "openva-assurance-projection-policy",
                "version": "0.1.1",
                "digest": SHA256_B,
            },
        ),
        lambda projection: projection["axes"]["instrument_state"].__setitem__(
            "reason_codes",
            ["point_in_time_scope"],
        ),
        lambda projection: projection["axes"]["instrument_state"].__setitem__(
            "caused_by",
            {"assurance_ids": [projection["assurance_id"]], "assurance_observation_ids": ["obs-a"]},
        ),
        lambda projection: projection["axes"]["instrument_state"].__setitem__(
            "interval_end_exclusive_at",
            "2027-01-11T00:00:00Z",
        ),
        lambda projection: (
            projection["axes"]["supersession_state"].__setitem__("topology", "chain_tip"),
            projection["axes"]["supersession_state"].__setitem__(
                "predecessor_assurance_id",
                "acme-predecessor",
            ),
            projection["axes"]["supersession_state"]["caused_by"].__setitem__(
                "assurance_ids",
                [projection["assurance_id"], "acme-predecessor"],
            ),
        ),
    ],
)
def test_state_value_unchanged_cases_do_not_emit_events(mutator: Any) -> None:
    base = fixture_projection("active-certification")
    changed = deepcopy(base)
    mutator(changed)

    assert diff(base, changed) == ()


def test_noop_rebuild_and_detected_at_identity_exclusion() -> None:
    projection_a = noop_projection("projection_a")
    projection_b = noop_projection("projection_b")
    assert diff(projection_a, projection_b, "2026-07-03T00:00:00Z") == ()

    first = diff(None, projection_a, "2026-07-03T00:00:00Z")
    second = diff(None, projection_a, "2026-07-04T00:00:00Z")
    assert [event["change_event_id"] for event in first] == [event["change_event_id"] for event in second]
    assert first[0]["detected_at"] == "2026-07-03T00:00:00Z"
    assert second[0]["detected_at"] == "2026-07-04T00:00:00Z"


def test_singular_reason_contract() -> None:
    base = fixture_projection("active-certification")
    changed = set_instrument(base, "expired", "stated_valid_until_passed")
    assert instrument_event(diff(base, changed))["reason_code"] == "stated_valid_until_passed"

    zero_reasons = deepcopy(changed)
    zero_reasons["axes"]["instrument_state"]["reason_codes"] = []
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, zero_reasons)
    assert exc.value.code == ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS

    multiple_reasons = deepcopy(changed)
    multiple_reasons["axes"]["instrument_state"]["reason_codes"] = [
        "stated_valid_until_passed",
        "effective_at_within_stated_interval",
    ]
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, multiple_reasons)
    assert exc.value.code == ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS

    wrong_reason = deepcopy(changed)
    wrong_reason["axes"]["instrument_state"]["reason_codes"] = ["explicit_successor_admitted"]
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, wrong_reason)
    assert exc.value.code in {ASSURANCE_PROJECTION_DIFF_INPUT_INVALID, ASSURANCE_CHANGE_EVENT_OUTPUT_INVALID}


def test_event_identity_stability_and_semantic_changes() -> None:
    base = fixture_projection("active-certification")
    changed = set_instrument(base, "expired", "stated_valid_until_passed")
    event = instrument_event(diff(base, changed))
    manifest = event_identity_manifest(event, projection_policy=changed["policy"])

    assert change_event_id_for_manifest(manifest) == event["change_event_id"]
    assert event["change_event_id"] == instrument_event(diff(dict(reversed(list(base.items()))), changed))[
        "change_event_id"
    ]

    cases = []
    changed_from = deepcopy(base)
    changed_from["axes"]["instrument_state"]["value"] = "not_yet_effective"
    cases.append(instrument_event(diff(changed_from, changed))["change_event_id"])

    changed_to = set_instrument(base, "historical", "point_in_time_scope")
    cases.append(instrument_event(diff(base, changed_to))["change_event_id"])

    changed_effective = deepcopy(changed)
    changed_effective["effective_at"] = "2026-07-01T00:00:00Z"
    cases.append(instrument_event(diff(base, changed_effective, "2026-07-01T00:00:00Z"))["change_event_id"])

    changed_cutoff = deepcopy(changed)
    changed_cutoff["knowledge_cutoff"] = "2026-07-01T00:00:00Z"
    cases.append(instrument_event(diff(base, changed_cutoff, "2026-07-01T00:00:00Z"))["change_event_id"])

    changed_digest = deepcopy(changed)
    changed_digest["input_digest"] = SHA256_A
    cases.append(instrument_event(diff(base, changed_digest))["change_event_id"])

    changed_policy = deepcopy(changed)
    changed_policy["policy"]["digest"] = SHA256_B
    cases.append(instrument_event(diff(base, changed_policy))["change_event_id"])

    changed_reason = set_instrument(base, "expired", "no_usable_dates")
    cases.append(instrument_event(diff(base, changed_reason))["change_event_id"])

    changed_provenance = deepcopy(changed)
    changed_provenance["axes"]["instrument_state"]["caused_by"]["assurance_ids"] = [
        base["assurance_id"],
        "related-assurance",
    ]
    cases.append(instrument_event(diff(base, changed_provenance))["change_event_id"])

    assert all(change_id != event["change_event_id"] for change_id in cases)
    assert event["change_event_id"] != supersession_event(diff(None, base))["change_event_id"]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("assurance_id", "other-assurance", ASSURANCE_PROJECTION_DIFF_INCOMPATIBLE),
        ("vendor_id", "other-vendor", ASSURANCE_PROJECTION_DIFF_INCOMPATIBLE),
        ("schema_version", "0.1.1", ASSURANCE_PROJECTION_DIFF_INPUT_INVALID),
        ("projection_profile", "other-profile", ASSURANCE_PROJECTION_DIFF_INPUT_INVALID),
        ("implemented_axes", ["supersession_state", "instrument_state"], ASSURANCE_PROJECTION_DIFF_INPUT_INVALID),
        ("advisory_boundary", "other", ASSURANCE_PROJECTION_DIFF_INPUT_INVALID),
    ],
)
def test_compatibility_failures(field: str, value: Any, code: str) -> None:
    base = fixture_projection("active-certification")
    changed = deepcopy(base)
    changed[field] = value

    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, changed)
    assert exc.value.code == code


def test_monotonicity_and_projected_at_behaviour() -> None:
    base = fixture_projection("active-certification")
    backward_effective = deepcopy(base)
    backward_effective["effective_at"] = "2026-06-29T00:00:00Z"
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, backward_effective)
    assert exc.value.code == ASSURANCE_PROJECTION_DIFF_NON_MONOTONIC

    backward_cutoff = deepcopy(base)
    backward_cutoff["knowledge_cutoff"] = "2026-06-29T00:00:00Z"
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, backward_cutoff)
    assert exc.value.code == ASSURANCE_PROJECTION_DIFF_NON_MONOTONIC

    changed_projected = deepcopy(base)
    changed_projected["projected_at"] = "2026-06-01T00:00:00Z"
    assert diff(base, changed_projected) == ()


def test_detected_at_handling() -> None:
    projection = fixture_projection("active-certification")
    event = diff(None, projection, "2026-06-30T08:00:00+08:00")[0]
    assert event["detected_at"] == "2026-06-30T00:00:00Z"

    with pytest.raises(AssuranceProjectionError) as exc:
        diff(None, projection, datetime(2026, 6, 30))
    assert exc.value.code == ASSURANCE_PROJECTION_DATETIME_NAIVE

    with pytest.raises(AssuranceProjectionError) as exc:
        diff(None, projection, "2026-06-29T23:59:59Z")
    assert exc.value.code == ASSURANCE_CHANGE_EVENT_TIME_INVALID


def test_malformed_inputs_and_output_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    base = fixture_projection("active-certification")
    malformed = deepcopy(base)
    del malformed["axes"]
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, malformed)
    assert exc.value.code == ASSURANCE_PROJECTION_DIFF_INPUT_INVALID

    with pytest.raises(AssuranceProjectionError) as exc:
        diff(malformed, base)
    assert exc.value.code == ASSURANCE_PROJECTION_DIFF_INPUT_INVALID

    changed = set_instrument(base, "expired", "stated_valid_until_passed")
    monkeypatch.setattr(assurance_projection, "event_policy_ref", lambda projection: {"id": ""})
    with pytest.raises(AssuranceProjectionError) as exc:
        diff(base, changed)
    assert exc.value.code == ASSURANCE_CHANGE_EVENT_OUTPUT_INVALID


def test_policy_change_behaviour() -> None:
    base = fixture_projection("active-certification")
    policy_changed = deepcopy(base)
    policy_changed["policy"]["digest"] = SHA256_B
    assert diff(base, policy_changed) == ()

    state_and_policy_changed = set_instrument(policy_changed, "expired", "stated_valid_until_passed")
    event = instrument_event(diff(base, state_and_policy_changed))
    assert event["policy"] == {
        "id": "openva-assurance-projection-policy",
        "version": "0.1.0",
    }
    assert event["input_digest"] == state_and_policy_changed["input_digest"]


def test_inputs_are_not_mutated_and_results_are_deterministic() -> None:
    previous = fixture_projection("active-certification")
    new = set_supersession(set_instrument(previous, "expired", "stated_valid_until_passed"), "superseded", "explicit_successor_admitted")
    previous_before = deepcopy(previous)
    new_before = deepcopy(new)

    first = diff(previous, new)
    second = diff(previous, new)

    assert first == second
    assert previous == previous_before
    assert new == new_before
    assert isinstance(diff(None, previous), tuple)


def test_projection_diff_source_has_no_clock_network_or_write_calls() -> None:
    source = inspect.getsource(assurance_projection.diff_assurance_projections)
    forbidden_tokens = [
        ".now(",
        ".utcnow(",
        "urlopen",
        "requests.",
        "httpx",
        "socket.",
        ".write(",
        "open(",
    ]
    assert [token for token in forbidden_tokens if token in source] == []
