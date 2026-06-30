from __future__ import annotations

import inspect
from copy import deepcopy
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva import assurance_projection
from tools.openva.assurance_projection import (
    ASSURANCE_PROJECTION_DATETIME_NAIVE,
    ASSURANCE_PROJECTION_INPUT_INVALID,
    ASSURANCE_PROJECTION_POLICY_INVALID,
    ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
    AssuranceProjectionError,
    ProjectionInputInvalidError,
    SupersessionStateResult,
    project_supersession_state,
)
from tools.openva.assurance_projection_policy import (
    AssuranceProjectionPolicy,
    load_assurance_projection_policy,
)
from tools.openva.schema_registry import ROOT, build_openva_schema_registry

POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
AXIS_SCHEMA = {
    "$ref": "https://openva.dev/schemas/openva/assurance-projection.schema.json#/$defs/supersessionStateAxis"
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


def assurance_record(
    assurance_id: str,
    *,
    vendor_id: str = "acme",
    recorded_at: str = "2026-01-01T00:00:00Z",
    supersedes: str | None = None,
    assurance_class: str = "regulatory_assertion",
    framework_id: str = "example_framework",
    source_id: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": "0.1.1",
        "assurance_id": assurance_id,
        "vendor_id": vendor_id,
        "assurance_class": assurance_class,
        "framework": {"framework_id": framework_id},
        "subject": {
            "entity_name": f"{vendor_id} Example Pte. Ltd.",
            "scope_description": "Example public assurance scope.",
        },
        "temporal_scope": {},
        "evidence": {"source_ids": [source_id or f"{vendor_id}-source-{assurance_id}"]},
        "advisory_boundary": "non_advisory",
        "recorded_at": recorded_at,
    }
    if supersedes is not None:
        record["supersedes_assurance_id"] = supersedes
    if assurance_class == "accredited_certification":
        record["issuer"] = {
            "name": "Example Certification Body",
            "authority_type": "certification_body",
            "country": "SG",
        }
        record["identifiers"] = {"certificate_number": f"{assurance_id.upper()}-CERT"}
        record["temporal_scope"] = {
            "issued_at": "2026-01-01",
            "valid_from": "2026-01-01",
            "valid_until": "2026-12-31",
        }
    return record


def project(
    target: dict[str, Any],
    records: list[dict[str, Any]],
    policy: AssuranceProjectionPolicy | dict[str, Any],
    cutoff: str = "2026-06-01T00:00:00Z",
) -> SupersessionStateResult:
    return project_supersession_state(target, records, policy, cutoff)


def assert_axis(
    result: SupersessionStateResult,
    *,
    validator: Draft202012Validator,
    target_id: str,
    value: str,
    topology: str,
    predecessor: str | None,
    successors: list[str],
    reason: str,
    caused_by: list[str],
) -> None:
    errors = sorted(result.axis and validator.iter_errors(result.axis), key=lambda error: list(error.path))
    assert errors == []
    assert result.axis == {
        "determination": "determined",
        "value": value,
        "topology": topology,
        "predecessor_assurance_id": predecessor,
        "successor_assurance_ids": successors,
        "reason_codes": [reason],
        "caused_by": {
            "assurance_ids": caused_by,
            "assurance_observation_ids": [],
            "source_observation_ids": [],
        },
    }
    assert target_id in result.axis["caused_by"]["assurance_ids"]
    assert len(result.axis["successor_assurance_ids"]) <= 1


def assert_projection_error_codes(exc: pytest.ExceptionInfo[ProjectionInputInvalidError], codes: list[str]) -> None:
    assert exc.value.code == ASSURANCE_PROJECTION_INPUT_INVALID
    assert [diagnostic.code for diagnostic in exc.value.diagnostics] == codes


@pytest.mark.parametrize(
    "target_id,records,expected",
    [
        (
            "assurance-a",
            [assurance_record("assurance-a")],
            {
                "value": "current",
                "topology": "standalone",
                "predecessor": None,
                "successors": [],
                "reason": "no_explicit_successor_admitted",
                "caused_by": ["assurance-a"],
            },
        ),
        (
            "assurance-a",
            [
                assurance_record("assurance-a"),
                assurance_record("assurance-b", supersedes="assurance-a"),
            ],
            {
                "value": "superseded",
                "topology": "chain_root",
                "predecessor": None,
                "successors": ["assurance-b"],
                "reason": "explicit_successor_admitted",
                "caused_by": ["assurance-a", "assurance-b"],
            },
        ),
        (
            "assurance-b",
            [
                assurance_record("assurance-a"),
                assurance_record("assurance-b", supersedes="assurance-a"),
                assurance_record("assurance-c", supersedes="assurance-b"),
            ],
            {
                "value": "superseded",
                "topology": "chain_intermediate",
                "predecessor": "assurance-a",
                "successors": ["assurance-c"],
                "reason": "explicit_successor_admitted",
                "caused_by": ["assurance-b", "assurance-a", "assurance-c"],
            },
        ),
        (
            "assurance-b",
            [
                assurance_record("assurance-a"),
                assurance_record("assurance-b", supersedes="assurance-a"),
            ],
            {
                "value": "current",
                "topology": "chain_tip",
                "predecessor": "assurance-a",
                "successors": [],
                "reason": "no_explicit_successor_admitted",
                "caused_by": ["assurance-b", "assurance-a"],
            },
        ),
    ],
)
def test_valid_supersession_topologies(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
    target_id: str,
    records: list[dict[str, Any]],
    expected: dict[str, Any],
) -> None:
    target = next(record for record in records if record["assurance_id"] == target_id)
    result = project(target, records, policy)
    assert_axis(
        result,
        validator=axis_validator,
        target_id=target_id,
        value=expected["value"],
        topology=expected["topology"],
        predecessor=expected["predecessor"],
        successors=expected["successors"],
        reason=expected["reason"],
        caused_by=expected["caused_by"],
    )


def test_successor_recorded_after_cutoff_is_excluded(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    a = assurance_record("assurance-a")
    b = assurance_record("assurance-b", supersedes="assurance-a", recorded_at="2026-06-20T00:00:00Z")
    result = project(a, [a, b], policy, "2026-06-19T23:59:59Z")
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


def test_successor_recorded_at_cutoff_is_admitted(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    a = assurance_record("assurance-a")
    b = assurance_record("assurance-b", supersedes="assurance-a", recorded_at="2026-06-20T00:00:00Z")
    result = project(a, [a, b], policy, "2026-06-20T00:00:00Z")
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="superseded",
        topology="chain_root",
        predecessor=None,
        successors=["assurance-b"],
        reason="explicit_successor_admitted",
        caused_by=["assurance-a", "assurance-b"],
    )


def test_predecessor_recorded_after_cutoff_makes_admitted_target_invalid(
    policy: AssuranceProjectionPolicy,
) -> None:
    a = assurance_record("assurance-a", recorded_at="2026-06-20T00:00:00Z")
    b = assurance_record("assurance-b", supersedes="assurance-a")
    with pytest.raises(ProjectionInputInvalidError) as exc:
        project(b, [a, b], policy, "2026-06-19T23:59:59Z")
    assert_projection_error_codes(exc, ["ASSURANCE_SUPERSEDES_UNKNOWN"])


def test_target_recorded_after_cutoff_is_rejected(policy: AssuranceProjectionPolicy) -> None:
    target = assurance_record("assurance-a", recorded_at="2026-06-20T00:00:00Z")
    with pytest.raises(AssuranceProjectionError) as exc:
        project(target, [target], policy, "2026-06-19T23:59:59Z")
    assert exc.value.code == ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF


def test_target_recorded_at_cutoff_is_admitted(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    target = assurance_record("assurance-a", recorded_at="2026-06-20T00:00:00Z")
    result = project(target, [target], policy, "2026-06-20T00:00:00Z")
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


def test_future_unrelated_records_do_not_affect_projection(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    target = assurance_record("assurance-a")
    future = assurance_record("assurance-z", recorded_at="2026-07-01T00:00:00Z")
    result = project(target, [future, target], policy, "2026-06-01T00:00:00Z")
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


def test_future_invalid_graph_defect_does_not_affect_admitted_snapshot(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    target = assurance_record("assurance-a")
    future_self_cycle = assurance_record(
        "assurance-z",
        supersedes="assurance-z",
        recorded_at="2026-07-01T00:00:00Z",
    )
    result = project(target, [future_self_cycle, target], policy, "2026-06-01T00:00:00Z")
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


def test_numeric_offset_cutoff_equivalent_to_utc(
    policy: AssuranceProjectionPolicy,
) -> None:
    target = assurance_record("assurance-a", recorded_at="2026-06-20T00:00:00+08:00")
    utc_result = project(target, [target], policy, "2026-06-19T16:00:00Z")
    offset_result = project(target, [target], policy, "2026-06-20T00:00:00+08:00")
    assert utc_result == offset_result


def test_naive_cutoff_is_rejected(policy: AssuranceProjectionPolicy) -> None:
    target = assurance_record("assurance-a")
    with pytest.raises(AssuranceProjectionError) as exc:
        project(target, [target], policy, "2026-06-01T00:00:00")
    assert exc.value.code == ASSURANCE_PROJECTION_DATETIME_NAIVE


@pytest.mark.parametrize(
    "records,target_id,codes",
    [
        (
            [assurance_record("assurance-b", supersedes="assurance-a")],
            "assurance-b",
            ["ASSURANCE_SUPERSEDES_UNKNOWN"],
        ),
        (
            [assurance_record("assurance-a", supersedes="assurance-a")],
            "assurance-a",
            ["ASSURANCE_SUPERSEDES_SELF"],
        ),
        (
            [
                assurance_record("assurance-a", vendor_id="acme"),
                assurance_record("assurance-b", vendor_id="beta", supersedes="assurance-a"),
            ],
            "assurance-b",
            ["ASSURANCE_SUPERSEDES_VENDOR_MISMATCH"],
        ),
        (
            [
                assurance_record("assurance-a"),
                assurance_record(
                    "assurance-b",
                    supersedes="assurance-a",
                    assurance_class="accredited_certification",
                    framework_id="hipaa",
                ),
            ],
            "assurance-a",
            ["ASSURANCE_CLASS_FRAMEWORK_INCOMPATIBLE"],
        ),
        (
            [
                assurance_record("assurance-a"),
                assurance_record("assurance-b", supersedes="assurance-a"),
                assurance_record("assurance-c", supersedes="assurance-a"),
            ],
            "assurance-a",
            ["ASSURANCE_SUPERSESSION_DIVERGENT"],
        ),
        (
            [
                assurance_record("assurance-a", supersedes="assurance-b"),
                assurance_record("assurance-b", supersedes="assurance-a"),
            ],
            "assurance-a",
            ["ASSURANCE_SUPERSESSION_CYCLE"],
        ),
    ],
)
def test_invalid_admitted_graphs_fail_closed(
    policy: AssuranceProjectionPolicy,
    records: list[dict[str, Any]],
    target_id: str,
    codes: list[str],
) -> None:
    target = next(record for record in records if record["assurance_id"] == target_id)
    with pytest.raises(ProjectionInputInvalidError) as exc:
        project(target, records, policy)
    assert_projection_error_codes(exc, codes)


def test_valid_explicit_links_policy_is_accepted(
    raw_policy: dict[str, Any],
    axis_validator: Draft202012Validator,
) -> None:
    target = assurance_record("assurance-a")
    result = project(target, [target], raw_policy)
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda policy: policy["supersession"].__setitem__("explicit_links_only", "yes"),
        lambda policy: policy.pop("supersession"),
        lambda policy: policy["supersession"].__setitem__("infer_from_dates", True),
    ],
)
def test_bad_supersession_policy_is_rejected(
    raw_policy: dict[str, Any],
    mutator: Any,
) -> None:
    target = assurance_record("assurance-a")
    malformed_policy = deepcopy(raw_policy)
    mutator(malformed_policy)
    with pytest.raises(AssuranceProjectionError) as exc:
        project(target, [target], malformed_policy)
    assert exc.value.code == ASSURANCE_PROJECTION_POLICY_INVALID


def test_date_relationship_is_not_inferred(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    old = assurance_record(
        "assurance-old",
        assurance_class="accredited_certification",
        framework_id="iso-27001",
    )
    new = assurance_record(
        "assurance-new",
        assurance_class="accredited_certification",
        framework_id="iso-27001",
    )
    result = project(old, [old, new], policy)
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-old",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-old"],
    )


def test_framework_match_is_not_inferred(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    a = assurance_record("assurance-a", framework_id="iso-27001")
    b = assurance_record("assurance-b", framework_id="iso-27001")
    result = project(a, [b, a], policy)
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


def test_identifier_similarity_is_not_inferred(
    policy: AssuranceProjectionPolicy,
    axis_validator: Draft202012Validator,
) -> None:
    a = assurance_record("assurance-a", assurance_class="accredited_certification", framework_id="iso-27001")
    b = assurance_record("assurance-b", assurance_class="accredited_certification", framework_id="iso-27001")
    a["identifiers"] = {"certificate_number": "SHARED-CERT"}
    b["identifiers"] = {"certificate_number": "SHARED-CERT"}
    result = project(a, [b, a], policy)
    assert_axis(
        result,
        validator=axis_validator,
        target_id="assurance-a",
        value="current",
        topology="standalone",
        predecessor=None,
        successors=[],
        reason="no_explicit_successor_admitted",
        caused_by=["assurance-a"],
    )


def test_projector_is_pure_and_deterministic(raw_policy: dict[str, Any]) -> None:
    a = assurance_record("assurance-a")
    b = assurance_record("assurance-b", supersedes="assurance-a")
    records = [a, b]
    target_before = deepcopy(a)
    records_before = deepcopy(records)
    policy_before = deepcopy(raw_policy)

    first = project(a, records, raw_policy)
    second = project(a, [b, a], raw_policy)
    third = project(a, records, raw_policy)

    assert first == second == third
    assert a == target_before
    assert records == records_before
    assert raw_policy == policy_before


def test_projector_source_has_no_clock_network_or_write_calls() -> None:
    source = inspect.getsource(assurance_projection.project_supersession_state)
    assert ".now(" not in source
    assert "urlopen" not in source
    assert "requests" not in source
    assert "socket" not in source
    assert ".write(" not in source
    assert "open(" not in source
