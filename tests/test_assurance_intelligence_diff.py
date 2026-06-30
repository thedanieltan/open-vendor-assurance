from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva.assurance_intelligence import (
    ASSURANCE_INTELLIGENCE_DIFF_INCOMPATIBLE,
    ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC,
    INTELLIGENCE_AXES,
    INTELLIGENCE_PROFILE,
    AssuranceIntelligenceError,
    diff_assurance_intelligence_projections,
    project_assurance_intelligence,
)
from tools.openva.assurance_projection import (
    ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS,
    AssuranceProjectionError,
)
from tools.openva.pack import canonical_json, sha256_bytes
from tools.openva.schema_registry import ROOT, build_openva_validator

VERIFICATION_CONTRACT_ROOT = ROOT / "tests/fixtures/assurance/verification/contracts"
LIFECYCLE_POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
VERIFICATION_POLICY_PATH = ROOT / "config/assurance-verification-policy.yaml"
FRESHNESS_POLICY_PATH = ROOT / "config/assurance-verification-freshness-policy.yaml"
EVIDENCE_POLICY_PATH = ROOT / "config/assurance-evidence-set-policy.yaml"
INTELLIGENCE_SCHEMA_PATH = ROOT / "schemas/openva/assurance-intelligence-projection.schema.json"
CHANGE_EVENT_SCHEMA_PATH = ROOT / "schemas/openva/assurance-change-event.schema.json"
SHA256_B = "sha256:" + "b" * 64

COMPLETE_FIELDS = {
    "stated_valid_from": "2026-01-10",
    "stated_valid_until": "2027-01-09",
    "stated_identifier": "ACME-ISO-2026",
    "stated_issuer_name": "Example Certification Body",
    "stated_scope_description": "Acme cloud service ISMS",
}


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policies() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    policies = tuple(
        load_yaml(path)
        for path in (
            LIFECYCLE_POLICY_PATH,
            VERIFICATION_POLICY_PATH,
            FRESHNESS_POLICY_PATH,
            EVIDENCE_POLICY_PATH,
        )
    )
    assert all(isinstance(policy, dict) for policy in policies)
    return policies


def policy_ref(policy: dict[str, Any]) -> dict[str, str]:
    return {
        "id": policy["policy_id"],
        "version": policy["policy_version"],
        "digest": sha256_bytes(canonical_json(policy)),
    }


def request_for(
    assurance_id: str = "acme-iso-2026",
    *,
    effective_at: str = "2026-06-30T00:00:00Z",
    knowledge_cutoff: str = "2026-06-30T00:00:00Z",
) -> dict[str, Any]:
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()
    return {
        "schema_version": "0.1.0",
        "assurance_id": assurance_id,
        "effective_at": effective_at,
        "knowledge_cutoff": knowledge_cutoff,
        "projection_profile": INTELLIGENCE_PROFILE,
        "policies": {
            "lifecycle": policy_ref(lifecycle_policy),
            "verification": policy_ref(verification_policy),
            "verification_freshness": policy_ref(freshness_policy),
            "evidence_set": policy_ref(evidence_policy),
        },
    }


def load_repository(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "assurances": {},
        "assurance_observations": {},
    }
    id_fields = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "assurances": "assurance_id",
        "assurance_observations": "assurance_observation_id",
    }
    for directory_name, id_field in id_fields.items():
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            records[directory_name][record[id_field]] = record
    return records


def verification_case(name: str) -> dict[str, dict[str, dict[str, Any]]]:
    return load_repository(VERIFICATION_CONTRACT_ROOT / name / "repository")


def complete_support_repository() -> dict[str, dict[str, dict[str, Any]]]:
    repository = verification_case("one-supporting-observation")
    observation = next(iter(repository["assurance_observations"].values()))
    observation["observed_fields"] = deepcopy(COMPLETE_FIELDS)
    observation["observed_at"] = "2026-06-01T00:00:00Z"
    observation["recorded_at"] = "2026-06-01T00:00:00Z"
    return repository


