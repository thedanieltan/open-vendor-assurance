# Catalog Growth Discovery

OpenVA uses taxonomy-driven discovery to grow the launch corpus without treating discovered vendors or sources as canonical truth.

## Control split

`config/category-taxonomy.yaml` is the semantic authority. It defines coverage lanes, vendor category tags, artifact categories, and launch coverage expectations.

`maintenance/queues/catalog-growth-discovery.json` is the operational queue. It selects which taxonomy lanes are active for launch discovery and sets bounded run limits.

## Discovery boundary

The queue may drive discovery reports and candidate records in later workflows, but it does not write canonical source records.

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

## Automation path

The intended downstream path is:

```text
catalog-growth-discovery queue
-> scheduled discovery workflow
-> vendor candidate and source discovery reports
-> promotion planning
-> reviewed candidate promotion plans
-> candidate-promotion-pr
-> generated Catalog PR
-> maintainer merge
```

Discovery can be automated. Canonical mutation remains reviewed.

## Guardrails

- taxonomy lanes must exist in `config/category-taxonomy.yaml`
- source types must map through taxonomy artifact categories
- no canonical writes from the queue
- no candidate auto-promotion
- no raw vendor document mirroring
- no vendor approval or suitability conclusion
- batch limits must stay small enough for reviewable PRs
