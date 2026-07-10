# OpenVA licensing and reuse

OpenVA is intended to be freely usable, forkable, modifiable, redistributable, and suitable for both commercial and non-commercial products.

## Software and documentation: MIT

The repository's software and project documentation are licensed under the MIT License in [`LICENSE`](../LICENSE).

This includes, among other things:

- Python and JavaScript source code;
- APIs, MCP integrations, adapters, services, command-line tools, and crawler components;
- schemas, tests, workflows, examples, and project documentation;
- the static website implementation.

Under MIT, users may use, copy, modify, merge, publish, distribute, sublicense, and sell copies of the software. Forks and substantial redistributions must retain the MIT copyright and permission notice.

## OpenVA-authored catalog metadata: CC0 1.0

To remove database-reuse friction, OpenVA dedicates its original catalog metadata, generated indexes, and database rights to the public domain under [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/), to the extent legally possible.

This applies to OpenVA-authored metadata and generated data surfaces such as:

- `data/vendors/**`;
- `catalog-batches/**`;
- `indexes/**`;
- `dist/vendors/**`;
- `openva-pack.json`;
- public catalog snapshots and release CSV/JSON files generated from those records;
- OpenVA-created classifications, source-type labels, identifiers, provenance fields, and database selection or arrangement.

CC0 permits copying, modification, redistribution, extraction, combination, and commercial use without asking permission. Attribution to OpenVA is appreciated but is not required for CC0-covered metadata.

## Third-party materials are not licensed by OpenVA

OpenVA records factual locator metadata about vendor-published public sources. It does not grant rights in third-party materials, including:

- vendor names, logos, marks, and branding;
- DPAs, privacy notices, subprocessor lists, policies, reports, certificates, trust-center content, or other vendor documents;
- text, images, files, and webpages owned or licensed by their respective publishers;
- materials reached through URLs recorded by OpenVA.

Those materials remain subject to their owners' rights and terms. OpenVA's MIT and CC0 grants apply only to rights OpenVA can grant.

## Forking and building on OpenVA

A public or private fork may:

- modify or replace the crawler, catalog, UI, API, MCP server, adapters, and schemas;
- combine the metadata with other datasets;
- self-host the resolver or embed it in another product;
- distribute modified versions;
- offer commercial services based on the software or metadata.

For software, retain the MIT notice. For CC0-covered metadata, no attribution or share-alike obligation is imposed. Do not imply that OpenVA or a referenced vendor endorses a fork, product, analysis, or decision.

## No warranty or advice

The software and metadata are provided without warranty. OpenVA is factual public-source infrastructure, not legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice.

This document explains the project's intended licensing boundary and is not legal advice.
