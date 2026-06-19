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


def _alt_ids(rec) -> set:
    out = set()
    for a in rec["alternatives"]:
        out.add(a["id"] if isinstance(a, dict) else a)
    return out


def test_contract_provider_recommendation_has_baseline_and_alternatives():
    rec = _contract()["provider_recommendation"]
    # Reassessed across review #402 rounds: converged on Cloud Run (container worker)
    # — Lambda's 15-min ceiling + best-effort gateway make it an alternative only.
    assert rec["baseline"] == "google-cloud-run"
    alts = _alt_ids(rec)
    assert {"azure-container-apps", "aws-lambda-container"} <= alts
    assert rec["worker_execution"] == "long_running_container"
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


# --- remediation locks (independent review #402) ------------------------------


def test_schema_models_capability_envelope_and_has_no_expired_state():
    schema = json.loads(_read(SCHEMA_PATH))
    props = schema["properties"]
    states = props["state"]["enum"]
    assert "expired" not in states, "expiry is time-based, not a persisted state"
    assert "job_token_digest" in props and "job_token_digest" in schema["required"]
    assert "request_ref" in props
    # Review #402: no content-derived dedup key AND no dedup field at all in v1.
    assert "request_digest" not in props, "content-derived dedup key must be removed"
    assert "idempotency_key_digest" not in props, "no deduplication in v1"
    # Job records are verify-only (cached mode is synchronous).
    assert props["freshness_mode"].get("const") == "verify"
    # job_id must be described as NOT a credential (capability is job_token).
    assert "not an access credential" in props["job_id"]["description"].lower()
    # Round 3: do not over-claim UUIDv4 while accepting any UUID shape.
    assert "uuidv4" not in props["job_id"]["description"].lower()


def test_schema_enforces_state_dependent_invariants():
    validator = _validator()
    base = json.loads(_read(EXAMPLES / "received.json"))

    def fails(mutate):
        rec = json.loads(json.dumps(base))
        mutate(rec)
        return bool(list(validator.iter_errors(rec)))

    # completed with no result_ref must fail.
    assert fails(lambda r: (r.update({"state": "completed", "request_ref": None}),))
    # failed with no error_code must fail.
    assert fails(lambda r: (r.update({"state": "failed", "request_ref": None, "result_ref": None}),))
    # terminal state retaining a request_ref must fail.
    assert fails(lambda r: (r.update({"state": "completed", "result_ref": "result/x"}),))  # request_ref still set
    # non-terminal state without a request envelope must fail.
    assert fails(lambda r: r.update({"request_ref": None}))
    # cached job record must fail (job records are verify-only).
    assert fails(lambda r: r.update({"freshness_mode": "cached"}))
    # a fully valid received record still passes.
    assert not list(validator.iter_errors(base))


def test_contract_idempotency_has_no_dedup_in_v1():
    idem = _contract()["idempotency"]
    assert idem["deduplication_in_v1"] is False
    assert idem["cross_caller_dedup"] is False
    assert idem["content_digest_dedup"] is False
    assert idem["default"] == "new_job_per_request"
    # A future key must be a server-keyed HMAC, not a content digest.
    assert idem["deferred_optional_key"]["binding"] == "server_keyed_hmac"


def test_contract_handoff_protocol_has_single_owner_per_transition():
    handoff = _contract()["handoff"]
    assert handoff["state_transitions"] == "compare_and_set"
    # The API owns the normal received -> queued (after enqueue ack).
    assert any("cas_received_to_queued" in step for step in handoff["normal_path"])
    # The worker advances {received|queued} -> executing and acks duplicates.
    assert any("executing" in step for step in handoff["worker"])
    assert "duplicate_delivery" in handoff
    # The reconciler is recovery-only; it never owns the normal transition.
    assert handoff["reconciler"]["role"] == "recovery_only"
    assert handoff["polling_distinguishes"]["received"]
    assert handoff["polling_distinguishes"]["queued"]


def test_contract_models_transient_data_path_and_edge():
    c = _contract()
    # No persisted expired state anywhere.
    assert "expired" not in c["job_states"]
    assert "expired" not in c["terminal_states"]
    # Transient request/result stores and the edge are in the topology.
    for component in ("edge_gateway", "transient_request_store", "transient_result_store"):
        assert component in c["topology_components"], f"topology missing {component}"
    # The request envelope is NOT carried in the queue or the durable record.
    assert c["request_envelope"]["carried_in_queue"] is False
    assert c["request_envelope"]["carried_in_job_record"] is False
    # Result access is a capability distinct from the loggable correlation id.
    assert c["result_access"]["correlation_id"] == "job_id"
    assert c["result_access"]["capability"] == "job_token"
    assert c["result_access"]["stored_as"] == "job_token_digest"
    # Expiry is time-based, not a persisted state.
    assert c["expiry"]["persisted_expired_state"] is False
    # The edge prevents direct-ingress bypass of rate limiting.
    assert c["edge"]["bypass_prevented"] is True
    # The capability token is a prohibited telemetry field.
    assert "job_token" in c["prohibited_telemetry_fields"]


