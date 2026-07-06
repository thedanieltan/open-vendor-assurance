# Unified vendor resolution (resolve-on-use)

OpenVA resolves vendor assurance source URLs **reference-cache-first, with optional live check or discovery on use**. The same pipeline serves browser users, API consumers, agents, and future MCP integrations: every human or agent request receives the best public-source locator result OpenVA can establish within the requested mode, and every useful discovered gap or stale source becomes input to the same autonomous reference-cache improvement lifecycle.

This is not a new advisory, scoring, monitoring, or document-versioning system. OpenVA remains a public-source metadata resolver. **OpenVA preserves source-reference and observation history. It does not archive, reproduce, monitor, compare, or interpret historical vendor documents.**

## The flow

```text
Vendor list or agent request
  -> resolve vendor identity
  -> check the OpenVA reference cache
  -> for each required source type:
       does a cached public source reference exist?
         cached answer available       -> return the cached source reference
         missing/stale/broken/         -> run bounded public discovery or check,
         redirected/unavailable           return the discovered candidate when safe,
                                         and submit reusable locator findings to
                                         autonomous verification and promotion
```

The orchestrator lives in [`tools/openva/vendor_resolution.py`](../tools/openva/vendor_resolution.py).
It composes existing machinery rather than duplicating it:

| Concern | Reused component |
| --- | --- |
| Vendor identity matching | `openva_vendor_inventory_matcher.core` (the single matching authority) |
| Source URL status + safety | `tools/openva/source_verification.py`, `tools/openva/url_safety.py` |
| Candidate emission + eligibility | `tools/openva/candidate_record.py` (`build_candidate`, `evaluate_eligibility`) |
| Durable lifecycle ingress | `maintenance/candidates/<candidate_id>.json` — the queue `autonomous-catalog-growth.yml` already consumes |
| Promotion | The existing candidate -> machine_provisional -> quorum -> PR -> release-gate -> automerge lifecycle |

## Result-state vocabulary

One small, consistent set is used everywhere (browser, API, agent, CSV export):

| State | Meaning |
| --- | --- |
| `catalog_current` | Existing OpenVA source reference was checked and remains usable. |
| `catalog_refreshed` | Existing source reference was outdated/moved/broken; a current replacement was found. |
| `newly_discovered` | Vendor or source was absent from the reference cache and found through live discovery. |
| `source_unavailable` | Existing source reference is unavailable and no replacement was found. |
| `not_found` | No cache match or suitable public source was found. |
| `identity_ambiguous` | Multiple plausible vendor identities or domains exist. |
| `verification_inconclusive` | OpenVA could not establish a reliable source locator result. |
| `candidate_processing` | A discovered/refreshed source has entered the autonomous lifecycle. |
| `catalogued` | The candidate passed existing promotion controls and is now an active catalog/reference-cache record. |

These nine are kept on independent axes, because conflating them misleads agents:

- **`status`** — the resolution/URL-status outcome (`catalog_current` …
  `verification_inconclusive`).
- **`catalog_membership`** — `canonical` when the answer is backed by an active
  catalogue/reference-cache record (true even when that record is stale or broken), else `none`.
- **`catalog_status`** — the *durable* lifecycle stage of the record backing the
  answer: `catalogued` (active), `candidate_processing` (eligible and
  **`workflow_visible`** — see the durability ladder below),
  `candidate_deferred`, `candidate_rejected`, or `pending_ingress`, or `null`.
- A deferred candidate's discovered URL is exposed only as an unverified
  `candidate_url`, never as the resolved `source_url`.

`catalog_status` is derived from the shared evaluator's actual decision plus the
ingress result — never asserted optimistically. A deferred or rejected candidate
is never reported as `candidate_processing`, and a rejected replacement is
downgraded to `verification_inconclusive` rather than returned as a usable
source.

## Freshness modes

| Mode | Behaviour |
| --- | --- |
| `cached` | Return current reference-cache metadata and the latest known observation state. No live fetch. `live_checked` is always `false`; `checked_at` is the last stored observation time. Use for fast bulk lookup. |
| `verify` | Check source availability and current location during the request. `live_checked` is `true` and `checked_at` is the current observation time. Stale/redirected/broken/incomplete sources trigger bounded public discovery. Use for onboarding/due diligence source preparation. |

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

