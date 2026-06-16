# Public Roadmap

This roadmap communicates OpenVA direction without creating a support, legal,
compliance, procurement, security, or vendor-certification commitment.

OpenVA is a public-source-only, metadata-first registry of vendor-published
assurance references. It is not an advisory or vendor-ranking service.

## Current state

OpenVA operates an autonomous catalog pipeline for bounded, machine-verifiable
public-source facts. Discovery, verification, observation, maintenance,
promotion, rollback, publication, and audit actions run through declared
workflows and pull-request gates. Humans govern code, schemas, authority,
permissions, thresholds, and exceptions.

The catalog remains an evolving public dataset. A published record means OpenVA
identified and classified a public source reference; it does not mean the vendor
is compliant, approved, safe, certified, suitable, or recommended.

## Priorities

### Coverage quality

- deepen DPA, subprocessor, privacy, security, compliance, and trust-center
  coverage for commonly used vendors;
- expand regional and industry coverage through bounded catalog batches;
- prefer authoritative vendor-controlled sources over inferred URLs;
- preserve native-language source metadata where available.

### Source freshness and reliability

- increase recent observation coverage;
- detect moved, unavailable, bot-protected, and materially changed sources;
- repair or quarantine sources only through evidence-bearing workflows;
- keep discovery and maintenance bounded by host, URL, byte, and time limits.

### Machine consumption

- keep static exports deterministic, schema-versioned, and digest-verifiable;
- maintain the hosted vendor pages, agent index, discovery manifest, sitemap,
  robots file, and `llms.txt` surface;
- publish stable MCP and package distributions when release operations are ready;
- provide importer fixtures and inventory-matching examples without introducing
  risk scoring or organization-specific decisions.

### Governance and compatibility

- preserve deny-by-default workflow authority;
- require independent evidence and separation of duties for autonomous promotion;
- keep every machine-created catalog claim reversible;
- maintain release gates, conformance fixtures, versioning rules, and public
  security and contribution policies;
- retire obsolete workflows and documentation only after their durable contracts
  and evidence have been identified.

## Operating boundaries

OpenVA will continue to use:

- public sources only;
- metadata-first records rather than raw document mirroring;
- pull requests for every repository mutation;
- machine-readable authority contracts and release gates;
- bounded automation that fails closed on ambiguity;
- human governance for policy, authority, schema, workflow, and permission changes.

## Not on the roadmap

OpenVA does not plan to provide:

- legal, compliance, procurement, audit, security, KYC, AML, sanctions, or
  vendor-risk advice;
- vendor approval badges, rankings, recommendations, or risk scores;
- customer-specific agreement analysis;
- authenticated trust-center or private-portal collection;
- credentialed scraping, CAPTCHA solving, proxy rotation, or anti-bot bypass;
- private evidence storage;
- raw document mirroring by default.

## Contribution priorities

Good contributions are bounded and testable, for example:

- correcting a public source reference;
- adding public metadata for a clearly identified vendor source;
- improving fixtures, examples, or factual documentation;
- adding tests around existing behavior;
- improving adapter compatibility without changing catalog meaning.

Schema, workflow-authority, permission, and policy-threshold changes require
maintainer review and explicit scope.

## Public operation checks

Maintainers should keep the following true:

- project scope and limitations are accurately documented;
- governance, contribution, security, and licensing documents are current;
- generated outputs are reproducible and drift-free;
- validation and release gates pass;
- scheduled workflows are enabled and observable;
- public discovery and agent-export endpoints are available;
- open issues and pull requests do not misrepresent catalog completeness or
  automation authority.
