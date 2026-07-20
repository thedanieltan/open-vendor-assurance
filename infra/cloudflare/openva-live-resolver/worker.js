const MAX_BODY_BYTES = 8192;
const MAX_TEXT_BYTES = 65536;
const MAX_FETCHES = 48;
const MAX_REDIRECTS = 2;
const FETCH_TIMEOUT_MS = 5000;
const DEFAULT_SOURCE_TYPES = [
  "privacy_notice",
  "dpa",
  "security_page",
  "subprocessors_list",
];

const SOURCE_PATHS = Object.freeze({
  privacy_notice: ["/privacy", "/legal/privacy", "/privacy-policy"],
  dpa: ["/legal/dpa", "/legal/data-processing-addendum", "/dpa"],
  security_page: ["/security", "/trust/security"],
  subprocessors_list: [
    "/legal/subprocessors",
    "/subprocessors",
    "/legal/sub-processors",
  ],
  trust_center: ["/trust", "/trust-center", "/security"],
  status_page: ["/status"],
});

const SOURCE_TERMS = Object.freeze({
  privacy_notice: {
    primary: ["privacy"],
    supporting: ["personal data", "personal information", "data protection"],
  },
  dpa: {
    primary: ["data processing addendum", "data processing agreement", "dpa"],
    supporting: ["processor", "controller", "subprocessor"],
  },
  security_page: {
    primary: ["security"],
    supporting: ["information security", "security controls", "certification", "trust"],
  },
  subprocessors_list: {
    primary: ["subprocessor", "sub-processor"],
    supporting: ["service provider", "third party", "list"],
  },
  trust_center: {
    primary: ["trust center", "security center", "compliance center"],
    supporting: ["security", "compliance", "certification"],
  },
  status_page: {
    primary: ["status", "system status"],
    supporting: ["operational", "incident", "uptime"],
  },
});

function responseHeaders(origin) {
  const headers = {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  };
  if (origin) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers.Vary = "Origin";
  }
  return headers;
}

function jsonResponse(payload, status = 200, origin = null) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: responseHeaders(origin),
  });
}

function allowedOrigins(env) {
  return new Set(
    String(env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
}

function corsOrigin(request, env) {
  const origin = request.headers.get("Origin");
  if (!origin || !allowedOrigins(env).has(origin)) return null;
  return origin;
}

function normalizeDomain(rawValue) {
  const raw = String(rawValue || "").trim().toLowerCase();
  if (!raw || raw.length > 253) throw new Error("invalid_domain");

  const supplied = raw.includes("://") ? raw : `https://${raw}`;
  let parsed;
  try {
    parsed = new URL(supplied);
  } catch {
    throw new Error("invalid_domain");
  }

  if (!["https:", "http:"].includes(parsed.protocol)) throw new Error("invalid_domain");
  if (parsed.username || parsed.password || parsed.port) throw new Error("invalid_domain");
  if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("domain_must_not_include_path");
  }

  const hostname = parsed.hostname.replace(/\.$/, "");
  if (
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "local" ||
    hostname.endsWith(".local") ||
    /^\d{1,3}(?:\.\d{1,3}){3}$/.test(hostname) ||
    hostname.includes(":") ||
    !hostname.includes(".")
  ) {
    throw new Error("invalid_domain");
  }

  const labels = hostname.split(".");
  if (
    labels.some(
      (label) =>
        !label ||
        label.length > 63 ||
        !/^[a-z0-9-]+$/.test(label) ||
        label.startsWith("-") ||
        label.endsWith("-"),
    )
  ) {
    throw new Error("invalid_domain");
  }

  return hostname.startsWith("www.") ? hostname.slice(4) : hostname;
}

function sameAuthority(hostname, domain) {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  return normalized === domain || normalized === `www.${domain}`;
}

function requestedSourceTypes(value) {
  const input = Array.isArray(value) && value.length ? value : DEFAULT_SOURCE_TYPES;
  const result = [];
  for (const sourceType of input) {
    if (!Object.hasOwn(SOURCE_PATHS, sourceType)) throw new Error("unsupported_source_type");
    if (!result.includes(sourceType)) result.push(sourceType);
  }
  if (result.length > 5) throw new Error("too_many_source_types");
  return result;
}

async function readLimitedText(response) {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";

  while (total < MAX_TEXT_BYTES) {
    const { value, done } = await reader.read();
    if (done) break;
    const remaining = MAX_TEXT_BYTES - total;
    const chunk = value.byteLength > remaining ? value.subarray(0, remaining) : value;
    total += chunk.byteLength;
    text += decoder.decode(chunk, { stream: true });
    if (chunk.byteLength < value.byteLength) {
      await reader.cancel("body sample limit reached");
      break;
    }
  }
  text += decoder.decode();
  return text;
}

function semanticMatch(sourceType, url, body) {
  const terms = SOURCE_TERMS[sourceType];
  const haystack = `${url.pathname} ${body}`.toLowerCase();
  const primary = terms.primary.some((term) => haystack.includes(term));
  const supporting = terms.supporting.some((term) => haystack.includes(term));
  return primary && supporting;
}

async function fetchCandidate(candidateUrl, domain, budget) {
  let current = candidateUrl;

  for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount += 1) {
    if (budget.count >= MAX_FETCHES) return null;
    budget.count += 1;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort("timeout"), FETCH_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(current, {
        method: "GET",
        redirect: "manual",
        cache: "no-store",
        signal: controller.signal,
        headers: {
          Accept: "text/html,application/xhtml+xml,text/plain;q=0.9",
          "User-Agent": "OpenVA-Live-Resolver/0.1 (+https://github.com/thedanieltan/open-vendor-assurance)",
        },
      });
    } catch {
      clearTimeout(timeout);
      return null;
    }
    clearTimeout(timeout);

    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("Location");
      if (!location || redirectCount === MAX_REDIRECTS) return null;
      let next;
      try {
        next = new URL(location, current);
      } catch {
        return null;
      }
      if (next.protocol !== "https:" || !sameAuthority(next.hostname, domain)) return null;
      if (next.username || next.password || next.port) return null;
      current = next.toString();
      continue;
    }

    if (!response.ok) return null;
    const contentType = (response.headers.get("Content-Type") || "").toLowerCase();
    if (
      !contentType.includes("text/html") &&
      !contentType.includes("application/xhtml+xml") &&
      !contentType.includes("text/plain")
    ) {
      return null;
    }

    return {
      finalUrl: current,
      contentType,
      body: await readLimitedText(response),
      status: response.status,
    };
  }

  return null;
}

