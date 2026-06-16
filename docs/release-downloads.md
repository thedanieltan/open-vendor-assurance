# Release Downloads For Spreadsheet Users

OpenVA publishes spreadsheet-friendly release assets through GitHub Releases.

These files are for users who want to inspect public vendor assurance metadata without installing Python, running Docker, or hosting a service.

To resolve your own vendor list against the catalogue, use the unified resolver
described in `docs/vendor-resolution.md`. Its `verify` mode confirms current
sources, refreshes stale or broken ones, and discovers missing vendors and source
types — all in one combined result with CSV/JSON export and a `result_state` per
vendor. The hosted browser Local Matcher offers the same combined result in
`cached` mode (latest known catalogue state only); it does not perform the live
check or routing.

OpenVA v0.1.0 is an infrastructure launch, not a completeness claim.

The initial catalog is a seed dataset. It is useful for testing importer
workflows, matching public vendor assurance references, and contributing
public-source metadata, but it should not be treated as complete vendor
assurance coverage.

## Where to find the files

1. Open the OpenVA repository on GitHub.
2. Select **Releases** in the right sidebar or open the latest release from the repository home page.
3. Expand **Assets**.
4. Download the files you need.

## Hosted catalog viewer

Hosted catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/

Use the hosted catalog viewer to browse the reviewed catalog snapshot, use the browser-local matcher, and export selected public OpenVA metadata without installing tooling.

The hosted viewer is static and read-only. It does not provide accounts, workspaces, server-side matching, hosted private inventory upload, vendor approval, risk scoring, legal advice, compliance advice, procurement advice, KYC/AML conclusions, sanctions conclusions, or certification-validity conclusions.

## Which file to download

Use:

```text
openva-csv.zip
```

to browse OpenVA in a spreadsheet. This is the main non-technical download.

It contains:

```text
vendors.csv
sources.csv
artifacts.csv
observations.csv
candidate_sources.csv
unavailable_sources.csv
source_coverage.csv
```

Use:

```text
openva-inventory-template.csv
```

to prepare your own vendor inventory for matching with OpenVA tooling. Use whichever columns you already have:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

`vendor_name` is usually enough to get a brand-level match. `business_entity_name` is useful when your inventory stores the contracting or billing entity name instead of the product or brand name. `domain` improves brand match confidence when available. `jurisdiction` lets OpenVA use the contracting-entity resolution index when the catalog has a public record for that vendor and jurisdiction. `registration_number` is optional, but it is the strongest entity-level identifier when OpenVA has the corresponding legal entity record. In Singapore, this is the UEN. `registered_address` is optional context from your own inventory and is preserved in the output.

Use:

```text
openva-sample-inventory.csv
```

to see a small example inventory.

Use:

```text
openva-release-downloads-manifest.json
release-artifacts.json
```

only if you want checksums and release artifact metadata.

## Deterministic pack timestamps

OpenVA pack and generated index timestamps may use a fixed value such as
`1970-01-01T00:00:00Z` to preserve deterministic rebuilds.

This value is not a catalog freshness signal.

Consumers that need freshness or provenance should use:

- the pinned release tag or repository commit SHA;
- source-level `provenance.collected_at`;
- change-level `detected_at`;
- observation-level `observed_at`, where observation records exist.

Do not treat pack-level `generated_at` or `generatedAt` as evidence that
a vendor source was collected, reviewed, updated, or observed at that time.

## How to read the CSVs

Start with `vendors.csv` to find a vendor by name or domain.

Use `source_coverage.csv` to see which public source types OpenVA currently records for each vendor, such as DPA, privacy notice, security page, and subprocessors.

Use `sources.csv` to inspect the public URLs themselves.

Use `candidate_sources.csv` and `unavailable_sources.csv` carefully:

- candidate sources are not canonical records yet;
- unavailable sources are catalog notes, not negative compliance findings;
- observations are fetch-time facts, not vendor ratings.

## Matching your own vendor list

OpenVA does not operate a public upload service or central hosted matching
service. HTTP access is available only through the optional self-hosted match
service. Users should keep private vendor inventories inside their own
environment.

If you want to match a vendor list against OpenVA today:

- prepare your file using `openva-inventory-template.csv`;
- use the hosted site's browser-local matcher, where your CSV is processed locally in your browser and is not uploaded to OpenVA;
- or run the local Python matcher / optional self-hosted match service inside your own environment;
- keep the input vendor inventory inside your own environment.

The local matcher accepts these columns:

```text
vendor_name
business_entity_name
domain
jurisdiction
registration_number
```

At least one of `vendor_name`, `business_entity_name`, `domain`, or `registration_number` is required. `jurisdiction` helps with legal entity resolution when a brand match already exists. `registered_address` and other columns, such as an internal owner, business unit, or category, are preserved in the output but are not required for matching.

and writes an enriched CSV with OpenVA public metadata references.

## Hosted catalog viewer and live observation feed

OpenVA provides a hosted viewer for browsing and exporting selected public
OpenVA metadata from a reviewed catalog snapshot.

Hosted catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/

The viewer may also display a live observation feed of machine-generated
public-source events. The live feed is non-canonical and is separate from the
human-reviewed catalog.

The live feed UI shell currently ships with an empty state. Real observation
events require the observation ledger workflow, which is a subsequent PR.

The viewer does not accept private vendor inventory uploads, private contracts,
SOC reports, credentials, screenshots, or customer-specific evidence.

The reviewed catalog is not a live monitoring feed. The page displays the
release tag, commit SHA, and catalog snapshot date where available. For
reproducible use, pin the GitHub release or commit.

Live observation events are machine-generated public-source facts. They are not
vendor approval, compliance findings, risk findings, procurement
recommendations, legal opinions, or materiality determinations.

The site is deployed to GitHub Pages from the static site build output.

For private inventory matching, use the browser-local matcher, local matcher, or optional self-hosted
match service inside your own environment.

## Legal entity resolution

OpenVA separates brand matching from legal entity matching.

For example, a Singapore inventory row for Stripe might produce:

```text
Vendor name: Stripe
Domain matched: stripe.com
Brand match: stripe, exact domain, confidence 1.00
Legal entity match method: jurisdiction_resolution_index
Legal entity resolution confidence: candidate
Candidate entity: Stripe Payments Singapore Pte. Ltd.
Registration number: populated when OpenVA has the public registry record
```

`candidate` means public metadata suggests the entity may be relevant for that jurisdiction. It is not confirmation from your signed agreement. OpenVA provides the public DPA reference only; confirm that the entity named in your signed agreement matches the entity shown in OpenVA.

## Missing or stale data

If a vendor is missing, a public source moved, or OpenVA records incomplete metadata, open a GitHub issue using the **Vendor catalog update** form.

Submit public URLs only. Do not submit private agreements, gated portal exports, screenshots, copied document text, credentials, SOC reports, private certificates, or customer-specific terms.

## Non-advisory reminder

OpenVA records public-source metadata only.

It does not approve, recommend, certify, score, or determine whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.
## Hosted site compiled catalog distribution

The hosted catalog viewer is generated as a compiled catalog distribution.
It uses a lightweight `vendor-search.min.json` index for browsing and loads
`data/vendors/{vendor_id}.json` detail shards on demand.

This keeps the non-dev hosted site usable as OpenVA grows. GitHub Release
assets remain the bulk-download path for CSVs, templates, and internal tooling.