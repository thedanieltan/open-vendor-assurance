"""Drift tests for the hosted public-read deployment decision package
(WP-OPENVA-AI-NATIVE-DISTRIBUTION-02).

Locks the decision-only posture so it cannot silently regress into a live/
provisioned claim, keeps the contract <-> schema <-> docs coherent, and holds the
non-advisory and ADR-referencing boundaries. No infrastructure is provisioned by
this package; these tests assert that stays true.
"""

from __future__ import annotations

import json
import re
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


def test_adr_0006_accepted_and_references_adr_0001():
    text = _read(ADR_0006)
    assert "**Status:** Accepted" in text
    assert "**Status:** Proposed" not in text
    assert "ADR-0001" in text
    # Acceptance authorises the architecture, not provisioning — the decision-only
    # posture stays explicit.
    assert "No production infrastructure is provisioned" in text


def test_adr_index_lists_0006_as_accepted():
    index = _read(DECISIONS / "README.md")
    assert "ADR-0006" in index
    # ADR-0006 is now Accepted via its status-change PR; no ADR row remains Proposed.
    assert index.count("| Accepted |") == 6
    assert index.count("| Proposed |") == 0


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


def _infra_gated_slice_labels() -> set[str]:
    """Slices whose depends_on closure reaches the infrastructure roots (WP-02F
    staging / WP-02G production), which need maintainer-accepted external deployment
    choices. Returned as both label forms (e.g. {"WP-02F", "02F"})."""
    deps = {s["id"]: list(s.get("depends_on") or []) for s in _contract()["implementation_slices"]}
    infra_roots = {"WP-02F-staging-environment", "WP-02G-production-infrastructure"}

    def closure(node: str, seen: set[str]) -> set[str]:
        for parent in deps.get(node, ()):
            if parent not in seen:
                seen.add(parent)
                closure(parent, seen)
        return seen

    labels: set[str] = set()
    for slice_id in deps:
        if ({slice_id} | closure(slice_id, set())) & infra_roots:
            prefix = "-".join(slice_id.split("-")[:2])  # WP-02F-... -> WP-02F
            labels.add(prefix)
            labels.add(prefix.removeprefix("WP-"))       # also the bare 02F form
    return labels


def test_roadmap_does_not_label_infra_gated_slices_currently_buildable():
    # Regression lock (PR #407 re-review): the roadmap must not call a transitively
    # infra-gated slice "buildable/startable now". The sequencing contradiction escaped
    # #406 and the first #407 head; this validates roadmap readiness claims against the
    # contract's implementation_slices.depends_on closure rather than prose review.
    #
    # After the WP-02 sequence reconciliation the provider-neutral application slices
    # (WP-02H application hardening, WP-02I, WP-02J) run BEFORE staging, so their
    # depends_on closure no longer reaches the infra roots — only WP-02F/02G/02K do.
    gated = _infra_gated_slice_labels()
    assert {"WP-02F", "WP-02G", "WP-02K"} <= gated, gated
    # The application-hardening / MCP / live-check slices are NOT infra-gated anymore.
    assert not ({"WP-02H", "WP-02I", "WP-02J"} & gated), gated

    roadmap = _read(ROOT / "docs" / "roadmap.md")
    readiness_markers = ("buildable now", "startable now", "startable at merge", "are buildable")
    flagged: list[tuple[str, str]] = []
    for sentence in re.split(r"(?<=\.)\s+", roadmap):
        low = sentence.lower()
        if not any(marker in low for marker in readiness_markers):
            continue
        for label in sorted(gated):
            if re.search(rf"(?<![0-9A-Za-z]){re.escape(label)}(?![0-9A-Za-z])", sentence):
                flagged.append((label, " ".join(sentence.split())))
    assert not flagged, f"roadmap labels infra-gated slice(s) as currently buildable: {flagged}"


