# Catalog Growth Discovery

OpenVA uses taxonomy-driven discovery to grow the launch corpus without treating discovered vendors or sources as canonical truth.

## Control split

`config/category-taxonomy.yaml` is the semantic authority. It defines coverage lanes, vendor category tags, artifact categories, and launch coverage expectations.

`maintenance/queues/catalog-growth-discovery.json` is the operational queue. It selects which taxonomy lanes are active for launch discovery and sets bounded run limits.

`maintenance/queues/catalog-growth-scale-readiness.json` is the scale-readiness contract. It defines how OpenVA moves from bootstrap seed files to queue-driven discovery, evidence-scored promotion, and continuous refresh without weakening catalog write controls.

## Discovery boundary

The queue drives discovery reports and generated candidate-promotion plan proposals. It does not write canonical vendor or source records.

Required queue posture:

```text
network_fetch_performed: false
writes_repository_state: false
writes_canonical_sources: false
creates_candidate_sources: false
non_advisory: true
```

The scale-readiness contract must also remain non-canonical:

```text
writes_canonical_vendors: false
writes_canonical_sources: false
creates_pull_requests: false
runs_promotion: false
```

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
-> human or maintainer-agent review candidate promotions
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

## Scale model after bootstrap seeds

Initial seed files are a bootstrap mechanism, not the permanent growth engine.

When a lane has enough seed identity coverage, growth should shift from manual seed expansion to queue-driven backlog selection:

```text
coverage gaps
+ source-health budget
+ candidate backlog state
+ official-domain authority
+ core source availability
-> next review-ready candidates
```

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

This keeps raw discovery and curated catalog records separate. Seed files and discovery reports are staging inputs. Reviewed plans under `maintenance/reviewed/` are promotion evidence. `data/vendors/**` remains the curated catalog.

## Promotion readiness

A candidate should not become promotion-ready merely because it exists or has a website.

Promotion readiness requires evidence across these dimensions:

- personal-data relevance: the vendor is likely to process personal data, support cross-border transfer, act as a subprocessor, or appear in vendor assurance workflows
- official-domain authority: the vendor has a clear official domain and source URLs can be evaluated against that domain
- core source coverage: discovery found at least one source candidate from the core source set
- coverage-gap fit: the candidate fills a taxonomy lane, region, or regulated-industry gap
- dedupe confidence: the candidate does not duplicate an existing canonical vendor, product surface, entity family, or reviewed candidate
- source-health budget: Lane B should slow down if Lane A source debt exceeds the allowed budget

Promotion is blocked when any of the following applies:

- official domain is unknown
- candidate duplicates an existing vendor or entity family
- no public source candidates are available
- source type appears mismatched
- only gated materials are available
- promotion would require raw document mirroring
- source-health budget is exceeded
- reviewed plan is not committed under `maintenance/reviewed/`

## Core and extended source types

The current growth queue intentionally starts with the core vendor-assurance source set:

```text
dpa
subprocessors_list
privacy_notice
security_page
```

These are the minimum useful source families for vendor assurance intake and evidence preparation.

Extended source types are deferred until the core discovery and promotion loop proves reliable:

```text
trust_center
security_whitepaper
compliance_page
certification_reference
product_terms
ai_terms
data_transfer_terms
```

Do not expand the automated target source set until core-source discovery quality, promotion batching, and Lane A source maintenance are stable.

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

A maintainer or maintainer-agent must review vendor candidates before any canonical vendor record is created.

## Source candidates

Generated candidate-promotion plan proposals are review inputs. Maintainers or maintainer-agents may copy approved proposals into `maintenance/reviewed/` before using `candidate-promotion-pr`.

## Batching

Candidate promotion proposals are split by `promotion_plan_batcher`.

Default batch size:

```text
50 candidate-promotion actions per generated plan proposal
```

Preferred initial batch size while the loop is still being proven:

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
- seed files must not become canonical vendor records
- `candidate-promotion-pr.yml` remains the controlled catalog write path
- Lane B growth must not bypass Lane A source-health constraints
