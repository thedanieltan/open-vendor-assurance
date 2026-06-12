import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml

from tools.openva.contribution_intake import ADVISORY_RE
from tools.openva.observation_ledger import (
    DOCTRINE,
    append_ledger,
    build_change_events,
    build_changed_report,
    build_freshness_report,
    build_latest_index,
    build_observation_records,
    build_review_report,
    classify_change,
    load_ledger_baseline,
    load_sla_config,
    query_events,
    stale_sources,
)

OBSERVED_AT = "2026-06-12T05:30:00Z"
NOW = datetime(2026, 6, 12, 6, 0, 0, tzinfo=UTC)
RUN_ID = "12345"

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64

LEDGER_SCHEMA = json.loads(
    Path("schemas/openva/observation-ledger-record.schema.json").read_text(encoding="utf-8")
)

SLA_CONFIG = {
    "schema_version": "0.1.0",
    "default": {"stale_after_days": 30, "expired_after_days": 90},
    "source_type_overrides": {
        "subprocessors_list": {"stale_after_days": 14, "expired_after_days": 45},
    },
}


def verification_row(
    *,
    source_id: str = "example-dpa",
    vendor_id: str = "example",
    url: str = "https://vendor.example/legal/dpa",
    final_url: str | None = None,
    status: str = "ok",
    http_status: int = 200,
    raw_hash: str = HASH_A,
    normalized_hash: str = HASH_B,
    content_type: str = "text/html; charset=utf-8",
) -> dict:
    return {
        "vendor_id": vendor_id,
        "source_id": source_id,
        "source_type": "dpa",
        "source_url": url,
        "final_url": final_url or url,
        "http_status": http_status,
        "content_type": content_type,
        "verification_status": status,
        "raw_sample_sha256": raw_hash,
        "normalized_text_sample_sha256": normalized_hash,
        "requires_review": False,
    }


def report_for(rows: list[dict]) -> dict:
    return {"sources": rows, "scope": {"is_partial": True}}


def baseline_entry(
    *,
    source_id: str = "example-dpa",
    observed_at: str = "2026-06-01T05:30:00Z",
    observation_id: str = "example-dpa-2026-06-01-100",
    final_url: str = "https://vendor.example/legal/dpa",
    health: str = "reachable",
    raw_hash: str = HASH_A,
    normalized_hash: str = HASH_B,
) -> dict:
    return {
        "vendor_id": "example",
        "source_id": source_id,
        "source_url": "https://vendor.example/legal/dpa",
        "observed_at": observed_at,
        "observation_id": observation_id,
        "final_url": final_url,
        "http_status": 200,
        "source_health_status": health,
        "raw_sample_sha256": raw_hash,
        "normalized_text_sample_sha256": normalized_hash,
        "change_class": "none",
        "retrieval_method": "html_page",
        "review_signal": {"required": False, "reason": None},
    }


def build(rows: list[dict], baseline: dict | None = None, source_records: dict | None = None) -> list[dict]:
    return build_observation_records(
        report_for(rows),
        baseline=baseline or {},
        source_records=source_records or {},
        run_id=RUN_ID,
        observed_at=OBSERVED_AT,
    )


def test_first_observation_chains_and_records_first_observed_event():
    records = build([verification_row()])
    record = records[0]

    assert record["previous_observation_id"] is None
    assert record["first_observed"] is True
    assert record["event_type"] == "first_observed"
    assert record["change_class"] == "none"
    assert record["source_health"]["status"] == "reachable"
    assert record["not_advice"] is True

    events = build_change_events(records)
    assert len(events) == 1
    assert events[0]["event_type"] == "first_observed"
    assert events[0]["change_class"] == "none"


def test_previous_observation_id_chains_from_baseline():
    baseline = {"example-dpa": baseline_entry()}
    record = build([verification_row()], baseline)[0]

    assert record["previous_observation_id"] == "example-dpa-2026-06-01-100"
    assert record["first_observed"] is False
    assert record["change_class"] == "none"
    assert record["event_type"] is None
    assert build_change_events([record]) == []


def test_non_material_change_when_only_raw_sample_drifts():
    baseline = {"example-dpa": baseline_entry()}
    record = build([verification_row(raw_hash=HASH_C)], baseline)[0]

    assert record["change_class"] == "non_material"
    assert record["event_type"] == "non_material_change"
    assert record["review_signal"]["required"] is False


