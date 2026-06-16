# Unified vendor resolution (resolve-on-use)

OpenVA resolves vendor assurance sources **catalogue-first, with live refresh on
use**. The same pipeline serves browser users, API consumers, agents, and future
MCP integrations: every human or agent request receives the best current
public-source result OpenVA can establish, and every discovered gap or stale
source becomes input to the same autonomous catalogue-improvement lifecycle.

This is not a new advisory or scoring system. OpenVA remains a public-source
metadata registry. **OpenVA preserves source-reference and observation history.
It does not archive or reproduce historical vendor documents.**

## The flow

```
Vendor list or agent request
  → resolve vendor identity
  → match against the OpenVA catalogue
  → for each required source type:
       does a catalogue source exist?  is it current?
         current               → return the catalogue source
         missing/stale/broken/ → run bounded public discovery,
         redirected/unavailable  return the discovered candidate,
                                 and submit it to autonomous
                                 verification and promotion
```

The orchestrator lives in [`tools/openva/vendor_resolution.py`](../tools/openva/vendor_resolution.py).
It composes existing machinery rather than duplicating it:

| Concern | Reused component |
| --- | --- |
| Vendor identity matching | `openva_vendor_inventory_matcher.core` (the single matching authority) |
| Source health + safety | `tools/openva/source_verification.py`, `tools/openva/url_safety.py` |
| Candidate emission + eligibility | `tools/openva/candidate_record.py` (`build_candidate`, `evaluate_eligibility`) |
| Durable lifecycle ingress | `maintenance/candidates/<candidate_id>.json` — the queue `autonomous-catalog-growth.yml` already consumes |
| Promotion | The existing candidate → machine_provisional → quorum → PR → release-gate → automerge lifecycle |

## Result-state vocabulary

One small, consistent set is used everywhere (browser, API, agent, CSV export):

| State | Meaning |
| --- | --- |
| `catalog_current` | Existing OpenVA source was checked and remains valid. |
| `catalog_refreshed` | Existing source was outdated/moved/broken; a current replacement was found. |
| `newly_discovered` | Vendor or source was absent from the catalogue and found through live discovery. |
| `source_unavailable` | Existing source is unavailable and no replacement was found. |
| `not_found` | No catalogue match or suitable public source was found. |
| `identity_ambiguous` | Multiple plausible vendor identities or domains exist. |
| `verification_inconclusive` | OpenVA could not establish a reliable current result. |
| `candidate_processing` | A discovered/refreshed source has entered the autonomous lifecycle. |
| `catalogued` | The candidate passed existing promotion controls and is now canonical. |

These nine are kept on three independent axes, because conflating them misleads
agents:

- **`status`** — the resolution/health outcome (`catalog_current …
  verification_inconclusive`).
- **`catalog_membership`** — `canonical` when the answer is backed by a canonical
  catalogue record (true even when that record is stale or broken), else `none`.
- **`catalog_status`** — the *durable* catalogue-lifecycle stage of the record
  backing the answer: `catalogued` (canonical), `candidate_processing` (eligible
  **and** durably enqueued), `candidate_deferred`, `candidate_rejected`, or
  `pending_ingress` (recorded but not durably enqueued), or `null`.

`catalog_status` is derived from the shared evaluator's actual decision plus the
ingress result — never asserted optimistically. A deferred or rejected candidate
is never reported as `candidate_processing`, and a rejected replacement is
downgraded to `verification_inconclusive` rather than returned as a usable
source.

## Freshness modes

| Mode | Behaviour |
| --- | --- |
| `cached` | Return current catalogue metadata and the latest known observation state. No live fetch. `live_checked` is always `false`; `checked_at` is the last stored observation time. Use for fast bulk lookup. |
| `verify` | Check source availability and canonical location during the request. `live_checked` is `true` and `checked_at` is the current observation time. Stale/redirected/broken/incomplete sources trigger live discovery. Use for onboarding/due diligence. |

Cached and verified results are never silently treated as equivalent: the
`live_checked` flag and `checked_at` timestamp always disclose which one a
consumer received.

## Agent / API contract

`resolve_vendor_sources(request, *, catalog, …)` accepts:

```json
{
  "vendor": { "vendor_name": "ExampleCloud", "domain": "examplecloud.com" },
  "required_source_types": ["privacy_notice", "dpa", "security_page",
                            "subprocessors_list", "trust_center"],
  "freshness_mode": "verify"
}
```

and returns a result that validates against
[`schemas/openva/vendor-resolution-result.schema.json`](../schemas/openva/vendor-resolution-result.schema.json):