- **cache-derived vs live-discovery** — `origin` (`catalog` / `live_discovery`);
- **cached vs checked-this-request** — `live_checked` + `checked_at`;
- **pending vs active cache update** — `catalog_status`
  (`candidate_processing` / `catalogued` / `null`).

## Human upload workflow

There are two surfaces with deliberately different capabilities:

- **Hosted browser Local Resolver** — a static, fully client-side page. It resolves
  an uploaded CSV (`vendor_name, business_entity_name, domain, jurisdiction,
  registration_number, registered_address`) against the reference cache in
  **cached** mode only, returning one unified result per vendor with a
  `result_state` column in the CSV/JSON export. Being static, it **does not**
  perform live discovery, fetch vendor URLs, or route candidates into the
  lifecycle; it reports cached reference-cache state and points to the resolver
  for live verification. It never uploads the CSV.
- **Resolver `verify` mode** (`resolve_inventory(...)` via Python/CLI, run
  server-side or in CI) — performs the live checks, discovers replacements and
  missing sources, and **durably enqueues** discovered/refreshed sources into the
  reference-cache lifecycle. Here users genuinely do not need to file GitHub
  issues for routine unmatched vendors, and never need to understand candidates,
  machine quorum, or internal workflow terminology.

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

Discovered/refreshed candidates are handed to a **durable, idempotent ingress**
that writes the unified candidate record to
`maintenance/candidates/<candidate_id>.json` — exactly the queue
`autonomous-catalog-growth.yml` reads eligible candidates from on a fresh
checkout.

### Durability ladder

Because the scheduled workflow checks out a ref (normally the remote default
branch) and only sees what is committed *there*, the resolver reports an
`ingress_state` and maps **only the top rung** to `candidate_processing`:

| `ingress_state` | meaning | eligible candidate's `catalog_status` |
| --- | --- | --- |
| `recorded` | in-memory only (`RecordingIngress`) | `pending_ingress` |
| `persisted_local` | written to the working tree | `pending_ingress` |
| `committed_local` | committed to a local ref (not pushed/merged) | `pending_ingress` |
| `submitted_remote` | submitted to a remote intake, visibility unconfirmed | `pending_ingress` |
| `workflow_visible` | reachable from the workflow ref (e.g. `origin/main`) | `candidate_processing` |

`CatalogQueueIngress(root, commit=…, workflow_ref="origin/main")` reaches
`workflow_visible` by comparing the candidate's blob OID against
`<workflow_ref>:<path>`, so a local-only commit never counts. `GitHubIntakeIngress`
implements the cleaner path — submit the candidate to a remote intake (PR/API or a
blob compare-and-swap onto the workflow branch) and report the acknowledged
visibility. Until a candidate is `workflow_visible`, the caller sees
`pending_ingress`.

### Concurrency and merge

The whole read -> validate -> merge -> re-evaluate -> write(-commit) transaction runs
under an exclusive lock (`fcntl` file lock for the shared queue;
`GitHubIntakeIngress` relies on the remote intake's serialisation / compare-and-swap
for cross-host safety). The persisted record is validated before merge (a corrupt
base is not trusted), and expanded evidence is merged by **normalised URL** so
trailing-slash/case/tracking-param variants do not create duplicates and newly
discovered sources are never silently dropped. Read-only/preview callers use the
non-durable `RecordingIngress`, which never claims a candidate is processing.

All fetches use the SSRF-safe `build_safe_verify_fetcher` bound to the vendor's
official domain (DNS-pinned IP, private/loopback/reserved/mixed-answer rejection,
per-hop redirect validation, same-authority enforcement, byte bound, deadline) —
never the legacy unrestricted client. URLs also fail closed via
`validate_url_safety` before any fetch.

## Catalogue mutation boundary

Live resolution **never** writes active catalogue/reference-cache files or `main`.
It resolves identity, checks URL status, discovers candidate URLs, classifies
provisionally, records observations, creates candidate records, and returns
session results. Active mutation continues only through the established lane:

```text
candidate -> eligibility -> machine_provisional -> observation
          -> independent machine quorum -> pull request
          -> release gates -> controlled automerge -> active catalogue/cache record
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