def test_material_possible_without_curated_baseline():
    baseline = {"example-dpa": baseline_entry()}
    record = build([verification_row(raw_hash=HASH_C, normalized_hash=HASH_D)], baseline)[0]

    assert record["change_class"] == "material_possible"
    assert record["event_type"] == "material_possible"
    assert record["material_change"] is None
    assert record["review_signal"] == {"required": True, "reason": "change_class_material_possible"}


def test_material_confirmed_against_curated_baseline():
    baseline = {"example-dpa": baseline_entry()}
    source_records = {
        "example-dpa": {
            "source_id": "example-dpa",
            "source_type": "dpa",
            "change_detection": {"baseline_normalized_text_sha256": HASH_B},
        }
    }
    record = build([verification_row(normalized_hash=HASH_D)], baseline, source_records)[0]

    assert record["change_class"] == "material_confirmed"
    assert record["material_change"] is True
    assert record["event_type"] == "material_confirmed"


def test_persisting_baseline_divergence_does_not_refire_events():
    # Content moved away from the curated baseline in a PRIOR run; this run
    # the content is stable. material_change stays true, but no repeat event.
    baseline = {"example-dpa": baseline_entry(normalized_hash=HASH_D)}
    source_records = {
        "example-dpa": {
            "source_id": "example-dpa",
            "source_type": "dpa",
            "change_detection": {"baseline_normalized_text_sha256": HASH_B},
        }
    }
    record = build([verification_row(normalized_hash=HASH_D)], baseline, source_records)[0]

    assert record["change_class"] == "none"
    assert record["material_change"] is True
    assert record["event_type"] is None


def test_access_changed_when_source_becomes_gated():
    baseline = {"example-dpa": baseline_entry()}
    record = build(
        [verification_row(status="gated_or_login_required", http_status=401)],
        baseline,
    )[0]

    assert record["source_health"]["status"] == "gated"
    assert record["change_class"] == "access_changed"
    assert record["event_type"] == "access_changed"
    assert record["review_signal"]["required"] is True


def test_redirect_changed_when_final_url_moves():
    baseline = {"example-dpa": baseline_entry()}
    record = build(
        [verification_row(status="redirected", final_url="https://vendor.example/trust/dpa")],
        baseline,
    )[0]

    assert record["change_class"] == "redirect_changed"
    assert record["event_type"] == "redirect_changed"


def test_access_change_takes_precedence_over_content_change():
    baseline = {"example-dpa": baseline_entry()}
    record = build(
        [
            verification_row(
                status="gated_or_login_required",
                http_status=401,
                raw_hash=HASH_C,
                normalized_hash=HASH_D,
            )
        ],
        baseline,
    )[0]

    assert record["change_class"] == "access_changed"
    assert record["event_type"] == "access_changed"


def test_reachable_to_unreachable_is_health_changed_not_access_changed():
    baseline = {"example-dpa": baseline_entry()}
    record = build(
        [verification_row(status="not_found", http_status=404, raw_hash="sha256:TBD", normalized_hash="sha256:TBD")],
        baseline,
    )[0]

    assert record["source_health"]["status"] == "unreachable"
    assert record["change_class"] == "none"
    assert record["event_type"] == "health_changed"
    assert record["review_signal"] == {"required": True, "reason": "source_health_unreachable"}


def test_classify_change_precedence_is_deterministic():
    previous = baseline_entry()
    change_class, _ = classify_change(
        previous=previous,
        health="gated",
        final_url="https://vendor.example/moved",
        raw_hash=HASH_C,
        normalized_hash=HASH_D,
        curated_baseline=HASH_B,
    )
    assert change_class == "access_changed"


def test_partial_scope_carries_forward_unverified_sources():
    baseline = {
        "example-dpa": baseline_entry(),
        "example-privacy": baseline_entry(
            source_id="example-privacy",
            observation_id="example-privacy-2026-06-01-100",
        ),
    }
    records = build([verification_row()], baseline)

    assert [record["source_id"] for record in records] == ["example-dpa"]
    assert build_change_events(records) == []

    latest = build_latest_index(records, baseline, generated_at=OBSERVED_AT)
    by_id = {entry["source_id"]: entry for entry in latest["sources"]}
    assert by_id["example-dpa"]["carried_forward"] is False
    assert by_id["example-dpa"]["observed_at"] == OBSERVED_AT
    assert by_id["example-privacy"]["carried_forward"] is True
    assert by_id["example-privacy"]["observed_at"] == "2026-06-01T05:30:00Z"
    assert latest["summary"] == {"source_count": 2, "observed_this_run": 1, "carried_forward": 1}


