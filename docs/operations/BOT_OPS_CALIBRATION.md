# OpenVA Bot Ops Calibration

WP23 calibrates the bot operating system after the WP16-WP22 runtime activation stack landed on `main`.

The purpose is to decide whether OpenVA should hold current bot authority, tune noisy signals, or allow the next narrow authority step. Calibration is deliberately local-only and report-only. It does not mutate catalog data, dispatch workflows, call GitHub APIs, or widen permissions.

## Inputs

The calibration runner consumes the existing bot-ops subsystems:

- bot dashboard rendering
- bot queue decisions
- bot failure routing
- bot observability scorecard
- local-audit chat-ops execution
- workflow retirement reporting
- bot ops smoke harness

Missing optional local artifacts are recorded as calibration evidence. They are not treated as critical failures unless the relevant contract says they are required.

## Required sections

The calibration report contains these sections:

1. Baseline repo posture
2. Dashboard usefulness review
3. Queue decision quality
4. Failure-router classification quality
5. Chat-ops safety review
6. Workflow retirement posture
7. Observability completeness
8. Smoke harness coverage
9. Missing artifact inventory
10. Noise / false-positive inventory
11. Automation authority recommendation
12. Next safe action

## Recommendation values

The report may recommend one or more of:

- `hold_current_authority`
- `tune_dashboard_signals`
- `tune_queue_policy`
- `tune_failure_taxonomy`
- `allow_limited_label_activation`
- `block_authority_expansion`

The default posture is conservative. A recommendation to consider limited live label activation is allowed only when the smoke harness passes and local-audit chat-ops behavior remains bounded.

## Safety posture

WP23 does not enable any new bot power. In particular, it does not:

- execute live chat-ops label mutation
- widen workflow permissions
- retire another workflow
- change catalog data
- change automerge policy
- dispatch workflows
- call GitHub APIs
- enable new bot authority

## Operator interpretation

A passing calibration report does not mean OpenVA is fully autonomous. It means the current bot substrate is coherent enough for the next reviewed work package.

If the report recommends `hold_current_authority`, later work packages should tune signals before enabling more behavior.

If the report recommends `allow_limited_label_activation`, the only authority expansion to consider is the narrow `/openva hold` and `/openva unhold` label path described in WP25.

If the report recommends `block_authority_expansion`, WP25 must stop and document blockers rather than enabling live mutation.

## CLI

```bash
python -m tools.openva.bot_calibration run \
  --out-json maintenance/bot-calibration-report.json \
  --out-md maintenance/bot-calibration-report.md
```

Generated reports under `maintenance/` are local evidence artifacts and should not be committed unless repository convention changes.
