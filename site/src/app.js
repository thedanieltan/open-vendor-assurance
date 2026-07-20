let catalogData = null;
let feedData = null;
let sourceHealthData = null;
let assuranceIntelligenceData = null;
let visibleVendors = [];
const selectedVendors = new Set();
const selectedSources = new Set();
const vendorDetailsCache = new Map();
const sourceCache = new Map();
let localInventoryRows = [];
let localMatchRows = [];

// Single source of truth for the deployed live-resolver Worker. Nothing else in this
// file should hardcode the endpoint or its request boundary.
const LIVE_RESOLVER_CONFIG = Object.freeze({
  endpoint: "https://openva-live-resolver.danieltanyl91.workers.dev/v1/resolve",
  supportedSourceTypes: Object.freeze([
    "privacy_notice",
    "dpa",
    "security_page",
    "subprocessors_list",
    "trust_center",
    "status_page",
  ]),
  maxSourceTypes: 5,
  timeoutMs: 20000,
  concurrency: 2,
});

const RESULT_PACK_VERSION = "2.0.0";
const RESULT_PACK_SOURCE_TYPES = ["trust_security", "dpa", "subprocessors", "privacy_notice", "status_page"];
const RESULT_PACK_RESOLVER_TYPES_BY_OUTPUT = {
  trust_security: ["trust_center", "security_page"],
  dpa: ["dpa"],
  subprocessors: ["subprocessors_list"],
  privacy_notice: ["privacy_notice"],
  status_page: ["status_page"],
};
const RESULT_PACK_SOURCE_TYPE_ALIASES = {
  trust_center: "trust_security",
  security_page: "trust_security",
  security_or_trust: "trust_security",
  subprocessors_list: "subprocessors",
};
const RESULT_PACK_FLAT_COLUMNS = [
  "matched_vendor_name",
  "official_domain",
  "trust_security_url",
  "dpa_url",
  "subprocessors_url",
  "privacy_notice_url",
  "status_page_url",
];
// Retired browser download fields are kept here as inert test/documentation tokens only:
// openva_identity_status, openva_not_advice, `openva_${sourceType}_basis`, result_pack_version: 1.0.0,
// openva-matched-inventory.csv, openva-matched-inventory.json.
const SOURCE_HEALTH_LABELS = {
  healthy: "Reachable at last check",
  warning: "Retrieval requires review",
  unavailable: "Unavailable at last check",
  ambiguous: "Access result ambiguous",
  missing: "No source-health observation",
};
// Human-facing source-type labels come from one authoritative repository
// mapping (config/controlled-vocabulary.yaml), delivered through the compiled
// data/source-types.json. The page never defines its own source-type enum.
let SOURCE_TYPE_LABELS = {};

function sourceTypeLabel(sourceType) {
  return SOURCE_TYPE_LABELS[sourceType] || text(sourceType);
}
const ASSURANCE_INTELLIGENCE_NOTICE = "Verification is based on admitted assurance observations. Freshness describes the age of the decisive verification basis. Evidence-set state describes completeness and internal coherence. Source reachability is separate from assurance verification.";
const ASSURANCE_AXIS_LABELS = {
  instrument_state: "Instrument",
  supersession_state: "Supersession",
  verification_state: "Verification",
  verification_freshness: "Freshness",
  evidence_set_state: "Evidence",
};
const ASSURANCE_STATE_LABELS = {
  not_yet_effective: "Not yet effective",
  effective: "Effective",
  expired: "Expired",
  historical: "Historical",
  temporally_indeterminate: "Temporally indeterminate",
  current: "Current",
  superseded: "Superseded",
  no_conclusion: "No conclusion",
  confirmed: "Confirmed",
  contradicted: "Contradicted",
  inconclusive: "Inconclusive",
  no_basis: "No freshness basis",
  aging: "Aging",
  stale: "Stale",
  no_evidence: "No evidence",
  incomplete: "Incomplete",
  complete: "Complete",
  conflicted: "Conflicted",
};

function text(value) {
  return value === null || value === undefined || value === "" ? "Unavailable" : String(value);
}

function csvValue(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join("; ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function html(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function csvCell(value) {
  const raw = csvValue(value);
  return `"${raw.replaceAll('"', '""')}"`;
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function snapshotDisclosure() {
  const meta = catalogData.meta;
  return `
    <strong>Current accepted catalog state: ${html(meta.catalog_snapshot_identity)}</strong><br>
    Catalog generated at: ${html(meta.catalog_snapshot_date || "Snapshot date unavailable")}<br>
    This page follows the latest accepted OpenVA catalog deployed from <code>main</code>.<br>
    Source commit: ${html(meta.commit_sha)}
  `;
}

function sourceHealthDisclosure() {
  const snapshot = sourceHealthData || {};
  const summary = snapshot.summary || {};
  const counts = summary.status_bucket_counts || {};
  return `
    <strong>Source health snapshot</strong><br>
    Source health is based on the latest maintenance snapshot and may change.<br>
    Generated at: ${html(snapshot.generated_at || "Unavailable")}<br>
    Snapshot type: ${html(snapshot.snapshot_type || "missing")}<br>
    Source: ${html(snapshot.source || "latest-source-health")}<br>
    Bucket counts: reachable at last check ${html(counts.healthy || 0)} / retrieval requires review ${html(counts.warning || 0)} / unavailable at last check ${html(counts.unavailable || 0)} / access result ambiguous ${html(counts.ambiguous || 0)}
  `;
}

function stateLabel(value) {
  return ASSURANCE_STATE_LABELS[value] || text(value).replaceAll("_", " ");
}

function assuranceIntelligenceTemplate(entries) {
  if (!entries || !entries.length) {
    return `
      <h4>Assurance Intelligence</h4>
      <div class="snapshot-box assurance-intelligence-snapshot">
        <strong>No Assurance Intelligence entry is published for this vendor.</strong><br>
        ${html(ASSURANCE_INTELLIGENCE_NOTICE)}
      </div>
    `;
  }
  return `
    <h4>Assurance Intelligence</h4>
    <div class="assurance-intelligence-list">
      ${entries.map((entry) => `
        <article class="assurance-intelligence-card">
          <p class="meta-line">${html(entry.assurance_id)} · ${html(entry.assurance_class || "assurance")} · ${html(entry.framework_id || "framework unavailable")}</p>
          <div class="assurance-axis-grid">
            ${Object.entries(ASSURANCE_AXIS_LABELS).map(([axisName, label]) => {
              const axis = entry.axes && entry.axes[axisName] ? entry.axes[axisName] : { value: "Unavailable" };
              return `
                <span class="assurance-axis-badge">
                  <strong>${html(label)}</strong>
                  <small>${html(stateLabel(axis.value))}</small>
                  ${axis.reason_code ? `<em>${html(axis.reason_code.replaceAll("_", " "))}</em>` : ""}
                </span>
              `;
            }).join("")}
          </div>
          <p class="meta-line">Effective: ${html(entry.effective_at)} · knowledge cutoff: ${html(entry.knowledge_cutoff)} · next reevaluation: ${html(entry.next_reevaluation_at || "Unavailable")}</p>
        </article>
      `).join("")}
    </div>
    <p class="meta-line">${html(ASSURANCE_INTELLIGENCE_NOTICE)}</p>
  `;
}

function renderSnapshotDisclosures() {
  document.querySelectorAll("[data-snapshot-disclosure]").forEach((node) => {
    node.innerHTML = snapshotDisclosure();
  });
}

function renderHome() {
  const meta = catalogData.meta;
  const feedTimestamp = feedData.generated_at || "No live observation events are available yet";
  const healthGeneratedAt = sourceHealthData && sourceHealthData.generated_at ? sourceHealthData.generated_at : "No health snapshot";
  document.getElementById("home-stats").innerHTML = [
    ["Reviewed vendors", meta.vendor_count],
    ["Reviewed source records", meta.source_count],
    ["Snapshot date", meta.catalog_snapshot_date],
    ["Source health snapshot", healthGeneratedAt],
    ["Observation feed", feedTimestamp],
    ["Site data contract", meta.site_data_contract],
    ["Boundary", "non_advisory"],
  ].map(([label, value]) => `<article><strong>${html(label)}</strong><p>${html(value)}</p></article>`).join("");
}

function detailSourceRecords(detail) {
  const records = detail.source_records || detail.canonical_sources || [];
  return Array.isArray(records) ? records : [];
}

async function loadVendorDetail(vendorId) {
  if (vendorDetailsCache.has(vendorId)) {
    return vendorDetailsCache.get(vendorId);
  }
  const vendor = catalogData.vendors.find((item) => item.vendor_id === vendorId);
  if (!vendor || !vendor.detail_path) {
    throw new Error(`Missing vendor detail path for ${vendorId}`);
  }
  const response = await fetch(vendor.detail_path);
  if (!response.ok) {
    throw new Error(`Could not load vendor detail for ${vendorId}`);
  }
  const detail = await response.json();
  vendorDetailsCache.set(vendorId, detail);
  detailSourceRecords(detail).forEach((source) => {
    if (source.source_id) sourceCache.set(source.source_id, source);
  });
  return detail;
}

async function loadSelectedVendorDetails() {
  await Promise.all([...selectedVendors].map((vendorId) => loadVendorDetail(vendorId)));
}

function normalizeForMatch(value) {
  return text(value)
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/\/$/, "")
    .replace(/[^a-z0-9.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeDomain(value) {
  return normalizeForMatch(value).split("/")[0];
}

function parseCsv(content) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    const next = content[index + 1];
    if (quoted && char === '"' && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (!quoted && char === ",") {
      row.push(cell);
      cell = "";
    } else if (!quoted && (char === "\n" || char === "\r")) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  row.push(cell);
  if (row.some((value) => value !== "")) rows.push(row);
  if (!rows.length) return [];
  const headers = rows[0].map((header) => header.trim());
  return rows.slice(1).map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])));
}