def test_freshness_statuses_against_sla_config():
    latest = {
        "sources": [
            baseline_entry(source_id="fresh-source", observed_at="2026-06-10T00:00:00Z"),
            baseline_entry(source_id="stale-source", observed_at="2026-05-01T00:00:00Z"),
            baseline_entry(source_id="expired-source", observed_at="2026-03-01T00:00:00Z"),
            {**baseline_entry(source_id="unknown-source"), "observed_at": None},
            baseline_entry(source_id="subs-source", observed_at="2026-05-23T00:00:00Z"),
        ]
    }
    source_records = {
        "subs-source": {"source_id": "subs-source", "source_type": "subprocessors_list"},
    }
    report = build_freshness_report(latest, SLA_CONFIG, now=NOW, source_records=source_records)
    by_id = {row["source_id"]: row["freshness"] for row in report["sources"]}

    assert by_id["fresh-source"]["status"] == "fresh"
    assert by_id["fresh-source"]["observed_within_sla"] is True
    assert by_id["stale-source"]["status"] == "stale"
    assert by_id["stale-source"]["observed_within_sla"] is False
    assert by_id["expired-source"]["status"] == "expired"
    assert by_id["unknown-source"]["status"] == "unknown"
    # 20 days old: fresh under the 30d default, stale under the 14d override.
    assert by_id["subs-source"]["status"] == "stale"
    assert by_id["subs-source"]["stale_after_days"] == 14
    assert report["summary"] == {"fresh": 1, "stale": 2, "expired": 1, "unknown": 1}


def test_repo_sla_config_parses_with_expected_defaults():
    config = load_sla_config(Path("config/observation-sla.yaml"))
    assert config["default"] == {"stale_after_days": 30, "expired_after_days": 90}
    assert config["source_type_overrides"]["subprocessors_list"] == {
        "stale_after_days": 14,
        "expired_after_days": 45,
    }


def test_reports_are_deterministic_and_carry_doctrine():
    baseline = {"example-dpa": baseline_entry()}
    rows = [verification_row(raw_hash=HASH_C, normalized_hash=HASH_D)]

    def all_reports():
        records = build(rows, dict(baseline))
        latest = build_latest_index(records, baseline, generated_at=OBSERVED_AT)
        return [
            latest,
            build_freshness_report(latest, SLA_CONFIG, now=NOW, source_records={}),
            build_changed_report(records, generated_at=OBSERVED_AT),
            build_review_report(records, generated_at=OBSERVED_AT),
        ]

    first = all_reports()
    second = all_reports()
    assert first == second
    for payload in first:
        assert payload["doctrine"] == DOCTRINE
        assert payload["not_advice"] is True
        assert not ADVISORY_RE.search(json.dumps(payload))


def test_changed_and_review_reports_filter_correctly():
    baseline = {
        "example-dpa": baseline_entry(),
        "example-privacy": baseline_entry(
            source_id="example-privacy",
            observation_id="example-privacy-2026-06-01-100",
        ),
    }
    records = build(
        [
            verification_row(raw_hash=HASH_C, normalized_hash=HASH_D),
            verification_row(source_id="example-privacy", url="https://vendor.example/legal/dpa"),
        ],
        baseline,
    )
    changed = build_changed_report(records, generated_at=OBSERVED_AT)
    review = build_review_report(records, generated_at=OBSERVED_AT)

    assert changed["summary"]["changed_count"] == 1
    assert changed["summary"]["by_change_class"] == {"material_possible": 1}
    assert review["summary"]["review_required_count"] == 1
    assert review["sources"][0]["source_id"] == "example-dpa"


def test_ledger_events_validate_against_schema():
    baseline = {"example-dpa": baseline_entry()}
    records = build([verification_row(raw_hash=HASH_C, normalized_hash=HASH_D)], baseline)
    for event in build_change_events(records):
        jsonschema.validate(event, LEDGER_SCHEMA)


