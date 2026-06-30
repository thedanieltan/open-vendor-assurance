from __future__ import annotations

import inspect
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva import assurance_projection
from tools.openva.assurance_projection import (
    ASSURANCE_PROJECTION_CLASS_RULE_MISSING,
    ASSURANCE_PROJECTION_DATETIME_NAIVE,
    ASSURANCE_PROJECTION_POLICY_INVALID,
    ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
    AssuranceProjectionError,
    InstrumentStateResult,
    project_instrument_state,
)
from tools.openva.assurance_projection_policy import (
    AssuranceProjectionPolicy,
    load_assurance_projection_policy,
)
from tools.openva.schema_registry import ROOT, build_openva_schema_registry, load_schema

POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
AXIS_SCHEMA = {
    "$ref": "https://openva.dev/schemas/openva/assurance-projection.schema.json#/$defs/instrumentStateAxis"
}


@pytest.fixture(scope="module")
def policy() -> AssuranceProjectionPolicy:
    return load_assurance_projection_policy()


@pytest.fixture(scope="module")
def raw_policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def axis_validator() -> Draft202012Validator:
    return Draft202012Validator(
        AXIS_SCHEMA,
        registry=build_openva_schema_registry(),
        format_checker=FormatChecker(),
    )


def dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def base_record(
    assurance_class: str,
    temporal_scope: dict[str, Any],
    *,
    assurance_id: str = "acme-assurance",
    recorded_at: str = "2026-01-01T00:00:00Z",
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.1",
        "assurance_id": assurance_id,
        "vendor_id": "acme",
        "assurance_class": assurance_class,
        "framework": {"framework_id": "example_framework"},
        "subject": {
            "entity_name": "Acme Example Pte. Ltd.",
            "scope_description": "Example public assurance scope.",
        },
        "temporal_scope": temporal_scope,
        "evidence": {"source_ids": ["acme-trust-center"]},
        "advisory_boundary": "non_advisory",
        "recorded_at": recorded_at,
    }


def certification_record(**kwargs: Any) -> dict[str, Any]:
    record = base_record(
        "accredited_certification",
        {"issued_at": "2026-01-10", "valid_from": "2026-01-10", "valid_until": "2027-01-09"},
        **kwargs,
    )
    record["issuer"] = {"name": "Example Certification Body", "authority_type": "certification_body", "country": "SG"}
    record["identifiers"] = {"certificate_number": "ACME-ISO-2026"}
    return record


def attestation_as_of_record() -> dict[str, Any]:
    record = base_record("attestation_report", {"issued_at": "2026-02-01", "as_of_date": "2026-01-31"})
    record["issuer"] = {"name": "Example Audit Firm", "authority_type": "audit_firm", "country": "SG"}
    return record


def attestation_period_record() -> dict[str, Any]:
    record = base_record(
        "attestation_report",
        {"issued_at": "2026-02-01", "reporting_period": {"start": "2025-01-01", "end": "2025-12-31"}},
    )
    record["issuer"] = {"name": "Example Audit Firm", "authority_type": "audit_firm", "country": "SG"}
    return record


def regulatory_record(temporal_scope: dict[str, Any]) -> dict[str, Any]:
    return base_record("regulatory_assertion", temporal_scope)


def contractual_record(temporal_scope: dict[str, Any]) -> dict[str, Any]:
    return base_record("contractual_capability", temporal_scope)


def assert_result(
    result: InstrumentStateResult,
    *,
    validator: Draft202012Validator,
    assurance_id: str,
    value: str,
    reason: str,
    temporal_model: str,
    next_reevaluation_at: str | None,
    expected_fields: dict[str, Any],
) -> None:
    errors = sorted(validator.iter_errors(result.axis), key=lambda error: list(error.path))
    assert errors == []
    assert result.axis["determination"] == "determined"
    assert result.axis["value"] == value
    assert result.axis["reason_codes"] == [reason]
    assert result.axis["temporal_model"] == temporal_model
    assert result.axis["caused_by"] == {
        "assurance_ids": [assurance_id],
        "assurance_observation_ids": [],
        "source_observation_ids": [],
    }
    for field_name, expected in expected_fields.items():
        assert result.axis[field_name] == expected
    assert result.next_reevaluation_at == (dt(next_reevaluation_at) if next_reevaluation_at else None)