def project(
    repository: dict[str, dict[str, dict[str, Any]]],
    request: dict[str, Any] | None = None,
    *,
    projected_at: str = "2026-06-30T00:00:00Z",
) -> dict[str, Any]:
    lifecycle_policy, verification_policy, freshness_policy, evidence_policy = load_policies()
    result = project_assurance_intelligence(
        request or request_for(),
        repository,
        lifecycle_policy,
        verification_policy,
        freshness_policy,
        evidence_policy,
        projected_at,
    )
    build_openva_validator(INTELLIGENCE_SCHEMA_PATH).validate(result)
    return dict(result)


def diff(
    previous: dict[str, Any] | None,
    new: dict[str, Any],
    detected_at: str = "2026-06-30T00:00:00Z",
) -> tuple[dict[str, Any], ...]:
    return tuple(dict(event) for event in diff_assurance_intelligence_projections(previous, new, detected_at))


def assert_event_valid(event: dict[str, Any]) -> None:
    build_openva_validator(CHANGE_EVENT_SCHEMA_PATH).validate(event)


def test_initial_diff_produces_five_ordered_events() -> None:
    projection = project(complete_support_repository())

    events = diff(None, projection)

    assert [event["transition"]["axis"] for event in events] == list(INTELLIGENCE_AXES)
    assert [event["transition"]["from"] for event in events] == [None, None, None, None, None]
    assert [event["transition"]["to"] for event in events] == [
        "effective",
        "current",
        "confirmed",
        "current",
        "complete",
    ]
    assert [event["reason_code"] for event in events] == [
        "effective_at_within_stated_interval",
        "no_explicit_successor_admitted",
        "decisive_observations_support",
        "decisive_basis_within_current_threshold",
        "required_evidence_complete",
    ]
    for event in events:
        assert_event_valid(event)


@pytest.mark.parametrize(
    ("axis_name", "from_value", "to_value", "reason_code"),
    [
        ("instrument_state", "not_yet_effective", "effective", "effective_at_within_stated_interval"),
        ("supersession_state", "current", "superseded", "explicit_successor_admitted"),
        ("verification_state", "no_conclusion", "confirmed", "decisive_observations_support"),
        ("verification_freshness", "no_basis", "current", "decisive_basis_within_current_threshold"),
        ("evidence_set_state", "no_evidence", "complete", "required_evidence_complete"),
    ],
)
def test_one_transition_for_each_individual_axis(
    axis_name: str,
    from_value: str,
    to_value: str,
    reason_code: str,
) -> None:
    if axis_name in {"verification_freshness", "evidence_set_state"}:
        previous = project(verification_case("no-observations"))
        new = project(complete_support_repository())
        for unchanged_axis in set(INTELLIGENCE_AXES) - {axis_name}:
            new["axes"][unchanged_axis] = deepcopy(previous["axes"][unchanged_axis])
    else:
        previous = project(complete_support_repository())
        new = deepcopy(previous)
        previous["axes"][axis_name]["value"] = from_value
        previous["axes"][axis_name]["reason_codes"] = [reason_code]
        new["axes"][axis_name]["value"] = to_value
        new["axes"][axis_name]["reason_codes"] = [reason_code]
    if axis_name == "supersession_state":
        new["axes"][axis_name]["topology"] = "chain_root"
        new["axes"][axis_name]["successor_assurance_ids"] = ["acme-successor"]
        new["axes"][axis_name]["caused_by"]["assurance_ids"] = ["acme-iso-2026", "acme-successor"]

    events = diff(previous, new)

    assert [event["transition"]["axis"] for event in events] == [axis_name]
    assert events[0]["transition"] == {"axis": axis_name, "from": from_value, "to": to_value}
    assert events[0]["reason_code"] == reason_code
    assert_event_valid(events[0])


def test_multiple_simultaneous_transitions_preserve_axis_order() -> None:
    previous = project(verification_case("no-observations"))
    new = project(complete_support_repository())
    previous["axes"]["instrument_state"]["value"] = "not_yet_effective"
    previous["axes"]["instrument_state"]["reason_codes"] = ["effective_at_before_valid_from"]

    events = diff(previous, new)

    assert [event["transition"]["axis"] for event in events] == [
        "instrument_state",
        "verification_state",
        "verification_freshness",
        "evidence_set_state",
    ]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda projection: projection.__setitem__("projected_at", "2026-07-01T00:00:00Z"),
        lambda projection: projection.__setitem__("input_digest", SHA256_B),
        lambda projection: projection["policies"]["verification"].__setitem__("digest", SHA256_B),
        lambda projection: projection["axes"]["verification_state"].__setitem__(
            "reason_codes",
            ["decisive_observation_inconclusive"],
        ),
        lambda projection: projection["axes"]["verification_state"]["caused_by"].__setitem__(
            "assurance_observation_ids",
            ["different-observation"],
        ),
        lambda projection: projection["axes"]["instrument_state"].__setitem__(
            "interval_end_exclusive_at",
            "2027-01-11T00:00:00Z",
        ),
    ],
)
def test_non_state_changes_do_not_emit_events(mutator: Any) -> None:
    previous = project(complete_support_repository())
    new = deepcopy(previous)
    mutator(new)

    assert diff(previous, new) == ()


