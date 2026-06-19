import json
from pathlib import Path

import jsonschema
import pytest

from tools.openva.agent_export import build_agent_exports

SCHEMA = json.loads(Path("schemas/openva/agent-export.schema.json").read_text(encoding="utf-8"))

COMMIT_SHA = "testsha0000000000000000000000000000000000"
GENERATED_AT = "2026-06-12T00:00:00Z"

HASH_BASELINE = "sha256:" + "b" * 64
HASH_CHANGED = "sha256:" + "c" * 64


def subschema(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]}


def make_repo(tmp_path: Path) -> Path:
    vendor_dir = tmp_path / "data" / "vendors" / "example-vendor"
    (vendor_dir / "sources").mkdir(parents=True)
    (vendor_dir / "vendor.yaml").write_text(
        "vendor_id: example-vendor\n"
        "display_name: Example Vendor\n"
        "official_domains:\n"
        "  - vendor.example\n",
        encoding="utf-8",
    )
    (vendor_dir / "sources" / "example-vendor-dpa.yaml").write_text(
        "source_id: example-vendor-dpa\n"
        "vendor_id: example-vendor\n"
        "source_type: dpa\n"
        "source_url: https://vendor.example/legal/dpa\n"
        "canonical_confidence:\n"
        "  class: canonical\n"
        "retrieval:\n"
        "  method: html_page\n"
        "  machine_readable: false\n"
        "change_detection:\n"
        f"  baseline_normalized_text_sha256: {HASH_BASELINE}\n",
        encoding="utf-8",
    )
    (vendor_dir / "sources" / "example-vendor-privacy.yaml").write_text(
        "source_id: example-vendor-privacy\n"
        "vendor_id: example-vendor\n"
        "source_type: privacy_notice\n"
        "source_url: https://vendor.example/privacy\n",
        encoding="utf-8",
    )
    return tmp_path


def write_legal_entity(
    tmp_path: Path,
    *,
    vendor_id: str = "example-vendor",
    entity_id: str = "example-vendor-le",
    registration_number: str = "RC-123456",
    jurisdiction: str = "GB",
    catalog_status: str = "stub",
) -> Path:
    entity_dir = tmp_path / "data" / "vendors" / vendor_id / "legal_entities"
    entity_dir.mkdir(parents=True, exist_ok=True)
    path = entity_dir / f"{entity_id}.yaml"
    path.write_text(
        "schema_version: 0.1.0\n"
        f"entity_id: {entity_id}\n"
        f"vendor_id: {vendor_id}\n"
        "legal_name: Example Vendor Ltd\n"
        f"jurisdiction: {jurisdiction}\n"
        f"registration_number: {registration_number}\n"
        "verification_source_ids: []\n"
        f"catalog_status: {catalog_status}\n"
        "not_advice: true\n",
        encoding="utf-8",
    )
    return path


def write_ledger_event(
    tmp_path: Path,
    *,
    observed_at: str,
    health: str = "reachable",
    normalized_hash: str = HASH_BASELINE,
) -> Path:
    ledger_dir = tmp_path / "maintenance" / "source-observations" / "events"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": "0.1.0",
        "ledger_record_id": f"example-vendor-dpa-{observed_at[:10]}-1-first-observed",
        "vendor_id": "example-vendor",
        "source_id": "example-vendor-dpa",
        "source_url": "https://vendor.example/legal/dpa",
        "observed_at": observed_at,
        "run_id": "1",
        "event_type": "first_observed",
        "change_class": "none",
        "previous_observation_id": None,
        "observation_id": f"example-vendor-dpa-{observed_at[:10]}-1",
        "final_url": "https://vendor.example/legal/dpa",
        "http_status": 200,
        "source_health_status": health,
        "raw_sample_sha256": normalized_hash,
        "normalized_text_sample_sha256": normalized_hash,
        "review_signal": {"required": False, "reason": None},
        "not_advice": True,
    }
    path = ledger_dir / f"{observed_at[:7]}.ndjson"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return ledger_dir


def run_artifact(
    *,
    observed_at: str = "2026-06-10T05:30:00Z",
    health: str = "reachable",
    normalized_hash: str = HASH_CHANGED,
) -> dict:
    return {
        "schema_version": "0.1.0",
        "report_type": "latest_observations_index",
        "sources": [
            {
                "vendor_id": "example-vendor",
                "source_id": "example-vendor-dpa",
                "source_url": "https://vendor.example/legal/dpa",
                "observed_at": observed_at,
                "observation_id": f"example-vendor-dpa-{observed_at[:10]}-9",
                "final_url": "https://vendor.example/legal/dpa",
                "http_status": 200,
                "source_health_status": health,
                "change_class": "none",
                "retrieval_method": "html_page",
                "raw_sample_sha256": normalized_hash,
                "normalized_text_sample_sha256": normalized_hash,
                "review_signal": {"required": False, "reason": None},
                "carried_forward": False,
            }
        ],
    }