@pytest.mark.parametrize(
    "effective_at,value,reason,next_reevaluation_at",
    [
        ("2026-01-09T23:59:59Z", "not_yet_effective", "effective_at_before_valid_from", "2026-01-10T00:00:00Z"),
        ("2026-01-10T00:00:00Z", "effective", "effective_at_within_stated_interval", "2027-01-10T00:00:00Z"),
        ("2026-06-30T00:00:00Z", "effective", "effective_at_within_stated_interval", "2027-01-10T00:00:00Z"),
        ("2027-01-09T23:59:59Z", "effective", "effective_at_within_stated_interval", "2027-01-10T00:00:00Z"),
        ("2027-01-10T00:00:00Z", "expired", "stated_valid_until_passed", None),
        ("2028-01-01T00:00:00Z", "expired", "stated_valid_until_passed", None),
    ],
)
def test_certification_boundaries(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
    effective_at: str,
    value: str,
    reason: str,
    next_reevaluation_at: str | None,
) -> None:
    record = certification_record(assurance_id="acme-cert")
    result = project_instrument_state(record, policy, effective_at, "2026-01-10T00:00:00Z")
    assert_result(
        result,
        validator=axis_validator,
        assurance_id="acme-cert",
        value=value,
        reason=reason,
        temporal_model="bounded_interval",
        next_reevaluation_at=next_reevaluation_at,
        expected_fields={
            "stated_valid_from": "2026-01-10",
            "stated_valid_until": "2027-01-09",
            "interval_start_at": "2026-01-10T00:00:00Z",
            "interval_end_exclusive_at": "2027-01-10T00:00:00Z",
        },
    )


@pytest.mark.parametrize(
    "effective_at,value,reason,next_reevaluation_at",
    [
        ("2026-01-30T23:59:59Z", "not_yet_effective", "effective_at_before_valid_from", "2026-01-31T00:00:00Z"),
        ("2026-01-31T00:00:00Z", "historical", "point_in_time_scope", None),
        ("2026-03-01T00:00:00Z", "historical", "point_in_time_scope", None),
    ],
)
def test_point_in_time_attestation(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
    effective_at: str,
    value: str,
    reason: str,
    next_reevaluation_at: str | None,
) -> None:
    result = project_instrument_state(attestation_as_of_record(), policy, effective_at, "2026-02-01T00:00:00Z")
    assert_result(
        result,
        validator=axis_validator,
        assurance_id="acme-assurance",
        value=value,
        reason=reason,
        temporal_model="point_or_period",
        next_reevaluation_at=next_reevaluation_at,
        expected_fields={"stated_as_of_date": "2026-01-31", "as_of_at": "2026-01-31T00:00:00Z"},
    )


@pytest.mark.parametrize(
    "effective_at,value,next_reevaluation_at",
    [
        ("2025-12-31T23:59:59Z", "not_yet_effective", "2026-01-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", "historical", None),
        ("2026-02-01T00:00:00Z", "historical", None),
    ],
)
def test_reporting_period_attestation(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
    effective_at: str,
    value: str,
    next_reevaluation_at: str | None,
) -> None:
    result = project_instrument_state(attestation_period_record(), policy, effective_at, "2026-02-01T00:00:00Z")
    assert_result(
        result,
        validator=axis_validator,
        assurance_id="acme-assurance",
        value=value,
        reason="reporting_period_scope",
        temporal_model="point_or_period",
        next_reevaluation_at=next_reevaluation_at,
        expected_fields={
            "stated_reporting_period_start": "2025-01-01",
            "stated_reporting_period_end": "2025-12-31",
            "reporting_period_start_at": "2025-01-01T00:00:00Z",
            "reporting_period_end_exclusive_at": "2026-01-01T00:00:00Z",
        },
    )


@pytest.mark.parametrize(
    "record,effective_at,value,reason,next_reevaluation_at,fields",
    [
        (
            regulatory_record({"claimed_as_of": "2026-03-01"}),
            "2026-02-28T23:59:59Z",
            "not_yet_effective",
            "effective_at_before_valid_from",
            "2026-03-01T00:00:00Z",
            {"stated_as_of_date": "2026-03-01", "as_of_at": "2026-03-01T00:00:00Z"},
        ),
        (
            regulatory_record({"claimed_as_of": "2026-03-01"}),
            "2026-03-01T00:00:00Z",
            "historical",
            "point_in_time_scope",
            None,
            {"stated_as_of_date": "2026-03-01", "as_of_at": "2026-03-01T00:00:00Z"},
        ),
        (
            regulatory_record({"effective_from_claimed": "2026-04-01"}),
            "2026-03-31T23:59:59Z",
            "not_yet_effective",
            "effective_at_before_valid_from",
            "2026-04-01T00:00:00Z",
            {
                "stated_effective_from_claimed": "2026-04-01",
                "claimed_interval_start_at": "2026-04-01T00:00:00Z",
            },
        ),
        (
            regulatory_record({"effective_from_claimed": "2026-04-01"}),
            "2026-04-01T00:00:00Z",
            "temporally_indeterminate",
            "no_stated_end_date",
            None,
            {
                "stated_effective_from_claimed": "2026-04-01",
                "claimed_interval_start_at": "2026-04-01T00:00:00Z",
            },
        ),
        (regulatory_record({}), "2026-04-01T00:00:00Z", "temporally_indeterminate", "no_usable_dates", None, {}),
    ],
)
def test_regulatory_assertion(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
    record: dict[str, Any],
    effective_at: str,
    value: str,
    reason: str,
    next_reevaluation_at: str | None,
    fields: dict[str, Any],
) -> None:
    result = project_instrument_state(record, policy, effective_at, "2026-02-01T00:00:00Z")
    assert_result(
        result,
        validator=axis_validator,
        assurance_id="acme-assurance",
        value=value,
        reason=reason,
        temporal_model="optional_claimed_scope",
        next_reevaluation_at=next_reevaluation_at,
        expected_fields=fields,
    )