def test_slice_status_is_consistent_with_dependency_closure():
    # Lock the reconciled WP-02 state (items 1/2/4): the merged in-repo slices are
    # `completed`, infra-gated slices match the depends_on closure, and a `startable_now`
    # slice has no incomplete predecessor and is not infra-gated.
    c = _contract()
    slices = {s["id"]: s for s in c["implementation_slices"]}
    status = {sid: s.get("status") for sid, s in slices.items()}

    # The transport (02A), positioning (02L), and async-persistence (02B) slices merged.
    for completed in (
        "WP-02A-hosted-transport-api",
        "WP-02B-async-job-persistence",
        "WP-02L-positioning-reconciliation",
    ):
        assert status[completed] == "completed", f"{completed} must be recorded completed"

    infra_labels = _infra_gated_slice_labels()

    def is_infra(sid: str) -> bool:
        prefix = "-".join(sid.split("-")[:2])  # WP-02F-... -> WP-02F
        return prefix in infra_labels

    completed_ids = {sid for sid, st in status.items() if st == "completed"}
    for sid, st in status.items():
        assert st in {"completed", "startable_now", "blocked", "infra_gated"}, f"{sid}: bad status {st}"
        if st == "infra_gated":
            assert is_infra(sid), f"{sid} is infra_gated but its closure does not reach an infra root"
        if st == "startable_now":
            assert not is_infra(sid), f"{sid} cannot be startable_now and infra-gated"
            deps = slices[sid].get("depends_on") or []
            assert all(d in completed_ids for d in deps), (
                f"{sid} is startable_now but has an incomplete predecessor"
            )
    # Every infra-gated slice is marked infra_gated (no infra slice mislabelled buildable).
    for sid in slices:
        if is_infra(sid):
            assert status[sid] == "infra_gated", f"{sid} reaches infra but is not infra_gated"


def test_cross_cutting_execution_constraints_are_recorded():
    # Item 6: the WP-02 execution constraints are encoded WITHOUT a separate
    # operating-mode work package — they live in the contract as cross-cutting properties.
    cc = _contract()["cross_cutting_execution_constraints"]
    assert cc["provider_neutral_code_before_infrastructure"] is True
    assert cc["hosted_capabilities_disabled_by_default"] is True
    assert cc["deterministic_local_test_paths"] is True
    assert {"queue", "store", "telemetry"} <= set(cc["provider_interfaces"])
    assert {"provider_account", "dns", "tls", "production_secrets", "paid_registry_publication", "public_endpoint"} <= set(
        cc["no_external_provisioning_before_staging"]
    )
    assert {"static_catalogue", "static_mcp", "cached_operation"} <= set(cc["static_layer_unaffected"])
    assert cc["external_decisions_maintainer_controlled"] is True
    assert cc["external_decisions_requested_once_before"] == "WP-02F-staging-environment"


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


# --- independent review round 4 (#402) locks -----------------------------------


def test_transition_graph_actor_scoped_no_received_to_executing():
    t = _contract()["transitions"]
    # received cannot go straight to executing — the worker recovers via queued.
    assert "executing" not in t["received"], "no direct received -> executing edge"
    assert "queued" in t["received"] and "worker" in t["received"]["queued"]
    assert t["queued"]["executing"] == ["worker"]
    # The worker protocol uses only declared edges.
    worker_steps = " ".join(_contract()["handoff"]["worker"])
    assert "received_to_queued" in worker_steps and "queued_to_executing" in worker_steps