def freshness_artifact() -> dict:
    return {
        "sources": [
            {
                "vendor_id": "example-vendor",
                "source_id": "example-vendor-dpa",
                "source_type": "dpa",
                "observed_at": "2026-06-10T05:30:00Z",
                "freshness": {
                    "status": "fresh",
                    "observed_within_sla": True,
                    "age_days": 2,
                    "stale_after_days": 30,
                    "expired_after_days": 90,
                },
            }
        ]
    }


def build(tmp_path: Path, out_name: str = "out", **kwargs) -> Path:
    root = make_repo(tmp_path) if not (tmp_path / "data").exists() else tmp_path
    out = tmp_path / out_name
    ledger_dir = tmp_path / "maintenance" / "source-observations" / "events"
    build_agent_exports(
        root=root,
        out_dir=out,
        commit_sha=COMMIT_SHA,
        generated_at=GENERATED_AT,
        ledger_dir=ledger_dir,
        **kwargs,
    )
    return out


def load(out: Path, rel: str) -> dict:
    return json.loads((out / rel).read_text(encoding="utf-8"))


def dpa_row(out: Path) -> dict:
    vendor = load(out, "vendors/example-vendor.json")
    return {row["source_id"]: row for row in vendor["sources"]}["example-vendor-dpa"]


EXPORT_FILES_AND_DEFS = [
    ("openva-agent-index.json", "agent_index"),
    ("vendors/index.json", "vendors_index"),
    ("vendors/example-vendor.json", "vendor_export"),
    ("sources/index.json", "sources_index"),
    ("observations/latest.json", "observations_latest"),
    ("changes/latest.json", "changes_latest"),
]


def test_every_export_validates_against_schema(tmp_path):
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    out = build(tmp_path, latest_observations=run_artifact(), freshness_report=freshness_artifact())
    for rel, def_name in EXPORT_FILES_AND_DEFS:
        document = load(out, rel)
        jsonschema.validate(document, subschema(def_name))


def test_vendor_export_matches_spec_shape(tmp_path):
    out = build(tmp_path, latest_observations=run_artifact())
    vendor = load(out, "vendors/example-vendor.json")

    assert set(vendor.keys()) == {
        "schema_version",
        "snapshot",
        "vendor_id",
        "canonical_name",
        "domains",
        "catalog_status",
        "sources",
        "not_advice",
    }
    assert vendor["schema_version"] == "0.1.0"
    assert set(vendor["snapshot"].keys()) == {"commit_sha", "generated_at", "digest"}
    assert vendor["snapshot"]["commit_sha"] == COMMIT_SHA
    assert vendor["vendor_id"] == "example-vendor"
    assert vendor["canonical_name"] == "Example Vendor"
    assert vendor["domains"] == ["vendor.example"]
    assert vendor["not_advice"] is True


def test_vendor_export_omits_legal_entities_when_absent(tmp_path):
    # Backward-compatible: a vendor with no legal entities keeps a byte-identical
    # export (no legal_entities key), so the shipped catalogue is unchanged.
    out = build(tmp_path, latest_observations=run_artifact())
    vendor = load(out, "vendors/example-vendor.json")
    assert "legal_entities" not in vendor
    jsonschema.validate(vendor, subschema("vendor_export"))


def test_vendor_export_includes_legal_entities_when_present(tmp_path):
    make_repo(tmp_path)
    write_legal_entity(tmp_path, entity_id="example-vendor-le-b", registration_number="RC-2")
    write_legal_entity(tmp_path, entity_id="example-vendor-le-a", registration_number="RC-1")
    out = build(tmp_path, latest_observations=run_artifact())
    vendor = load(out, "vendors/example-vendor.json")
    jsonschema.validate(vendor, subschema("vendor_export"))
    entities = vendor["legal_entities"]
    # Sorted by entity_id (deterministic), exact public field set, no extra keys.
    assert [e["entity_id"] for e in entities] == ["example-vendor-le-a", "example-vendor-le-b"]
    assert set(entities[0]) == {
        "entity_id", "vendor_id", "legal_name", "jurisdiction",
        "registration_number", "catalog_status", "registered_address",
    }
    assert entities[0]["registration_number"] == "RC-1"
    assert entities[0]["registered_address"] is None  # absent in the record -> null


