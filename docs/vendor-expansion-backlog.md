# Vendor Expansion Backlog

This backlog guides future OpenVA catalog expansion.

It is not a commitment that every listed vendor will be added. A vendor should be added only when there is a suitable public vendor-controlled source and the record can remain metadata-only, public-source-only, and non-advisory.

## Batch rules

Future expansion batches should:

- add three to five vendors at a time;
- prefer one coherent category per batch;
- use public vendor-controlled sources only;
- avoid raw document mirroring;
- keep hashes as `sha256:TBD` unless observation tooling was run;
- regenerate indexes and `openva-pack.json` before merge;
- pass pack integrity and URL safety validation.

## Priority 1: developer and deployment platforms

These vendors frequently appear in software supply chains and developer workflows.

Suggested batch:

- GitHub
- GitLab
- Vercel
- Netlify
- Docker

Likely source types:

- trust center;
- security page;
- DPA or data protection terms;
- subprocessor list.

## Priority 2: payments, communications, and customer infrastructure

These vendors often process personal data, transaction metadata, communication metadata, or customer records.

Suggested batch:

- Stripe
- Twilio
- SendGrid
- Intercom
- Zendesk

Likely source types:

- DPA;
- subprocessor list;
- trust center;
- privacy or data protection terms.

## Priority 3: identity, access, and secrets management

These vendors are security-critical and commonly appear in enterprise assurance reviews.

Suggested batch:

- Okta
- Auth0
- 1Password
- Keeper
- Bitwarden

Likely source types:

- trust center;
- security page;
- DPA;
- subprocessor list.

## Priority 4: productivity and collaboration SaaS

These vendors often hold business communications, files, project data, or customer content.

Suggested batch:

- Slack
- Notion
- Asana
- Monday.com
- Miro

Likely source types:

- trust center;
- security page;
- DPA;
- subprocessor list.

## Priority 5: CRM, marketing, and customer data platforms

These vendors are common in data inventories and often process customer, lead, and behavioral data.

Suggested batch:

- HubSpot
- Mailchimp
- Braze
- Segment
- Amplitude

Likely source types:

- DPA;
- subprocessor list;
- privacy terms;
- security page.

## Priority 6: APAC and mainland China SaaS

OpenVA should not overfit only US and western SaaS vendors.

Suggested batch candidates:

- Lark
- BytePlus
- Huawei Cloud
- Kingsoft Cloud
- NAVER Cloud
- LINE WORKS
- Cybozu
- SmartHR

Likely source types:

- trust center;
- security page;
- privacy or data protection terms;
- public legal terms.

## Priority 7: EU infrastructure and SaaS

EU vendors improve regional diversity and help expose multilingual and regional-document edge cases.

Suggested batch candidates:

- OVHcloud
- Scaleway
- Hetzner
- Personio
- Mistral AI

Likely source types:

- trust center;
- security page;
- DPA;
- privacy terms;
- regional legal terms.

## Observation backlog

After several more vendor batches, OpenVA should add observation records for a small subset.

Suggested first observation subset:

- AWS subprocessor source;
- Google Cloud subprocessor source;
- Microsoft DPA or licensing source;
- Alibaba Cloud legal or trust source;
- Tencent Cloud subprocessor source.

The purpose is to validate observation schemas, hash handling, dry-run behavior, URL safety, and downstream pack import behavior.

## Deferral list

Do not prioritize these until the public-source-only and metadata-only boundaries are more battle-tested:

- vendors whose assurance materials are mostly behind private trust portals;
- vendors whose useful materials require customer login;
- vendors whose sources require form submission;
- vendors whose public pages are mostly marketing claims with little assurance metadata;
- vendors whose sources are primarily third-party mirrors.

## Priority 8: payments and KYC expansion

Recent payments and KYC expansion added public metadata for Adyen, PayPal, Airwallex, Plaid, Wise, Trulioo, Sumsub, Alloy, Chainalysis, and ComplyAdvantage.

Future work in this lane should prioritize deeper public DPA, subprocessor, security, and trust-center coverage for these vendors where clear public vendor-controlled sources are available.
