# Discovery mesh runner

The discovery mesh runner processes the complete eligible catalog through deterministic shards. It has no default vendor-count cap.

## Execution model

- Every catalog vendor is assigned to exactly one shard by stable vendor-id hashing.
- `vendor_limit` is optional and reserved for diagnostics, recovery, or operator-directed incident response.
- Per-vendor page, request, link, response, redirect, and delegated-host limits remain mandatory network safety controls.
- Source candidates are report-only until staged into candidate-source records.
- Existing eligibility, source verification, promotion, release, and controlled-automerge workflows remain authoritative.

## Example

```bash
python -m tools.openva.discovery_mesh_runner shard \
  --shard-index 0 \
  --shard-count 16 \
  --output reports/discovery-mesh/shard-0.json
```

Aggregate worker artifacts and stage noncanonical candidate-source records:

```bash
python -m tools.openva.discovery_mesh_runner aggregate \
  --input-dir reports/discovery-mesh/shards \
  --output reports/discovery-mesh/source-discovery-report.json \
  --identity-output reports/discovery-mesh/vendor-identity-signals.json \
  --manifest-output reports/discovery-mesh/candidate-manifest.json \
  --write-candidates
```

The aggregate command never writes canonical vendor or source records.

Operational metadata only. Not legal, compliance, procurement, security, KYC, AML, audit, certification, or vendor-risk advice.
