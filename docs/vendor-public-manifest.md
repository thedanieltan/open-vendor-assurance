# Vendor Public Manifest

Vendors that want to support public metadata reuse may optionally publish a machine-readable public manifest.

This is not required for OpenVA participation. It is a convenience pattern for vendors that want public trust, legal, privacy, security, DPA, and subprocessor references to be easier for contributors and agents to discover.

## Purpose

A public manifest helps OpenVA discover public changes without bypassing vendor infrastructure.

It can point to public vendor-controlled sources such as:

- trust centers;
- data processing addenda;
- subprocessor lists;
- security pages;
- privacy notices;
- AI or data-use terms;
- regional data residency pages;
- public changelogs.

## Suggested location

A vendor may publish a manifest at a stable public URL, such as:

```text
https://vendor.example/.well-known/openva.json
```

Other public vendor-controlled locations are acceptable.

## Example

```json
{
  "profileId": "openva.vendor-public-manifest.v1",
  "vendorId": "example-vendor",
  "updatedAt": "2026-05-14T00:00:00Z",
  "sources": [
    {
      "sourceType": "dpa",
      "title": "Data Processing Addendum",
      "url": "https://vendor.example/legal/dpa",
      "version": "2026-05-01"
    },
    {
      "sourceType": "subprocessors_list",
      "title": "Subprocessors",
      "url": "https://vendor.example/legal/subprocessors",
      "version": "2026-04-20"
    }
  ]
}
```

## Boundary

A public manifest should contain references to public sources only.

It should not contain private customer agreements, bespoke terms, NDA materials, customer-portal exports, private reports, private certificates, login-only URLs, or materials requiring form submission, sales approval, support ticket access, credentials, or private portal access.

## Review posture

A vendor public manifest is a source discovery aid, not an endorsement or certification mechanism.

OpenVA maintainers still review proposed records for public-source-only, metadata-first, non-advisory, non-promotional, and URL safety rules.

## Future schema

OpenVA may later add a formal JSON schema for vendor public manifests after the convention has been tested with real contributors and vendors.

Until then, this document is guidance, not a mandatory interface.
