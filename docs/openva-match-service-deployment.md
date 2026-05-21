# OpenVA Match Service Deployment

The OpenVA match service is an optional self-hosted HTTP wrapper around the pack reader and vendor inventory matcher. It serves public metadata enrichment only. It does not make risk, compliance, approval, or suitability assertions.

OpenVA does not operate a central hosted service. Consumers that want HTTP access should run their own service instance from a pinned repository commit or release.

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
