from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from tools.openva.schema_registry import ROOT, build_openva_validator

ASSURANCE_PROJECTION_POLICY_INVALID = "ASSURANCE_PROJECTION_POLICY_INVALID"
ASSURANCE_PROJECTION_CLASS_RULE_MISSING = "ASSURANCE_PROJECTION_CLASS_RULE_MISSING"
EXPLICIT_SUPERSESSION_POLICY = MappingProxyType(
    {
        "explicit_links_only": True,
        "infer_from_dates": False,
        "infer_from_framework_match": False,
        "infer_from_identifier_similarity": False,
    }
)

DEFAULT_POLICY_PATH = ROOT / "config/assurance-projection-policy.yaml"
POLICY_SCHEMA_PATH = ROOT / "schemas/openva/assurance-projection-policy.schema.json"


class AssuranceProjectionPolicyError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        instance_path: str = "",
        related_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.instance_path = instance_path
        self.related_ids = related_ids


JsonFrozen = Mapping[str, Any] | tuple[Any, ...] | str | int | float | bool | None


def deep_freeze_json(value: Any) -> JsonFrozen:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): deep_freeze_json(nested) for key, nested in value.items()})
    if isinstance(value, list | tuple):
        return tuple(deep_freeze_json(nested) for nested in value)
    return value


@dataclass(frozen=True, slots=True)
class AssuranceProjectionPolicy:
    data: Mapping[str, Any]

    @property
    def policy_id(self) -> str:
        value = self.data.get("policy_id")
        if not isinstance(value, str):
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_POLICY_INVALID,
                instance_path="/policy_id",
                message="Projection policy must define a string policy_id.",
            )
        return value

    @property
    def policy_version(self) -> str:
        value = self.data.get("policy_version")
        if not isinstance(value, str):
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_POLICY_INVALID,
                instance_path="/policy_version",
                message="Projection policy must define a string policy_version.",
            )
        return value

    @property
    def class_rules(self) -> Mapping[str, Any]:
        value = self.data.get("class_rules")
        if not isinstance(value, Mapping):
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_POLICY_INVALID,
                instance_path="/class_rules",
                message="Projection policy must define class_rules.",
            )
        return value

    def temporal_model_for(self, assurance_class: str) -> str:
        rule = self.class_rules.get(assurance_class)
        if not isinstance(rule, Mapping):
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_CLASS_RULE_MISSING,
                instance_path=f"/class_rules/{assurance_class}",
                message=f"Projection policy has no class rule for {assurance_class!r}.",
                related_ids=(assurance_class,),
            )
        temporal_model = rule.get("temporal_model")
        if not isinstance(temporal_model, str):
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_POLICY_INVALID,
                instance_path=f"/class_rules/{assurance_class}/temporal_model",
                message=f"Projection class rule for {assurance_class!r} has no temporal_model.",
                related_ids=(assurance_class,),
            )
        return temporal_model

    @property
    def supersession(self) -> Mapping[str, Any]:
        value = self.data.get("supersession")
        if not isinstance(value, Mapping):
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_POLICY_INVALID,
                instance_path="/supersession",
                message="Projection policy must define supersession rules.",
            )
        return value

    def require_explicit_supersession_policy(self) -> None:
        supersession = self.supersession
        for key, expected in EXPLICIT_SUPERSESSION_POLICY.items():
            if supersession.get(key) is expected:
                continue
            raise AssuranceProjectionPolicyError(
                code=ASSURANCE_PROJECTION_POLICY_INVALID,
                instance_path=f"/supersession/{key}",
                message=(
                    "Supersession projection v1 requires explicit links only "
                    "and disables inference rules."
                ),
            )


def build_assurance_projection_policy(raw_policy: Mapping[str, Any]) -> AssuranceProjectionPolicy:
    if not isinstance(raw_policy.get("class_rules"), Mapping):
        raise AssuranceProjectionPolicyError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path="/class_rules",
            message="Projection policy must define class_rules.",
        )

    validator = build_openva_validator(POLICY_SCHEMA_PATH)
    errors = sorted(validator.iter_errors(raw_policy), key=lambda error: list(error.path))
    missing_class_errors = [
        error
        for error in errors
        if error.validator == "required" and list(error.path) == ["class_rules"]
    ]
    if missing_class_errors:
        missing_class = str(missing_class_errors[0].message).split("'")[1]
        raise AssuranceProjectionPolicyError(
            code=ASSURANCE_PROJECTION_CLASS_RULE_MISSING,
            instance_path=f"/class_rules/{missing_class}",
            message=f"Projection policy has no class rule for {missing_class!r}.",
            related_ids=(missing_class,),
        )
    if errors:
        error = errors[0]
        instance_path = "/" + "/".join(str(part) for part in error.path) if error.path else ""
        raise AssuranceProjectionPolicyError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path=instance_path,
            message=f"Projection policy is invalid: {error.message}",
        )

    frozen = deep_freeze_json(raw_policy)
    if not isinstance(frozen, Mapping):
        raise AssuranceProjectionPolicyError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            message="Projection policy must be an object.",
        )
    return AssuranceProjectionPolicy(data=frozen)


def load_assurance_projection_policy(path: Path = DEFAULT_POLICY_PATH) -> AssuranceProjectionPolicy:
    with path.open("r", encoding="utf-8") as handle:
        raw_policy = yaml.safe_load(handle)
    if not isinstance(raw_policy, Mapping):
        raise AssuranceProjectionPolicyError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            message=f"{path} must contain a mapping.",
        )
    return build_assurance_projection_policy(raw_policy)
