# Source Classification

OpenVA classifies public source references by access and rights posture.

This policy exists to keep records factual, public-source-only, and metadata-first while still allowing maintainers to describe different public publication patterns.

## Access classes

### `public_web`

A normal public web page accessible without login, credentials, customer status, NDA, sales approval, support ticket access, private portal access, or anti-bot bypass.

### `public_pdf`

A directly accessible public PDF or public document file.

OpenVA still defaults to metadata-only records. A public PDF is not automatically mirrored.

### `public_doc_portal`

A public documentation portal where the content is browseable without restricted access.

### `public_landing_gated_docs`

A public landing page that mentions or links to restricted materials.

OpenVA may record the public landing page. It must not record the gated document contents, gated document hashes, screenshots, extracted text, or summaries of the gated content.

#### Trust-center landing pages and verification scope

A public trust-center landing page is a content-bearing source, even when the documents it links require approval. Distinguish three cases:

| Case | Eligible for materialization | Disclosure |
| --- | --- | --- |
| Public, content-bearing landing page (HTTP 200, identifies the vendor, names document categories); child documents gated | Yes — as a `trust_center` source verified at landing-page scope | `verified_scope: landing_page_only`, `gated_child_content_observed: false` |
| Login wall with no public assurance content | No | `unavailable_source` / access-state fact only |
| Unfetchable or bot-protected locator | No | candidate / access-state fact only |

A landing-page-only source establishes that the trust center exists and which document categories it lists. It must not assert possession or validity of any certification, report coverage periods, report contents, gated DPA or subprocessor contents, child-document hashes, or child-document summaries. Sources record `verified_scope` (`full_content` by default, `landing_page_only` for `public_landing_gated_docs`); `gated_child_content_observed` is a doctrine guarantee that is always `false`.

### `excluded_non_public`

A source that is not public enough for OpenVA records. This class should normally appear only in review notes or quarantined records.

## Rights classes

### `metadata_only`

Store metadata, public URL, provenance, and optional hashes only.

### `public_link_only`

Store only link and minimal descriptive metadata.

### `snapshot_allowed`

Raw or extracted snapshots may be retained only when redistribution rights are clear and maintainers explicitly approve retention.

### `snapshot_forbidden`

Do not retain raw or extracted source content.

### `gated_excluded`

The underlying material is gated or non-public and excluded from OpenVA.

## Valid combinations

The validator enforces conservative combinations:

| access_class | allowed rights_class values |
|---|---|
| `public_web` | `metadata_only`, `public_link_only`, `snapshot_forbidden`, `snapshot_allowed` |
| `public_pdf` | `metadata_only`, `public_link_only`, `snapshot_forbidden`, `snapshot_allowed` |
| `public_doc_portal` | `metadata_only`, `public_link_only`, `snapshot_forbidden` |
| `public_landing_gated_docs` | `metadata_only`, `public_link_only`, `gated_excluded` |
| `excluded_non_public` | `gated_excluded` |

## Official publisher exceptions

Most source URLs should live under the vendor's `official_domains`.

Some vendors publish public assurance materials through clearly official third-party platforms or dedicated trust domains. Those exceptions must be explicit and reviewable.

Add exceptions only through `config/official-publisher-exceptions.yaml`.

Do not use exceptions to include private portals, customer-only portals, NDA materials, or scraped third-party copies.
