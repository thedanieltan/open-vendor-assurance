# WP40 — Autonomous catalog operations closure

This document records the WP40 work to complete OpenVA's autonomous catalog
operating model, the maturity state of each component, and the evidence behind
each claim. It complements the canonical contracts; where it disagrees with a
machine-readable contract, the contract wins (see `AGENTS.md`).

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.

## Maturity vocabulary

| State | Meaning |
| --- | --- |
| `designed` | Documented intent only. |
| `fixture_proven` | Logic implemented and proven by tests/fixtures. |
| `workflow_wired` | Wired into a workflow / CLI; contracts updated. |
| `live_smoke_proven` | Exercised end-to-end over the real tool chain (controlled root). |
| `production_observed` | Observed running on `main` via live GitHub Actions. |

## Operating model

Agents autonomously perform candidate intake, vendor/source discovery, identity
and source verification, duplicate detection, machine-provisional
materialisation, observation, quorum promotion, source repair, quarantine,
rollback, index generation, publication, and operational auditing.

Humans govern only code, schema, workflow, authority, and bot-constitution
changes, policy thresholds, permissions, credentials, and the emergency hold.
Routine catalog records do **not** require human approval. When evidence is
insufficient the system fails closed: `deferred`, `rejected`, `quarantined`,
`rolled_back`. Uncertainty is never converted into a human-review queue.

## Component status

| Issue | Component | Maturity | Evidence |
| --- | --- | --- | --- |
| 4 | Unified candidate schema + record | `fixture_proven` | `schemas/openva/candidate-record.schema.json`, `tools/openva/candidate_record.py`, `tests/test_candidate_record.py` |
| 1, 2 | Human-submission bridge + per-URL verification | `fixture_proven` | `tools/openva/submission_bridge.py`, `tests/test_submission_bridge.py` |
| 12 | Issue lifecycle status comment | `fixture_proven` | `tools/openva/submission_lifecycle.py`, `tests/test_submission_lifecycle.py` |
| 5 | Machine eligibility-state mapping | `fixture_proven` | `tools/openva/machine_states.py`, `tests/test_machine_states.py` |
| 3 | Scheduled autonomous growth | `workflow_wired` | `tools/openva/autonomous_growth_controller.py`, `.github/workflows/autonomous-catalog-growth.yml`, `tests/test_autonomous_growth_*` |
| 6 | Autonomous source-repair classifier | `fixture_proven` | `tools/openva/source_repair_classifier.py`, `tests/test_source_repair_classifier.py` |
| 9 | Self-audit → rollback eligibility | `fixture_proven` | `tools/openva/rollback_eligibility.py`, `tests/test_rollback_eligibility.py` |
| 7 | Live-queue state guard | `fixture_proven` | `tools/openva/bot_queue.py` (`enforce_live_state`), `tests/test_bot_queue_live_state.py` |
| 8 | Global work priority | `fixture_proven` | `docs/operations/contracts/bot-work-priority.yaml`, `tools/openva/work_priority.py`, `tests/test_work_priority.py` |
| 11 | Authoritative telemetry | `fixture_proven` | `tools/openva/bot_telemetry.py`, `tests/test_bot_telemetry_wp40.py` |
| 13 | Generated machine-evidence PR bodies | `fixture_proven` | `tools/openva/autonomous_pr_body.py`, `tests/test_autonomous_pr_body.py` |
| 14 | Root agent-routing document | `workflow_wired` | `AGENTS.md`, `tests/test_agents_routing_doc.py` |
| 10 | Documentation reconciliation | `workflow_wired` | `README.md`, `GOVERNANCE.md`, `docs/submission-intake.md`, `tests/test_autonomy_docs_regression.py` |
| 15 | Full lifecycle smoke | `live_smoke_proven` | `tools/openva/lifecycle_smoke.py`, `tests/test_lifecycle_smoke.py`, `maintenance/smoke/wp40-lifecycle-smoke-evidence.json` |

## Lifecycle smoke evidence

`python -m tools.openva.lifecycle_smoke --root <isolated>` drives one candidate
through the real tool chain:

```text
submission -> candidate record (origin human_submission, every URL verified)
  -> materialize_provisional decision (append-only, deciding bot != discovery bot)
  -> machine_provisional vendor
  -> observation events appended
  -> promotion decision (independent quorum, deciding bot != discovery bot)
  -> active vendor
  -> clean reproducibility self-audit (0 defects)
  -> telemetry: 1 promoted vendor, 2 decisions
  -> rollback-eligibility: nothing to revert
```

The committed evidence snapshot is `maintenance/smoke/wp40-lifecycle-smoke-evidence.json`.
It runs against an isolated root and never writes the public catalog.

## Remaining gate to `production_observed`

The lifecycle is `live_smoke_proven` over the real modules. Reaching
`production_observed` requires:

1. merging this work to `main` so the new modules and the
   `autonomous-catalog-growth.yml` schedule are live;
2. one scheduled cycle materialising a real machine_provisional vendor from the
   discovery queue, its PR merging through the existing automerge lane after the
   `not_before` delay and release gates;
3. the committed machine-decision store and reproducibility audit confirming the
   result on `main`.

Until then the `maintenance/machine-decisions/` store on `main` is empty by
design — no machine decision is fabricated ahead of a real autonomous run.