async function resolveSourceType(sourceType, domain, budget) {
  for (const path of SOURCE_PATHS[sourceType]) {
    const candidate = new URL(path, `https://${domain}`).toString();
    const fetched = await fetchCandidate(candidate, domain, budget);
    if (!fetched) continue;
    const finalUrl = new URL(fetched.finalUrl);
    if (!semanticMatch(sourceType, finalUrl, fetched.body)) continue;
    return {
      source_type: sourceType,
      status: "newly_discovered",
      source_url: finalUrl.toString(),
      origin: "live_discovery",
      live_checked: true,
      checked_at: new Date().toISOString(),
      catalog_status: null,
      http_status: fetched.status,
      content_type: fetched.contentType.split(";")[0],
    };
  }

  return {
    source_type: sourceType,
    status: "not_found",
    source_url: null,
    origin: null,
    live_checked: true,
    checked_at: new Date().toISOString(),
    catalog_status: null,
  };
}

async function resolveRequest(request, env, origin) {
  const contentLength = Number(request.headers.get("Content-Length") || "0");
  if (contentLength > MAX_BODY_BYTES) {
    return jsonResponse({ error: "request_too_large" }, 413, origin);
  }

  let body;
  try {
    const text = await request.text();
    if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) {
      return jsonResponse({ error: "request_too_large" }, 413, origin);
    }
    body = JSON.parse(text);
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400, origin);
  }

  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return jsonResponse({ error: "invalid_request" }, 400, origin);
  }

  const unexpected = Object.keys(body).filter(
    (key) => !["vendor_name", "domain", "source_types"].includes(key),
  );
  if (unexpected.length) {
    return jsonResponse(
      { error: "unexpected_fields", fields: unexpected.sort() },
      400,
      origin,
    );
  }

  let domain;
  let sourceTypes;
  try {
    domain = normalizeDomain(body.domain);
    sourceTypes = requestedSourceTypes(body.source_types);
  } catch (error) {
    return jsonResponse({ error: error.message }, 400, origin);
  }

  const budget = { count: 0 };
  const sources = [];
  for (const sourceType of sourceTypes) {
    sources.push(await resolveSourceType(sourceType, domain, budget));
  }

  const found = sources.filter((source) => source.source_url);
  return jsonResponse(
    {
      schema_version: "0.1.0",
      vendor: {
        vendor_id: null,
        display_name: String(body.vendor_name || "").trim() || null,
        official_domain: domain,
      },
      resolution_status: found.length ? "newly_discovered" : "not_found",
      freshness_mode: "verify",
      sources,
      catalog_submission: {
        state: "not_enabled",
        explanation: "Immediate resolution is active; governed catalog intake is separate.",
      },
      request_budget: {
        external_fetches: budget.count,
        external_fetch_limit: MAX_FETCHES,
      },
      privacy: {
        accepted_fields: ["vendor_name", "domain", "source_types"],
        retained: false,
        logged: false,
      },
      not_advice: true,
    },
    200,
    origin,
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz" && request.method === "GET") {
      return jsonResponse({ status: "ok" });
    }

    const origin = corsOrigin(request, env);
    if (request.method === "OPTIONS") {
      if (!origin) return jsonResponse({ error: "origin_not_allowed" }, 403);
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Origin": origin,
          "Access-Control-Max-Age": "86400",
          Vary: "Origin",
        },
      });
    }

    if (url.pathname !== "/v1/resolve") {
      return jsonResponse({ error: "not_found" }, 404, origin);
    }
    if (request.method !== "POST") {
      return jsonResponse({ error: "method_not_allowed" }, 405, origin);
    }
    if (!origin) {
      return jsonResponse({ error: "origin_not_allowed" }, 403);
    }
    if (env.RESOLVE_RATE_LIMITER) {
      const clientIp = request.headers.get("CF-Connecting-IP") || "unknown";
      const { success } = await env.RESOLVE_RATE_LIMITER.limit({ key: clientIp });
      if (!success) {
        return jsonResponse({ error: "rate_limited" }, 429, origin);
      }
    }
    if (!(request.headers.get("Content-Type") || "").includes("application/json")) {
      return jsonResponse({ error: "content_type_must_be_json" }, 415, origin);
    }

    return resolveRequest(request, env, origin);
  },
};
