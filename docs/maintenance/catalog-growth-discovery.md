# Catalog Growth Discovery

OpenVA grows the catalog through staged discovery. Discovery output is not catalog truth.

## Control split

`config/category-taxonomy.yaml` is the semantic control file. It defines coverage areas, vendor category tags, artifact categories, and coverage targets.

`maintenance/queues/catalog-growth-discovery.json` is the run queue. It selects active coverage areas and bounded run limits.

`maintenance/queues/catalog-growth-scale-readiness.json` is the scale contract. It defines the move from bootstrap seed files to queue-driven discovery, reviewed promotion, and post-promotion maintenance.

## Discovery boundary

The discovery queue produces reports and candidate-promotion plan proposals. It does not write canonical vendor or source records.

Required queue posture:

```text
network_fetch_performed: false
writes_repository_state: false
writes_canonical_sources: false
creates_candidate_sources: false
non_advisory: true
```

The scale contract is also non-executing:

```text
writes_canonical_vendors: false
writes_canonical_sources: false
creates_pull_requests: false
runs_promotion: false
```

## Launch corpus target

The launch target is a starter vendor registry with useful coverage across major assurance areas. It is not a scrape of every company registry.

Priority areas include cloud, CRM, payments, security, data and AI, developer tooling, productivity, HR, healthcare, insurance, public sector, commerce, GRC, KYC/risk, logistics, and APAC.

APAC is a regional coverage area, not a substitute category. APAC candidates still need functional tags such as `payments`, `cloud_infrastructure`, `hr_software`, `collaboration_software`, or `ecommerce_platform`.

## Pipeline

Catalog growth is staged:

```text
seed vendor identities
-> validate IDs, domains, tags, coverage areas, and country codes
-> generate vendor-candidate reports
-> run official-domain source discovery
-> produce candidate_sources or unavailable_sources
-> review candidate promotions
-> commit reviewed plans under maintenance/reviewed/
-> run candidate-promotion-pr.yml
-> observe and maintain promoted records
```

Seed identities live under `maintenance/seeds/vendors/`. They are staging records, not catalog records.

Seed files must keep:

```text
requires_review: true
writes_canonical_vendors: false
non_advisory: true
```

Validate seed identity shape with:

```text
python -m tools.openva.vendor_candidate_discovery validate-seeds
```

## Scale model after bootstrap

Seed files bootstrap coverage. They are not the long-term growth mechanism.

After a coverage area has enough seed coverage, candidate selection should come from:

```text
coverage gaps
+ source-health budget
+ candidate backlog state
+ official-domain authority
+ core source availability
-> review-ready candidates
```

Candidate lifecycle:

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

A promotion-ready candidate needs:

- personal-data relevance: processes personal data, supports cross-border transfer, acts as a subprocessor, or commonly appears in assurance reviews
- official-domain authority: official domain is clear enough to evaluate source URLs
- core source coverage: discovery found at least one core source candidate
- coverage-gap fit: candidate fills a priority coverage area, region, or regulated-industry gap
- dedupe confidence: candidate does not duplicate an existing vendor, product surface, entity family, or reviewed candidate
- source-health budget: catalog growth does not outpace source-maintenance capacity

Block promotion when:

- official domain is unknown
- candidate duplicates an existing vendor or entity family
- no public source candidates are available
- source type is mismatched
- only gated materials are available
- promotion would require raw document mirroring
- source-health budget is exceeded
- reviewed plan is not committed under `maintenance/reviewed/`

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

Do not expand the automated source target set until core-source discovery, promotion batching, and source maintenance are stable.

## Automated workflow

`catalog-growth-discovery.yml` runs on schedule and by manual dispatch.

Workflow path:

```text
catalog-growth-discovery queue
-> validate taxonomy-linked queue
-> discover vendor candidates
-> run source discovery against bounded vendor scope
-> build promotion plan
-> split promotion actions into plan proposals
-> update catalog growth discovery issue
-> upload artifacts
```

The workflow writes no canonical records and opens no Catalog PR.

## Vendor candidates

Vendor candidates are staging outputs. They are not catalog records.

A vendor candidate may include:

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

A maintainer or maintainer-agent must review vendor candidates before any catalog record is created.

## Source candidates

Generated candidate-promotion plan proposals are review inputs. Approved proposals may be copied into `maintenance/reviewed/` before running `candidate-promotion-pr.yml`.

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

Keep batches small enough for review.

## Guardrails

- taxonomy coverage areas must exist in `config/category-taxonomy.yaml`
- source types must map through taxonomy artifact categories
- no canonical writes from queue or discovery workflows
- no candidate auto-promotion
- no raw vendor document mirroring
- no vendor approval or suitability conclusion
- batch limits must stay reviewable
- seed files must not become catalog records
- `candidate-promotion-pr.yml` remains the controlled catalog write path
- catalog growth must not bypass source-health constraints