def test_per_source_projection_from_registry_fields(tmp_path):
    out = build(tmp_path, latest_observations=run_artifact(), freshness_report=freshness_artifact())
    rows = {row["source_id"]: row for row in load(out, "vendors/example-vendor.json")["sources"]}

    decorated = rows["example-vendor-dpa"]
    assert decorated["canonical_confidence"] == "canonical"
    assert decorated["retrieval_method"] == "html_page"
    assert decorated["machine_readable"] is False
    assert decorated["source_health"] == "reachable"
    assert decorated["last_observed_at"] == "2026-06-10T05:30:00Z"

    bare = rows["example-vendor-privacy"]
    assert bare["canonical_confidence"] is None
    assert bare["retrieval_method"] is None
    assert bare["machine_readable"] is None
    assert bare["source_health"] is None
    assert bare["last_observed_at"] is None
    assert bare["material_change_since_baseline"] is None


@pytest.mark.parametrize(
    "committed_observed_at",
    [
        "2026-06-01T05:30:00Z",  # older than the artifact row
        "2026-06-11T05:30:00Z",  # NEWER than the artifact row
    ],
)
def test_run_artifact_wins_and_committed_fallback_is_ignored_entirely(tmp_path, committed_observed_at):
    # The committed event says gated with a different hash; the run artifact
    # says reachable. When the artifact exists it is authoritative regardless
    # of committed-event age or content — a future refactor must not
    # re-prioritize the sparse ledger.
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at=committed_observed_at, health="gated", normalized_hash=HASH_BASELINE)
    out = build(tmp_path, latest_observations=run_artifact(observed_at="2026-06-10T05:30:00Z"))

    row = dpa_row(out)
    assert row["source_health"] == "reachable"
    assert row["last_observed_at"] == "2026-06-10T05:30:00Z"
    assert load(out, "openva-agent-index.json")["observation_input"] == "run_artifact"
    assert load(out, "observations/latest.json")["observation_input"] == "run_artifact"


def test_sparse_ledger_trap_no_change_reobservation_overrides_older_event(tmp_path):
    # Committed ledger still holds the old first_observed event (gated); a
    # later no-change re-observation in the artifact shows reachable.
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z", health="gated")
    out = build(tmp_path, latest_observations=run_artifact(health="reachable"))

    assert dpa_row(out)["source_health"] == "reachable"


def test_committed_events_fallback_only_when_artifact_absent(tmp_path):
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z", health="gated")
    out = build(tmp_path)

    row = dpa_row(out)
    assert row["source_health"] == "gated"
    assert row["last_observed_at"] == "2026-06-01T05:30:00Z"
    assert load(out, "openva-agent-index.json")["observation_input"] == "committed_events_fallback"


def test_no_observation_input_degrades_to_nulls(tmp_path):
    out = build(tmp_path)

    row = dpa_row(out)
    assert row["source_health"] is None
    assert row["last_observed_at"] is None
    assert load(out, "openva-agent-index.json")["observation_input"] == "none"
    assert load(out, "observations/latest.json")["count"] == 0


def test_material_change_since_baseline_truth_table(tmp_path):
    make_repo(tmp_path)

    changed = build(tmp_path, "out-changed", latest_observations=run_artifact(normalized_hash=HASH_CHANGED))
    assert dpa_row(changed)["material_change_since_baseline"] is True

    unchanged = build(tmp_path, "out-unchanged", latest_observations=run_artifact(normalized_hash=HASH_BASELINE))
    assert dpa_row(unchanged)["material_change_since_baseline"] is False

    tbd = build(tmp_path, "out-tbd", latest_observations=run_artifact(normalized_hash="sha256:TBD"))
    assert dpa_row(tbd)["material_change_since_baseline"] is None


def test_changes_latest_always_derives_from_committed_ledger(tmp_path):
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    out = build(tmp_path, latest_observations=run_artifact())

    changes = load(out, "changes/latest.json")
    assert changes["count"] == 1
    assert changes["by_event_type"] == {"first_observed": 1}
    assert changes["sources"][0]["source_id"] == "example-vendor-dpa"
    assert changes["sources"][0]["event_type"] == "first_observed"


def test_observations_latest_merges_freshness(tmp_path):
    out = build(tmp_path, latest_observations=run_artifact(), freshness_report=freshness_artifact())
    observations = load(out, "observations/latest.json")

    assert observations["count"] == 1
    assert observations["sources"][0]["freshness"]["status"] == "fresh"
    assert observations["sources"][0]["freshness"]["observed_within_sla"] is True


def test_not_advice_and_doctrine_everywhere(tmp_path):
    out = build(tmp_path, latest_observations=run_artifact())
    for rel, _ in EXPORT_FILES_AND_DEFS:
        document = load(out, rel)
        assert document["not_advice"] is True, rel
        if "doctrine" in document:
            assert "does not version vendor truth" in document["doctrine"]
