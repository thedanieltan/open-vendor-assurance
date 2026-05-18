# Public Update Pathway

OpenVA welcomes updates from vendors, contributors, researchers, and agents when those updates improve public-source metadata.

The public source remains the authority. OpenVA does not rely on contributor identity alone as source authority.

Vendor participation is encouraged when it helps keep public metadata accurate, current, and machine-readable.

## What this pathway is for

Use this pathway to submit factual updates to public vendor-controlled sources, such as:

- trust centers;
- security pages;
- data processing addenda;
- subprocessor lists;
- privacy notices;
- AI or data-use terms;
- public changelogs;
- public legal terms;
- public regional data residency pages.

## What this pathway is not for

Do not submit:

- private customer agreements;
- bespoke or negotiated terms;
- NDA-gated materials;
- customer portal exports;
- private trust-center documents;
- private SOC reports;
- private certificates;
- login-only documents;
- materials that require form submission, sales approval, support ticket access, credentials, or private portal access;
- vendor ratings, scores, approvals, recommendations, or suitability claims.

## Anti-bot and access-control boundary

OpenVA does not bypass anti-bot systems, CAPTCHAs, login gates, private portals, form gates, or access controls.

If a public source cannot be observed automatically, OpenVA may still retain metadata about the public source and may accept human- or vendor-submitted updates that reference the public URL.

Vendor cooperation should create better public update paths, not exceptions to OpenVA's public-source-only boundary.

## Update paths

### Non-technical contributor updates

Non-technical contributors should use the GitHub issue form named:

```text
Vendor catalog update
```

That issue is an intake request, not a catalog record. The catalog intake handoff workflow comments with the maintainer or catalog-agent checklist, and an accepted request must still become a reviewed `Catalog:` PR before it changes OpenVA data.

### Agent-observed updates

An agent may observe public vendor URLs, compute metadata or hashes when safe, and propose updates.

Agents must not log in, submit forms, solve CAPTCHAs, rotate proxies, bypass anti-bot controls, or collect gated materials.

### Human-maintained updates

Human contributors may submit corrections when automation is blocked, ambiguous, or incomplete.

Human-maintained updates should still point to public vendor-controlled sources and remain metadata-only.

### Vendor-submitted updates

Vendors may submit updates when they publish, move, retire, or revise public assurance materials.

Vendor-submitted updates should point to public URLs and should remain factual metadata. Vendor-submitted does not mean OpenVA endorses, approves, certifies, or scores the vendor.

## Better public update signals

Vendors that want to support public metadata reuse may optionally publish public update signals, such as:

- a public changelog;
- a public RSS or Atom feed;
- sitemap entries;
- a public JSON manifest;
- a public repository containing metadata references;
- a stable public legal or trust-center update page.

These mechanisms help OpenVA and downstream consumers discover public changes without bypassing vendor infrastructure.

## Review rule

Every update is reviewed against the same boundaries:

- public-source-only;
- metadata-first;
- non-advisory;
- no raw document mirroring by default;
- no gated materials;
- no promotional claims;
- source URL must be vendor-controlled or covered by an approved public publisher exception.

The handoff is complete only when the resulting PR is linked back to the intake issue or the issue is closed with a clear scope decision.