```json
{
  "vendor": { "vendor_id": "examplecloud", "display_name": "ExampleCloud",
              "official_domain": "examplecloud.com" },
  "resolution_status": "catalog_refreshed",
  "freshness_mode": "verify",
  "sources": [
    {
      "source_type": "dpa",
      "source_url": "https://examplecloud.com/legal/dpa",
      "status": "catalog_refreshed",
      "origin": "live_discovery",
      "live_checked": true,
      "checked_at": "2026-06-16T08:30:00Z",
      "catalog_status": "candidate_processing",
      "previous_source_url": "https://examplecloud.com/old-dpa"
    }
  ],
  "snapshot": { "catalog_commit_sha": "…", "catalog_generated_at": "…" }
}
```

Each source distinguishes:

- **catalogue-derived vs live-discovery** — `origin` (`catalog` / `live_discovery`);
- **cached vs checked-this-request** — `live_checked` + `checked_at`;
- **pending vs canonical catalogue update** — `catalog_status`
  (`candidate_processing` / `catalogued` / `null`).

## Human upload workflow

There are two surfaces with deliberately different capabilities:

- **Hosted browser Local Matcher** — a static, fully client-side page. It resolves
  an uploaded CSV (`vendor_name, business_entity_name, domain, jurisdiction,
  registration_number, registered_address`) against the catalogue in **cached**
  mode only, returning one unified result per vendor with a `result_state` column
  in the CSV/JSON export. Being static, it **does not** perform live discovery,
  fetch vendor URLs, or route candidates into the lifecycle; it reports cached
  catalogue state and points to the resolver for live verification. It never
  uploads the CSV.
- **Resolver `verify` mode** (`resolve_inventory(...)` via Python/CLI, run
  server-side or in CI) — performs the live checks, discovers replacements and
  missing sources, and **durably enqueues** discovered/refreshed sources into the
  catalogue lifecycle. Here users genuinely do not need to file GitHub issues for
  routine unmatched vendors, and never need to understand candidates, machine
  quorum, or internal workflow terminology.

Connecting the hosted page to a running resolver service (so browser uploads also
get `verify` mode) is tracked in `docs/roadmap.md`; today that live path is the
Python/CLI contract.

## Candidate emission and idempotency

Discovered or refreshed sources become candidate records via `build_candidate`,
each carrying:

- a **channel** in `discovery_component` (`public_matcher_discovery`,
  `agent_resolution`, `api_resolution`, `scheduled_discovery`, `human_submission`);
- a **catalogue-change origin** mapped onto the existing `candidate_origin` enum
  (`source_replacement` for a moved/broken source, `coverage_gap` for a missing
  type on a known vendor, `catalog_discovery` for a brand-new vendor).

All channels converge on the same `evaluate_eligibility` evaluator; origin never
reduces verification. Candidate ids are derived deterministically from
`(origin, origin_reference)`, so the same vendor/source requested repeatedly by
many users or agents reuses one in-flight candidate instead of spawning
duplicates.

A brand-new vendor is emitted as **one aggregate candidate** carrying its full
discovery set (all discovered source types), so it materialises from complete
evidence rather than fragmenting into one candidate per source type (which would
risk duplicate provisional PRs and identity collisions). Existing-vendor source
replacements and coverage-gap fills remain independently keyed.

Discovered/refreshed candidates are handed to a **durable, idempotent ingress**:
`CatalogQueueIngress` writes the unified candidate record to
`maintenance/candidates/<candidate_id>.json` (skipping if it already exists),
which is exactly the queue `autonomous-catalog-growth.yml` reads eligible
candidates from. The response's `catalog_status` reflects the actual persisted
state. Read-only/preview callers can use the non-durable `RecordingIngress`,
which never claims a candidate is processing.

## Catalogue mutation boundary

Live resolution **never** writes canonical catalogue files or `main`. It resolves
identity, checks health, discovers candidate URLs, classifies provisionally,
records observations, creates candidate records, and returns session results.
Canonical mutation continues only through the established lane:

```
candidate → eligibility → machine_provisional → observation
          → independent machine quorum → pull request
          → release gates → controlled automerge → active catalogue
```

## Historical source-reference model

A replacement is only ever returned as `catalog_refreshed` when the final URL
passes safety validation, stays on the vendor's authoritative domain, is not a
generic/homepage redirect, and remains semantically consistent with the source
type. A redirect that fails any of these is not treated as a moved source:
discovery runs, and if no safe replacement is found the result is
`verification_inconclusive` (not a refreshed source).

When a URL is replaced, OpenVA proposes **reference metadata only**: the former
URL, the current URL, first/last observed timestamps, redirect target,
unavailable state, and a `superseded_by` relationship — in the
`proposed_source_history` block of the resolution result (`source_history` in the
schema). It is *proposed* because durable supersession history is written through
the existing observation/change-event model only after the replacement is admitted
by the lifecycle. It records **no** document content, DPA/privacy text,
clause-level versions, document comparisons, or full-text archives.