def test_execution_lease_and_watchdog_recover_a_crashed_executing_job():
    c = _contract()
    t = c["transitions"]
    # A crashed worker must be recoverable: the watchdog owns the executing exits.
    assert t["executing"]["queued"] == ["watchdog"], "stale-lease takeover -> queued"
    assert "watchdog" in t["executing"]["failed"], "watchdog can time out a stale lease"
    # The lease model exists and is owned by the watchdog for stale recovery.
    lease = c["execution_lease"]
    assert lease["stale_recovery_owner"] == "watchdog"
    assert lease["live_lease_preemption"] == "forbidden"
    assert c["access_matrix"]["watchdog"]["owned_transitions"]
    # The schema makes the lease mandatory while executing and absent otherwise.
    validator = _validator()
    ex = json.loads(_read(EXAMPLES / "executing.json"))
    assert not list(validator.iter_errors(ex))
    no_lease = dict(ex, lease_owner=None, lease_expires_at=None)
    assert list(validator.iter_errors(no_lease)), "executing without a lease must fail"
    leased_received = dict(json.loads(_read(EXAMPLES / "received.json")), lease_owner="w1")
    assert list(validator.iter_errors(leased_received)), "a lease in a non-executing state must fail"


def test_access_matrix_permits_the_documented_request_flow():
    am = _contract()["access_matrix"]
    api = am["public_api"]
    # The API must own its CAS edges and be able to read the result (with a token).
    assert "owned_cas" in api["job_record"]
    assert "received->queued" in api["owned_transitions"]
    assert "job_token" in api["result_blob"]  # result read gated on a valid token
    assert _contract()["result_read_rule"].startswith("no_result_blob_read_without")
    worker = am["async_worker"]
    assert "queued->executing" in worker["owned_transitions"]
    assert "executing->completed" in worker["owned_transitions"]


def test_verify_execution_budget_is_grounded_in_real_resolver_constants():
    # Independent review #402 round 6, Finding 1: the hosted live-verify budget must
    # be derived from the resolver's ACTUAL fetch behaviour, not an invented timeout.
    # Import the executable constants so the contract cannot drift from the code.
    import math

    from tools.openva.vendor_resolution import SAFE_TIMEOUT_SECONDS, _DISCOVERY_PATHS

    c = _contract()
    hv = c["hosted_verify_limits"]
    budget = c["verify_execution_budget"]
    pl = c["platform_limits"]

    # 1) The per-fetch deadline is the REAL resolver timeout, not a lower invention.
    assert budget["per_fetch_deadline_seconds"] == int(SAFE_TIMEOUT_SECONDS), (
        "contract per_fetch_deadline_seconds must equal the resolver's SAFE_TIMEOUT_SECONDS"
    )
    assert SAFE_TIMEOUT_SECONDS == 20.0  # guards against a silent resolver change

    # 2) Worst-case network ops per source type = 1 primary verify fetch + the longest
    #    discovery-fallback path list. Derived from the real _DISCOVERY_PATHS, not assumed.
    max_discovery_paths = max(len(paths) for paths in _DISCOVERY_PATHS.values())
    assert max_discovery_paths == 3  # current resolver: dpa/subprocessors/privacy each have 3
    assert budget["network_ops_per_source_type_worst"] == 1 + max_discovery_paths, (
        "network ops per source type must be 1 (verify) + max discovery-fallback paths"
    )

    # 3) Recompute the worst-case wall time from the grounded inputs and check the
    #    contract's recorded figure has not drifted.
    per_row_seconds = (
        hv["max_source_types_per_verify_row"]
        * budget["network_ops_per_source_type_worst"]
        * budget["per_fetch_deadline_seconds"]
    )
    waves = math.ceil(hv["max_verify_rows"] / hv["verify_row_concurrency"])
    worst_seconds = waves * per_row_seconds + budget["handler_overhead_seconds"]
    assert worst_seconds == budget["worst_case_seconds_v1"], (
        f"recomputed worst case {worst_seconds}s != recorded {budget['worst_case_seconds_v1']}s"
    )

    # 4) Ordering invariant: worst case < per-job budget < the platform dispatch deadline.
    worst_minutes = worst_seconds / 60
    assert (
        worst_minutes
        < pl["baseline_per_job_budget_minutes"]
        < pl["cloud_tasks_http_dispatch_deadline_minutes"]
    ), "verify worst case must fit inside the per-job budget inside the dispatch deadline"
    assert budget["fits_with_margin"] is True

    # 5) The hosted live-verify limit (egress) is DISTINCT from the cached/batch limit
    #    (no egress). Conflating them is exactly the round-6 error.
    assert hv["max_verify_rows"] < c["limits"]["max_rows_cached"]
    # The job record's row_count is bounded by the verify limit, not the cached limit.
    schema = json.loads(_read(SCHEMA_PATH))
    assert schema["properties"]["row_count"]["maximum"] == hv["max_verify_rows"]


