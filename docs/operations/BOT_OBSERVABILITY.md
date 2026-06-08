# OpenVA Bot Observability

WP16 defines the local OpenVA bot observability scorecard. It consolidates report-only signals from the bot dashboard, queue enforcer, failure router, dashboard issue sync, and chat-ops command parser into deterministic metrics.

The machine-readable contract is `docs/operations/contracts/bot-observability.yaml`.

## Purpose

Bot observability answers whether automation is helping OpenVA or creating noise. The scorecard tracks bot throughput, queue pressure, failure classes, stale evidence, command decisions, and missing telemetry so maintainers can adjust throttling before automation becomes disruptive.

WP16 is local and report-only. It does not call GitHub APIs, compute live PR state from GitHub, update dashboard issues, enforce queues, execute chat-ops commands, retire workflows, or mutate catalog data.

## Metrics

The scorecard declares the WP9 bot-ops metrics:

- bot PRs opened
- bot PRs merged
- bot PRs failed before creation
- bot PRs closed
- human interventions per PR
- average time to merge
- failure reasons by class
- candidate conversion rate
- source preflight failure rate
- redirect canonicalization rate
- deferred backlog age
- review backlog age
- queue denials by lane
- queue deferrals by lane
- stale evidence denials
- chat-ops command decisions by status

Metrics that require live GitHub PR history are included with explicit missing-data status until a future API-backed collector exists. Local report metrics are computed only from configured files that are present.

## Source Artifacts

The initial local inputs are:

- `maintenance/bot-queue-report.json`
- `maintenance/bot-failure-routing-report.json`
- `maintenance/bot-chatops-decision.json`
- `maintenance/bot-dashboard-issue-sync-report.json`
- `maintenance/bot-dashboard.md`

Each JSON input may be either a single report object or a list of report objects. This lets OpenVA use the scorecard immediately with current single-run reports and later switch to historical rollups without changing the metric contract.

## Missing-Data Behavior

All inputs are optional in WP16. Missing optional inputs are recorded in a dedicated missing-inputs section and reduce metric completeness. Missing data must not be treated as success, failure, or zero activity unless the metric definition explicitly says a missing local source has value `null`.

This is important for notification fatigue: absence of a queue report does not mean there were no queue denials; it means the scorecard lacks queue evidence.

## Dashboard Feedback

The scorecard can feed the WP10 dashboard and WP15 dashboard issue sync by providing:

- queue denials and deferrals by lane
- failure reasons by taxonomy class
- stale evidence pressure
- chat-ops accepted, denied, and ignored command counts
- missing inputs that should be regenerated

The dashboard remains advisory. The scorecard should not become a catalog truth source or a command execution surface.

## Throttling And Notification Fatigue

Queue deferrals, queue denials, failed-before-creation counts, and repeated failure classes should guide bot throttling. Rising deferrals may mean batch sizes or open PR limits are too aggressive. Rising denials may mean a lane is missing authority or evidence is stale. Repeated accepted report-only chat-ops commands without follow-through may indicate maintainers need clearer next safe actions.

Notification fatigue should be investigated when:

- queue deferrals cluster in one lane
- stale evidence denials recur
- human interventions per PR rises after enabling a lane
- chat-ops denied decisions increase
- repeated failure classes are routed to the same escalation owner

## Future GitHub/API Integration

A later work package may add an API-backed collector for live PR metrics. That collector should produce local reports consumed by this scorecard rather than embedding GitHub reads directly into dashboard rendering.

Future live metrics should preserve the same contract names and add evidence for:

- PR opened, merged, and closed counts
- time to merge
- human intervention counts
- dashboard issue update cadence
- recurring notification volume

Any future integration must remain under the Bot Operating Model, use least-privilege permissions, and keep report-only lanes from mutating catalog truth.