def test_job_lifecycle_defines_envelope_result_access_and_410_expiry():
    text = _read(OPS / "hosted-deployment-job-lifecycle.md")
    low = text.lower()
    assert "transient request" in low and "request envelope" in low
    assert "job_token" in text  # result-access capability
    assert "410" in text  # time-based expiry response
    assert "not a state" in low or "not a persisted state" in low
    assert "expired" not in low.split("## states")[1].split("##")[0]  # no expired state row


def test_architecture_defines_transient_stores_edge_and_capability():
    text = _read(OPS / "hosted-deployment-architecture.md")
    for token in ("transient_request_store", "transient_result_store", "edge_gateway", "job_token"):
        assert token in text, f"architecture must define {token}"
    assert "re-read" in text.lower()  # worker reconstructs the request from the envelope


def test_threat_model_covers_result_access_and_transient_stores():
    text = _read(ROOT / "docs" / "security" / "hosted-deployment-threat-model.md")
    # Strip markdown emphasis so bolded words don't hide phrases.
    low = " ".join(text.lower().replace("*", "").replace("`", "").split())
    assert "job_token" in low
    assert "idor" in low  # the result-access/IDOR threat row
    assert "not an access credential" in low  # job_id is not a credential
    assert "transient request" in low or "request envelope" in low
    assert "bypass" in low  # edge bypass prevention


def test_customer_specific_input_statement_is_accurate():
    # Codex #402: "never handles customer-specific material" is false for a service
    # that accepts uploaded inventories. The accurate framing must be present.
    for path in (OPS / "hosted-deployment-decision.md", OPS / "hosted-deployment-architecture.md"):
        flat = " ".join(_read(path).lower().split())
        assert "transiently processes" in flat, f"{path.name} needs the accurate transient-processing framing"
        assert "never publishes" in flat or "never publishes, logs, retains" in flat
        # The inaccurate claim must be gone.
        assert "never handles private or gated or customer-specific material" not in flat


def test_cost_envelope_uses_bounded_spend_rate_not_hard_cap():
    flat = " ".join(_read(OPS / "hosted-deployment-cost-envelope.md").lower().split())
    assert "no major cloud offers a hard spend cap" in flat
    assert "soft" in flat  # max-instances is a soft cap on Cloud Run
    assert "overrun" in flat  # worst-case overrun window quantified
    assert "load balancer" in flat or "load-balancer" in flat  # edge fixed floor acknowledged
    # The overstated "hard ceiling on worst-case running compute" must be gone.
    assert "hard ceiling on worst-case running compute" not in flat
    # Review #402: the concrete Cloud Run edge floor (~$24/mo), the reassessment,
    # and the accurate best-effort gateway framing must be present.
    assert "$24" in flat or "~$24" in flat
    assert "reassess" in flat
    assert "best-effort" in flat  # API Gateway throttling is best-effort, not a cap
    # The overstated "strongest hard throttle" Lambda claim must be gone.
    assert "strongest hard throttle" not in flat


def test_decision_and_adr_lead_with_cloud_run_baseline():
    for path in (OPS / "hosted-deployment-decision.md", ADR_0006):
        flat = " ".join(_read(path).lower().split())
        assert "google cloud run" in flat
        assert "reassess" in flat  # the baseline reassessment is explicit
        # Lambda is an alternative that needs fan-out, not the baseline.
        assert "fan-out" in flat or "fan out" in flat
        assert "best-effort" in flat  # accurate gateway framing


def test_job_lifecycle_has_no_dedup_and_documents_recovery():
    flat = " ".join(_read(OPS / "hosted-deployment-job-lifecycle.md").lower().split())
    assert "no deduplication in v1" in flat
    assert "no content-derived dedup key" in flat
    assert "request_digest" not in flat  # the unsafe content key is gone
    assert "reconciler is recovery-only" in flat or "recovery only" in flat
    assert "compare-and-set" in flat or "cas " in flat
    assert "state invariants" in flat


def test_adr_lifecycle_supports_proposed_on_main_via_status_change():
    index = _read(DECISIONS / "README.md")
    low = index.lower()
    assert "non-authoritative" in low
    assert "status-change pr" in low
    adr = _read(ADR_0006).lower()
    assert "non-authoritative" in adr
    assert "status-change pr" in adr


def test_baseline_is_consistent_across_files():
    # Codex #402 r3: cross-file semantic agreement, not token presence. After the
    # reassessment, every file names Google Cloud Run as the baseline.
    c = _contract()
    assert c["provider_recommendation"]["baseline"] == "google-cloud-run"
    prov = next(d for d in c["maintainer_decisions"] if d["id"] == "provider")
    assert str(prov["recommended"]).startswith("google-cloud-run")
    for path in (ADR_0006, OPS / "hosted-deployment-decision.md", OPS / "hosted-deployment-cost-envelope.md"):
        flat = " ".join(_read(path).lower().split())
        assert "google cloud run" in flat
        # No file declares Lambda/AWS as THE baseline.
        assert "aws lambda (baseline)" not in flat
        assert "lambda (container) (baseline)" not in flat
        assert "aws lambda container (baseline)" not in flat


def test_no_request_digest_field_anywhere():
    targets = HOSTED_DOCS + [ADR_0006, CONTRACT_PATH, SCHEMA_PATH] + list(EXAMPLES.glob("*.json"))
    for path in targets:
        assert "request_digest" not in _read(path), (
            f"{path.name} still references the removed request_digest field"
        )