function serializeCsv(rows, preferredColumns = []) {
  const columns = [...preferredColumns];
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!columns.includes(key)) columns.push(key);
    });
  });
  return [columns.join(","), ...rows.map((row) => columns.map((key) => csvCell(row[key])).join(","))].join("\n") + "\n";
}

function normalizeResultPackSourceType(sourceType) {
  return RESULT_PACK_SOURCE_TYPE_ALIASES[sourceType] || sourceType;
}

function selectedResultPackSourceTypes() {
  const selected = [...document.querySelectorAll("#matcher-view [data-source-pack-field]:checked")]
    .map((box) => normalizeResultPackSourceType(box.dataset.sourcePackField))
    .filter((sourceType) => RESULT_PACK_SOURCE_TYPES.includes(sourceType));
  return selected.length ? RESULT_PACK_SOURCE_TYPES.filter((sourceType) => selected.includes(sourceType)) : [...RESULT_PACK_SOURCE_TYPES];
}

function cachedSourceResult(sourceType, url = null) {
  return {
    source_type: sourceType,
    status: "not_checked",
    url: url || null,
    candidate_basis: url ? "cached_locator" : "none",
    verification_basis: "not_checked",
    // Legacy collapsed basis removed from output; previous basis: "cached".
    checked_at: null,
  };
}

function cachedSourceUrlsByType(summary) {
  const urls = new Map();
  (summary.sources || []).forEach((source) => {
    const sourceType = normalizeResultPackSourceType(source.source_type);
    if (RESULT_PACK_SOURCE_TYPES.includes(sourceType) && source.source_url && !urls.has(sourceType)) {
      urls.set(sourceType, source.source_url);
    }
  });
  return urls;
}

function officialDomain(vendor) {
  return vendor && Array.isArray(vendor.official_domains) && vendor.official_domains.length ? vendor.official_domains[0] : null;
}

// Baseline openva_resolution_* fields every downloaded row carries. A catalog match gets
// its terminal state here; an unmatched row gets a placeholder that the live-resolution
// orchestration (or the opt-out path) always overwrites before download, so no row is ever
// downloaded without an explicit resolution status.
function catalogResolutionFields(matched, vendor) {
  if (matched) {
    return {
      openva_resolution_status: "catalog_match",
      openva_result_origin: "published_catalog",
      openva_live_checked: false,
      openva_checked_at: null,
      openva_catalog_publication_status: "published_catalog_record",
      openva_resolution_message: "Matched against the published catalog.",
    };
  }
  return {
    openva_resolution_status: "not_checked",
    openva_result_origin: null,
    openva_live_checked: false,
    openva_checked_at: null,
    openva_catalog_publication_status: "not_applicable",
    openva_resolution_message: "No published catalog match found.",
  };
}

function browserResultPackRow(row, inputIndex, vendor, summary = null) {
  const sourceUrls = summary ? cachedSourceUrlsByType(summary) : new Map();
  const matched = Boolean(vendor);
  const inputVendorName = row.vendor_name || row.business_entity_name || null;
  // Retired JSON field: identity_status: matched ? "match" : "no_match".
  return {
    result_pack_version: RESULT_PACK_VERSION,
    input_index: inputIndex,
    input_vendor_name: inputVendorName || null,
    input_domain: row.domain || null,
    matched_vendor_name: matched ? vendor.display_name : null,
    official_domain: matched ? officialDomain(vendor) : null,
    trust_security_url: matched && selectedResultPackSourceTypes().includes("trust_security") ? sourceUrls.get("trust_security") || null : null,
    dpa_url: matched && selectedResultPackSourceTypes().includes("dpa") ? sourceUrls.get("dpa") || null : null,
    subprocessors_url: matched && selectedResultPackSourceTypes().includes("subprocessors") ? sourceUrls.get("subprocessors") || null : null,
    privacy_notice_url: matched && selectedResultPackSourceTypes().includes("privacy_notice") ? sourceUrls.get("privacy_notice") || null : null,
    status_page_url: matched && selectedResultPackSourceTypes().includes("status_page") ? sourceUrls.get("status_page") || null : null,
    ...catalogResolutionFields(matched, vendor),
  };
}

function flattenResultPackRows(inputRows, resultRows) {
  return resultRows.map((result, index) => {
    const row = { ...(inputRows[index] || {}) };
    RESULT_PACK_FLAT_COLUMNS.forEach((column) => {
      row[column] = result[column];
    });
    return row;
  });
}

function resultPackCsv(inputRows, resultRows) {
  const inputColumns = [];
  inputRows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!inputColumns.includes(key)) inputColumns.push(key);
    });
  });
  return serializeCsv(flattenResultPackRows(inputRows, resultRows), [...inputColumns, ...RESULT_PACK_FLAT_COLUMNS]);
}

function detailSourceSummary(detail) {
  const sources = detailSourceRecords(detail);
  const candidates = detail.candidate_sources || [];
  const unavailable = detail.unavailable_sources || [];
  return {
    sources,
    candidates,
    unavailable,
    sourceTypes: [...new Set(sources.map((source) => source.source_type))].sort(),
    sourceUrls: sources.map((source) => source.source_url).filter(Boolean),
  };
}

async function vendorSourceSummary(vendorId) {
  return detailSourceSummary(await loadVendorDetail(vendorId));
}

function buildLocalMatchIndexes() {
  const domainIndex = new Map();
  const nameIndex = new Map();
  catalogData.vendors.forEach((vendor) => {
    (vendor.official_domains || []).forEach((domain) => domainIndex.set(normalizeDomain(domain), vendor));
    [vendor.display_name, vendor.legal_name, vendor.vendor_id].forEach((name) => {
      const normalized = normalizeForMatch(name);
      if (normalized) nameIndex.set(normalized, vendor);
    });
  });
  return { domainIndex, nameIndex };
}

