# Catalog Growth Discovery

OpenVA uses taxonomy-driven discovery to grow the launch corpus without treating discovered vendors or sources as canonical truth.

## Control split

`config/category-taxonomy.yaml` is the semantic authority. It defines coverage lanes, vendor category tags, artifact categories, and launch coverage expectations.

`maintenance/queues/catalog-growth-discovery.json` is the operational queue. It selects which taxonomy lanes are active for launch discovery and sets bounded run limits.

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

This keeps later Catalog PRs reviewable as the repository grows to thousands of vendors.

## Guardrails

- taxonomy lanes must exist in `config/category-taxonomy.yaml`
- source types must map through taxonomy artifact categories
- no canonical writes from the queue or discovery workflow
- no candidate auto-promotion
- no raw vendor document mirroring
- no vendor approval or suitability conclusion
- batch limits must stay small enough for reviewable PRs