def test_watchdog_authority_is_exactly_two_executing_edges():
    # Independent review #402 round 6, Finding 2: the watchdog owns EXACTLY
    # executing->queued and executing->failed — no more. This test fails on EXTRA
    # authority (e.g. a re-introduced queued->failed [watchdog] edge).
    c = _contract()
    t = c["transitions"]

    # Reconstruct every edge the watchdog is granted directly from the transition map.
    watchdog_edges = {
        f"{src}->{dst}"
        for src, dests in t.items()
        for dst, actors in dests.items()
        if "watchdog" in actors
    }
    assert watchdog_edges == {"executing->queued", "executing->failed"}, (
        f"watchdog must own exactly its two executing edges, got {sorted(watchdog_edges)}"
    )

    # The access_matrix must agree exactly (no extra owned_transitions).
    owned = set(c["access_matrix"]["watchdog"]["owned_transitions"])
    assert owned == {"executing->queued", "executing->failed"}, (
        f"access_matrix watchdog owned_transitions must be exactly the two edges, got {sorted(owned)}"
    )

    # A queued record holds no lease, so there is intentionally no queued->failed edge
    # for ANY actor (the watchdog has nothing to recover there).
    assert "failed" not in t["queued"], "queued has no failed edge (queued holds no lease)"


def test_transition_mutations_apply_to_fixtures_and_validate_against_schema():
    # Independent review #402 round 6, Finding 3: every transition is a complete,
    # schema-valid atomic mutation. Apply each mutation's `set` (and envelope delete)
    # to the source-state fixture and assert the result validates.
    c = _contract()
    validator = _validator()
    mutations = c["transition_mutations"]

    # Concrete, schema-valid sample values for the contract's "<placeholder>" tokens.
    samples = {
        "state": None,  # always provided explicitly by the mutation
        "error_code": "execution_timeout",
        "result_ref": "result/9f1c2d3e-4b5a-46c7-8d9e-0a1b2c3d4e5f",
        "lease_owner": "worker-9f1c2d3e-01",
        "lease_expires_at": "2026-06-20T12:05:00Z",
        "updated_at": "2026-06-20T12:02:00Z",
        "attempt": 1,
    }

    def materialize(value, key):
        # Replace "<...>" placeholders with schema-valid concrete values; keep nulls/literals.
        if isinstance(value, str) and value.startswith("<") and value.endswith(">"):
            assert key in samples, f"no sample value for placeholder field {key}"
            return samples[key]
        return value

    fixtures = {p.stem: json.loads(_read(p)) for p in EXAMPLES.glob("*.json")}

    for name, mut in mutations.items():
        src_state = mut["from"]
        assert src_state in fixtures, f"{name}: no source fixture for state {src_state}"
        record = json.loads(json.dumps(fixtures[src_state]))
        # Sanity: the fixture really is in the declared source state.
        assert record["state"] == src_state, f"{name}: fixture state mismatch"

        for field, raw in mut["set"].items():
            record[field] = materialize(raw, field)
        # The optional post-step physically deletes the request envelope -> request_ref null.
        if mut.get("then") == "delete_request_envelope":
            record["request_ref"] = None

        errors = [e.message for e in validator.iter_errors(record)]
        assert errors == [], f"{name}: post-mutation record is not schema-valid: {errors}"

    # Negative: an INCOMPLETE terminal mutation (forgets to clear request_ref) must be
    # rejected by the schema — proving the invariant is enforced, not just documented.
    completed = json.loads(json.dumps(fixtures["executing"]))
    completed.update(
        {
            "state": "completed",
            "result_ref": samples["result_ref"],
            "error_code": None,
            "lease_owner": None,
            "lease_expires_at": None,
        }
    )  # NOTE: request_ref deliberately left set
    assert list(validator.iter_errors(completed)), (
        "a completed record that still carries request_ref must fail validation"
    )


