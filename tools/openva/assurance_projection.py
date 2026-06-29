from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from tools.openva.assurance_projection_policy import AssuranceProjectionPolicy

ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF = "ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF"
ASSURANCE_PROJECTION_DATETIME_NAIVE = "ASSURANCE_PROJECTION_DATETIME_NAIVE"
ASSURANCE_PROJECTION_POLICY_INVALID = "ASSURANCE_PROJECTION_POLICY_INVALID"
ASSURANCE_PROJECTION_CLASS_RULE_MISSING = "ASSURANCE_PROJECTION_CLASS_RULE_MISSING"


class AssuranceProjectionError(Exception):
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


@dataclass(frozen=True, slots=True)
class InstrumentStateResult:
    axis: Mapping[str, Any]
    next_reevaluation_at: datetime | None


def normalize_aware_datetime(value: datetime | str, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AssuranceProjectionError(
                code=ASSURANCE_PROJECTION_DATETIME_NAIVE,
                instance_path=f"/{field_name}",
                message=f"{field_name} must be a timezone-aware date-time.",
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_DATETIME_NAIVE,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be a timezone-aware date-time.",
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_DATETIME_NAIVE,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be timezone-aware.",
        )
    return parsed.astimezone(UTC)


def parse_source_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path=f"/{field_name}",
            message=f"{field_name} must be an ISO date.",
        ) from exc


def start_of_utc_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def end_exclusive_after_inclusive_date(value: date) -> datetime:
    return start_of_utc_day(value + timedelta(days=1))


def format_utc_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def empty_instrument_axis(*, assurance_id: str, temporal_model: str) -> dict[str, Any]:
    return {
        "determination": "determined",
        "value": None,
        "temporal_model": temporal_model,
        "reason_codes": [],
        "caused_by": {
            "assurance_ids": [assurance_id],
            "assurance_observation_ids": [],
            "source_observation_ids": [],
        },
        "stated_valid_from": None,
        "stated_valid_until": None,
        "interval_start_at": None,
        "interval_end_exclusive_at": None,
        "stated_as_of_date": None,
        "as_of_at": None,
        "stated_reporting_period_start": None,
        "stated_reporting_period_end": None,
        "reporting_period_start_at": None,
        "reporting_period_end_exclusive_at": None,
        "stated_effective_from_claimed": None,
        "stated_effective_until_claimed": None,
        "claimed_interval_start_at": None,
        "claimed_interval_end_exclusive_at": None,
    }


def ensure_target_known_at_cutoff(
    assurance_record: Mapping[str, Any],
    *,
    knowledge_cutoff: datetime,
) -> None:
    assurance_id = assurance_record.get("assurance_id")
    recorded_at_raw = assurance_record.get("recorded_at")
    if not isinstance(recorded_at_raw, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
            instance_path="/recorded_at",
            message="Assurance record has no usable recorded_at timestamp.",
            related_ids=(str(assurance_id),) if isinstance(assurance_id, str) else (),
        )
    recorded_at = normalize_aware_datetime(recorded_at_raw, field_name="recorded_at")
    if recorded_at > knowledge_cutoff:
        raise AssuranceProjectionError(
            code=ASSURANCE_TARGET_NOT_KNOWN_AT_CUTOFF,
            instance_path="/recorded_at",
            message="Assurance record is not known at the supplied knowledge cutoff.",
            related_ids=(assurance_id,) if isinstance(assurance_id, str) else (),
        )


def temporal_model_for_record(
    assurance_record: Mapping[str, Any],
    policy: AssuranceProjectionPolicy,
) -> str:
    assurance_class = assurance_record.get("assurance_class")
    if not isinstance(assurance_class, str):
        raise AssuranceProjectionError(
            code=ASSURANCE_PROJECTION_POLICY_INVALID,
            instance_path="/assurance_class",
            message="Assurance record must define assurance_class.",
        )
    try:
        return policy.temporal_model_for(assurance_class)
    except Exception as exc:
        code = getattr(exc, "code", ASSURANCE_PROJECTION_POLICY_INVALID)
        instance_path = getattr(exc, "instance_path", "")
        related_ids = getattr(exc, "related_ids", ())
        raise AssuranceProjectionError(
            code=code,
            instance_path=instance_path,
            message=str(exc),
            related_ids=tuple(related_ids),
        ) from exc