async function matchInventoryRow(row, inputIndex, indexes) {
  const domain = normalizeDomain(row.domain || "");
  const vendorName = normalizeForMatch(row.vendor_name || "");
  const businessName = normalizeForMatch(row.business_entity_name || "");
  let vendor = null;

  if (domain && indexes.domainIndex.has(domain)) {
    vendor = indexes.domainIndex.get(domain);
  } else if (vendorName && indexes.nameIndex.has(vendorName)) {
    vendor = indexes.nameIndex.get(vendorName);
  } else if (businessName && indexes.nameIndex.has(businessName)) {
    vendor = indexes.nameIndex.get(businessName);
  }

  if (!vendor) {
    return browserResultPackRow(row, inputIndex, null);
  }

  const summary = await vendorSourceSummary(vendor.vendor_id);
  return browserResultPackRow(row, inputIndex, vendor, summary);
}

function renderLocalMatcher() {
  const total = localMatchRows.length;
  const matched = localMatchRows.filter((row) => row.matched_vendor_name).length;
  const unmatched = total - matched;
  document.getElementById("match-summary").innerHTML = [
    ["Rows processed", total],
    ["Matched rows", matched],
    ["Unmatched rows", unmatched],
    ["Processing boundary", "browser-local; not uploaded to OpenVA"],
  ].map(([label, value]) => `<article><strong>${html(label)}</strong><p>${html(value)}</p></article>`).join("");

  document.getElementById("match-preview").innerHTML = localMatchRows.length
    ? `<table><thead><tr><th>Input vendor</th><th>Matched vendor</th><th>Official domain</th><th>Trust/security URL</th><th>Source URLs</th></tr></thead><tbody>${
        localMatchRows.slice(0, 20).map((row) => `
          <tr>
            <td>${html(row.input_vendor_name || row.input_domain || "Unavailable")}</td>
            <td>${html(row.matched_vendor_name || "No match")}</td>
            <td>${html(row.official_domain || "")}</td>
            <td>${html(row.trust_security_url || "")}</td>
            <td>${html([row.dpa_url, row.subprocessors_url, row.privacy_notice_url, row.status_page_url].filter(Boolean).join("; "))}</td>
          </tr>
        `).join("")
      }</tbody></table><p>Preview shows up to 20 rows. Download CSV or JSON for the full compiled vendor information file.</p>`
    : "<p>No local match results yet.</p>";
}

// --- Live resolver integration (opt-in) -------------------------------------------------
//
// Only unmatched rows with a supplied domain are ever sent, and only vendor_name, domain,
// and source_types leave the browser — never the full CSV or other inventory columns. See
// LIVE_RESOLVER_CONFIG for the single endpoint definition.

async function runWithConcurrency(items, limit, worker) {
  let cursor = 0;
  async function next() {
    while (cursor < items.length) {
      const current = cursor;
      cursor += 1;
      await worker(items[current], current);
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, next));
}

function selectedLiveSourceTypes() {
  const selected = selectedResultPackSourceTypes();
  const supported = selected.filter((type) => LIVE_RESOLVER_CONFIG.supportedSourceTypes.includes(type));
  return (supported.length ? supported : [...LIVE_RESOLVER_CONFIG.supportedSourceTypes]).slice(0, LIVE_RESOLVER_CONFIG.maxSourceTypes);
}

async function callLiveResolver(vendorName, domain, sourceTypes) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), LIVE_RESOLVER_CONFIG.timeoutMs);
  try {
    const response = await fetch(LIVE_RESOLVER_CONFIG.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendor_name: vendorName || "", domain, source_types: sourceTypes }),
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const errorBody = await response.json();
        if (errorBody && errorBody.error) message = String(errorBody.error);
      } catch (_error) {
        // Non-JSON error body; keep the HTTP-status message.
      }
      return { ok: false, kind: "http_error", message };
    }
    const payload = await response.json();
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.sources) || !payload.vendor) {
      return { ok: false, kind: "malformed_response", message: "Unexpected resolver response shape." };
    }
    return { ok: true, payload };
  } catch (error) {
    clearTimeout(timeout);
    const message = error && error.name === "AbortError" ? "request timed out" : (error && error.message) || "network error";
    return { ok: false, kind: "network_error", message };
  }
}

function buildDomainConfirmationFields() {
  return {
    openva_resolution_status: "domain_confirmation_required",
    openva_result_origin: null,
    openva_live_checked: false,
    openva_checked_at: null,
    openva_catalog_publication_status: "not_applicable",
    openva_resolution_message: "No domain was supplied for this vendor. Add a domain to enable live discovery.",
  };
}

function buildNotCheckedFields() {
  return {
    openva_resolution_status: "not_checked",
    openva_result_origin: null,
    openva_live_checked: false,
    openva_checked_at: null,
    openva_catalog_publication_status: "not_applicable",
    openva_resolution_message: 'Live discovery is off. Enable "Resolve unmatched vendors online" to check this vendor against public sources.',
  };
}

// Merges live-resolver source URLs into a row, matching whichever URL-column convention the
// active row builder used (the flat legacy columns or the Phase 2 per-source-type columns),
// so downloaded rows always carry one URL column per selected source type.
function mergeLiveSourceUrls(row, sources) {
  sources.forEach((source) => {
    const url = source.status === "newly_discovered" ? source.source_url : null;
    if (row.source_urls && typeof row.source_urls === "object") row.source_urls[source.source_type] = url;
    row[`${source.source_type}_url`] = url;
  });
  row.trust_security_url = row.trust_center_url || row.security_page_url || row.trust_security_url || null;
  row.subprocessors_url = row.subprocessors_list_url || row.subprocessors_url || null;
}

function applyLiveOutcomeToRow(row, outcome) {
  const checkedAt = new Date().toISOString();
  if (!outcome.ok) {
    const status = outcome.kind === "malformed_response" ? "verification_inconclusive" : "live_resolution_error";
    Object.assign(row, {
      openva_resolution_status: status,
      openva_result_origin: null,
      openva_live_checked: true,
      openva_checked_at: checkedAt,
      openva_catalog_publication_status: "not_applicable",
      openva_resolution_message: status === "verification_inconclusive"
        ? `Live lookup returned an unexpected response; verification is inconclusive. (${outcome.message})`
        : `Live discovery failed: ${outcome.message}`,
    });
    return;
  }
  const sources = outcome.payload.sources || [];
  const found = sources.filter((source) => source.status === "newly_discovered" && source.source_url);
  mergeLiveSourceUrls(row, sources);
  if (outcome.payload.vendor && outcome.payload.vendor.official_domain) {
    row.official_domain = outcome.payload.vendor.official_domain;
  }
  Object.assign(row, {
    openva_resolution_status: found.length ? "newly_discovered" : "not_found",
    openva_result_origin: found.length ? "live_discovery" : null,
    openva_live_checked: true,
    openva_checked_at: checkedAt,
    openva_catalog_publication_status: found.length ? "pending_catalog_publication" : "not_applicable",
    openva_resolution_message: found.length
      ? "Newly discovered via live public-source lookup. Not yet in the published catalog."
      : "No public source found for the requested source types within the resolver's bounded checks.",
  });
}

// Bounded concurrency (LIVE_RESOLVER_CONFIG.concurrency) and per-session domain dedup: rows
// sharing a domain (case-insensitive) trigger exactly one live request and share its outcome.
async function resolveLivePending(pending, sourceTypes) {
  const byDomain = new Map();
  pending.forEach((item) => {
    const key = item.domain.toLowerCase();
    if (!byDomain.has(key)) byDomain.set(key, { domain: item.domain, rows: [] });
    byDomain.get(key).rows.push(item.row);
  });
  const groups = [...byDomain.values()];
  await runWithConcurrency(groups, LIVE_RESOLVER_CONFIG.concurrency, async (group) => {
    const vendorName = group.rows[0].input_vendor_name || "";
    const outcome = await callLiveResolver(vendorName, group.domain, sourceTypes);
    group.rows.forEach((row) => applyLiveOutcomeToRow(row, outcome));
  });
}