def test_result_token_transport_is_header_only_bearer_capability():
    # Independent review #402 round 6, Finding 4: the job_token is transported
    # header-only as `Authorization: Bearer`, never in a URL/query/path/redirect,
    # redacted in logs, compared in constant time, and not rotated in v1.
    c = _contract()
    tt = c["result_access"]["token_transport"]
    assert tt["mechanism"] == "Authorization: Bearer <job_token>"
    assert tt["header_only"] is True
    assert tt["query_string_forbidden"] is True
    assert tt["url_path_forbidden"] is True
    assert tt["redirect_carries_token"] is False
    assert tt["authorization_header_redacted_in_logs"] is True
    assert tt["edge_proxy_must_not_log_token"] is True
    assert tt["raw_token_persisted"] is False
    assert tt["digest_comparison"] == "constant_time"
    assert tt["failed_auth_response"] == "generic_content_free"
    assert tt["response_echoes_token"] is False
    assert tt["token_rotation_in_v1"] is False

    # Both the header and the raw token are prohibited telemetry fields.
    prohibited = set(c["prohibited_telemetry_fields"])
    assert {"authorization_header", "job_token"} <= prohibited

    # The raw capability never appears in any example fixture (only job_token_digest).
    for path in EXAMPLES.glob("*.json"):
        text = _read(path)
        assert "job_token_digest" in text
        assert '"job_token"' not in text, f"{path.name} must not carry a raw job_token"

    # The threat model and observability docs both pin header-only transport.
    threat = " ".join(
        _read(ROOT / "docs" / "security" / "hosted-deployment-threat-model.md").lower().split()
    )
    obs = " ".join(_read(OPS / "hosted-deployment-observability.md").lower().split())
    for flat in (threat, obs):
        assert "authorization: bearer" in flat or "authorization header" in flat
        assert "constant-time" in flat or "constant time" in flat


def test_no_received_or_queued_to_executing_phrase_drift():
    # The stale "{received|queued} -> executing" wording must be gone everywhere; the
    # authoritative path is received -> queued -> executing.
    for path in (OPS / "hosted-deployment-decision.md", OPS / "hosted-deployment-architecture.md", OPS / "hosted-deployment-job-lifecycle.md"):
        text = _read(path)
        assert "{received|queued}" not in text and "{received | queued}" not in text, f"{path.name} has stale transition wording"
    flat = " ".join(_read(OPS / "hosted-deployment-job-lifecycle.md").lower().split())
    assert "received → queued" in _read(OPS / "hosted-deployment-job-lifecycle.md") or "received -> queued" in flat
    # 'received' no longer claims a content digest is validated.
    assert "limits + digest" not in _read(OPS / "hosted-deployment-job-lifecycle.md")