def test_event_ids_are_deterministic_and_exclude_detected_and_projected_times() -> None:
    first_projection = project(complete_support_repository(), projected_at="2026-06-30T00:00:00Z")
    second_projection = deepcopy(first_projection)
    second_projection["projected_at"] = "2026-07-01T00:00:00Z"

    first = diff(None, first_projection, "2026-06-30T00:00:00Z")
    second = diff(None, second_projection, "2026-07-01T00:00:00Z")

    assert [event["change_event_id"] for event in first] == [event["change_event_id"] for event in second]
    assert [event["detected_at"] for event in first] != [event["detected_at"] for event in second]


def test_new_axis_state_reason_schema_coupling() -> None:
    projection = project(complete_support_repository())
    event = next(event for event in diff(None, projection) if event["transition"]["axis"] == "verification_state")
    bad_event = deepcopy(event)
    bad_event["reason_code"] = "explicit_successor_admitted"

    with pytest.raises(Exception):
        build_openva_validator(CHANGE_EVENT_SCHEMA_PATH).validate(bad_event)


def test_legacy_event_regression() -> None:
    legacy = {
        "schema_version": "0.1.0",
        "change_event_id": "legacy-verification-event",
        "assurance_id": "acme-iso-2026",
        "vendor_id": "acme",
        "detected_at": "2026-06-30T00:00:00Z",
        "effective_at": "2026-06-30T00:00:00Z",
        "knowledge_cutoff": "2026-06-30T00:00:00Z",
        "input_digest": "sha256:" + "a" * 64,
        "change_type": "verification_state_changed",
        "transition": {"axis": "verification_state", "from": None, "to": "authoritatively_confirmed"},
        "reason_code": "authoritative_status_confirmed",
        "caused_by": {"assurance_ids": ["acme-iso-2026"]},
        "policy": {"id": "legacy", "version": "0.1.0"},
        "advisory_boundary": "non_advisory",
    }

    assert_event_valid(legacy)


def test_incompatible_and_non_monotonic_projections_rejected() -> None:
    projection = project(complete_support_repository())
    other_profile = deepcopy(projection)
    other_profile["assurance_id"] = "other-assurance"
    with pytest.raises(AssuranceIntelligenceError) as incompatible:
        diff(projection, other_profile)
    assert incompatible.value.code == ASSURANCE_INTELLIGENCE_DIFF_INCOMPATIBLE

    earlier = deepcopy(projection)
    earlier["effective_at"] = "2026-06-29T00:00:00Z"
    with pytest.raises(AssuranceIntelligenceError) as non_monotonic:
        diff(projection, earlier)
    assert non_monotonic.value.code == ASSURANCE_INTELLIGENCE_DIFF_NON_MONOTONIC


def test_singular_reason_required_for_new_axis_event() -> None:
    previous = project(complete_support_repository())
    new = deepcopy(previous)
    new["axes"]["verification_state"]["value"] = "inconclusive"
    new["axes"]["verification_state"]["reason_codes"] = [
        "decisive_observations_support",
        "decisive_observations_conflict",
    ]

    with pytest.raises(AssuranceProjectionError) as exc_info:
        diff(previous, new)

    assert exc_info.value.code == ASSURANCE_CHANGE_EVENT_REASON_AMBIGUOUS


def test_diff_does_not_mutate_inputs() -> None:
    previous = project(verification_case("no-observations"))
    new = project(complete_support_repository())
    previous_before = json.loads(json.dumps(previous))
    new_before = json.loads(json.dumps(new))

    diff(previous, new)

    assert previous == previous_before
    assert new == new_before
