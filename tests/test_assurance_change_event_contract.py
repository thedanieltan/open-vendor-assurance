from __future__ import annotations

from typing import Any

import pytest
import yaml

from tools.openva.schema_registry import ROOT, build_openva_validator, load_schema

CHANGE_EVENT_SCHEMA_PATH = ROOT / "schemas/openva/assurance-change-event.schema.json"
PROJECTION_VOCAB_PATH = ROOT / "schemas/openva/vocabularies/assurance-projection-v1.schema.json"
LEGACY_VOCAB_PATH = ROOT / "schemas/openva/vocabularies/assurance-v1.schema.json"


@pytest.fixture(scope="module")
def validator() -> Any:
    return build_openva_validator(CHANGE_EVENT_SCHEMA_PATH)


def projection_enum(definition_name: str) -> list[str]:
    return list(load_schema(PROJECTION_VOCAB_PATH)["$defs"][definition_name]["enum"])


def legacy_enum(definition_name: str) -> list[str]:
    return list(load_schema(LEGACY_VOCAB_PATH)["$defs"][definition_name]["enum"])


def base_event(*, transition: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "change_event_id": "example-change-event",
        "assurance_id": "example-assurance",
        "vendor_id": "example-vendor",
        "detected_at": "2026-06-30T00:00:00Z",
        "effective_at": "2026-06-29T00:00:00Z",
        "knowledge_cutoff": "2026-06-29T00:00:00Z",
        "input_digest": "sha256:" + "a" * 64,
        "change_type": change_type_for_axis(transition["axis"]),
        "transition": transition,
        "reason_code": reason_code,
        "caused_by": {"assurance_ids": ["example-assurance"]},
        "policy": {
            "id": "openva-assurance-projection-policy",
            "version": "0.1.0",
        },
        "advisory_boundary": "non_advisory",
    }


def change_type_for_axis(axis: str) -> str:
    return {
        "instrument_state": "instrument_state_changed",
        "supersession_state": "assurance_superseded",
        "verification_state": "verification_state_changed",
        "verification_freshness": "verification_freshness_changed",
        "evidence_set": "evidence_set_changed",
    }[axis]


def instrument_transition() -> dict[str, Any]:
    return {"axis": "instrument_state", "from": None, "to": "effective"}


def supersession_transition() -> dict[str, Any]:
    return {"axis": "supersession_state", "from": None, "to": "current"}


def verification_state_transition() -> dict[str, Any]:
    return {"axis": "verification_state", "from": None, "to": "first_party_claim_only"}


def verification_freshness_transition() -> dict[str, Any]:
    return {"axis": "verification_freshness", "from": None, "to": "current"}


def evidence_set_transition() -> dict[str, Any]:
    return {"axis": "evidence_set", "from": None, "to": {"source_ids": ["example-source"]}}


@pytest.mark.parametrize("reason_code", projection_enum("instrumentStateReasonCode"))
def test_instrument_state_events_accept_all_instrument_reasons(
    validator: Any,
    reason_code: str,
) -> None:
    assert list(validator.iter_errors(base_event(transition=instrument_transition(), reason_code=reason_code))) == []


@pytest.mark.parametrize("reason_code", projection_enum("supersessionStateReasonCode"))
def test_supersession_state_events_accept_all_supersession_reasons(
    validator: Any,
    reason_code: str,
) -> None:
    assert list(validator.iter_errors(base_event(transition=supersession_transition(), reason_code=reason_code))) == []


def test_instrument_reason_is_rejected_for_supersession_transition(validator: Any) -> None:
    event = base_event(
        transition=supersession_transition(),
        reason_code="effective_at_within_stated_interval",
    )
    assert list(validator.iter_errors(event))


def test_supersession_reason_is_rejected_for_instrument_transition(validator: Any) -> None:
    event = base_event(
        transition=instrument_transition(),
        reason_code="explicit_successor_admitted",
    )
    assert list(validator.iter_errors(event))


@pytest.mark.parametrize(
    "transition",
    [
        verification_state_transition(),
        verification_freshness_transition(),
        evidence_set_transition(),
    ],
    ids=lambda transition: transition["axis"],
)
def test_projection_reason_is_rejected_for_legacy_axes(
    validator: Any,
    transition: dict[str, Any],
) -> None:
    event = base_event(
        transition=transition,
        reason_code="effective_at_within_stated_interval",
    )
    assert list(validator.iter_errors(event))


@pytest.mark.parametrize(
    "transition",
    [
        verification_state_transition(),
        verification_freshness_transition(),
        evidence_set_transition(),
    ],
    ids=lambda transition: transition["axis"],
)
def test_legacy_reason_remains_valid_for_legacy_axes(
    validator: Any,
    transition: dict[str, Any],
) -> None:
    event = base_event(
        transition=transition,
        reason_code="authoritative_status_confirmed",
    )
    assert list(validator.iter_errors(event)) == []


@pytest.mark.parametrize("reason_code", legacy_enum("transitionReasonCode"))
def test_legacy_reason_vocabulary_still_validates_for_verification_state(
    validator: Any,
    reason_code: str,
) -> None:
    event = base_event(
        transition=verification_state_transition(),
        reason_code=reason_code,
    )
    assert list(validator.iter_errors(event)) == []


def test_checked_in_change_event_fixtures_still_validate(validator: Any) -> None:
    fixture_paths = sorted(
        (ROOT / "tests/fixtures/assurance/projection").glob("**/assurance_changes/*.yaml")
    )
    assert fixture_paths
    for fixture_path in fixture_paths:
        event = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
        assert list(validator.iter_errors(event)) == [], fixture_path


def test_change_event_schema_refs_resolve_offline(validator: Any) -> None:
    event = base_event(
        transition=instrument_transition(),
        reason_code="effective_at_before_valid_from",
    )
    validator.validate(event)