def test_execution_surface_is_concrete_and_bounded():
    c = _contract()
    surf = c["execution_surface"]
    assert "cloud_run_service_handler" in surf["baseline"]
    # The verify batch is bounded by the grounded hosted_verify_limits (round 6),
    # and a larger batch is explicitly a separate future WP, not a hand-waved scale-up.
    assert surf["verify_batch_bounded_by"] == "hosted_verify_limits"
    assert "separate_wp" in surf["larger_verify_batches"]
    assert "parent_child" in surf["larger_verify_batches"]
    pl = c["platform_limits"]
    assert pl["cloud_tasks_http_dispatch_deadline_minutes"] == 30
    assert pl["baseline_per_job_budget_minutes"] < pl["cloud_tasks_http_dispatch_deadline_minutes"]
    # No doc may claim a "no invocation ceiling" or re-introduce the withdrawn 16-min figure.
    for path in HOSTED_DOCS + [ADR_0006]:
        low = _read(path).lower()
        assert "no invocation ceiling" not in low, f"{path.name} claims no invocation ceiling"
        assert "16 min" not in low and "16-min" not in low, f"{path.name} re-introduced the withdrawn 16-min figure"


def test_limits_aligned_across_schema_and_contract():
    schema = json.loads(_read(SCHEMA_PATH))
    c = _contract()
    # Round 6: two DISTINCT limits. The cached/batch limit (no egress) is the larger
    # one; the hosted live-verify limit (egress, grounded budget) bounds job records.
    cached = c["limits"]["max_rows_cached"]
    verify = c["hosted_verify_limits"]["max_verify_rows"]
    assert verify < cached, "verify (egress) limit must be smaller than the cached/batch limit"
    # The job record is verify-only, so row_count is bounded by the VERIFY limit.
    assert schema["properties"]["row_count"]["maximum"] == verify
    # Pre-job rejection codes are NOT durable job error codes.
    err = schema["properties"]["error_code"]["enum"]
    assert "input_too_large" not in err and "row_limit_exceeded" not in err
    assert set(c["limits"]["pre_job_rejections"]) == {"input_too_large", "row_limit_exceeded"}


def test_expiry_is_three_phase_410_then_404():
    exp = _contract()["expiry"]
    assert "410" in exp["expired_record_retained"]
    assert "404" in exp["after_physical_deletion"]
    # Decision + lifecycle docs spell out the 404-after-deletion case.
    for path in (OPS / "hosted-deployment-decision.md", OPS / "hosted-deployment-job-lifecycle.md"):
        flat = " ".join(_read(path).lower().split())
        assert "410" in flat and "404" in flat


def test_credential_isolation_api_and_worker_hold_no_github_key():
    am = _contract()["access_matrix"]
    assert am["public_api"]["github_app_key"] == "none"
    assert am["async_worker"]["github_app_key"] == "none"
    assert am["candidate_ingress"]["github_app_key"].startswith("access")
    # Docs state the isolation.
    for path in (ADR_0006, OPS / "hosted-deployment-decision.md", ROOT / "docs" / "security" / "hosted-deployment-threat-model.md"):
        flat = " ".join(_read(path).lower().split())
        assert "candidate-ingress" in flat or "candidate_ingress" in flat
        assert "no github credential" in flat or "hold no github" in flat or "holds no github" in flat


def test_terminalization_order_is_specified():
    order = _contract()["terminalization_order"]
    # result blob written, then completed CAS, then envelope deleted.
    joined = " ".join(order)
    assert order[0].startswith("write_result")
    assert "completed" in joined
    assert order[-1].startswith("delete_request_envelope")


def test_regional_logs_are_explicitly_configured_not_automatic():
    for path in (OPS / "hosted-deployment-decision.md", OPS / "hosted-deployment-observability.md", OPS / "hosted-deployment-implementation-plan.md"):
        flat = " ".join(_read(path).lower().split())
        assert "log bucket" in flat or "_default sink" in flat or "regional log" in flat
        assert "not automatic" in flat or "explicitly configured" in flat or "not assumed" in flat


# --- independent review round 7 (#402) locks -----------------------------------

_CLOUD_TASKS_TASK_ID = re.compile(r"^[A-Za-z0-9_-]+$")  # Cloud Tasks TASK_ID charset


