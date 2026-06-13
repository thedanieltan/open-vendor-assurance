# OpenVA Roadmap Decision — June 2026

> **SUPERSEDED 2026-06-13 by the WP34.6 corrective decision below.** The original June decision (Option A — run 3–4 weekly cycles before starting WP35) is retained unchanged beneath the corrective decision as the auditable superseded record. Merged history is not rewritten; this file is moved forward in a new commit.

## Corrective Decision — WP34.6 (2026-06-13)

**Status:** accepted. **Supersedes:** the June 2026 decision below (Option A — run 3–4 weekly cycles before starting WP35).

### Context

The June system review (`docs/reviews/openva-system-review-2026-06.md`) remains the valid historical input and is **unchanged**. Its measurements are a historical snapshot, not live planning inputs. The decision it fed — defer WP35 release gates until after 3–4 weekly maintenance cycles (target mid-July 2026), with only a narrow catalog-growth slice running meanwhile — is now superseded.

### Decision

P0 work begins **immediately**, not after several weekly cycles:

1. **WP35 — consolidated source-intelligence release gates**: a machine-readable, test-pinned bot constitution plus a reusable release-gate CLI wired into the existing validation and release-candidate workflows.
2. **WP35.5 — autonomous observation-ledger continuity**: recurring ledger-append PRs authored and merged through a path-restricted, append-only, release-gated automerge lane — with no human author or approver.

These are sequenced ahead of, not behind, operational cycles. The earlier concern that gates over one-shard cold-start data would institutionalize noise is addressed structurally rather than by waiting: freshness and continuity gates ship **warn-only** until a complete first observation baseline is committed, then flip to enforce. That baseline is seeded as a Day-0 operational step instead of being waited for.

After P0, the program proceeds in strict order: **WP36** (machine-provisional vendor materialization with append-only decision records), **WP37** (independent bot quorum and autonomous promotion), then stretch **WP38** (autonomous repair, quarantine, rollback) and **WP39** (self-auditing and regression benchmark).

### Autonomy doctrine (binding on all subsequent packages)

Strict machine autonomy is permitted **only** through:

- independent machine review — separate identity, domain-authority, source, duplicate, and adversarial reviewers, replacing human review with independent machine review, not with unchecked automation;
- evidence-bearing, append-only machine decision records;
- delay and observation windows before promotion;
- PR-based merge paths only — no workflow pushes directly to `main`.

Hard invariants: **no single bot may discover, approve, and merge the same claim**; a discovery component may not approve its own discovery; **ambiguous, conflicting, gated, private, or meaning-level cases fail closed** (reject, defer, or quarantine — the system must not manufacture certainty merely to avoid review); every machine-created claim is reversible.

### Measurement discipline

Operational measurements must be **regenerated** before each planning step, never copied from the June snapshot. Regenerated baseline (main @ `6d091f0`, 2026-06-13): 164 vendors · 610 sources · **0** sources carry any WP29 registry field · **0** `status_page` sources · 153/610 sources observed (one shard) · 1,037-row coverage queue (13 `missing_vendor`) · `identity_access` depth 4 · `security` depth 12.

**Correction to the June "missing vendor" list:** of the nine vendors the review named missing, six now exist in the catalog (Okta, Auth0, 1Password [as `onepassword`], Hetzner, Personio, Mistral AI). Only **OVHcloud, Keeper, Bitwarden** are genuinely absent. The growth queue still lists `1password` as missing because of an id↔alias mismatch (catalog id `onepassword`, domain `1password.com`) — a false positive that the WP36 identity-resolution stage must catch before materialization. This is exactly why measurements are regenerated rather than copied.

### What this corrective decision does not change

The trust boundary is unchanged: public-source-only, metadata-first; no compliance, legal, procurement, security, suitability, approval, or vendor-risk advice; no scoring or ranking; no anti-bot bypass; declared-gated sources are never fetched; provenance-first. Bots detect and route material change; they never interpret its legal or compliance meaning.

### Non-advisory reminder

This corrective decision concerns OpenVA's own catalog operations. Nothing in it is a statement about any vendor's compliance, safety, suitability, or risk.

---

## Original decision — June 2026 (superseded; retained for audit)

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