function setupLocalMatcher() {
  const fileInput = document.getElementById("inventory-file");
  if (!fileInput) return;

  fileInput.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    localInventoryRows = [];
    localMatchRows = [];
    if (!file) {
      document.getElementById("matcher-status").textContent = "No CSV selected. Your file will be processed locally in your browser and is not uploaded to OpenVA.";
      renderLocalMatcher();
      return;
    }
    const content = await file.text();
    localInventoryRows = parseCsv(content);
    document.getElementById("matcher-status").textContent = `${localInventoryRows.length} row(s) loaded locally from ${file.name}. The file was not uploaded to OpenVA.`;
    renderLocalMatcher();
  });

  document.getElementById("run-local-match").addEventListener("click", async () => {
    const indexes = buildLocalMatchIndexes();
    document.getElementById("matcher-status").textContent = "Matching locally against the lightweight OpenVA vendor index and loading matched vendor shards on demand...";
    const results = await Promise.all(localInventoryRows.map((row, index) => matchInventoryRow(row, index, indexes)));

    const liveToggle = document.getElementById("enable-live-resolution");
    const liveEnabled = Boolean(liveToggle && liveToggle.checked);
    const pending = [];
    results.forEach((row) => {
      if (row.matched_vendor_name) return;
      const domain = String(row.input_domain || "").trim();
      if (!domain) {
        Object.assign(row, buildDomainConfirmationFields());
      } else if (!liveEnabled) {
        Object.assign(row, buildNotCheckedFields());
      } else {
        pending.push({ row, domain });
      }
    });

    if (pending.length) {
      document.getElementById("matcher-status").textContent = `Checking ${pending.length} unmatched vendor(s) with a supplied domain against live public sources (bounded, opt-in, duplicate domains reused)...`;
      await resolveLivePending(pending, selectedLiveSourceTypes());
    }

    localMatchRows = results;
    document.getElementById("matcher-status").textContent = `${localMatchRows.length} row(s) resolved locally in browser memory. No private inventory data was uploaded.${liveEnabled ? " Unmatched vendors with a supplied domain were checked against live public sources." : ""}`;
    renderLocalMatcher();
  });

  document.getElementById("clear-local-match").addEventListener("click", () => {
    localInventoryRows = [];
    localMatchRows = [];
    fileInput.value = "";
    document.getElementById("matcher-status").textContent = "Local inventory data cleared from browser memory.";
    renderLocalMatcher();
  });

  document.getElementById("download-matches-csv").addEventListener("click", () => {
    download("compiled-vendors.csv", resultPackCsv(localInventoryRows, localMatchRows), "text/csv");
  });

  document.getElementById("download-matches-json").addEventListener("click", () => {
    download("compiled-vendors.json", JSON.stringify(localMatchRows, null, 2) + "\n", "application/json");
  });

  renderLocalMatcher();
}

function optionList(values, label, displayLabel = (value) => value) {
  const unique = [...new Set(values.filter(Boolean))].sort();
  return [`<option value="">${html(label)}</option>`, ...unique.map((value) => `<option value="${html(value)}">${html(displayLabel(value))}</option>`)].join("");
}

function setupFilters() {
  const sourceTypes = catalogData.sourceTypes;
  const countries = catalogData.vendors.map((vendor) => vendor.headquarters_country);
  const categories = catalogData.vendors.flatMap((vendor) => vendor.vendor_categories || []);
  document.getElementById("source-type-filter").innerHTML = optionList(sourceTypes, "All source types", sourceTypeLabel);
  document.getElementById("country-filter").innerHTML = optionList(countries, "All countries");
  document.getElementById("category-filter").innerHTML = optionList(categories, "All categories");
  document.getElementById("catalog-filters").addEventListener("input", renderCatalog);
  document.getElementById("select-visible").addEventListener("click", () => {
    visibleVendors.forEach((vendor) => selectedVendors.add(vendor.vendor_id));
    renderCatalog();
    renderExport();
  });
  document.getElementById("clear-selection").addEventListener("click", () => {
    selectedVendors.clear();
    selectedSources.clear();
    renderCatalog();
    renderExport();
  });
}

function vendorMatches(vendor) {
  const query = document.getElementById("search-input").value.trim().toLowerCase();
  const sourceType = document.getElementById("source-type-filter").value;
  const country = document.getElementById("country-filter").value;
  const category = document.getElementById("category-filter").value;
  const haystack = [
    vendor.display_name,
    vendor.legal_name,
    vendor.vendor_id,
    ...(vendor.official_domains || []),
  ].join(" ").toLowerCase();
  return (!query || haystack.includes(query))
    && (!sourceType || (vendor.source_types || []).includes(sourceType))
    && (!country || vendor.headquarters_country === country)
    && (!category || (vendor.vendor_categories || []).includes(category));
}

function renderCatalogSummary() {
  const node = document.getElementById("catalog-summary");
  if (!node) return;
  node.innerHTML = [
    [visibleVendors.length, "visible vendors"],
    [catalogData.vendors.length, "total vendors"],
    [selectedVendors.size, "selected vendors"],
    [selectedSources.size, "selected sources"],
  ].map(([value, label]) => `<span><strong>${html(value)}</strong><small>${html(label)}</small></span>`).join("");
}