def test_recovery_task_name_is_a_valid_cloud_tasks_id():
    # Finding 1 (r7): the recovery task name must be a valid Cloud Tasks TASK_ID
    # (letters/numbers/hyphen/underscore only); a colon is invalid.
    rec = _contract()["handoff"]["reconciler"]
    template = rec["recovery_task_name_template"]
    assert ":" not in template, "recovery task name template must not use a colon"
    sample_job_id = "9f1c2d3e-4b5a-46c7-8d9e-0a1b2c3d4e5f"  # a UUID job_id (hyphenated)
    seen = set()
    for dispatch_attempt in range(1, int(rec["dispatch_recovery_max"]) + 1):
        task_id = template.format(job_id=sample_job_id, dispatch_attempt=dispatch_attempt)
        assert _CLOUD_TASKS_TASK_ID.fullmatch(task_id), f"invalid Cloud Tasks task id: {task_id!r}"
        assert len(task_id) <= 500  # Cloud Tasks TASK_ID max length
        seen.add(task_id)
    # Finding (r8): successive recovery attempts MUST produce DISTINCT task ids.
    assert len(seen) == int(rec["dispatch_recovery_max"]), "recovery task ids must be distinct per generation"

    # Regression: the invalid colon form must not reappear in the contract or docs,
    # and the ~24h tombstone behaviour it works around must stay documented.
    for path in [CONTRACT_PATH, OPS / "hosted-deployment-job-lifecycle.md"] + HOSTED_DOCS:
        text = _read(path)
        assert "job_id:r" not in text and ":r{n}" not in text, f"{path.name} has an invalid colon task id"
    lifecycle = " ".join(_read(OPS / "hosted-deployment-job-lifecycle.md").lower().split())
    assert "tombstone" in lifecycle  # the 24h tombstone semantics remain documented


def test_dispatch_recovery_counter_is_separate_from_execution_attempt():
    # Finding (r8): the recovery task name is driven by a RECONCILER-owned dispatch
    # generation (dispatch_attempt), NOT the watchdog's execution counter (attempt),
    # which is pinned to 0 while received and would regenerate the same -r0 forever.
    rec = _contract()["handoff"]["reconciler"]
    template = rec["recovery_task_name_template"]
    assert "{dispatch_attempt}" in template, "recovery name must derive from dispatch_attempt"
    assert "{attempt}" not in template, "recovery name must NOT derive from the execution attempt counter"
    assert rec["dispatch_recovery_counter"] == "dispatch_attempt"
    assert rec["role"] == "recovery_only"
    # Reconciler-owned, atomic CAS increment while received (concurrent-safe).
    assert "cas" in rec["dispatch_recovery_increment"].lower()
    assert "received" in rec["dispatch_recovery_increment"].lower()
    # First recovery is r1, never the tombstoned original r0.
    assert int(rec["first_recovery_generation"]) == 1
    first = template.format(job_id="9f1c2d3e-4b5a-46c7-8d9e-0a1b2c3d4e5f", dispatch_attempt=1)
    assert first.endswith("-r1"), f"first recovery must be -r1, got {first!r}"
    not_r0 = template.format(job_id="9f1c2d3e-4b5a-46c7-8d9e-0a1b2c3d4e5f", dispatch_attempt=0)
    assert not_r0.endswith("-r0")  # generation 0 is the ORIGINAL enqueue, never used for recovery
    # Bounded with a terminal: beyond the max the job expires (410), never strands/churns.
    assert int(rec["dispatch_recovery_max"]) >= 1
    exhausted = rec["on_dispatch_exhausted"].lower()
    assert "410" in exhausted or "expiry" in exhausted

    # The two counters are distinct, both schema-required fields.
    schema = json.loads(_read(SCHEMA_PATH))
    assert "dispatch_attempt" in schema["required"] and "attempt" in schema["required"]
    assert "dispatch_attempt" in schema["properties"] and "attempt" in schema["properties"]

    # A received job can advance dispatch_attempt while attempt stays 0 (the exact
    # state the original bug stranded). Both must be schema-valid.
    validator = _validator()
    received = json.loads(_read(EXAMPLES / "received.json"))
    recovered = dict(received, dispatch_attempt=2)  # reconciler re-enqueued twice, still received
    assert recovered["attempt"] == 0
    assert not list(validator.iter_errors(recovered)), "received with advanced dispatch_attempt must validate"
    # Deleting dispatch_attempt must fail (required; default does not populate it).
    no_dispatch = {k: v for k, v in received.items() if k != "dispatch_attempt"}
    assert list(validator.iter_errors(no_dispatch)), "missing dispatch_attempt must fail validation"


