const baseUrl = String(process.env.RESOLVER_URL || "").replace(/\/$/, "");
if (!baseUrl) {
  throw new Error("Set RESOLVER_URL to the deployed Worker URL.");
}

const health = await fetch(`${baseUrl}/healthz`);
if (!health.ok) {
  throw new Error(`Health check failed: ${health.status}`);
}

const resolution = await fetch(`${baseUrl}/v1/resolve`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Origin: "https://thedanieltan.github.io",
  },
  body: JSON.stringify({
    vendor_name: "Cloudflare",
    domain: "cloudflare.com",
    source_types: ["privacy_notice"],
  }),
});

if (!resolution.ok) {
  throw new Error(`Resolution smoke failed: ${resolution.status} ${await resolution.text()}`);
}

const payload = await resolution.json();
if (payload.vendor?.official_domain !== "cloudflare.com") {
  throw new Error("Resolution response did not preserve the normalized official domain.");
}
if (!Array.isArray(payload.sources) || payload.sources.length !== 1) {
  throw new Error("Resolution response did not contain exactly one requested source type.");
}
if (payload.privacy?.retained !== false) {
  throw new Error("Resolution response did not disclose the no-retention boundary.");
}

console.log(
  JSON.stringify(
    {
      health: "ok",
      resolution_status: payload.resolution_status,
      source: payload.sources[0],
      external_fetches: payload.request_budget?.external_fetches,
    },
    null,
    2,
  ),
);
