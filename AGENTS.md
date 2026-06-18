# AGENTS.md — OpenVA agent routing

Single entry point for any agent (human or bot) operating on this repository.
This file **routes** to the canonical files; it does not restate or fork their
policy. When this document and a canonical file disagree, the canonical file
wins (see [Documentation conflict order](#documentation-conflict-order)).

Operational metadata only. Nothing here is legal, compliance, procurement,
security, KYC, AML, audit, or vendor-risk advice.

## Repository purpose

OpenVA is a **public, machine-readable and human-inspectable registry of
vendor-published assurance sources**. It records observable public metadata and
provenance only. It is **not** an upload-driven crawler, a private SaaS
intelligence service, a workspace app, a stateless retrieval engine, or a
vendor-risk scoring system.

Routine catalog growth and maintenance run **autonomously** through pull
requests. Humans govern only code, schemas, workflows, authority, the bot
constitution, policy thresholds, permissions, credentials, and the emergency
hold. Routine catalog *records* do not require human approval.

When evidence is insufficient the system **fails closed** —
`deferred` / `rejected` / `quarantined` / `rolled_back` — and never converts
uncertainty into a human-review queue.

## Prohibited actions (non-negotiable)

- **Public-source-only.** Never authenticate into a portal, bypass CAPTCHA / WAF
  / bot protection, submit forms for gated material, retrieve NDA-controlled
  documents, store private reports, or commit raw/summarised/hashed inaccessible
  private content. A gated source is recorded only as an *access-state fact*.
- **Non-advisory.** Never state a vendor is compliant, safe, approved, adequate,
  recommended, suitable, low risk, or high risk. No scoring or ranking.
- **PR-only mutation.** No automation writes directly to `main`. Every mutation
  goes branch → PR → authority checks → path checks → validation → release gate
  → delay where required → controlled automerge.
- **Reversibility.** Every machine-created claim references a committed machine
  decision, its evidence, the deciding component, and a reversal path, and
  preserves append-only decision/observation history.
- **Separation of duties.** The component that discovers a candidate is never
  the sole component that decides and merges it. Discovery, verification,
  decision, and merge authority stay independently bounded.

The machine-enforced form of these rules lives in
[`config/bot-constitution.yaml`](config/bot-constitution.yaml) and is proven by
negative fixtures in `tests/test_release_gates.py` /
`tests/test_constitution_regression.py`.

## Canonical contracts (authoritative)

| Concern | Canonical file |
| --- | --- |
| Higher-order deny-first invariants | [`config/bot-constitution.yaml`](config/bot-constitution.yaml) |
| Per-lane write / label / merge authority (levels 0–5) | [`docs/operations/contracts/bot-authority.yaml`](docs/operations/contracts/bot-authority.yaml) |
| Queue limits, holds, cooldowns, concurrency | [`docs/operations/contracts/bot-queue-policy.yaml`](docs/operations/contracts/bot-queue-policy.yaml) |
| Live queue state schema | [`docs/operations/contracts/bot-queue-state.schema.yaml`](docs/operations/contracts/bot-queue-state.schema.yaml) |
| Global work priority (constrained-capacity ordering) | [`docs/operations/contracts/bot-work-priority.yaml`](docs/operations/contracts/bot-work-priority.yaml) |
| Release-gate configuration | [`config/release-gates.yaml`](config/release-gates.yaml) |
| Machine evidence thresholds | [`config/machine-evidence-thresholds.yaml`](config/machine-evidence-thresholds.yaml) |
| Automerge lanes | [`config/automerge-policy.yaml`](config/automerge-policy.yaml) |
| Workflow inventory | [`docs/operations/contracts/workflow-inventory.yaml`](docs/operations/contracts/workflow-inventory.yaml) |
| Prohibited advisory vocabulary | [`config/prohibited-claims.yaml`](config/prohibited-claims.yaml) |

Lifecycle, terminology, and the autonomy boundary are described in
[`docs/catalog-autonomy-policy.md`](docs/catalog-autonomy-policy.md),
[`docs/architecture/OPENVA_TERMINOLOGY.md`](docs/architecture/OPENVA_TERMINOLOGY.md),
and [`docs/operations/WORKFLOW_OPERATING_MODEL.md`](docs/operations/WORKFLOW_OPERATING_MODEL.md).

## Required reading by task type

| Task | Read first |
| --- | --- |
| Human-submission intake / new vendor | `docs/submission-intake.md`, `docs/submission-verification.md`, `tools/openva/submission_bridge.py`, `schemas/openva/candidate-record.schema.json` |
| Machine-provisional growth | `docs/catalog-autonomy-policy.md`, `tools/openva/machine_provisional_controller.py`, `bot-authority.yaml` lane `catalog_growth_promotion` |
| Quorum promotion | `tools/openva/bot_quorum.py`, `tools/openva/quorum_promotion.py`, `config/machine-evidence-thresholds.yaml` |
| Source repair | `tools/openva/source_repair_classifier.py`, `docs/source-refinement-workflow.md`, `bot-authority.yaml` lane `source_repair` |
| Quarantine | `tools/openva/source_quarantine.py`, `bot-authority.yaml` lane `source_quarantine` |
| Rollback | `tools/openva/rollback.py`, `tools/openva/rollback_eligibility.py`, `tools/openva/catalog_audit.py`, `bot-authority.yaml` lane `source_rollback` |
| Queue / scheduling | `bot-queue-policy.yaml`, `bot-work-priority.yaml`, `tools/openva/bot_queue.py`, `tools/openva/work_priority.py` |
| Telemetry / dashboards | `tools/openva/bot_telemetry.py`, `docs/operations/BOT_DASHBOARD.md` |
| Architecture / distribution / integration decisions | [`docs/architecture/decisions/`](docs/architecture/decisions/README.md) (ADR log), `docs/agent-workspace-composition.md`, `docs/agent-integrations.md` |
| Any code/schema/workflow/policy change | `GOVERNANCE.md`, `CONTRIBUTING.md`, this file |

## Permitted paths

Each lane's `allowed_paths` in `bot-authority.yaml` is authoritative. Routine
autonomous lanes are bounded to:

- `data/vendors/**` — catalog records (one vendor per machine-provisional PR);
- `maintenance/machine-decisions/**` — append-only decision records;
- `maintenance/source-observations/events/**` — append-only observation events;
- `maintenance/reviewed/**` — reviewed repair evidence (legacy lane).

Generated/derived outputs (`indexes/**`, `dist/**`, `site/**`, registry
outputs) are produced by `python -m tools.openva.validate build-indexes` and
must not be hand-edited.

## Required tests

Before reporting completion, run the repository's canonical commands:

```
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
```

Also run the release-gate, constitution, workflow-contract, catalog-audit, and
telemetry suites (`tests/test_release_gates.py`,
`tests/test_constitution_regression.py`, `tests/test_*_workflow.py`,
`tests/test_catalog_audit.py`, `tests/test_bot_telemetry.py`).

## Stop conditions

Stop and fail closed (do **not** merge, do **not** escalate to a human queue)
when:

- a write-capable lane would rely on fallback queue state;
- generated files drift from committed sources;
- documentation contradicts implementation;
- evidence is stale, insufficient, conflicting, gated, or ambiguous;
- separation of duties cannot be satisfied;
- the emergency hold (`openva-hold` / `openva-bot-paused`) is set.

Human review remains **required** for changes to code, schemas, workflows,
policy thresholds, authority, permissions, and governance.

## Documentation conflict order

When sources disagree, resolve in this order (highest authority first):

1. machine-readable authority contracts (`config/bot-constitution.yaml`, `bot-authority.yaml`, `bot-queue-policy.yaml`, `bot-work-priority.yaml`);
2. schemas and validators (`schemas/openva/**`, `tools/openva/validate.py`);
3. workflow implementation (`.github/workflows/**`);
4. machine-readable policies (`config/**`);
5. generated documentation (`dist/**`, `site/**`, generated reports);
6. narrative documentation (`README.md`, `docs/**`).