def test_attempt_counter_is_required_and_zero_on_received():
    # Finding 2: the retry counter must be REQUIRED (default does not populate it),
    # zero on a newly received record, and bounded-retry terminalization stays valid.
    schema = json.loads(_read(SCHEMA_PATH))
    assert "attempt" in schema["required"], "attempt must be a required field"

    validator = _validator()
    # Deleting attempt from EVERY lifecycle fixture must fail validation.
    for path in sorted(EXAMPLES.glob("*.json")):
        record = json.loads(_read(path))
        assert "attempt" in record, f"{path.name} fixture must carry attempt"
        del record["attempt"]
        assert list(validator.iter_errors(record)), f"{path.name} without attempt must fail validation"

    # A newly received record must be attempt 0.
    received = json.loads(_read(EXAMPLES / "received.json"))
    assert received["attempt"] == 0
    assert list(validator.iter_errors(dict(received, attempt=1))), "received with attempt>0 must fail"

    # The watchdog increment-and-terminalize path stays schema-valid:
    # executing -> queued with attempt incremented (stale-lease takeover, re-queued).
    executing = json.loads(_read(EXAMPLES / "executing.json"))
    requeued = dict(executing, state="queued", lease_owner=None, lease_expires_at=None, attempt=executing["attempt"] + 1)
    assert not list(validator.iter_errors(requeued)), "watchdog re-queue with incremented attempt must validate"
    # executing -> failed at the retry bound (terminalize).
    terminalized = dict(
        executing, state="failed", error_code="execution_timeout",
        request_ref=None, result_ref=None, lease_owner=None, lease_expires_at=None, attempt=10,
    )
    assert not list(validator.iter_errors(terminalized)), "watchdog terminalize at the bound must validate"


def test_withdrawn_500_live_row_rationale_cannot_reappear():
    # Finding 3: the authoritative contract must not claim verify is 500 rows of live
    # fetch; 500 is the cached/batch (no-egress) limit, verify is bounded (max_verify_rows).
    contract_text = _read(CONTRACT_PATH).lower()
    for withdrawn in ("rows of live fetch", "500 rows of live", "up to 500 rows of live"):
        assert withdrawn not in contract_text, f"withdrawn 500-live-row rationale reappeared: {withdrawn!r}"
    c = _contract()
    # The two limits remain distinct and correctly ordered (verify < cached).
    assert c["hosted_verify_limits"]["max_verify_rows"] < c["limits"]["max_rows_cached"]
    # No hosted doc revives the false "500 live rows" framing either.
    for path in HOSTED_DOCS + [ADR_0006]:
        assert "rows of live fetch" not in _read(path).lower(), f"{path.name} revives the withdrawn 500-live claim"


def test_adr0006_acceptance_is_a_status_change_pr_not_this_merge():
    # Finding 4: acceptance happens via a SUBSEQUENT ADR-0006 status-change PR, not by
    # merging this proposal PR (consistent with the non-authoritative ADR lifecycle).
    decision = next(d for d in _contract()["maintainer_decisions"] if d["id"] == "adr0006_acceptance")
    rec = decision["recommended"].lower()
    assert "status-change pr" in rec, "adr0006_acceptance must point to a status-change PR"
    assert "merges adr-0006 to accept" not in rec, "must not say merging this PR accepts the architecture"
