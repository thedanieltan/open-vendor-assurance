# OpenVA Match Service Deployment

The OpenVA match service is an optional self-hosted HTTP wrapper around the pack reader and vendor inventory matcher. It serves public metadata enrichment only. It does not make risk, compliance, approval, or suitability assertions.

OpenVA does not currently operate a production central matching service or a hosted private-inventory upload service. The repository now ships an optional, API-key-gated verify transport for self-hosted use and future hosted deployment. The transport is disabled by default, and this release does not include the durable backend, worker, production infrastructure, or public verify endpoint required for an operated hosted service. Until those later deployment gates are completed, private vendor inventories should remain browser-local, local, or inside a consumer-controlled self-hosted environment. Consumers that want HTTP access should run their own service instance from a pinned repository commit or release. When OPENVA_VERIFY_TRANSPORT_ENABLED=true, the service exposes the transport-only verify API; accepted jobs remain received because durable persistence and worker execution are later slices.

## Pack Strategy

The default deployment strategy is to mount the OpenVA pack at runtime. The image is pack-agnostic, and `OPENVA_PACK_PATH` points to the mounted pack directory. Operators update pack freshness by replacing the mounted pack and restarting the service.

For simpler deployments, operators may bake a pack into a derived image and set `OPENVA_PACK_PATH` to that copied directory. Fetching a pack at startup is out of scope for v1 because the service is designed to fail fast from local startup state.

## Build

Build from the repository root so Docker can install the isolated service package and the two adapter packages it consumes:

```sh
docker build -f services/openva_match_service/Dockerfile -t openva-match-service:local .
```

The image installs:

- `adapters/python/openva_pack_reader`
- `adapters/python/openva_vendor_inventory_matcher`
- `services/openva_match_service`

It does not install the root OpenVA validator, catalog tooling, or development dependencies.

## Run

Mount the generated pack directory at `/data/openva-pack` and provide a pre-shared API key:

```sh
docker run --rm \
  -p 8000:8000 \
  -v "$PWD:/data/openva-pack:ro" \
  -e OPENVA_PACK_PATH=/data/openva-pack \
  -e OPENVA_SERVICE_API_KEY=replace-with-a-secret \
  openva-match-service:local
```

`OPENVA_SERVICE_PORT` is optional and defaults to `8000`. If you change it, publish the same container port in your runtime configuration.

## Health probes

The service exposes unauthenticated probes for orchestrators:

- `GET /healthz` — liveness; returns `200 {"status": "ok"}` whenever the process is up.
- `GET /readyz` — readiness; returns `200 {"status": "ready"}` once the pack/matcher state is loaded, and `503 {"status": "not_ready"}` otherwise.

## Configuration limits

Optional environment variables bound request size and shape (defaults shown). An invalid (non-integer or non-positive) value fails service startup.

| Variable | Default | Effect |
| --- | --- | --- |
| `OPENVA_MAX_UPLOAD_BYTES` | `5000000` | `POST /match` rejects an upload larger than this with `413` (the in-memory read is bounded). |
| `OPENVA_MAX_ROWS` | `500` | `POST /match` rejects an inventory with more rows than this with `400`. |
| `OPENVA_MAX_ACTIVE_JOBS` | `3` | Reserved; not enforced in WP-02A (verify concurrency control is deferred to the worker, WP-02C). |
| `OPENVA_JOB_TTL_HOURS` | `24` | Verify job TTL when the verify transport is enabled: the job `expires_at`, after which the poll returns `410` and the record is physically purged (`404`). |
| `OPENVA_VERIFY_TRANSPORT_ENABLED` | `false` | Gates the optional async verify transport. Off ⇒ cached-only; verify routes return `404`. |
| `OPENVA_MAX_VERIFY_ROWS` | `20` | Max rows per `/v1/verify` request (hard-capped at 20). |

The cached `/match` and `/v1` read path is synchronous with no persistence and no network egress. The optional, flag-gated verify transport (`OPENVA_VERIFY_TRANSPORT_ENABLED`, default off) adds an in-memory async job lifecycle: transient job metadata only (no submitted identities — those are discarded), TTL-reaped; no worker or network egress in this release (WP-02C).

## Smoke Tests

From the repository root, with the container running:

```sh
OPENVA_SERVICE_API_KEY=replace-with-a-secret \
  services/openva_match_service/examples/smoke_pack_meta.sh
```

```sh
OPENVA_SERVICE_API_KEY=replace-with-a-secret \
  services/openva_match_service/examples/smoke_match.sh
```

The scripts call `GET /pack/meta` and `POST /match` with `services/openva_match_service/examples/sample_inventory.csv`, then pretty-print the JSON responses.

Equivalent `curl` calls:

```sh
curl -fsS \
  -H "Authorization: Bearer replace-with-a-secret" \
  http://localhost:8000/pack/meta \
  | python -m json.tool
```

```sh
curl -fsS \
  -H "Authorization: Bearer replace-with-a-secret" \
  -F "inventory_csv=@services/openva_match_service/examples/sample_inventory.csv;type=text/csv" \
  http://localhost:8000/match \
  | python -m json.tool
```

## Operator Responsibilities

Operators are responsible for:

- Rebuilding or replacing the mounted OpenVA pack and restarting the service when freshness changes.
- Setting and rotating `OPENVA_SERVICE_API_KEY`.
- TLS termination, network access controls, logging, and deployment monitoring.
- Choosing whether the pack is mounted at runtime or baked into a derived image.

## Service Boundaries

The service does not:

- Rebuild or update the OpenVA pack.
- Fetch packs at startup.
- Persist tenant state or request history.
- Write back to OpenVA or any consumer system.
- Emit advisory, risk, compliance, approval, or suitability decisions.
