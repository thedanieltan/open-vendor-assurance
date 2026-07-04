import copy
import json
import subprocess

import pytest

from tools.openva.discovery_ledger import (
    AUTOMERGE_OBSERVATION_LABEL,
    DISCOVERY_LEDGER_LABEL,
    append_events,
    check_discovery_automerge,
)


def event(event_id="a" * 32):
    return {
        "schema_version": "0.1.0",
        "discovery_event_id": event_id,
        "candidate_id": "example-dpa-123",
        "vendor_id": "example",
        "source_type": "dpa",
        "origin": "source_discovery",
        "candidate_url": "https://example.test/dpa",
        "evidence_digest": "sha256:" + "b" * 64,
        "classification": "strong_same_authority_canonical_url",
        "reason_codes": ["strong_same_authority_canonical_url"],
        "retry_after": None,
        "supersedes": None,
        "discovered_at": "2026-06-14T00:00:00Z",
        "discovery_run_id": "run-1",
        "policy_version": "source_discovery_registry_0.2.0",
        "not_advice": True,
    }


def test_discovery_ledger_rejects_duplicate_event_id(tmp_path):
    ledger = tmp_path / "maintenance/discovery-events"
    append_events([event()], ledger)

    with pytest.raises(ValueError, match="duplicate_existing_event_id"):
        append_events([event()], ledger)


def test_discovery_ledger_rejects_invalid_event(tmp_path):
    invalid = copy.deepcopy(event())
    invalid["evidence_digest"] = "md5:bad"

    with pytest.raises(ValueError, match="evidence_digest_invalid"):
        append_events([invalid], tmp_path / "maintenance/discovery-events")


def test_discovery_ledger_enforces_max_append_count(tmp_path):
    with pytest.raises(ValueError, match="too_many_discovery_events"):
        append_events([event("a" * 32), event("b" * 32)], tmp_path / "events", max_append_count=1)


LABELS = [DISCOVERY_LEDGER_LABEL, AUTOMERGE_OBSERVATION_LABEL]
DISCOVERY_PATH = "maintenance/discovery-events/2026-07.ndjson"


def ndjson(rows):
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def loader_for(base_by_path, head_by_path):
    def loader(ref: str, path: str) -> str:
        source = base_by_path if ref == "BASE" else head_by_path
        if path not in source:
            raise subprocess.CalledProcessError(128, ["git", "show"])
        return source[path]

    return loader


def check(paths, base_by_path=None, head_by_path=None, labels=None, existing_ids=None):
    return check_discovery_automerge(
        paths,
        labels or LABELS,
        "BASE",
        "HEAD",
        loader=loader_for(base_by_path or {}, head_by_path or {}),
        list_paths=lambda _ref: sorted((base_by_path or {}).keys()),
        committed_event_ids=existing_ids if existing_ids is not None else set(),
    )


def test_discovery_automerge_accepts_clean_monthly_append():
    new_event = event("c" * 32)
    result = check([DISCOVERY_PATH], head_by_path={DISCOVERY_PATH: ndjson([new_event])})

    assert result.eligible, result.reasons
    assert result.appended_rows == 1


def test_discovery_automerge_requires_discovery_label_pair():
    result = check(
        [DISCOVERY_PATH],
        head_by_path={DISCOVERY_PATH: ndjson([event("c" * 32)])},
        labels=[AUTOMERGE_OBSERVATION_LABEL],
    )

    assert result.eligible is False
    assert f"missing_label:{DISCOVERY_LEDGER_LABEL}" in result.reasons


def test_discovery_automerge_rejects_non_discovery_paths():
    rejected = [
        "data/vendors/example/vendor.yaml",
        "data/vendors/example/sources/example.yaml",
        "maintenance/source-observations/events/2026-07.ndjson",
        "maintenance/machine-decisions/2026-07.ndjson",
        "indexes/sources.json",
        "site/dist/index.html",
    ]
    result = check(rejected)

    assert result.eligible is False
    for path in rejected:
        assert f"disallowed_path:{path}" in result.reasons


def test_discovery_automerge_rejects_non_monthly_discovery_paths():
    for path in (
        "maintenance/discovery-events/current.ndjson",
        "maintenance/discovery-events/2026-7.ndjson",
        "maintenance/discovery-events/2026-07.json",
    ):
        result = check([path])
        assert result.eligible is False
        assert f"disallowed_path:{path}" in result.reasons


def test_discovery_automerge_enforces_append_only_existing_lines():
    base = ndjson([event("a" * 32)])
    tampered = ndjson([event("b" * 32)])

    result = check([DISCOVERY_PATH], {DISCOVERY_PATH: base}, {DISCOVERY_PATH: tampered})

    assert result.eligible is False
    assert any("not_append_only" in reason for reason in result.reasons)


def test_discovery_automerge_rejects_duplicate_delta_event_id():
    duplicate = event("d" * 32)
    result = check([DISCOVERY_PATH], head_by_path={DISCOVERY_PATH: ndjson([duplicate, duplicate])})

    assert result.eligible is False
    assert "duplicate_delta_event_id:" + "d" * 32 in result.reasons


def test_discovery_automerge_rejects_existing_committed_event_id():
    duplicate = event("e" * 32)
    result = check(
        [DISCOVERY_PATH],
        head_by_path={DISCOVERY_PATH: ndjson([duplicate])},
        existing_ids={"e" * 32},
    )

    assert result.eligible is False
    assert "duplicate_existing_event_id:" + "e" * 32 in result.reasons


def test_discovery_automerge_rejects_invalid_json_and_event_ids():
    result = check([DISCOVERY_PATH], head_by_path={DISCOVERY_PATH: "{not-json}\n"})

    assert result.eligible is False
    assert any("invalid_json" in reason for reason in result.reasons)

    invalid = event("not-a-valid-id")
    result = check([DISCOVERY_PATH], head_by_path={DISCOVERY_PATH: ndjson([invalid])})

    assert result.eligible is False
    assert any("discovery_event_id_invalid" in reason for reason in result.reasons)


def test_discovery_automerge_rejects_advisory_rows():
    invalid = event("f" * 32)
    invalid["not_advice"] = False
    result = check([DISCOVERY_PATH], head_by_path={DISCOVERY_PATH: ndjson([invalid])})

    assert result.eligible is False
    assert any("not_advice_not_true" in reason for reason in result.reasons)

    promotional = event("1" * 32)
    promotional["classification"] = "recommended"
    result = check([DISCOVERY_PATH], head_by_path={DISCOVERY_PATH: ndjson([promotional])})

    assert result.eligible is False
    assert any("advisory_term:classification:recommended" in reason for reason in result.reasons)
