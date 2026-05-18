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

The queue targets broad coverage across major lanes such as cloud platforms, CRM, payments, security, data and AI, developer tools, productivity, HR, commerce, GRC, KYC/risk, and regional APAC.

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
