# Agent Update Workflow

OpenVA may eventually be updated by agents that observe public vendor sources and propose metadata changes.

The agent model must stay aligned with OpenVA's core boundary:

```text
public vendor source -> observation -> proposed metadata update -> validation -> review
```

Agents should not become legal, compliance, procurement, security, KYC, AML, or vendor-risk advisors.

## Core rule

Agents may observe public vendor-published sources.

Agents must not rely on contributor identity as authority. The public source reference, observed URL, access class, rights class, provenance metadata, and validation results are the evidence.

## Allowed agent actions

Agents may:

- fetch public source URLs already recorded in OpenVA;
- compute `raw_sha256` when safe;
- compute `normalized_text_sha256` when safe;
- create observation records;
- detect changed hashes;
- propose source URL updates when a public source moved;
- propose artifact metadata updates;
- regenerate indexes;
- open pull requests for maintainer review.

## Prohibited agent actions

Agents must not:

- log in;
- use credentials;
- bypass anti-bot systems;
- submit forms;
- scrape private portals;
- collect NDA-gated materials;
- summarize private or gated documents;
- store raw vendor documents by default;
- score vendors;
- approve vendors;
- generate legal or compliance conclusions;
- rewrite records into promotional language.

## Change workflow

```text
1. Agent reads existing source records.
2. Agent fetches only public URLs.
3. Agent produces observation records.
4. Agent compares hashes and metadata.
5. Agent opens a pull request when a public source appears changed.
6. CI validates source classes, rights classes, prohibited wording, paths, references, and generated indexes.
7. Maintainer or trusted automation reviews the PR.
```

## Vendor hooks

If vendors later expose webhooks, feeds, signed changelogs, RSS, sitemap updates, or public update pages, agents may use those public mechanisms as change signals.

A vendor hook should create a proposed update, not an automatic endorsement.

The update must still pass OpenVA validation.

## Minimal posture

OpenVA should prefer small, reviewable PRs:

- one vendor per PR where practical;
- one source move per PR where practical;
- observation records separated from metadata edits where practical;
- no generated legal interpretation.
