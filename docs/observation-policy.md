# Observation and Hashing Policy

OpenVA is metadata-first. Hashing is an integrity mechanism, not the purpose of the project.

## Why hash public sources

Hashes help OpenVA record what was observed at a point in time without storing or redistributing the source material.

A hash can support:

- change detection;
- reproducibility;
- source integrity checks;
- lightweight provenance;
- contributor review when a public source changes.

## Hashing is not mandatory for every record

A record may remain useful with `sha256:TBD` when:

- the public source is difficult to fetch safely;
- the page is highly dynamic;
- the site blocks automated access;
- the source needs human review;
- hashing would create excessive operational burden.

OpenVA should prefer accurate metadata over brittle automation.

## Cost at scale

Hashing has real maintenance cost:

- network requests consume CI or runner time;
- large vendor pages can be slow or unstable;
- bot defenses may cause noisy failures;
- dynamic pages may produce unstable hashes;
- observation records increase repository size over time;
- contributors must review false-positive diffs.

The mitigation is selective observation, retention limits, and metadata-only defaults.

## Public-only fetch rule

Observation tooling must stop when a source appears to require login, credentials, customer status, NDA, sales approval, private portal access, support-ticket access, or anti-bot bypass.

Observation tooling must not:

- submit forms;
- use credentials;
- bypass access controls;
- execute remote JavaScript as trusted code;
- scrape authenticated portals;
- store raw documents by default.

## Hash classes

OpenVA uses two hash concepts:

- `raw_sha256`: SHA-256 of the fetched byte response when safely available;
- `normalized_text_sha256`: SHA-256 of normalized text extracted from a public response.

The normalized text hash is usually more useful for HTML pages because it reduces noise from formatting and markup changes.

## Observation output

Observation tooling should create observation records. It should not automatically rewrite source or artifact records unless a maintainer explicitly chooses to do so.

This keeps hashing as provenance evidence, not as a required gate for contribution.
