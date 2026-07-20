# OpenVA live resolver Worker

This Worker provides bounded, domain-first public-source discovery for an unmatched
vendor during browser CSV resolution. It is a lightweight staging path under
`WP-02F-STAGING`; it does not replace the full hosted resolver programme.

## Runtime boundary

The public endpoint accepts only:

```json
{
  "vendor_name": "Example SaaS",
  "domain": "example.com",
  "source_types": ["privacy_notice", "dpa"]
}
```

It rejects unexpected fields so the browser cannot accidentally upload the user's
full vendor inventory. It does not retain or log request bodies, create accounts,
store jobs, write catalog files, or hold GitHub credentials.

The Worker:

- accepts one vendor domain per request;
- probes a fixed list of HTTPS paths on that exact domain or its `www` equivalent;
- follows at most two same-authority redirects;
- reads at most 64 KiB of textual response content per candidate;
- validates source-type terms before returning a URL;
- uses at most 48 external subrequests per invocation;
- returns `newly_discovered` or `not_found` immediately;
- leaves governed catalog intake disabled until the existing remote intake boundary
  is connected separately.

## Deploy through the Cloudflare dashboard

1. Open **Workers & Pages** and choose **Create application**.
2. Choose **Import a repository** and select
   `thedanieltan/open-vendor-assurance`.
3. Select branch `agent/cloudflare-live-resolver-01` for the initial staging deploy.
4. Set the root directory to:

   ```text
   infra/cloudflare/openva-live-resolver
   ```

5. Use:

   ```text
   Build command: npm install
   Deploy command: npm run deploy
   ```

6. Keep the Worker name `openva-live-resolver` and deploy to the generated
   `workers.dev` address.
7. Copy the deployed URL. It will be needed to connect the OpenVA browser resolver.

The committed `wrangler.jsonc` allows browser calls only from
`https://thedanieltan.github.io`. Local development origins must be added explicitly
rather than broadening CORS to `*`.

## Validate the deployment

Health:

```bash
curl -sS https://<worker>.workers.dev/healthz
```

One-vendor live resolution:

```bash
curl -sS https://<worker>.workers.dev/v1/resolve \
  -H 'Origin: https://thedanieltan.github.io' \
  -H 'Content-Type: application/json' \
  --data '{
    "vendor_name":"Cloudflare",
    "domain":"cloudflare.com",
    "source_types":["privacy_notice"]
  }'
```

Or run the committed smoke:

```bash
npm install
RESOLVER_URL=https://<worker>.workers.dev npm run smoke
```

## Local development

```bash
npm install
npm run check
npm run dev
```

For a local browser origin, override `ALLOWED_ORIGINS` in a local Wrangler
environment. Do not commit wildcard production CORS.

## Next integration

After staging returns a successful smoke result, connect `site/src/app.js` so only
unmatched rows with a supplied domain are sent to `/v1/resolve`. The original CSV
continues to stay in browser memory. Returned URLs can be inserted into the current
compiled CSV immediately, while catalog submission remains a separate governed
operation.
