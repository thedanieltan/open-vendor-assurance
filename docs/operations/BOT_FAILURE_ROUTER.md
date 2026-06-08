# OpenVA Bot Failure Router

The OpenVA Bot Failure Router is a local, report-only classifier for failed bot runs and candidate failures. It converts structured failure observations into WP9 taxonomy-backed routing decisions.

WP12 introduced the local report-only classifier. WP20 wires that classifier into selected bot workflow failure paths so failed or safely stopped runs can upload taxonomy-backed routing artifacts. The router does not create or update GitHub issues. It does not call GitHub APIs, retry workflows, defer candidates automatically, stop workflows automatically, implement slash commands, retire workflows, change catalog data, change automerge policy, or widen workflow permissions.

## Purpose

The router gives bot lanes a shared way to answer:

- what failure class occurred
- whether retry is eligible
- what retry policy applies
- who owns escalation
- whether a hardening issue should be opened or updated later
- whether a candidate should be deferred
- whether the lane should stop
- what the next safe action is

The output is designed for WP10 dashboard display and workflow hardening. In integrated workflows, routing reports are artifacts only; the original workflow failure remains the workflow conclusion.

## Input Shape

The router accepts YAML or JSON input:

```yaml
version: 1
lane_id: catalog_growth_promotion
failure:
  code: stale_evidence_failure
  message: Evidence is older than strict-growth stale evidence limit.
  artifact: promotion-plan.json
```

It also accepts queue-enforcer output embedded as local state:

```yaml
version: 1
lane_id: catalog_growth_promotion
queue_report:
  decision: defer
  reasons:
    - stale_evidence
```

## Output Shape

The router writes deterministic JSON and can also write markdown:

```json
{
  "lane_id": "catalog_growth_promotion",
  "matched_failure_code": "stale_evidence_failure",
  "classification": "taxonomy_match",
  "match_confidence": "explicit",
  "match_basis": "failure.code",
  "retry_eligible": true,
  "retry_policy": "refresh evidence before promotion, repair, or merge",
  "escalation_target": "maintainer",
  "open_or_update_hardening_issue": false,
  "defer_candidate": true,
  "stop_lane": false,
  "next_safe_action": "Refresh evidence before retrying the lane.",
  "explanation": "Required source, redirect, or deterministic evidence is older than the lane stale-evidence limit."
}
```

Unknown failures are not guessed aggressively. If a failure cannot be matched to the taxonomy, the router returns a manual-review result with no taxonomy code and a lane-stop recommendation.

## Workflow Integration

The following workflows emit failure routing artifacts on failure paths:

| Workflow | Artifact | Lane |
|---|---|---|
| `source-repair-pr.yml` | `openva-source-repair-failure-routing` | `source_repair` |
| `candidate-promotion-pr.yml` | `openva-catalog-promotion-failure-routing` | `catalog_growth_promotion` |
| `catalog-growth-discovery.yml` | `openva-catalog-growth-discovery-failure-routing` | `catalog_growth_discovery` |
| `source-maintenance-report.yml` | `openva-source-maintenance-failure-routing` | `source_maintenance_report` |
| `source-refinement-scan.yml` | `openva-source-refinement-failure-routing` | `source_maintenance_report` |
| `agent-automerge.yml` machine-canonical job | `openva-automerge-machine-canonical-failure-routing` | `pr_safety` |
| `agent-automerge.yml` strict-growth job | `openva-automerge-strict-growth-failure-routing` | `pr_safety` |
| `agent-automerge.yml` P0 source repair job | `openva-automerge-p0-source-repair-failure-routing` | `pr_safety` |

Each artifact may include:

- failure input JSON
- failure routing report JSON
- failure routing report markdown

The workflows use `if: failure()` for routing and `if: always()` for artifact upload. A successful router step does not convert a failed workflow into a successful workflow.

## Taxonomy Mapping

Explicit codes from `docs/operations/contracts/bot-failure-taxonomy.yaml` are authoritative. Message-based matching is conservative and currently recognizes only narrow phrases such as:

- `Unexpected inputs provided` -> `workflow_input_compatibility_failure`
- `schema validation failed` -> `schema_validation_failure`
- `generated files are stale` -> `generated_drift_failure`
- `permission denied by bot authority` -> `permission_policy_denial`

Queue-enforcer output may also route common queue reasons:

- `stale_evidence` or `missing_evidence` -> `stale_evidence_failure`
- `duplicate_pr_policy` -> `duplicate_url_failure`
- `pause_switch_active`, `lane_not_write_capable`, `unknown_lane`, or `lane_missing_queue_policy` -> `permission_policy_denial`

Integrated workflows add targeted failure inputs for:

- schema validation failures -> `schema_validation_failure`
- generated drift failures -> `generated_drift_failure`
- source preflight failures -> `source_preflight_failure`
- automerge lane preflight failures -> `automerge_lane_mismatch`
- workflow input compatibility failures -> `workflow_input_compatibility_failure`
- external fetch instability in report/discovery workflows -> `external_fetch_instability`

## Future Issue Path

Future automation may use routing reports to open or update hardening issues. That later implementation must preserve the report-only classifier, include the original artifact and lane context, and remain under WP9 bot authority and queue policy contracts.

Routing reports are local or workflow artifacts only. They may be displayed in the WP10 dashboard or attached to workflow artifacts, but they must not mutate GitHub state. Operators should read `next_safe_action`, confirm the matched taxonomy code, and decide manually whether to refresh evidence, rerun a workflow, repair a contract, or open a hardening issue.