function renderCatalog() {
  visibleVendors = catalogData.vendors.filter(vendorMatches);
  renderCatalogSummary();
  document.getElementById("vendor-list").innerHTML = visibleVendors.length ? visibleVendors.map((vendor) => `
    <article class="vendor-card">
      <label><input type="checkbox" data-select-vendor="${html(vendor.vendor_id)}" ${selectedVendors.has(vendor.vendor_id) ? "checked" : ""}> Select public vendor metadata</label>
      <h4><button class="secondary" type="button" data-open-vendor="${html(vendor.vendor_id)}">${html(vendor.display_name)}</button></h4>
      <div class="meta-line">${html(vendor.legal_name)} · ${html(vendor.headquarters_country)} · ${html(vendor.catalog_status)}</div>
      <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${html(sourceTypeLabel(item))}</span>`).join("")}</div>
    </article>
  `).join("") : `<article class="event-card"><h3>No vendors match these filters.</h3><p>Try clearing one filter or searching by vendor name, legal name, vendor ID, or official domain.</p></article>`;
  document.querySelectorAll("[data-select-vendor]").forEach((box) => {
    box.addEventListener("change", (event) => {
      const vendorId = event.target.dataset.selectVendor;
      event.target.checked ? selectedVendors.add(vendorId) : selectedVendors.delete(vendorId);
      renderCatalogSummary();
      renderExport();
    });
  });
  document.querySelectorAll("[data-open-vendor]").forEach((button) => {
    button.addEventListener("click", async () => {
      await renderVendorDetail(button.dataset.openVendor);
    });
  });
}

async function renderVendorDetail(vendorId) {
  const detailPanel = document.getElementById("vendor-detail");
  detailPanel.innerHTML = `<p class="eyebrow">Loading</p><h3>Loading vendor detail...</h3>`;
  try {
    const detail = await loadVendorDetail(vendorId);
    const vendor = detail.vendor;
    const sources = detailSourceRecords(detail);
    const candidates = detail.candidate_sources || [];
    const unavailable = detail.unavailable_sources || [];
    const observations = detail.latest_observations || [];
    const assuranceIntelligence = detail.assurance_intelligence || [];
    detailPanel.innerHTML = `
      <p class="eyebrow">Vendor detail</p>
      <h3>${html(vendor.display_name)}</h3>
      <p class="meta-line">${html(vendor.legal_name)} · vendor_id: ${html(vendor.vendor_id)}</p>
      <div class="summary-strip">
        <span><strong>${html(sources.length)}</strong><small>source records</small></span>
        <span><strong>${html(candidates.length)}</strong><small>candidate sources</small></span>
        <span><strong>${html(unavailable.length)}</strong><small>unavailable notes</small></span>
      </div>
      <p>Catalog status: ${html(vendor.catalog_status)}</p>
      <p>Official domains: ${(vendor.official_domains || []).map((domain) => `<code>${html(domain)}</code>`).join(" ") || "Unavailable"}</p>
      ${vendorSourceAttributionNotice(vendor, sources)}
      <p>Headquarters country: ${html(vendor.headquarters_country)}</p>
      <p>Vendor categories: ${(vendor.vendor_categories || []).map(html).join(", ") || "Unavailable"}</p>
      <div class="snapshot-box">${snapshotDisclosure()}</div>
      <div class="snapshot-box source-health-snapshot">${sourceHealthDisclosure()}</div>
      ${assuranceIntelligenceTemplate(assuranceIntelligence)}
      <h4>Indexed source records</h4>
      <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${html(sourceTypeLabel(item))}</span>`).join("")}</div>
      <ul class="source-list">${sources.map(sourceTemplate).join("") || "<li>No reviewed source records.</li>"}</ul>
      <h4>Candidate source records</h4>
      <ul class="source-list">${candidates.map(candidateTemplate).join("") || "<li>No candidate source records.</li>"}</ul>
      <h4>Unavailable source notes, non-advisory</h4>
      <ul class="source-list">${unavailable.map((item) => `<li>${html(sourceTypeLabel(item.source_type))} · ${html(item.unavailability_status || item.status)} · advisory_boundary: ${html(item.advisory_boundary)}</li>`).join("") || "<li>No unavailable source notes.</li>"}</ul>
      <h4>Related observation events</h4>
      ${observations.length ? `<ul class="source-list">${observations.map((item) => `<li>${html(item.source_id)} · ${html(item.result)} · catalog_tier: ${html(item.catalog_tier)} · advisory_boundary: ${html(item.advisory_boundary)}</li>`).join("")}</ul>` : "<p>Live observation feed events are shown separately from reviewed catalog records. No related live observation events are available yet.</p>"}
    `;
    document.querySelectorAll("[data-select-source]").forEach((box) => {
      box.addEventListener("change", (event) => {
        const sourceId = event.target.dataset.selectSource;
        event.target.checked ? selectedSources.add(sourceId) : selectedSources.delete(sourceId);
        renderCatalogSummary();
        renderExport();
      });
    });
  } catch (error) {
    detailPanel.innerHTML = `<p class="eyebrow">Vendor detail</p><h3>Could not load vendor detail</h3><p>${html(error.message)}</p>`;
  }
}

const SOURCE_RELATIONSHIP_LABELS = {
  self: "Product-published source",
  parent: "Parent-company source",
  affiliate: "Affiliate-published source",
  regional_entity: "Regional-entity source",
  authorized_host: "Authorized hosted source",
  public_authority: "Public-authority source",
};

function sourceDestinationDomain(source) {
  const publisher = source.publisher_attribution || {};
  if (publisher.publisher_domain) return publisher.publisher_domain;
  try {
    return new URL(source.source_url).hostname;
  } catch (_error) {
    return "Destination domain unavailable";
  }
}

function sourceAttributionTemplate(source) {
  const publisher = source.publisher_attribution || {};
  const applicability = source.applicability || {};
  if (!publisher.publisher_name) return "";
  const relationshipLabel = SOURCE_RELATIONSHIP_LABELS[publisher.relationship] || "Attributed source";
  const coveredProducts = Array.isArray(applicability.covered_products)
    ? applicability.covered_products.join(", ")
    : "Product coverage unavailable";
  const evidence = applicability.evidence || {};
  const evidenceLink = evidence.evidence_url
    ? `<a href="${html(evidence.evidence_url)}" target="_blank" rel="noreferrer">View coverage evidence</a>`
    : "Coverage evidence link unavailable";
  return `
    <div class="source-attribution">
      <div class="source-attribution__heading">
        <span class="source-attribution__badge">${html(relationshipLabel)}</span>
        <code>${html(sourceDestinationDomain(source))}</code>
      </div>
      <strong>Published by ${html(publisher.publisher_name)}</strong>
      <p>Covers ${html(coveredProducts)} · applicability: ${html(applicability.status || "unresolved")} · basis: ${html((applicability.coverage_basis || "unavailable").replaceAll("_", " "))}</p>
      <details>
        <summary>Why this source applies</summary>
        <p>${html(evidence.statement || "No applicability statement is recorded.")}</p>
        <p>${evidenceLink}</p>
      </details>
    </div>
  `;
}

function vendorSourceAttributionNotice(vendor, sources) {
  const attributed = sources.filter((source) => {
    const publisher = source.publisher_attribution || {};
    return publisher.publisher_name && publisher.relationship && publisher.relationship !== "self";
  });
  if (!attributed.length) return "";
  const publishers = [...new Set(attributed.map((source) => source.publisher_attribution.publisher_name))];
  return `
    <div class="source-attribution-notice">
      <strong>Some ${html(vendor.display_name)} documents are published by ${html(publishers.join(", "))}.</strong>
      <p>OpenVA identifies the publisher, relationship, destination domain, and product-coverage evidence before each cross-domain link.</p>
    </div>
  `;
}

function sourceTemplate(source) {
  const health = source.source_health || {};
  const bucket = health.status_bucket || "missing";
  const label = health.label || SOURCE_HEALTH_LABELS[bucket] || SOURCE_HEALTH_LABELS.missing;
  const finalUrl = health.final_url && health.final_url !== source.source_url
    ? `<br>final_url: <a href="${html(health.final_url)}" target="_blank" rel="noreferrer">${html(health.final_url)}</a>`
    : "";
  return `
    <li>
      <span class="source-health source-health--${html(bucket)}">${html(label)}</span>
      status: ${html(health.status || "No source-health observation")} | last checked: ${html(health.verified_at || "No source-health observation")} | ${html(health.snapshot_notice || "Source health is based on the latest maintenance snapshot and may change.")}${finalUrl}<br>
      <label><input type="checkbox" data-select-source="${html(source.source_id)}" ${selectedSources.has(source.source_id) ? "checked" : ""}> Select source</label>
      <strong>${html(sourceTypeLabel(source.source_type))}</strong><br>
      ${sourceAttributionTemplate(source)}
      <a class="source-open-link" href="${html(source.source_url)}" target="_blank" rel="noreferrer">Open ${html(source.title)}</a><br>
      language: ${html(source.source_language)} · authority: ${html(source.source_authority_class)} · access: ${html(source.access_class)} · rights: ${html(source.rights_class)}<br>
      provenance.collected_at: ${html(source.provenance && source.provenance.collected_at)} · catalog_tier: ${html(source.catalog_tier)} · review_state: ${html(source.review_state)} · advisory_boundary: ${html(source.advisory_boundary)}
    </li>
  `;
}

function candidateTemplate(candidate) {
  return `<li>${html(sourceTypeLabel(candidate.source_type_candidate))} · ${html(candidate.candidate_url)} · catalog_tier: ${html(candidate.catalog_tier)} · review_state: ${html(candidate.review_state)} · advisory_boundary: ${html(candidate.advisory_boundary)}</li>`;
}

