# Catalog Lifecycle Materializer

OpenVA catalog manifests support three lifecycle operations:

```text
create
refresh
deprecate
```

These modes exist because the catalog is a public metadata ledger, not a static directory.

## create

Use `create` for new vendors or new public source/artifact references.

Expected behavior:

```text
create vendor/source/artifact records
rebuild indexes
optionally emit created change events
```

## refresh

Use `refresh` when an existing public DPA, subprocessor list, privacy notice, security page, compliance page, or other public source has been reviewed again.

Expected behavior:

```text
update current metadata records
append change events with change_type: updated
rebuild indexes
```

Refresh events must remain factual and non-advisory. They should not score, approve, reject, or interpret whether a change is good, bad, compliant, safe, or risky.

## deprecate

Use `deprecate` when a vendor, source, or artifact is no longer current, has moved, has become unavailable, has become non-public, or the vendor has ceased operations.

Expected behavior:

```text
set relevant status metadata where supported
append change events with change_type: metadata_changed or removed
rebuild indexes
```

Deprecation is a catalog lifecycle state. It is not a procurement, risk, legal, compliance, or security conclusion.

## Manifest operation field

Every lifecycle manifest must declare one explicit operation:

```yaml
operation: create
```

or:

```yaml
operation: refresh
```

or:

```yaml
operation: deprecate
```

This prevents accidental destructive behavior and keeps catalog updates auditable.
