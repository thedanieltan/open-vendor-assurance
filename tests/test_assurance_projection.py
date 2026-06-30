from __future__ import annotations

import inspect
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.openva import assurance_projection
from tools.openva.assurance_projection import (
    ASSURANCE_PROJECTION_CLASS_RULE_MISSING,
    ASSURANCE_PROJECTION_DATETIME_NAIVE,
    ASSURANCE_PROJECTION_POLICY_INVALID,
    ASSURANCE_PROJECTION_POLICY_MISMATCH,
    ASSURANCE_PROJECTION_REQUEST_INVALID,
    ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
    ASSURANCE_TARGET_UNKNOWN,
    AssuranceProjectionError,
    ProjectionInputInvalidError,
    ProjectionPolicyIdentity,
    project_assurance,
    projection_input_digest,
    projection_input_manifest,
    projection_policy_identity,
)
from tools.openva.schema_registry import ROOT, build_openva_validator

PROJECTION_ROOT = ROOT / "tests/fixtures/assurance/projection"
POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policy() -> dict[str, Any]:
    policy = load_yaml(POLICY_PATH)
    assert isinstance(policy, dict)
    return policy


def load_repository(repository_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, dict[str, Any]]] = {
        "vendors": {},
        "sources": {},
        "assurances": {},
    }
    id_field_by_dir = {
        "vendors": "vendor_id",
        "sources": "source_id",
        "assurances": "assurance_id",
    }
    for directory_name, id_field in id_field_by_dir.items():
        directory = repository_root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            assert isinstance(record, dict)
            records[directory_name][record[id_field]] = record
    return records


def valid_expectation_paths() -> list[Path]:
    return sorted((PROJECTION_ROOT / "projection-valid").glob("*/expectations.json"))


def semantic_invalid_expectation_paths() -> list[Path]:
    return sorted((PROJECTION_ROOT / "semantic-invalid").glob("*/expectations.json"))


def assert_projection_valid(projection: dict[str, Any]) -> None:
    errors = sorted(
        build_openva_validator(ROOT / "schemas/openva/assurance-projection.schema.json").iter_errors(projection),
        key=lambda error: list(error.path),
    )
    assert errors == []


def run_fixture_projection(expectation_path: Path, projected_at: str | None = None) -> dict[str, Any]:
    expectation = load_json(expectation_path)
    repository = load_repository(expectation_path.parent / "repository")
    policy = load_policy()
    return dict(
        project_assurance(
            expectation["request"],
            repository,
            policy,
            projected_at or expectation["expected_projection"]["projected_at"],
        )
    )


