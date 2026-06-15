# Catalog Growth Discovery

OpenVA uses taxonomy-driven discovery to grow the launch corpus without treating discovered vendors or sources as canonical truth.

## Control split

`config/category-taxonomy.yaml` is the semantic authority. It defines coverage lanes, vendor category tags, artifact categories, and launch coverage expectations.

`maintenance/queues/catalog-growth-discovery.json` is the operational queue. It selects which taxonomy lanes are active for launch discovery and sets bounded run limits.

`docs/maintenance/catalog-growth-scale-readiness.md` explains how catalog growth moves from bootstrap seed identities to queue-based discovery, reviewed promotion, and source maintenance.

## Discovery boundary

The queue drives discovery reports and generated candidate-promotion plan proposals. It does not write canonical vendor or source records.

The queue posture declares the aggregate capability of its enabled discovery modes. Network-fetching modes (`official_domain_source_discovery`, `sitemap_source_discovery`) make `network_fetch_performed` true; the queue and discovery lane still never write repository state, canonical sources, or candidate source records. Each enabled mode also carries a per-mode capability declaration validated against the authoritative code registry (`tools/openva/catalog_growth_discovery_queue.py`), so a network-fetching mode cannot be enabled under a no-network posture.

Required queue posture (for the committed queue, whose enabled modes fetch):

```text
network_fetch_performed: true
writes_repository_state: false
writes_canonical_sources: false
creates_candidate_sources: false
non_advisory: true
```

Discovery may fetch a vendor's own public assurance locators, but it never creates pull requests, runs promotion, or writes canonical vendor/source records. Catalog admission stays on the human-reviewed, PR-only promotion path.

## Launch corpus goal

The launch corpus target is a sizable starter registry, not every vendor in the world.

The seed corpus favors global and regulated-industry spread over raw count. It should cover
major lanes such as cloud platforms, CRM, payments, security, data and AI, developer tools,
productivity, HR, healthcare, insurance, public sector and defense, commerce, GRC, KYC/risk,
logistics, and APAC-focused discovery.

APAC discovery is a regional lane, not a vendor category shortcut. Vendors in that lane must
still carry functional `vendor_category_candidates` such as payments, cloud infrastructure,
HR software, collaboration software, or ecommerce.

## Staged identity-to-source pipeline

The catalog growth path is intentionally staged:

```text
seed vendor identities
-> validate IDs, domains, category tags, coverage lanes, and country-code shape
-> generate reviewed vendor-candidate reports
-> run official-domain source discovery for approved/materialized vendors
-> write candidate_sources or unavailable_sources
-> human review candidate promotions
-> promote approved sources into canonical records
-> use observation workflows to maintain freshness
```

Seed identities live under `maintenance/seeds/vendors/`. They are not canonical vendor
records and must keep:

```text
requires_review: true
writes_canonical_vendors: false
non_advisory: true
```

Validate seed identity shape with:

```text
python -m tools.openva.vendor_candidate_discovery validate-seeds
```

## After bootstrap seeds

Seed files are the bootstrap layer. They are not the permanent growth mechanism.

After a coverage lane has enough seed identity coverage, new candidates should come from the operational queue and candidate backlog. Candidate selection should account for:

- coverage gaps,
- source-health budget,
- candidate backlog state,
- official-domain authority,
- core source availability,
- duplicate or entity-family risk.

The durable lifecycle is:

```text
seeded
-> discovered
-> deduplicated
-> source_discovered
-> review_ready
-> approved_for_promotion
-> promoted
-> observed
-> maintenance_required
```

Keep the layers separate:

```text
seed files and discovery reports = staging input
maintenance/reviewed/ = reviewed promotion evidence
data/vendors/** = curated catalog
```

## Promotion readiness

A candidate is not promotion-ready just because it has a website.

Promotion requires reviewed evidence that the candidate has personal-data relevance, clear official-domain authority, useful public source coverage, coverage-gap fit, and enough dedupe confidence.

Promotion is blocked when:

- the official domain is unknown,
- the candidate duplicates an existing vendor or entity family,
- no public source candidates are available,
- source type appears mismatched,
- only gated materials are available,
- promotion would require raw document mirroring,
- source-health debt exceeds the agreed budget,
- the reviewed plan is not committed under `maintenance/reviewed/`.

## Source type scope

Start with the core vendor-assurance source set:

```text
dpa
subprocessors_list
privacy_notice
security_page
```

These are sufficient for vendor assurance intake and evidence preparation.

Defer extended source types until the core loop is stable:

```text
trust_center
security_whitepaper
compliance_page
certification_reference
product_terms
ai_terms
data_transfer_terms
```

## Automated workflow

`catalog-growth-discovery` runs on schedule and by manual dispatch.

It performs this path:

```text
catalog-growth-discovery queue
-> validate taxonomy-linked queue
-> discover new vendor candidates from public index surfaces
-> run source discovery against bounded existing vendor scope
-> build promotion plan
-> split candidate promotion actions into generated plan proposals
-> update catalog growth discovery issue
-> upload workflow artifacts
```

The workflow writes no canonical records and opens no Catalog PR directly.

## Vendor candidates

Vendor candidates are launch-corpus discovery outputs. They are not catalog vendor records.

A vendor candidate may identify:

```text
candidate_vendor_id
display_name_candidate
official_domain_candidate
coverage_lane
vendor_category_candidates
headquarters_country_candidate
cohort_id
source_index_url
```

A maintainer must review vendor candidates before any canonical vendor record is created.

## Source candidates

Generated candidate-promotion plan proposals are review inputs. Maintainers may copy approved proposals into `maintenance/reviewed/` before using `candidate-promotion-pr`.

## Batching

Candidate promotion proposals are split by `promotion_plan_batcher`.

Default batch size:

```text
50 candidate-promotion actions per generated plan proposal
```

Preferred initial reviewed batch size:

```text
25 candidate-promotion actions per reviewed plan
```

This keeps later Catalog PRs reviewable as the repository grows to thousands of vendors.

## Guardrails

- taxonomy lanes must exist in `config/category-taxonomy.yaml`
- source types must map through taxonomy artifact categories
- no canonical writes from the queue or discovery workflow
- no candidate auto-promotion
- no raw vendor document mirroring
- no vendor approval or suitability conclusion
- batch limits must stay small enough for reviewable PRs
- seed files must not become catalog records
- `candidate-promotion-pr.yml` remains the controlled catalog write path
- catalog growth must not bypass source-health constraints
