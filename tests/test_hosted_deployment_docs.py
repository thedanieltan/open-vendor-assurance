"""Drift tests for the hosted public-read deployment decision package
(WP-OPENVA-AI-NATIVE-DISTRIBUTION-02).

Locks the decision-only posture so it cannot silently regress into a live/
provisioned claim, keeps the contract <-> schema <-> docs coherent, and holds the
non-advisory and ADR-referencing boundaries. No infrastructure is provisioned by
this package; these tests assert that stays true.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "architecture" / "decisions"
OPS = ROOT / "docs" / "operations"
CONTRACT_PATH = OPS / "contracts" / "hosted-deployment.yaml"
ADR_0006 = DECISIONS / "ADR-0006-hosted-public-read-deployment.md"
SCHEMA_PATH = ROOT / "schemas" / "openva" / "hosted-job-record.schema.json"
EXAMPLES = ROOT / "examples" / "hosted-deployment" / "job-records"

# Mirrors tools/openva/release_smoke.py REQUIRED_LIMITATION_PHRASES.
REQUIRED_LIMITATION_PHRASES = [
    "public-source-only",
    "metadata-first",
    "does not provide legal",
    "vendor-risk advice",
    "private or gated",
    "customer-specific",
    "raw vendor documents",
]

HOSTED_DOCS = [
    OPS / "hosted-deployment-decision.md",
    OPS / "hosted-deployment-architecture.md",
    OPS / "hosted-deployment-job-lifecycle.md",
    OPS / "hosted-deployment-runbook.md",
    OPS / "hosted-deployment-observability.md",
    OPS / "hosted-deployment-cost-envelope.md",
    OPS / "hosted-deployment-implementation-plan.md",
    ROOT / "docs" / "security" / "hosted-deployment-threat-model.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contract() -> dict:
    return yaml.safe_load(_read(CONTRACT_PATH))


# --- ADR-0006 -----------------------------------------------------------------


def test_adr_0006_exists_proposed_and_references_adr_0001():
    text = _read(ADR_0006)
    assert "**Status:** Proposed" in text
    assert "**Status:** Accepted" not in text
    assert "ADR-0001" in text
    # Decision-only posture is explicit.
    assert "No production infrastructure is provisioned" in text


def test_adr_index_adds_0006_as_proposed_and_keeps_accepted_count():
    index = _read(DECISIONS / "README.md")
    assert "ADR-0006" in index
    # The existing five ADRs remain Accepted; ADR-0006 is the only Proposed row.
    assert index.count("| Accepted |") == 5
    assert index.count("| Proposed |") == 1


# --- contract -----------------------------------------------------------------


def test_contract_loads_and_is_decision_only():
    c = _contract()
    assert c["contract"] == "hosted-deployment"
    # Every posture flag asserting provisioning/liveness MUST be false here.
    posture = c["posture"]
    assert posture["decision_only"] is True
    for key in (
        "production_infrastructure_provisioned",
        "hosted_endpoint_live",
        "provider_accepted_by_maintainer",
        "dns_or_tls_configured",
        "production_secrets_created",
    ):
        assert posture[key] is False, f"{key} must be false in a decision-only package"


def test_contract_provider_recommendation_has_baseline_and_alternatives():
    rec = _contract()["provider_recommendation"]
    assert rec["baseline"] == "google-cloud-run"
    assert len(rec["alternatives"]) >= 2
    assert rec["accepted_by_maintainer"] is False


def test_contract_governed_and_referenced_paths_exist():
    c = _contract()
    for rel in c["governed_by"] + [c["source_document"], c["job_record_schema"]]:
        assert (ROOT / rel).exists(), f"contract references missing path: {rel}"


def test_contract_job_states_and_transitions_are_coherent():
    c = _contract()
    states = set(c["job_states"])
    assert set(c["terminal_states"]).issubset(states)
    for src, dests in c["transitions"].items():
        assert src in states
        for dest in dests:
            assert dest in states, f"transition target {dest} not a declared state"


def test_contract_lists_maintainer_decisions_and_slices():
    c = _contract()
    ids = {d["id"] for d in c["maintainer_decisions"]}
    for required in ("provider", "region", "domain", "spend_ceiling", "adr0006_acceptance"):
        assert required in ids
    assert len(c["implementation_slices"]) >= 10


# --- schema + examples --------------------------------------------------------


def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(_read(SCHEMA_PATH))
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def test_job_record_examples_validate():
    validator = _validator()
    files = sorted(EXAMPLES.glob("*.json"))
    assert files, "no job-record example fixtures found"
    for path in files:
        record = json.loads(_read(path))
        errors = [e.message for e in validator.iter_errors(record)]
        assert errors == [], f"{path.name}: {errors}"


def test_job_record_rejects_leaked_content_field():
    # additionalProperties:false must reject any inventory/identity leakage.
    validator = _validator()
    record = json.loads(_read(EXAMPLES / "received.json"))
    record["inventory_row"] = "acme,acme.com"  # forbidden submitted content
    assert list(validator.iter_errors(record)), "leaked content field must fail validation"


def test_job_record_rejects_unknown_state():
    validator = _validator()
    record = json.loads(_read(EXAMPLES / "received.json"))
    record["state"] = "promoted"  # not a declared lifecycle state
    assert list(validator.iter_errors(record)), "unknown state must fail validation"


def test_job_record_requires_not_advice_true():
    validator = _validator()
    record = json.loads(_read(EXAMPLES / "received.json"))
    record["not_advice"] = False
    assert list(validator.iter_errors(record)), "not_advice must be const true"


# --- docs coherence -----------------------------------------------------------


def test_all_hosted_docs_exist_reference_adrs_and_stay_decision_only():
    for path in HOSTED_DOCS:
        assert path.exists(), f"missing hosted-deployment doc: {path}"
        text = _read(path)
        assert "ADR-0001" in text, f"{path.name} must reference ADR-0001"
        assert "ADR-0006" in text, f"{path.name} must reference ADR-0006"
        # Non-advisory marker present.
        assert ("not_advice" in text) or ("non-advisory" in text.lower())
        # Decision-only marker present (no doc claims the service is live).
        # Whitespace-normalised so line wraps never hide the marker.
        flat = " ".join(text.lower().split())
        markers = (
            "decision-only",
            "decision/specification only",
            "not provisioned",
            "nothing here is provisioned",
            "nothing here is built or provisioned",
            "nothing here is deployed, provisioned",
            "no hosted openva endpoint is live",
            "no infrastructure is provisioned",
        )
        assert any(m in flat for m in markers), (
            f"{path.name} must carry a decision-only / not-live marker"
        )


def test_decision_report_preserves_required_limitation_phrases():
    # Whitespace-normalised so a line wrap never splits a required phrase.
    text = " ".join(_read(OPS / "hosted-deployment-decision.md").lower().split())
    for phrase in REQUIRED_LIMITATION_PHRASES:
        assert phrase in text, f"decision report missing required limitation phrase: {phrase}"


def test_implementation_plan_covers_every_contract_slice():
    plan = _read(OPS / "hosted-deployment-implementation-plan.md")
    for slice_def in _contract()["implementation_slices"]:
        slice_id = slice_def["id"]
        short = slice_id.split("-")[1] if "-" in slice_id else slice_id  # e.g. 02A
        assert short in plan or slice_id in plan, f"impl plan missing slice {slice_id}"


def test_threat_model_extends_existing_security_boundaries():
    text = _read(ROOT / "docs" / "security" / "hosted-deployment-threat-model.md")
    assert "ssrf-fetch-boundary.md" in text
    assert "remote-mcp-threat-model.md" in text
    assert "Fail-closed" in text or "fail-closed" in text


def test_observability_doc_lists_prohibited_telemetry_fields():
    text = _read(OPS / "hosted-deployment-observability.md").lower()
    for field in ("request bod", "vendor identity", "inventory row"):
        assert field in text, f"observability doc must prohibit telemetry: {field}"