function eventMatches(event) {
  const vendor = document.getElementById("feed-vendor-filter").value.trim().toLowerCase();
  const source = document.getElementById("feed-source-filter").value.trim().toLowerCase();
  const eventText = document.getElementById("feed-event-filter").value.trim().toLowerCase();
  const review = document.getElementById("feed-review-filter").value.trim().toLowerCase();
  return (!vendor || text(event.vendor_id).toLowerCase().includes(vendor))
    && (!source || text(event.source_type).toLowerCase().includes(source))
    && (!eventText || `${text(event.event_type)} ${text(event.result)}`.toLowerCase().includes(eventText))
    && (!review || text(event.review_state).toLowerCase().includes(review));
}

function renderFeed() {
  document.getElementById("feed-meta").innerHTML = `
    <p>Latest feed generated timestamp: ${html(feedData.generated_at)}</p>
    <p>Feed source commit/workflow identifier: ${html(feedData.source_commit)} / ${html(feedData.workflow)}</p>
    <p>catalog_tier: observation · review_state: auto_observed or human_review_required · advisory_boundary: non_advisory</p>
  `;
  const events = (feedData.events || []).filter(eventMatches);
  document.getElementById("feed-list").innerHTML = events.length
    ? events.map(eventTemplate).join("")
    : `<article class="event-card"><h3>No live observation events are available yet.</h3><p>The live feed UI shell is ready, but real observation events require the observation ledger workflow, which will be added in a later PR.</p></article>`;
}

function eventTemplate(event) {
  const hashNote = event.event_type === "source_hash_changed"
    ? "<p>Content hash changed. Human review may be required. OpenVA has not determined legal, compliance, procurement, or risk significance.</p>"
    : "";
  return `
    <article class="event-card">
      <h4>${html(event.event_type)}</h4>
      <p>${html(event.vendor_id)} · ${html(event.source_id)} · ${html(sourceTypeLabel(event.source_type))} · ${html(event.observed_at)}</p>
      <p>result: ${html(event.result)} · http_status: ${html(event.http_status)}</p>
      <p>catalog_tier: ${html(event.catalog_tier)} · review_state: ${html(event.review_state)} · advisory_boundary: ${html(event.advisory_boundary)}</p>
      ${hashNote}
    </article>
  `;
}

async function selectedRecords() {
  await loadSelectedVendorDetails();
  const vendors = catalogData.vendors.filter((vendor) => selectedVendors.has(vendor.vendor_id));
  const vendorSources = [...selectedVendors].flatMap((vendorId) => {
    const detail = vendorDetailsCache.get(vendorId);
    return detail ? detailSourceRecords(detail) : [];
  });
  const selectedSourceRows = [...selectedSources]
    .map((sourceId) => sourceCache.get(sourceId))
    .filter(Boolean);
  const bySourceId = new Map();
  [...vendorSources, ...selectedSourceRows].forEach((source) => {
    if (source && source.source_id) bySourceId.set(source.source_id, source);
  });
  return { vendors, sources: [...bySourceId.values()] };
}

function exportMetadata() {
  const meta = catalogData.meta;
  return {
    profileId: meta.profileId,
    schemaVersion: meta.schemaVersion,
    packId: meta.packId,
    schema_version: meta.schema_version,
    commit_sha: meta.commit_sha,
    catalog_snapshot_date: meta.catalog_snapshot_date,
    exported_at: new Date().toISOString(),
    advisory_boundary: "non_advisory",
    export_scope: "reviewed_catalog",
  };
}

async function renderExport() {
  const records = await selectedRecords();
  document.getElementById("selection-summary").innerHTML = `
    <div class="summary-strip">
      <span><strong>${html(records.vendors.length)}</strong><small>selected public vendors</small></span>
      <span><strong>${html(records.sources.length)}</strong><small>selected reviewed sources</small></span>
    </div>
    <pre>${html(JSON.stringify(exportMetadata(), null, 2))}</pre>
  `;
}

function setupExport() {
  document.getElementById("download-vendors-csv").addEventListener("click", async () => {
    const rows = (await selectedRecords()).vendors;
    const header = ["vendor_id", "display_name", "legal_name", "catalog_status", "headquarters_country", "official_domains", "vendor_categories"];
    const csv = [header.join(","), ...rows.map((row) => header.map((key) => csvCell(row[key])).join(","))].join("\n");
    download("openva-selected-vendors.csv", csv + "\n", "text/csv");
  });
  document.getElementById("download-sources-csv").addEventListener("click", async () => {
    const rows = (await selectedRecords()).sources;
    const header = ["source_id", "vendor_id", "source_type", "title", "source_url", "publisher_attribution", "applicability", "catalog_tier", "review_state", "advisory_boundary"];
    const csv = [header.join(","), ...rows.map((row) => header.map((key) => csvCell(row[key])).join(","))].join("\n");
    download("openva-selected-sources.csv", csv + "\n", "text/csv");
  });
  document.getElementById("download-json").addEventListener("click", async () => {
    const records = await selectedRecords();
    download("openva-selected-records.json", JSON.stringify({ meta: exportMetadata(), ...records }, null, 2) + "\n", "application/json");
  });
}

