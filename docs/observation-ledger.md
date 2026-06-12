# Observation Ledger v2

OpenVA does not version vendor truth. OpenVA observes vendor-published sources and records source state, provenance, hashes, timestamps, and change signals.

The observation ledger answers four operational questions:

```text
What did OpenVA observe?
When?
Did the source move, fail, become gated, or materially change?
Does a maintainer need to review it?
```

It is not vendor-content versioning, not a raw document archive, not legal interpretation, and not vendor risk scoring. A ledger row describes the observed state of a public source reference; it never means OpenVA approves, recommends, certifies, scores, or determines whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.

## How it works

`python -m tools.openva.observation_ledger build` consumes the source-verification report produced by `source-maintenance-report.yml` (no second fetch pass) and emits:

```text
observation-records.json              full per-run observation rows (artifact-only)
latest-observations.json              latest observation per source
source-freshness-report.json          freshness vs SLA per source
changed-since-last-observation.json   sources whose change_class is not none this run
sources-requiring-review.json         observations with review_signal.required
observation-ledger-delta.ndjson       proposed committed event rows (NOT applied)
```

Scheduled maintenance runs verify one shard of the catalog; sources absent from a run produce no records and no events. The latest index carries forward their prior state, and their freshness simply ages.

## Two axes, kept separate

```text
Can we reach it?         -> source_health.status
Did it materially vary?  -> change_class / event_type
```

`source_health.status` is reachability and access posture only: `reachable`, `unreachable`, `gated`, `bot_protected`, `redirected`, `quarantined`. Content variation is never a health status.

## Change classification

`change_class` is computed against the previous observation and the source record's curated `change_detection` baseline, with deterministic precedence:

```text
access_changed > redirect_changed > material_confirmed > material_possible > non_material > none
```

| change_class | Meaning |
| --- | --- |
| `access_changed` | The source moved into or out of the access-restricted bucket ({gated, bot_protected}). |
| `redirect_changed` | The final URL differs from the previous observation's final URL. |
| `material_confirmed` | Normalized content hash moved this run and differs from the curated change-detection baseline. |
| `material_possible` | Normalized content hash differs from the previous observation, but no curated baseline exists. |
| `non_material` | Raw sample hash changed while normalized text stayed identical (markup/asset churn). |
| `none` | Nothing changed. |

Hashes are **sample hashes** (`raw_sample_sha256`, `normalized_text_sample_sha256`) computed over the 128KB fetch sample, not full documents. A known divergence from the curated baseline keeps `material_change: true` on records but does not emit repeat events while the content stays put.

## Committed event ledger

The durable ledger stores **events**, not vendor content, under:

```text
maintenance/source-observations/events/YYYY-MM.ndjson
```

`event_type` records why a row exists; `change_class` records the change signal. They are separate so first observations are recorded honestly:

| event_type | change_class |
| --- | --- |
| `first_observed` | `none` |
| `access_changed` | `access_changed` |
| `redirect_changed` | `redirect_changed` |
| `material_confirmed` / `material_possible` | same |
| `non_material_change` | `non_material` |
| `health_changed` | usually `none` — any health transition not covered by `access_changed` (e.g. reachable→unreachable) |

Event-type precedence when signals coincide: `access_changed > redirect_changed > material_confirmed > material_possible > health_changed > non_material_change`.

Append rules:

- rows are appended only via `python -m tools.openva.observation_ledger append --delta observation-ledger-delta.ndjson`, **through a reviewed pull request** — workflows never commit ledger files;
- existing lines are never rewritten or reordered;
- a row whose `observed_at` predates the last committed row for the same source is refused;
- rows validate against `schemas/openva/observation-ledger-record.schema.json`.

## Freshness

Freshness is computed per source at report time from `config/observation-sla.yaml`; it is not a property of an observation. Defaults: fresh within 30 days, stale after 30, expired after 90; `subprocessors_list` overrides to 14/45. A source with no observation history reads `unknown`. `observed_within_sla` is true while the latest observation is within the stale threshold.

## Review signals

`review_signal.required` is true, with a reason, when:

- `change_class` is `material_possible`, `material_confirmed`, `access_changed`, or `redirect_changed`; or
- `source_health.status` is `gated`, `bot_protected`, `unreachable`, or `quarantined`.

`non_material` and `none` do not require review. Review signals route maintainer attention; nothing in the ledger mutates canonical source records automatically.

## Queries

```bash
python -m tools.openva.observation_ledger query --changed-since 2026-06-01
python -m tools.openva.observation_ledger query --stale-by-sla --latest latest-observations.json
python -m tools.openva.observation_ledger query --access-changed
python -m tools.openva.observation_ledger query --redirect-changed
python -m tools.openva.observation_ledger query --material-change
```

These support changed-since-last-assessment workflows for maintainers and agents.

## Non-goals

- No raw document archive and no copyrighted page snapshots.
- No automatic canonical source replacement: redirect, access, and content changes produce review signals, never record mutations.
- No legal interpretation, no vendor risk scoring, no company-specific assessment output.