@pytest.mark.parametrize(
    "expectation_path",
    valid_expectation_paths(),
    ids=lambda path: path.parent.name,
)
def test_projection_valid_fixtures_execute(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    projection = run_fixture_projection(expectation_path)

    assert_projection_valid(projection)
    assert projection["axes"] == expectation["expected_axes"]
    assert projection["next_reevaluation_at"] == expectation["expected_next_reevaluation_at"]
    assert projection["policy"] == expectation["request"]["policy"]
    assert projection["assurance_id"] == expectation["request"]["assurance_id"]
    assert projection["vendor_id"]
    assert projection["projection_profile"] == "openva.assurance-lifecycle.v1"
    assert projection["implemented_axes"] == ["instrument_state", "supersession_state"]
    assert projection["advisory_boundary"] == "non_advisory"
    assert SHA256_PATTERN.fullmatch(projection["input_digest"])
    assert projection["input_digest"] != "sha256:" + "0" * 64

    assert projection == expectation["expected_projection"]


def test_valid_request_and_policy_identity() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    projection = run_fixture_projection(expectation_path)
    _, identity = projection_policy_identity(load_policy())
    assert projection["policy"] == identity.as_mapping()


@pytest.mark.parametrize(
    "mutator,code",
    [
        (lambda request: request.pop("assurance_id"), ASSURANCE_PROJECTION_REQUEST_INVALID),
        (lambda request: request.__setitem__("schema_version", "9.9.9"), ASSURANCE_PROJECTION_REQUEST_INVALID),
        (lambda request: request["policy"].__setitem__("id", "other-policy"), ASSURANCE_PROJECTION_POLICY_MISMATCH),
        (lambda request: request["policy"].__setitem__("version", "9.9.9"), ASSURANCE_PROJECTION_POLICY_MISMATCH),
        (
            lambda request: request["policy"].__setitem__("digest", "sha256:" + "1" * 64),
            ASSURANCE_PROJECTION_POLICY_MISMATCH,
        ),
    ],
)
def test_request_and_policy_mismatch_failures(mutator: Any, code: str) -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    mutator(request)
    with pytest.raises(AssuranceProjectionError) as exc:
        project_assurance(
            request,
            load_repository(expectation_path.parent / "repository"),
            load_policy(),
            expectation["expected_projection"]["projected_at"],
        )
    assert exc.value.code == code


@pytest.mark.parametrize(
    "mutator,expected_code",
    [
        (lambda policy: policy.__setitem__("schema_version", "9.9.9"), ASSURANCE_PROJECTION_POLICY_INVALID),
        (
            lambda policy: policy["class_rules"].pop("accredited_certification"),
            ASSURANCE_PROJECTION_CLASS_RULE_MISSING,
        ),
    ],
)
def test_malformed_policy_failures(mutator: Any, expected_code: str) -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    policy = load_policy()
    mutator(policy)
    expectation = load_json(expectation_path)
    with pytest.raises(AssuranceProjectionError) as exc:
        project_assurance(
            expectation["request"],
            load_repository(expectation_path.parent / "repository"),
            policy,
            expectation["expected_projection"]["projected_at"],
        )
    assert exc.value.code == expected_code


def test_unknown_target_assurance_fails() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    request["assurance_id"] = "missing-assurance"
    with pytest.raises(AssuranceProjectionError) as exc:
        project_assurance(
            request,
            load_repository(expectation_path.parent / "repository"),
            load_policy(),
            expectation["expected_projection"]["projected_at"],
        )
    assert exc.value.code == ASSURANCE_TARGET_UNKNOWN


def test_target_not_known_at_cutoff_fails() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    request["knowledge_cutoff"] = "2026-01-11T00:00:00Z"
    with pytest.raises(AssuranceProjectionError) as exc:
        project_assurance(
            request,
            load_repository(expectation_path.parent / "repository"),
            load_policy(),
            expectation["expected_projection"]["projected_at"],
        )
    assert exc.value.code == ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF


@pytest.mark.parametrize(
    "field",
    ["effective_at", "knowledge_cutoff"],
)
def test_naive_request_datetimes_are_rejected(field: str) -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    request[field] = "2026-06-30T00:00:00"
    with pytest.raises(AssuranceProjectionError) as exc:
        project_assurance(
            request,
            load_repository(expectation_path.parent / "repository"),
            load_policy(),
            expectation["expected_projection"]["projected_at"],
        )
    assert exc.value.code == ASSURANCE_PROJECTION_DATETIME_NAIVE


def test_naive_projected_at_is_rejected() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    with pytest.raises(AssuranceProjectionError) as exc:
        project_assurance(
            expectation["request"],
            load_repository(expectation_path.parent / "repository"),
            load_policy(),
            "2026-07-01T00:00:00",
        )
    assert exc.value.code == ASSURANCE_PROJECTION_DATETIME_NAIVE


def test_numeric_offset_request_timestamps_match_utc_semantics() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    request["effective_at"] = "2026-06-30T08:00:00+08:00"
    request["knowledge_cutoff"] = "2026-06-30T08:00:00+08:00"
    projection = project_assurance(
        request,
        load_repository(expectation_path.parent / "repository"),
        load_policy(),
        "2026-07-01T08:00:00+08:00",
    )
    baseline = run_fixture_projection(expectation_path)
    assert projection["effective_at"] == baseline["effective_at"]
    assert projection["knowledge_cutoff"] == baseline["knowledge_cutoff"]
    assert projection["axes"] == baseline["axes"]


def test_future_effective_time_beyond_knowledge_cutoff_is_allowed() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    request["effective_at"] = "2028-01-01T00:00:00Z"
    projection = project_assurance(
        request,
        load_repository(expectation_path.parent / "repository"),
        load_policy(),
        expectation["expected_projection"]["projected_at"],
    )
    assert projection["effective_at"] > projection["knowledge_cutoff"]
    assert_projection_valid(projection)


def test_projected_at_changes_only_projected_at() -> None:
    expectation_path = PROJECTION_ROOT / "semantic-no-op-rebuild/expectations.json"
    expectation = load_json(expectation_path)
    repository = load_repository(expectation_path.parent / "repository")
    policy = load_policy()
    projection_a = dict(project_assurance(expectation["request"], repository, policy, "2026-07-01T00:00:00Z"))
    projection_b = dict(project_assurance(expectation["request"], repository, policy, "2026-07-02T00:00:00Z"))

    assert projection_a["projected_at"] != projection_b["projected_at"]
    without_projected_at_a = {key: value for key, value in projection_a.items() if key != "projected_at"}
    without_projected_at_b = {key: value for key, value in projection_b.items() if key != "projected_at"}
    assert without_projected_at_a == without_projected_at_b

    assert projection_a == expectation["projection_a"]
    assert projection_b == expectation["projection_b"]


def test_input_digest_stability_and_change_cases() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/linear-supersession-chain/expectations.json"
    expectation = load_json(expectation_path)
    repository = load_repository(expectation_path.parent / "repository")
    policy = load_policy()
    baseline = dict(
        project_assurance(
            expectation["request"],
            repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )
    )

    list_repository = {
        "vendors": list(reversed(list(repository["vendors"].values()))),
        "sources": list(reversed(list(repository["sources"].values()))),
        "assurances": list(reversed(list(repository["assurances"].values()))),
    }
    assert (
        project_assurance(
            expectation["request"],
            list_repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        == baseline["input_digest"]
    )

    reordered_repository = deepcopy(repository)
    target = reordered_repository["assurances"][expectation["request"]["assurance_id"]]
    reordered_repository["assurances"][expectation["request"]["assurance_id"]] = dict(reversed(list(target.items())))
    assert (
        project_assurance(
            expectation["request"],
            reordered_repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        == baseline["input_digest"]
    )

    assert (
        project_assurance(expectation["request"], repository, policy, "2026-08-01T00:00:00Z")["input_digest"]
        == baseline["input_digest"]
    )

    changed_effective_request = deepcopy(expectation["request"])
    changed_effective_request["effective_at"] = "2026-07-01T00:00:00Z"
    assert (
        project_assurance(
            changed_effective_request,
            repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        != baseline["input_digest"]
    )

    changed_cutoff_request = deepcopy(expectation["request"])
    changed_cutoff_request["knowledge_cutoff"] = "2026-07-01T00:00:00Z"
    assert (
        project_assurance(
            changed_cutoff_request,
            repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        != baseline["input_digest"]
    )

    changed_target_repository = deepcopy(repository)
    changed_target_repository["assurances"][expectation["request"]["assurance_id"]]["subject"][
        "scope_description"
    ] = "Changed public assurance scope."
    assert (
        project_assurance(
            expectation["request"],
            changed_target_repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        != baseline["input_digest"]
    )

    changed_admitted_repository = deepcopy(repository)
    changed_admitted_repository["assurances"]["acme-chain-c"]["subject"][
        "scope_description"
    ] = "Changed successor scope."
    assert (
        project_assurance(
            expectation["request"],
            changed_admitted_repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        != baseline["input_digest"]
    )

    future_repository = deepcopy(repository)
    future_record = deepcopy(next(iter(repository["assurances"].values())))
    future_record["assurance_id"] = "future-unadmitted"
    future_record["recorded_at"] = "2026-07-01T00:00:00Z"
    future_repository["assurances"]["future-unadmitted"] = future_record
    future_changed_repository = deepcopy(future_repository)
    future_changed_repository["assurances"]["future-unadmitted"]["subject"][
        "scope_description"
    ] = "Future-only change."
    assert (
        project_assurance(
            expectation["request"],
            future_repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        == baseline["input_digest"]
    )
    assert (
        project_assurance(
            expectation["request"],
            future_changed_repository,
            policy,
            expectation["expected_projection"]["projected_at"],
        )["input_digest"]
        == baseline["input_digest"]
    )

    assert SHA256_PATTERN.fullmatch(baseline["input_digest"])


def test_input_digest_helper_changes_when_policy_identity_changes() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/active-certification/expectations.json"
    expectation = load_json(expectation_path)
    repository = load_repository(expectation_path.parent / "repository")
    _, identity = projection_policy_identity(load_policy())
    baseline_manifest = projection_input_manifest(
        request=expectation["request"],
        repository=repository,
        policy_identity=identity,
        effective_at=assurance_projection.normalize_aware_datetime(
            expectation["request"]["effective_at"],
            field_name="effective_at",
        ),
        knowledge_cutoff=assurance_projection.normalize_aware_datetime(
            expectation["request"]["knowledge_cutoff"],
            field_name="knowledge_cutoff",
        ),
    )
    changed_identity = ProjectionPolicyIdentity(
        id=identity.id,
        version=identity.version,
        digest="sha256:" + "2" * 64,
    )
    changed_manifest = projection_input_manifest(
        request=expectation["request"],
        repository=repository,
        policy_identity=changed_identity,
        effective_at=assurance_projection.normalize_aware_datetime(
            expectation["request"]["effective_at"],
            field_name="effective_at",
        ),
        knowledge_cutoff=assurance_projection.normalize_aware_datetime(
            expectation["request"]["knowledge_cutoff"],
            field_name="knowledge_cutoff",
        ),
    )
    assert projection_input_digest(changed_manifest) != projection_input_digest(baseline_manifest)


@pytest.mark.parametrize(
    "expectation_path",
    semantic_invalid_expectation_paths(),
    ids=lambda path: path.parent.name,
)
def test_semantic_invalid_fixtures_preserve_diagnostics(expectation_path: Path) -> None:
    expectation = load_json(expectation_path)
    with pytest.raises(ProjectionInputInvalidError) as exc:
        project_assurance(
            expectation["request"],
            load_repository(expectation_path.parent / "repository"),
            load_policy(),
            "2026-07-01T00:00:00Z",
        )
    assert [diagnostic.code for diagnostic in exc.value.diagnostics] == [
        diagnostic["code"] for diagnostic in expectation["expected_diagnostics"]
    ]
    assert [diagnostic.record_id for diagnostic in exc.value.diagnostics] == [
        diagnostic["record_ids"][0] for diagnostic in expectation["expected_diagnostics"]
    ]


def test_projection_inputs_are_not_mutated() -> None:
    expectation_path = PROJECTION_ROOT / "projection-valid/linear-supersession-chain/expectations.json"
    expectation = load_json(expectation_path)
    request = deepcopy(expectation["request"])
    repository = load_repository(expectation_path.parent / "repository")
    policy = load_policy()
    request_before = deepcopy(request)
    repository_before = deepcopy(repository)
    policy_before = deepcopy(policy)

    first = project_assurance(request, repository, policy, expectation["expected_projection"]["projected_at"])
    second = project_assurance(request, repository, policy, expectation["expected_projection"]["projected_at"])

    assert first == second
    assert request == request_before
    assert repository == repository_before
    assert policy == policy_before


def test_projector_source_has_no_clock_network_or_write_calls() -> None:
    source = inspect.getsource(assurance_projection.project_assurance)
    assert ".now(" not in source
    assert "time.time" not in source
    assert "urlopen" not in source
    assert "requests" not in source
    assert "socket" not in source
    assert ".write(" not in source
    assert "open(" not in source
