# Source Registry Schema v1

WP29 evolves the OpenVA catalog model from a list of vendor URLs into a source registry:

```text
vendor identity -> assurance source map -> retrieval hints -> source confidence -> health status -> observation history
```

This document defines the schema additions that support that model. It is a data-contract change only. It adds optional fields to existing schemas. It does not add workflows, bot authority, intake forms, verification automation, export endpoints, or index projections. Those are later work packages (WP30 through WP33).

## Design rules

- All new fields are optional. Every existing record remains valid without modification.
- The record `schema_version` line stays at `0.1.x`, per `docs/versioning-policy.md`: backward-compatible optional field additions may remain in the current line when validators and consumers can safely ignore them.
- `additionalProperties: false` discipline is preserved. New fields are declared explicitly; unknown fields remain rejected.
- Curated state and observed state stay separate. Fields on `source-reference` records are catalog truth: they change through reviewed pull requests. Continuous measurement stays in observation records and generated reports.
- Non-advisory boundary is unchanged. Confidence, health, and retrieval fields describe the evidentiary and operational state of a public source reference. They are not vendor risk, compliance, suitability, or approval signals.

## Vendor identity (`vendor-public-profile.schema.json`)

New optional fields:

| Field | Type | Meaning |
|---|---|---|
| `display_aliases` | array of strings | Former or alternate public names for the vendor (renames, common abbreviations, prior brand names). |
| `previous_domains` | array of domains | Domains that were previously official for this vendor. Preserves identity continuity across renames and domain migrations. |

`official_domains` remains the current-identity authority. `previous_domains` exists so that a vendor rename or domain change is recorded as history rather than overwritten.

## Assurance source map (`source-reference.schema.json`)

Four new optional objects.

### `canonical_confidence`

How confident the catalog is that this URL is the vendor's canonical location for this source type.

| Field | Type | Notes |
|---|---|---|
| `class` (required) | enum | `canonical`, `likely_canonical`, `mirror`, `redirected_entrypoint`, `ambiguous` |
| `basis` | string or null | Short evidence summary for the classification. |
| `assessed_at` | date-time or null | When the classification was last assessed. |

This complements `source_authority_class` (who published it) with where it sits in the vendor's own URL space. `ambiguous` is an explicit value so that uncertain classifications route to review instead of being silently recorded as canonical.

### `retrieval`

How the source can be retrieved, for both humans and agents.

| Field | Type | Notes |
|---|---|---|
| `method` (required) | enum | `html_page`, `pdf_document`, `rss_feed`, `atom_feed`, `json_api`, `llms_txt`, `mcp_server`, `sitemap`, `csv_download`, `other` |
| `machine_readable` (required) | boolean | Whether the source is consumable without HTML scraping. |
| `hints` | object or null | Optional machine-readable retrieval hints: `feed_url`, `api_endpoint`, `llms_txt_url`, `content_selector`, `notes`. |

### `source_health`

Curated, slowly-changing registry state for the source. This is the reviewed summary of health, not the measurement stream; per-run measurement remains in observation records and `source-health` reports.

| Field | Type | Notes |
|---|---|---|
| `status` (required) | enum | `ok`, `stale`, `moved`, `gated`, `broken`, `retired`, `unknown` |
| `as_of` (required) | date-time | When this status was last confirmed. |
| `basis` | string or null | Short evidence summary (for example a source-health run reference). |

Status vocabulary aligns with the observation result taxonomy: `moved` corresponds to redirect outcomes, `gated` to `auth_required`/`bot_protected` outcomes, `broken` to persistent `unreachable`/`fetch_failed` outcomes.

### `change_detection`

The reviewed baseline that future observations are compared against to decide whether a source materially changed.

| Field | Type | Notes |
|---|---|---|
| `baseline_observed_at` (required) | date-time | When the baseline was captured. |
| `baseline_observation_id` | string or null | Observation record the baseline came from, when one exists. |
| `baseline_raw_sha256` | sha256 string or null | Raw content hash at baseline. |
| `baseline_normalized_text_sha256` | sha256 string or null | Normalized text hash at baseline. |

## Observation history (`observation.schema.json`)

New optional fields on observation records:

| Field | Type | Meaning |
|---|---|---|
| `redirect_chain` | array of URIs or null | Ordered intermediate URLs observed between `source_url` and `final_url`. |
| `material_change` | boolean or null | Whether this observation's content hash differs from the source's recorded change-detection baseline. `null` means not evaluated. |
| `previous_observation_id` | string or null | The prior observation for the same source, forming a traversable history chain. |

These fields give Observation Ledger v2 (WP32) a schema substrate: hash history, redirect-chain history, and a changed-since-baseline marker, without changing how observations are produced today.

## How the classification vocabulary fits together

A submitted or observed source is described by independent axes rather than one overloaded status:

```text
who published it        -> source_authority_class (vendor_published, ...)
is the URL canonical    -> canonical_confidence.class (canonical, mirror, redirected_entrypoint, ambiguous, ...)
how to retrieve it      -> retrieval.method + retrieval.machine_readable + retrieval.hints
is it currently usable  -> source_health.status (ok, stale, moved, gated, broken, retired, unknown)
did it change           -> change_detection baseline + observation.material_change
```

WP30 (human submission intake) and WP31 (submitted source verification) will write candidate values for these axes; high-confidence cases can promote, ambiguous cases route to review.

## Out of scope for WP29

- No data backfill. Existing records adopt the new fields opportunistically through normal reviewed catalog work.
- No changes to index projections (`vendor-search.json`, `vendor-match-index.json` payload functions). Full-record indexes (`sources.json`, `vendors.json`, `observations.json`, vendor manifests) carry the new fields automatically. Projection and export contracts are WP33.
- No changes to `observe.py`, `source_health.py`, intake workflows, or bot authority contracts.
- No new pack `profileId` or `schemaVersion`: guarantees and manifest shape are unchanged.

## Validation

```bash
python -m tools.openva.validate validate
python -m pytest -q
```

Schema acceptance and rejection cases live in `tests/test_source_registry_schema.py`.

## Non-advisory reminder

Source registry fields describe the state of public source references. No combination of `canonical_confidence`, `retrieval`, `source_health`, or `change_detection` values means that OpenVA certifies, approves, scores, or recommends a vendor.