def test_append_ledger_routes_by_month_and_is_append_only(tmp_path):
    ledger_dir = tmp_path / "events"
    baseline = {"example-dpa": baseline_entry()}
    first_delta = build_change_events(
        build([verification_row(raw_hash=HASH_C, normalized_hash=HASH_D)], baseline)
    )

    touched = append_ledger(first_delta, ledger_dir)
    assert [path.name for path in touched] == ["2026-06.ndjson"]
    original_bytes = (ledger_dir / "2026-06.ndjson").read_bytes()

    later = [dict(first_delta[0])]
    later[0]["observed_at"] = "2026-07-01T05:30:00Z"
    later[0]["ledger_record_id"] = "example-dpa-2026-07-01-12345-material-possible"
    later[0]["observation_id"] = "example-dpa-2026-07-01-12345"
    append_ledger(later, ledger_dir)

    # Existing lines are preserved byte-for-byte; new month gets its own file.
    assert (ledger_dir / "2026-06.ndjson").read_bytes() == original_bytes
    assert (ledger_dir / "2026-07.ndjson").exists()

    with pytest.raises(ValueError, match="duplicate ledger_record_id"):
        append_ledger(later, ledger_dir)

    out_of_order = [dict(later[0])]
    out_of_order[0]["observed_at"] = "2026-05-01T05:30:00Z"
    out_of_order[0]["ledger_record_id"] = "example-dpa-2026-05-01-12345-material-possible"
    with pytest.raises(ValueError, match="out-of-order append refused"):
        append_ledger(out_of_order, ledger_dir)

    replayed = load_ledger_baseline(ledger_dir)
    assert replayed["example-dpa"]["observed_at"] == "2026-07-01T05:30:00Z"


def test_query_modes_filter_ledger_events():
    events = [
        {"source_id": "a", "observed_at": "2026-06-01T00:00:00Z", "event_type": "material_possible"},
        {"source_id": "b", "observed_at": "2026-06-05T00:00:00Z", "event_type": "access_changed"},
        {"source_id": "c", "observed_at": "2026-06-08T00:00:00Z", "event_type": "redirect_changed"},
        {"source_id": "d", "observed_at": "2026-05-01T00:00:00Z", "event_type": "material_confirmed"},
    ]

    assert [event["source_id"] for event in query_events(events, changed_since="2026-06-01")] == ["a", "b", "c"]
    assert [event["source_id"] for event in query_events(events, access_changed=True)] == ["b"]
    assert [event["source_id"] for event in query_events(events, redirect_changed=True)] == ["c"]
    assert [event["source_id"] for event in query_events(events, material_change=True)] == ["d", "a"]


def test_stale_by_sla_query_lists_stale_expired_and_unknown():
    latest = {
        "sources": [
            baseline_entry(source_id="fresh-source", observed_at="2026-06-10T00:00:00Z"),
            baseline_entry(source_id="stale-source", observed_at="2026-05-01T00:00:00Z"),
            {**baseline_entry(source_id="unknown-source"), "observed_at": None},
        ]
    }
    rows = stale_sources(latest, SLA_CONFIG, now=NOW, source_records={})
    assert sorted(row["source_id"] for row in rows) == ["stale-source", "unknown-source"]


def test_workflow_extension_is_read_only():
    # Central WP32 boundary: the workflow gains report steps and artifacts
    # only. It must keep read-only permissions and must never commit ledger
    # files; committed ledger rows enter only via reviewed-PR append.
    path = Path(".github/workflows/source-maintenance-report.yml")
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert "tools.openva.observation_ledger build" in text
    assert "observation-ledger/observation-ledger-delta.ndjson" in text
    assert "observation-ledger/latest-observations.json" in text
    assert "observation-ledger/source-freshness-report.json" in text
    assert "observation-ledger/changed-since-last-observation.json" in text
    assert "observation-ledger/sources-requiring-review.json" in text
    assert "observation_ledger append" not in text
    assert "git commit" not in text
    assert "git push" not in text
    assert "create-pull-request" not in text
    assert "maintenance/source-observations" not in text


def test_observation_ledger_doc_states_doctrine_and_boundaries():
    text = Path("docs/observation-ledger.md").read_text(encoding="utf-8")

    assert DOCTRINE.split(". ")[0] in text
    assert "does not version vendor truth" in text
    assert "reviewed pull request" in text
    assert "maintenance/source-observations/events/YYYY-MM.ndjson" in text
    assert "No raw document archive" in text
    assert "No automatic canonical source replacement" in text
    assert "first_observed" in text
    assert "health_changed" in text
    assert "docs/observation-ledger.md" in Path("docs/index.md").read_text(encoding="utf-8")
