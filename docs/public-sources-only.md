# Public Sources Only Policy

OpenVA accepts only public vendor-published or standards-body-published source metadata.

## Public means

A source is public only if it is accessible without:

- login;
- credentials;
- NDA;
- customer status;
- sales approval;
- support ticket access;
- private trust-center access;
- private customer portal access;
- anti-bot bypass;
- credentialed API access.

## Excluded sources

The following are out of scope:

- bespoke agreements;
- private customer contracts;
- order forms;
- reseller-specific private terms;
- NDA materials;
- authenticated trust-center documents;
- customer portal downloads;
- private SOC reports;
- private ISO certificates;
- documents requiring login, sales approval, or customer status.

## Gated-material rule

If a vendor publicly states that gated materials exist, OpenVA may record the public landing page as a source reference.

OpenVA must not include:

- gated document contents;
- gated document hashes;
- summaries of gated documents;
- extracted text from gated documents;
- screenshots of gated documents.

## Bot behavior

If automation encounters a login wall, access denied page, bot challenge, or customer-only portal, it must stop and flag the source as out of scope or human review required.
