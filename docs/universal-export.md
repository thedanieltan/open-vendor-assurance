# Universal Export Stance

OpenVA should export a universal, consumer-neutral dataset/pack format.

The primary OpenVA export should not be named or shaped around any single downstream application, runtime, or product.

## Intended model

```text
OpenVA canonical records
  -> OpenVA universal export pack
  -> consumer compatibility profiles
  -> downstream imports
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
- internal vendor catalogs;
- other downstream systems.

## P1 rule

P1 does not implement exports yet.

Native schemas should stabilize first. Universal exports and compatibility profiles should follow once the native public-data model is validated.