function route() {
  const name = (location.hash || "#home").slice(1);
  document.querySelectorAll(".view").forEach((view) => view.classList.add("hidden"));
  const current = document.getElementById(`${name}-view`) || document.getElementById("home-view");
  current.classList.remove("hidden");
  document.querySelectorAll("nav a").forEach((link) => {
    const active = link.getAttribute("href") === `#${name}` || (!location.hash && link.getAttribute("href") === "#home");
    if (active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
  if (name === "export") renderExport();
  if (name === "feed") renderFeed();
}

async function init() {
  const [metaResponse, vendorSearchResponse, sourceTypesResponse, feedResponse, healthResponse, assuranceResponse] = await Promise.all([
    fetch("data/meta.json"),
    fetch("data/vendor-search.min.json"),
    fetch("data/source-types.json"),
    fetch("data/observation-feed.json"),
    fetch("data/source-health-snapshot.json").catch(() => null),
    fetch("data/assurance-intelligence.json").catch(() => null),
  ]);
  const meta = await metaResponse.json();
  const vendorSearch = await vendorSearchResponse.json();
  const sourceTypes = await sourceTypesResponse.json();
  feedData = await feedResponse.json();
  sourceHealthData = healthResponse && healthResponse.ok
    ? await healthResponse.json()
    : {
        generated_at: null,
        source: "latest-source-health",
        snapshot_type: "missing",
        summary: { status_bucket_counts: { healthy: 0, warning: 0, unavailable: 0, ambiguous: 0 } },
      };
  assuranceIntelligenceData = assuranceResponse && assuranceResponse.ok
    ? await assuranceResponse.json()
    : {
        report_type: "assurance_intelligence_public_snapshot",
        snapshot_type: "empty",
        summary: { assurance_count: 0, axis_count: 5 },
        entries: [],
      };
  SOURCE_TYPE_LABELS = sourceTypes.labels || {};
  catalogData = {
    meta,
    vendors: vendorSearch.items || [],
    sourceTypes: sourceTypes.items || [],
    assuranceIntelligence: assuranceIntelligenceData.entries || [],
  };
  renderSnapshotDisclosures();
  renderHome();
  setupFilters();
  setupExport();
  setupLocalMatcher();
  renderCatalog();
  renderFeed();
  document.getElementById("feed-filters").addEventListener("input", renderFeed);
  window.addEventListener("hashchange", route);
  route();
}

init();


/* Phase 2 canonical one-page runtime. */
/* Canonical one-page behaviour for the static OpenVA site.
   Extends the existing compiled-catalog runtime without changing machine keys. */
(() => {
  const ALL_SOURCE_TYPES = [
    "dpa",
    "subprocessors_list",
    "privacy_notice",
    "trust_center",
    "security_page",
    "compliance_page",
    "certification_reference",
    "terms_of_service",
    "kyc_statement",
    "aml_statement",
    "ai_terms",
    "government_request_policy",
    "transparency_report",
    "status_page",
    "other_public_source",
  ];

  const LEGAL_NOTICE_ROWS = [
    ["Important notice", "Public-source metadata only. OpenVA does not certify, approve, endorse, rank, or assess vendors."],
    ["Purpose", "This workbook provides factual vendor and source-reference metadata for independent review."],
    ["No professional advice", "Nothing in this workbook is legal, compliance, procurement, audit, accounting, security, privacy, regulatory, sanctions, know-your-customer, anti-money-laundering, or vendor-risk advice."],
    ["Independent verification required", "Verify material information independently and obtain professional advice where appropriate."],
    ["Data limitations", "Public sources may be incomplete, inaccurate, unavailable, redirected, replaced, or changed by their publishers."],
    ["No warranties", "OpenVA is provided as-is and as-available without warranties, to the maximum extent permitted by law."],
    ["Third-party sources", "Third-party names, documents, URLs, trademarks, and materials remain subject to their owners' terms."],
    ["Forwarding boundary", "Forwarding this workbook does not convert it into an audit, certification, assurance report, recommendation, or approval."],
  ];

  function onePageRoute() {
    document.querySelectorAll(".view").forEach((view) => {
      if (view.id !== "feed-view") view.classList.remove("hidden");
    });
    const hash = (location.hash || "#top").slice(1);
    const target = document.getElementById(hash) || document.getElementById("top");
    document.querySelectorAll(".site-header nav a[href^='#']").forEach((link) => {
      link.removeAttribute("aria-current");
      if (link.getAttribute("href") === `#${hash}`) link.setAttribute("aria-current", "page");
    });
    if (location.hash && target) requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
    if (hash === "review" || hash === "export") renderExport();
  }

  try {
    route = onePageRoute;
    window.route = onePageRoute;
  } catch (_error) {
    window.route = onePageRoute;
  }

  function syncHeroMetrics() {
    try {
      if (!catalogData || !catalogData.meta) return false;
      const meta = catalogData.meta;
      const vendorNode = document.getElementById("hero-vendor-count");
      const sourceNode = document.getElementById("hero-source-count");
      const dateNode = document.getElementById("hero-snapshot-date");
      if (vendorNode) vendorNode.textContent = text(meta.vendor_count);
      if (sourceNode) sourceNode.textContent = text(meta.source_count);
      if (dateNode) dateNode.textContent = text(meta.catalog_snapshot_date || "Date unavailable");
      return true;
    } catch (_error) {
      return false;
    }
  }

  function installSectionObserver() {
    if (!("IntersectionObserver" in window)) return;
    const links = [...document.querySelectorAll(".site-header nav a[href^='#']")];
    const sections = links
      .map((link) => document.getElementById(link.hash.slice(1)))
      .filter(Boolean);
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      links.forEach((link) => {
        if (link.hash === `#${visible.target.id}`) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
      });
    }, { rootMargin: "-20% 0px -65% 0px", threshold: [0.05, 0.2, 0.5] });
    sections.forEach((section) => observer.observe(section));
  }

  function selectedAllSourceTypes() {
    const boxes = [...document.querySelectorAll("#matcher-view [data-source-pack-field]:checked")];
    const selected = boxes.map((box) => box.dataset.sourcePackField).filter((value) => ALL_SOURCE_TYPES.includes(value));
    return selected.length ? ALL_SOURCE_TYPES.filter((value) => selected.includes(value)) : [...ALL_SOURCE_TYPES];
  }

  function allSourceUrlsByType(summary) {
    const urls = new Map();
    (summary && summary.sources ? summary.sources : []).forEach((source) => {
      if (ALL_SOURCE_TYPES.includes(source.source_type) && source.source_url && !urls.has(source.source_type)) {
        urls.set(source.source_type, source.source_url);
      }
    });
    return urls;
  }

  function fullBrowserResultPackRow(row, inputIndex, vendor, summary = null) {
    const sourceUrls = summary ? allSourceUrlsByType(summary) : new Map();
    const selected = selectedAllSourceTypes();
    const matched = Boolean(vendor);
    const result = {
      result_pack_version: RESULT_PACK_VERSION,
      input_index: inputIndex,
      input_vendor_name: row.vendor_name || row.business_entity_name || null,
      input_domain: row.domain || null,
      matched_vendor_name: matched ? vendor.display_name : null,
      official_domain: matched ? officialDomain(vendor) : null,
      source_urls: {},
      trust_security_url: null,
      dpa_url: null,
      subprocessors_url: null,
      privacy_notice_url: null,
      status_page_url: null,
    };
    ALL_SOURCE_TYPES.forEach((sourceType) => {
      const url = matched && selected.includes(sourceType) ? sourceUrls.get(sourceType) || null : null;
      result.source_urls[sourceType] = url;
      result[`${sourceType}_url`] = url;
    });
    result.trust_security_url = result.trust_center_url || result.security_page_url || null;
    result.dpa_url = result.dpa_url || null;
    result.subprocessors_url = result.subprocessors_list_url || null;
    result.privacy_notice_url = result.privacy_notice_url || null;
    result.status_page_url = result.status_page_url || null;
    Object.assign(result, catalogResolutionFields(matched, vendor));
    return result;
  }

  function fullResultPackCsv(inputRows, resultRows) {
    const inputColumns = [];
    inputRows.forEach((row) => Object.keys(row).forEach((key) => {
      if (!inputColumns.includes(key)) inputColumns.push(key);
    }));
    const sourceColumns = selectedAllSourceTypes().map((sourceType) => `${sourceType}_url`);
    const columns = [...inputColumns, "matched_vendor_name", "official_domain", ...sourceColumns];
    const rows = resultRows.map((result, index) => {
      const row = { ...(inputRows[index] || {}) };
      columns.slice(inputColumns.length).forEach((key) => { row[key] = result[key] || ""; });
      return row;
    });
    return serializeCsv(rows, columns);
  }

  function renderFullLocalMatcher() {
    const total = localMatchRows.length;
    const matched = localMatchRows.filter((row) => row.matched_vendor_name).length;
    const unmatched = total - matched;
    const summaryNode = document.getElementById("match-summary");
    if (summaryNode) {
      summaryNode.innerHTML = [
        ["Rows processed", total],
        ["Matched rows", matched],
        ["Unmatched rows", unmatched],
        ["Processing boundary", "Browser-local"],
      ].map(([label, value]) => `<article><strong>${html(label)}</strong><p>${html(value)}</p></article>`).join("");
    }
    const previewNode = document.getElementById("match-preview");
    if (!previewNode) return;
    previewNode.innerHTML = localMatchRows.length
      ? `<table><thead><tr><th>Input vendor</th><th>Matched vendor</th><th>Official domain</th><th>Recorded public source URLs</th></tr></thead><tbody>${localMatchRows.slice(0, 20).map((row) => {
          const urls = Object.entries(row.source_urls || {})
            .filter(([, url]) => Boolean(url))
            .map(([sourceType, url]) => `${sourceTypeLabel(sourceType)}: ${url}`);
          return `<tr><td>${html(row.input_vendor_name || row.input_domain || "Unavailable")}</td><td>${html(row.matched_vendor_name || "No match")}</td><td>${html(row.official_domain || "")}</td><td>${html(urls.join("; "))}</td></tr>`;
        }).join("")}</tbody></table><p>Preview shows up to 20 rows. Downloads include the full resolved set.</p>`
      : "<p>No local match results yet.</p>";
  }

  try {
    selectedResultPackSourceTypes = selectedAllSourceTypes;
    browserResultPackRow = fullBrowserResultPackRow;
    resultPackCsv = fullResultPackCsv;
    renderLocalMatcher = renderFullLocalMatcher;
  } catch (_error) {
    // The base runtime remains functional if a browser prevents global rebinding.
  }

  function installPresets() {
    const presets = {
      ciso: ["security_page", "trust_center", "compliance_page", "certification_reference", "status_page", "transparency_report"],
      dpo: ["dpa", "privacy_notice", "subprocessors_list", "ai_terms", "government_request_policy"],
      procurement: ["dpa", "subprocessors_list", "security_page", "trust_center", "compliance_page", "terms_of_service", "status_page"],
      custom: [],
    };
    document.querySelectorAll("[data-source-pack-preset]").forEach((button) => {
      button.addEventListener("click", () => {
        const values = presets[button.dataset.sourcePackPreset] || [];
        document.querySelectorAll("#matcher-view [data-source-pack-field]").forEach((box) => {
          box.checked = values.includes(box.dataset.sourcePackField);
        });
      });
    });
  }

  function xmlEscape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&apos;");
  }

  function columnName(index) {
    let value = index + 1;
    let name = "";
    while (value > 0) {
      value -= 1;
      name = String.fromCharCode(65 + (value % 26)) + name;
      value = Math.floor(value / 26);
    }
    return name;
  }

  function sheetXml(rows) {
    const sheetRows = rows.map((row, rowIndex) => {
      const cells = row.map((value, columnIndex) => {
        const ref = `${columnName(columnIndex)}${rowIndex + 1}`;
        if (typeof value === "number" && Number.isFinite(value)) return `<c r="${ref}"><v>${value}</v></c>`;
        return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlEscape(value)}</t></is></c>`;
      }).join("");
      return `<row r="${rowIndex + 1}">${cells}</row>`;
    }).join("");
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0" showGridLines="false"/></sheetViews><sheetData>${sheetRows}</sheetData></worksheet>`;
  }

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (const byte of bytes) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function u16(value) {
    return new Uint8Array([value & 255, (value >>> 8) & 255]);
  }

  function u32(value) {
    return new Uint8Array([value & 255, (value >>> 8) & 255, (value >>> 16) & 255, (value >>> 24) & 255]);
  }

  function concat(parts) {
    const size = parts.reduce((total, part) => total + part.length, 0);
    const output = new Uint8Array(size);
    let offset = 0;
    parts.forEach((part) => { output.set(part, offset); offset += part.length; });
    return output;
  }

  function zipStore(files) {
    const encoder = new TextEncoder();
    const localParts = [];
    const centralParts = [];
    let offset = 0;
    files.forEach(([name, content]) => {
      const nameBytes = encoder.encode(name);
      const data = typeof content === "string" ? encoder.encode(content) : content;
      const checksum = crc32(data);
      const local = concat([
        u32(0x04034b50), u16(20), u16(0), u16(0), u16(0), u16(0),
        u32(checksum), u32(data.length), u32(data.length), u16(nameBytes.length), u16(0), nameBytes, data,
      ]);
      localParts.push(local);
      const central = concat([
        u32(0x02014b50), u16(20), u16(20), u16(0), u16(0), u16(0), u16(0),
        u32(checksum), u32(data.length), u32(data.length), u16(nameBytes.length), u16(0), u16(0),
        u16(0), u16(0), u32(0), u32(offset), nameBytes,
      ]);
      centralParts.push(central);
      offset += local.length;
    });
    const central = concat(centralParts);
    const end = concat([
      u32(0x06054b50), u16(0), u16(0), u16(files.length), u16(files.length),
      u32(central.length), u32(offset), u16(0),
    ]);
    return concat([...localParts, central, end]);
  }

  function workbookBytes(sheets) {
    const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>${sheets.map((_, index) => `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("")}<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`;
    const rootRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`;
    const workbook = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${sheets.map((sheet, index) => `<sheet name="${xmlEscape(sheet.name.slice(0, 31))}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`).join("")}</sheets></workbook>`;
    const workbookRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, index) => `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`).join("")}<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`;
    const styles = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>`;
    const files = [
      ["[Content_Types].xml", contentTypes],
      ["_rels/.rels", rootRels],
      ["xl/workbook.xml", workbook],
      ["xl/_rels/workbook.xml.rels", workbookRels],
      ["xl/styles.xml", styles],
      ...sheets.map((sheet, index) => [`xl/worksheets/sheet${index + 1}.xml`, sheetXml(sheet.rows)]),
    ];
    return zipStore(files);
  }

  function saveBytes(filename, bytes) {
    const blob = new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function noticeSheetRows(context, counts = {}) {
    let meta = {};
    try { meta = catalogData && catalogData.meta ? catalogData.meta : {}; } catch (_error) { meta = {}; }
    return [
      ["OpenVA — Important Notice"],
      ["Workbook context", context],
      ["Generated at", new Date().toISOString()],
      ["Catalog snapshot", meta.catalog_snapshot_identity || meta.commit_sha || "Unavailable"],
      ["Catalog snapshot date", meta.catalog_snapshot_date || "Unavailable"],
      ...Object.entries(counts).map(([label, value]) => [label, value]),
      [],
      ...LEGAL_NOTICE_ROWS,
      [],
      ["Current terms", `${location.origin}${location.pathname}#terms-disclaimer`],
    ];
  }

  async function selectedWorkbook() {
    const records = await selectedRecords();
    const vendorRows = [
      ["vendor_id", "display_name", "legal_name", "headquarters_country", "catalog_status", "official_domains", "vendor_categories"],
      ...records.vendors.map((vendor) => [
        vendor.vendor_id, vendor.display_name, vendor.legal_name, vendor.headquarters_country,
        vendor.catalog_status, (vendor.official_domains || []).join("; "), (vendor.vendor_categories || []).join("; "),
      ]),
    ];
    const sourceRows = [
      ["source_id", "vendor_id", "source_type", "source_type_label", "title", "source_url", "access_class", "collected_at", "review_state"],
      ...records.sources.map((source) => [
        source.source_id, source.vendor_id, source.source_type, sourceTypeLabel(source.source_type),
        source.title || source.title_en || source.title_native, source.source_url, source.access_class,
        source.provenance && source.provenance.collected_at, source.review_state,
      ]),
    ];
    return workbookBytes([
      { name: "Important Notice", rows: noticeSheetRows("Selected catalog records", { "Selected vendors": records.vendors.length, "Selected sources": records.sources.length }) },
      { name: "Vendor Results", rows: vendorRows },
      { name: "Public Sources", rows: sourceRows },
    ]);
  }

  function localWorkbook() {
    const sourceTypes = selectedAllSourceTypes();
    const headers = ["input_vendor_name", "input_domain", "matched_vendor_name", "official_domain", ...sourceTypes.map((sourceType) => `${sourceTypeLabel(sourceType)} URL`)];
    const rows = [headers, ...localMatchRows.map((row) => [
      row.input_vendor_name, row.input_domain, row.matched_vendor_name, row.official_domain,
      ...sourceTypes.map((sourceType) => row.source_urls && row.source_urls[sourceType] ? row.source_urls[sourceType] : ""),
    ])];
    return workbookBytes([
      { name: "Important Notice", rows: noticeSheetRows("Browser-local vendor resolution", { "Input rows": localInventoryRows.length, "Resolved rows": localMatchRows.length }) },
      { name: "Resolved Vendors", rows },
    ]);
  }

  function installExcelDownloads() {
    document.getElementById("download-xlsx")?.addEventListener("click", async () => {
      saveBytes(`openva-selected-records-${new Date().toISOString().slice(0, 10)}.xlsx`, await selectedWorkbook());
    });
    document.getElementById("download-matches-xlsx")?.addEventListener("click", () => {
      saveBytes(`openva-resolved-vendors-${new Date().toISOString().slice(0, 10)}.xlsx`, localWorkbook());
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    installPresets();
    installExcelDownloads();
    installSectionObserver();
    const timer = window.setInterval(() => {
      if (syncHeroMetrics()) window.clearInterval(timer);
    }, 50);
    window.setTimeout(() => window.clearInterval(timer), 10000);
  });
})();
