# Universal Export Stance

OpenVA should export a universal, consumer-neutral dataset/pack format.

Compliance OS may consume OpenVA through a compatibility profile, but the primary OpenVA export should not be named or shaped as a Compliance OS-only export.

## Intended model

```text
OpenVA canonical records
  -> OpenVA universal export pack
  -> profiles/compliance-os
  -> Compliance OS import
```

## Why

OpenVA is intended to be useful to:

- GRC tools;
- procurement systems;
- vendor-risk systems;
- privacy tools;
- security review tools;
- researchers;
- public-interest projects;
- Compliance OS.

## P0 rule

P0 does not implement exports yet.

P1/P2 should define the native schema first. Universal exports and compatibility profiles should follow once the native public-data model stabilizes.