@pytest.mark.parametrize(
    "record,effective_at,value,reason,next_reevaluation_at,fields",
    [
        (
            contractual_record({"effective_from_claimed": "2026-01-01", "effective_until_claimed": "2026-12-31"}),
            "2025-12-31T23:59:59Z",
            "not_yet_effective",
            "effective_at_before_valid_from",
            "2026-01-01T00:00:00Z",
            {
                "stated_effective_from_claimed": "2026-01-01",
                "stated_effective_until_claimed": "2026-12-31",
                "claimed_interval_start_at": "2026-01-01T00:00:00Z",
                "claimed_interval_end_exclusive_at": "2027-01-01T00:00:00Z",
            },
        ),
        (
            contractual_record({"effective_from_claimed": "2026-01-01", "effective_until_claimed": "2026-12-31"}),
            "2026-06-01T00:00:00Z",
            "effective",
            "effective_at_within_stated_interval",
            "2027-01-01T00:00:00Z",
            {
                "stated_effective_from_claimed": "2026-01-01",
                "stated_effective_until_claimed": "2026-12-31",
                "claimed_interval_start_at": "2026-01-01T00:00:00Z",
                "claimed_interval_end_exclusive_at": "2027-01-01T00:00:00Z",
            },
        ),
        (
            contractual_record({"effective_from_claimed": "2026-01-01", "effective_until_claimed": "2026-12-31"}),
            "2027-01-01T00:00:00Z",
            "expired",
            "stated_valid_until_passed",
            None,
            {
                "stated_effective_from_claimed": "2026-01-01",
                "stated_effective_until_claimed": "2026-12-31",
                "claimed_interval_start_at": "2026-01-01T00:00:00Z",
                "claimed_interval_end_exclusive_at": "2027-01-01T00:00:00Z",
            },
        ),
        (
            contractual_record({"effective_from_claimed": "2026-01-01"}),
            "2025-12-31T23:59:59Z",
            "not_yet_effective",
            "effective_at_before_valid_from",
            "2026-01-01T00:00:00Z",
            {"stated_effective_from_claimed": "2026-01-01", "claimed_interval_start_at": "2026-01-01T00:00:00Z"},
        ),
        (
            contractual_record({"effective_from_claimed": "2026-01-01"}),
            "2026-01-01T00:00:00Z",
            "temporally_indeterminate",
            "no_stated_end_date",
            None,
            {"stated_effective_from_claimed": "2026-01-01", "claimed_interval_start_at": "2026-01-01T00:00:00Z"},
        ),
        (
            contractual_record({"effective_until_claimed": "2026-12-31"}),
            "2026-12-31T23:59:59Z",
            "temporally_indeterminate",
            "no_usable_dates",
            "2027-01-01T00:00:00Z",
            {
                "stated_effective_until_claimed": "2026-12-31",
                "claimed_interval_end_exclusive_at": "2027-01-01T00:00:00Z",
            },
        ),
        (
            contractual_record({"effective_until_claimed": "2026-12-31"}),
            "2027-01-01T00:00:00Z",
            "expired",
            "stated_valid_until_passed",
            None,
            {
                "stated_effective_until_claimed": "2026-12-31",
                "claimed_interval_end_exclusive_at": "2027-01-01T00:00:00Z",
            },
        ),
        (contractual_record({}), "2026-01-01T00:00:00Z", "temporally_indeterminate", "no_usable_dates", None, {}),
    ],
)
def test_contractual_capability(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
    record: dict[str, Any],
    effective_at: str,
    value: str,
    reason: str,
    next_reevaluation_at: str | None,
    fields: dict[str, Any],
) -> None:
    result = project_instrument_state(record, policy, effective_at, "2026-02-01T00:00:00Z")
    assert_result(
        result,
        validator=axis_validator,
        assurance_id="acme-assurance",
        value=value,
        reason=reason,
        temporal_model="optional_claimed_interval",
        next_reevaluation_at=next_reevaluation_at,
        expected_fields=fields,
    )


