# OpenVA Roadmap Decision — June 2026

Input: `docs/reviews/openva-system-review-2026-06.md` (WP29–WP34 system review).

Options considered:

```text
A. run the system for a few weekly cycles
B. do targeted catalog growth
C. improve agent export ergonomics
D. improve maintainer queue usability
E. proceed to WP35 release gates
```

## Decision

**Primary: A — run the system for 3–4 weekly cycles, with a narrow slice of B running alongside it. E (WP35) is scheduled to start after those cycles. C and D are queued as small follow-ups, not packages.**

### A (primary): run 3–4 weekly cycles

Every WP29–WP34 subsystem has exactly one live run behind it. The most valuable thing the system can produce right now is its own operational evidence:

- observation shards 2–4 complete first-pass coverage (610/610 sources), turning the 160 `unknown`-freshness rows into real fresh/stale signal and producing the first genuine change events against the seeded baseline;
- weekly growth reports show whether the queue moves (completeness ratios, backlog) rather than just exists;
- the submission → verification → review loop gets exercised by real traffic, if any arrives;
- ledger appends accumulate through the reviewed-PR path, validating the growth-control model.

During this period the maintainer's standing cadence is deliberately small: review the weekly growth summary top-N (~5 rows), apply reviewed ledger appends, triage any submissions.

### B (narrow slice, alongside A): identity/security depth + first registry-field decoration

Two measured deficits justify targeted catalog work now rather than after the cycles:

1. **Materialize the identity and security wishlist vendors** (Okta, Auth0, 1Password, Keeper, Bitwarden — 5 vendors) through the normal candidate/catalog-batch lane. Identity at 4 vendors is the single largest usefulness gap; this is one standard 3–5 vendor batch plus one follow-up.
2. **Decorate a pilot set of 20–30 tier-1 sources with WP29 registry fields** (`retrieval`, `canonical_confidence`, and `change_detection` baselines from the next observation run) via reviewed catalog PRs. This is the smallest action that makes the WP29→WP33 intelligence layer carry real data end to end, and it gives WP35's gates something to gate.

Out of scope for B: mass growth, new categories, anything outside the existing candidate/batch lanes.

### E (scheduled, not started): WP35 release gates after the cycles

WP35 is deliberately sequenced AFTER A, not skipped. Reasons: half its proposed gates measure operational state that is currently cold-start (high-priority sources observed within SLA would fail today purely from one-shard coverage; material-change surfacing has no baselines to compare). Gating on a system with one data point hardens noise. After 3–4 cycles the gates measure something real. Target: plan WP35 in July 2026 with the cycle data in hand.

### C and D: folded in as small follow-ups, not packages

- **C (agent export ergonomics)**: add a site `llms.txt`/README pointer to `openva-agent-index.json` and a `site_base`/self-URL field in the index. Cheap, high leverage for cold-start agents; can ride along with any PR touching the site or be a one-commit change. Not a package.
- **D (queue usability)**: a "queue row → prefilled submission/candidate" shortcut and a top-N-only summary view. Worth doing once A shows which queue classes the maintainer actually consumes; designing it before that usage data exists would be guessing.

## What this decision rejects

- Building any new engine now — the review found catalog-work deficits, not machinery deficits.
- Mass vendor growth — uncontrolled growth is exactly what WP34 exists to prevent; the queue's 1,037 rows are a measurement surface, and only the ~30–40 row actionable core is work.
- Starting WP35 immediately — gates over cold-start data would institutionalize noise.

## Review trigger

Revisit this decision after 3–4 source-maintenance cycles (target: mid-July 2026), or earlier if: external submissions arrive in volume; an agent consumer reports export friction; or the cycles surface an operational failure the gates should have caught.

## Non-advisory reminder

This decision concerns OpenVA's own catalog operations. Nothing in it is a statement about any vendor's compliance, safety, suitability, or risk.
