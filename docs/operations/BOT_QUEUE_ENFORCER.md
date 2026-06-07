# OpenVA Bot Queue Enforcer

The OpenVA Bot Queue Enforcer is a local, report-only decision layer for write-capable bot lanes. It converts the WP9 bot authority and queue policy contracts into deterministic `allow`, `defer`, `deny`, or `pause` decisions before a bot lane opens a PR or takes another write-capable action.

WP11 does not enforce queue policy inside production workflows. It does not create, close, label, or update PRs. It does not call GitHub APIs, run workflows, update the bot dashboard issue, implement slash commands, retire workflows, change catalog data, change automerge policy, or widen workflow permissions.

## Inputs

The enforcer reads:

- `docs/operations/contracts/bot-authority.yaml`
- `docs/operations/contracts/bot-queue-policy.yaml`
- `docs/operations/contracts/bot-failure-taxonomy.yaml`
- a local queue state file supplied by the caller

The local queue state file represents the GitHub and artifact state that the enforcer needs but does not fetch itself. It may include open PRs, recent bot PR counts, the last failure, evidence timestamps, duplicate keys, source host, vendor domain, base-change posture, and pause state.

## Decisions

The enforcer returns one of:

- `allow`: the lane may proceed according to the local state and contracts.
- `defer`: the lane is valid but should wait because of queue limits, cooldown, stale evidence, duplicate PR state, source-host concurrency, vendor-domain concurrency, or base-change posture.
- `deny`: the lane is not declared, is not in queue policy, lacks write authority, violates deny-by-default posture, or has invalid state.
- `pause`: the pause switch model is active.

`pause` takes precedence over write actions for declared lanes. Policy denials take precedence over deferrals.

## Evaluated Controls

The initial local enforcer evaluates:

- global pause switch model
- lane exists in the authority contract
- lane exists in the queue policy
- lane is allowed to write
- `deny_by_default` is explicitly true
- max open PR policy
- max PRs per day and week
- cooldown after failure
- stale evidence limit
- duplicate PR policy
- source-host rate limit placeholder
- vendor-domain concurrency limit placeholder
- base-change policy placeholder

The source-host, vendor-domain, and base-change checks are intentionally local placeholders. They consume supplied state only and do not fetch external state.

## Reports

The CLI writes deterministic JSON reports:

```bash
python -m tools.openva.bot_queue evaluate --lane catalog_growth_promotion --state path/to/state.yaml --out maintenance/bot-queue-report.json
```

Each report includes:

- lane ID
- decision
- reasons
- violated policies
- referenced queue policy values
- referenced authority values
- stale evidence evaluation
- cooldown evaluation
- duplicate PR evaluation
- next safe action

Reports are safe for WP10 dashboard ingestion. They are advisory until a later workflow integration makes them part of a report-only check.

## Future Workflow Use

Future write-capable workflows should call the enforcer before creating branches, opening PRs, applying labels, enabling auto-merge, merging, or mutating catalog truth. A future workflow should supply queue state from GitHub context or API output, write the report as an artifact, and stop or continue based on the decision only after that behavior is explicitly approved.

The enforcer must remain subordinate to WP9:

- unknown lanes are deny-by-default
- undeclared write paths are denied
- discovery and report-only lanes do not write catalog truth
- controlled promotion and source repair remain the only catalog-writing bot paths
- stale evidence must be refreshed before write recommendations