def test_bitemporal_admission_accepts_known_before_and_at_cutoff(policy: AssuranceProjectionPolicy) -> None:
    before = certification_record(recorded_at="2026-01-01T00:00:00Z")
    at_cutoff = certification_record(recorded_at="2026-01-10T00:00:00Z")
    assert project_instrument_state(before, policy, "2026-06-01T00:00:00Z", "2026-01-10T00:00:00Z").axis["value"]
    assert project_instrument_state(at_cutoff, policy, "2026-06-01T00:00:00Z", "2026-01-10T00:00:00Z").axis["value"]


def test_bitemporal_admission_rejects_target_after_cutoff(policy: AssuranceProjectionPolicy) -> None:
    record = certification_record(recorded_at="2026-01-11T00:00:00Z")
    with pytest.raises(AssuranceProjectionError) as exc_info:
        project_instrument_state(record, policy, "2026-06-01T00:00:00Z", "2026-01-10T00:00:00Z")
    assert exc_info.value.code == ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF


def test_effective_at_after_knowledge_cutoff_is_allowed(policy: AssuranceProjectionPolicy) -> None:
    result = project_instrument_state(
        certification_record(),
        policy,
        "2027-02-01T00:00:00Z",
        "2026-01-10T00:00:00Z",
    )
    assert result.axis["value"] == "expired"


def test_numeric_offsets_normalize_to_identical_results(policy: AssuranceProjectionPolicy) -> None:
    record = certification_record()
    utc = project_instrument_state(record, policy, "2026-01-10T00:00:00Z", "2026-01-10T00:00:00Z")
    offset = project_instrument_state(record, policy, "2026-01-10T08:00:00+08:00", "2026-01-10T08:00:00+08:00")
    assert utc == offset


@pytest.mark.parametrize("effective_at,knowledge_cutoff", [(datetime(2026, 1, 10), "2026-01-10T00:00:00Z"), ("2026-01-10T00:00:00Z", datetime(2026, 1, 10))])
def test_naive_datetimes_are_rejected(
    policy: AssuranceProjectionPolicy,
    effective_at: datetime | str,
    knowledge_cutoff: datetime | str,
) -> None:
    with pytest.raises(AssuranceProjectionError) as exc_info:
        project_instrument_state(certification_record(), policy, effective_at, knowledge_cutoff)
    assert exc_info.value.code == ASSURANCE_PROJECTION_DATETIME_NAIVE


def test_malformed_policy_rejected(raw_policy: dict[str, Any]) -> None:
    malformed = deepcopy(raw_policy)
    malformed["policy_id"] = "wrong-policy"
    with pytest.raises(AssuranceProjectionError) as exc_info:
        project_instrument_state(certification_record(), malformed, "2026-01-10T00:00:00Z", "2026-01-10T00:00:00Z")
    assert exc_info.value.code == ASSURANCE_PROJECTION_POLICY_INVALID


def test_missing_class_rule_rejected(raw_policy: dict[str, Any]) -> None:
    missing_rule = deepcopy(raw_policy)
    del missing_rule["class_rules"]["accredited_certification"]
    with pytest.raises(AssuranceProjectionError) as exc_info:
        project_instrument_state(certification_record(), missing_rule, "2026-01-10T00:00:00Z", "2026-01-10T00:00:00Z")
    assert exc_info.value.code == ASSURANCE_PROJECTION_CLASS_RULE_MISSING


def test_inputs_are_unchanged_and_repeated_calls_are_equal(raw_policy: dict[str, Any]) -> None:
    record = certification_record()
    record_before = deepcopy(record)
    policy_before = deepcopy(raw_policy)
    first = project_instrument_state(record, raw_policy, "2026-06-01T00:00:00Z", "2026-01-10T00:00:00Z")
    second = project_instrument_state(record, raw_policy, "2026-06-01T00:00:00Z", "2026-01-10T00:00:00Z")
    assert first == second
    assert record == record_before
    assert raw_policy == policy_before


def test_projection_function_has_no_clock_network_or_write_calls() -> None:
    source = inspect.getsource(assurance_projection)
    forbidden_tokens = [
        ".now(",
        ".utcnow(",
        "urlopen",
        "requests.",
        "socket.",
        ".write(",
        "open(",
    ]
    assert [token for token in forbidden_tokens if token in source] == []


def test_axis_schema_is_the_locked_slice3a_contract(axis_validator: Draft202012Validator) -> None:
    schema = load_schema(ROOT / "schemas/openva/assurance-projection.schema.json")
    assert schema["$defs"]["instrumentStateAxis"]["properties"]["interval_end_exclusive_at"]["format"] == "date-time"
    result = project_instrument_state(
        certification_record(),
        load_assurance_projection_policy(),
        "2026-06-01T00:00:00Z",
        "2026-01-10T00:00:00Z",
    )
    assert sorted(axis_validator.iter_errors(result.axis), key=lambda error: list(error.path)) == []
