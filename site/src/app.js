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

const CORE_COVERAGE = ["dpa", "privacy_notice", "security_page", "subprocessors_list", "trust_center"];
const RESULT_PACK_VERSION = "1.0.0";
const RESULT_PACK_SOURCE_TYPES = ["trust_center", "dpa", "subprocessors_list", "privacy_notice", "security_page", "status_page"];
const RESULT_PACK_FLAT_COLUMNS = [
  "openva_identity_status",
  "openva_no_match_reason",
  "openva_matched_vendor_id",
  "openva_matched_vendor_name",
  ...RESULT_PACK_SOURCE_TYPES.flatMap((sourceType) => [
    `openva_${sourceType}_status`,
    `openva_${sourceType}_url`,
    `openva_${sourceType}_basis`,
    `openva_${sourceType}_checked_at`,
  ]),
  "openva_not_advice",
];
const SOURCE_HEALTH_LABELS = {
  healthy: "Reachable at last check",
  warning: "Retrieval requires review",
  unavailable: "Unavailable at last check",
  ambiguous: "Access result ambiguous",
  missing: "No source-health observation",
};
const CONFIDENCE_NOTICE = "Catalog confidence labels are metadata about OpenVA review coverage, not advice.";
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

function html(value) {
  return text(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function csvCell(value) {
  const raw = Array.isArray(value) ? value.join("; ") : text(value);
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
    <strong>Reviewed catalog snapshot: ${html(meta.catalog_snapshot_identity)}</strong><br>
    Catalog date: ${html(meta.catalog_snapshot_date)}<br>
    This catalog is a read-only view of an OpenVA public metadata snapshot, not a live monitoring feed.
    For the latest reproducible pack, check <a href="${html(meta.github_releases_url)}">GitHub Releases</a>.
    ${meta.release_tag ? `Release tag: ${html(meta.release_tag)}` : `Commit SHA: ${html(meta.commit_sha)}`}
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

function confidenceTemplate(confidence) {
  const data = confidence || {};
  const completeness = data.catalog_completeness || { label: "Not reviewed" };
  const entity = data.entity_review || { label: "Not reviewed" };
  const provenance = data.field_provenance || { label: "Missing" };
  return `
    <div class="confidence-grid">
      <span><strong>Source health</strong><small>Shown per source record</small></span>
      <span><strong>Catalog completeness</strong><small>${html(completeness.label)}</small></span>
      <span><strong>Entity review</strong><small>${html(entity.label)}</small></span>
      <span><strong>Field provenance</strong><small>${html(provenance.label)}</small></span>
    </div>
    <p class="meta-line">${html(data.notice || CONFIDENCE_NOTICE)}</p>
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
  document.getElementById("github-releases-link").href = catalogData.meta.github_releases_url;
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
  (detail.canonical_sources || []).forEach((source) => {
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

function selectedResultPackSourceTypes() {
  const selected = [...document.querySelectorAll("#matcher-view [data-source-pack-field]:checked")]
    .map((box) => box.dataset.sourcePackField)
    .filter((sourceType) => RESULT_PACK_SOURCE_TYPES.includes(sourceType));
  return selected.length ? RESULT_PACK_SOURCE_TYPES.filter((sourceType) => selected.includes(sourceType)) : [...RESULT_PACK_SOURCE_TYPES];
}

function cachedSourceResult(sourceType, url = null) {
  return {
    source_type: sourceType,
    status: "not_checked",
    url: url || null,
    basis: "cached",
    checked_at: null,
  };
}

function cachedSourceUrlsByType(summary) {
  const urls = new Map();
  (summary.sources || []).forEach((source) => {
    if (RESULT_PACK_SOURCE_TYPES.includes(source.source_type) && source.source_url && !urls.has(source.source_type)) {
      urls.set(source.source_type, source.source_url);
    }
  });
  return urls;
}

function browserResultPackRow(row, inputIndex, vendor, summary = null) {
  const sourceUrls = summary ? cachedSourceUrlsByType(summary) : new Map();
  const matched = Boolean(vendor);
  const inputVendorName = row.vendor_name || row.business_entity_name || null;
  return {
    result_pack_version: RESULT_PACK_VERSION,
    input_index: inputIndex,
    input_vendor_name: inputVendorName || null,
    input_domain: row.domain || null,
    identity_status: matched ? "match" : "no_match",
    no_match_reason: matched ? null : (inputVendorName || row.domain ? "not_in_reference" : "no_public_identity"),
    matched_vendor_id: matched ? vendor.vendor_id : null,
    matched_vendor_name: matched ? vendor.display_name : null,
    sources: selectedResultPackSourceTypes().map((sourceType) => cachedSourceResult(sourceType, sourceUrls.get(sourceType))),
    not_advice: true,
  };
}

function flattenResultPackRows(inputRows, resultRows) {
  return resultRows.map((result, index) => {
    const row = { ...(inputRows[index] || {}) };
    row.openva_identity_status = result.identity_status;
    row.openva_no_match_reason = result.no_match_reason;
    row.openva_matched_vendor_id = result.matched_vendor_id;
    row.openva_matched_vendor_name = result.matched_vendor_name;
    RESULT_PACK_SOURCE_TYPES.forEach((sourceType) => {
      const source = (result.sources || []).find((item) => item.source_type === sourceType) || cachedSourceResult(sourceType);
      row[`openva_${sourceType}_status`] = source.status;
      row[`openva_${sourceType}_url`] = source.url;
      row[`openva_${sourceType}_basis`] = source.basis;
      row[`openva_${sourceType}_checked_at`] = source.checked_at;
    });
    row.openva_not_advice = result.not_advice ? "true" : "false";
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
  const sources = detail.canonical_sources || [];
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
  // Browser-local resolution is always cached. Known URLs are locators only:
  // they remain not_checked/cached until the live resolver actually checks them.
  return browserResultPackRow(row, inputIndex, vendor, summary);
}

function renderLocalMatcher() {
  const total = localMatchRows.length;
  const matched = localMatchRows.filter((row) => row.matched_vendor_id).length;
  const unmatched = total - matched;
  document.getElementById("match-summary").innerHTML = [
    ["Rows processed", total],
    ["Matched rows", matched],
    ["Unmatched rows", unmatched],
    ["Processing boundary", "browser-local; not uploaded to OpenVA"],
  ].map(([label, value]) => `<article><strong>${html(label)}</strong><p>${html(value)}</p></article>`).join("");

  document.getElementById("match-preview").innerHTML = localMatchRows.length
    ? `<table><thead><tr><th>Input vendor</th><th>Matched vendor</th><th>Identity status</th><th>No-match reason</th><th>Cached source locators</th></tr></thead><tbody>${
        localMatchRows.slice(0, 20).map((row) => `
          <tr>
            <td>${html(row.input_vendor_name || row.input_domain || "Unavailable")}</td>
            <td>${html(row.matched_vendor_name || "No match")}</td>
            <td>${html(row.identity_status)}</td>
            <td>${html(row.no_match_reason)}</td>
            <td>${html((row.sources || []).filter((source) => source.url).map((source) => source.source_type).join("; "))}</td>
          </tr>
        `).join("")
      }</tbody></table><p>Preview shows up to 20 rows. Download CSV or JSON for the full resolver result-pack. Browser-local sources are cached/not_checked only.</p>`
    : "<p>No local match results yet.</p>";
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
    localMatchRows = await Promise.all(localInventoryRows.map((row, index) => matchInventoryRow(row, index, indexes)));
    document.getElementById("matcher-status").textContent = `${localMatchRows.length} row(s) matched locally in browser memory. No private inventory data was uploaded.`;
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
    download("openva-matched-inventory.csv", resultPackCsv(localInventoryRows, localMatchRows), "text/csv");
  });

  document.getElementById("download-matches-json").addEventListener("click", () => {
    download("openva-matched-inventory.json", JSON.stringify(localMatchRows, null, 2) + "\n", "application/json");
  });

  renderLocalMatcher();
}

function optionList(values, label) {
  const unique = [...new Set(values.filter(Boolean))].sort();
  return [`<option value="">${html(label)}</option>`, ...unique.map((value) => `<option value="${html(value)}">${html(value)}</option>`)].join("");
}

function setupFilters() {
  const sourceTypes = catalogData.sourceTypes;
  const countries = catalogData.vendors.map((vendor) => vendor.headquarters_country);
  const categories = catalogData.vendors.flatMap((vendor) => vendor.vendor_categories || []);
  document.getElementById("source-type-filter").innerHTML = optionList(sourceTypes, "All source types");
  document.getElementById("country-filter").innerHTML = optionList(countries, "All countries");
  document.getElementById("category-filter").innerHTML = optionList(categories, "All categories");
  document.getElementById("coverage-filter").innerHTML = optionList(CORE_COVERAGE, "All coverage");
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
  const coverage = document.getElementById("coverage-filter").value;
  const haystack = [
    vendor.display_name,
    vendor.legal_name,
    vendor.vendor_id,
    ...(vendor.official_domains || []),
  ].join(" ").toLowerCase();
  return (!query || haystack.includes(query))
    && (!sourceType || (vendor.source_types || []).includes(sourceType))
    && (!country || vendor.headquarters_country === country)
    && (!category || (vendor.vendor_categories || []).includes(category))
    && (!coverage || (vendor.source_types || []).includes(coverage));
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
      <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${html(item)}</span>`).join("")}</div>
      ${confidenceTemplate(vendor.catalog_confidence)}
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
    const sources = detail.canonical_sources || [];
    const candidates = detail.candidate_sources || [];
    const unavailable = detail.unavailable_sources || [];
    const observations = detail.latest_observations || [];
    const assuranceIntelligence = detail.assurance_intelligence || [];
    detailPanel.innerHTML = `
      <p class="eyebrow">Vendor detail</p>
      <h3>${html(vendor.display_name)}</h3>
      <p class="meta-line">${html(vendor.legal_name)} · vendor_id: ${html(vendor.vendor_id)}</p>
      <div class="summary-strip">
        <span><strong>${html(sources.length)}</strong><small>canonical sources</small></span>
        <span><strong>${html(candidates.length)}</strong><small>candidate sources</small></span>
        <span><strong>${html(unavailable.length)}</strong><small>unavailable notes</small></span>
      </div>
      <p>Catalog status: ${html(vendor.catalog_status)}</p>
      <p>Official domains: ${(vendor.official_domains || []).map((domain) => `<code>${html(domain)}</code>`).join(" ") || "Unavailable"}</p>
      <p>Headquarters country: ${html(vendor.headquarters_country)}</p>
      <p>Vendor categories: ${(vendor.vendor_categories || []).map(html).join(", ") || "Unavailable"}</p>
      <div class="snapshot-box">${snapshotDisclosure()}</div>
      <div class="snapshot-box source-health-snapshot">${sourceHealthDisclosure()}</div>
      <div class="snapshot-box catalog-confidence-snapshot">${confidenceTemplate(vendor.catalog_confidence)}</div>
      ${assuranceIntelligenceTemplate(assuranceIntelligence)}
      <h4>Source coverage summary</h4>
      <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${html(item)}</span>`).join("")}</div>
      <h4>Canonical source records</h4>
      <ul class="source-list">${sources.map(sourceTemplate).join("") || "<li>No reviewed source records.</li>"}</ul>
      <h4>Candidate source records, non-canonical</h4>
      <ul class="source-list">${candidates.map(candidateTemplate).join("") || "<li>No candidate source records.</li>"}</ul>
      <h4>Unavailable source notes, non-advisory</h4>
      <ul class="source-list">${unavailable.map((item) => `<li>${html(item.source_type)} · ${html(item.unavailability_status || item.status)} · advisory_boundary: ${html(item.advisory_boundary)}</li>`).join("") || "<li>No unavailable source notes.</li>"}</ul>
      <h4>Related observation events</h4>
      ${
        observations.length
          ? `<ul class="source-list">${observations.map((item) => `<li>${html(item.source_id)} · ${html(item.result)} · catalog_tier: ${html(item.catalog_tier)} · canonical: false · advisory_boundary: ${html(item.advisory_boundary)}</li>`).join("")}</ul>`
          : "<p>Live observation feed events are shown separately from reviewed catalog records. No related live observation events are available yet.</p>"
      }
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
      <strong>${html(source.source_type)}</strong> · <a href="${html(source.source_url)}" target="_blank" rel="noreferrer">${html(source.title)}</a><br>
      language: ${html(source.source_language)} · authority: ${html(source.source_authority_class)} · access: ${html(source.access_class)} · rights: ${html(source.rights_class)}<br>
      provenance.collected_at: ${html(source.provenance && source.provenance.collected_at)} · catalog_tier: ${html(source.catalog_tier)} · review_state: ${html(source.review_state)} · advisory_boundary: ${html(source.advisory_boundary)}
    </li>
  `;
}

function candidateTemplate(candidate) {
  return `<li>${html(candidate.source_type_candidate)} · ${html(candidate.candidate_url)} · canonical: false · catalog_tier: ${html(candidate.catalog_tier)} · review_state: ${html(candidate.review_state)} · advisory_boundary: ${html(candidate.advisory_boundary)}</li>`;
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
    <p>catalog_tier: observation · review_state: auto_observed or human_review_required · canonical: false · advisory_boundary: non_advisory</p>
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
      <p>${html(event.vendor_id)} · ${html(event.source_id)} · ${html(event.source_type)} · ${html(event.observed_at)}</p>
      <p>result: ${html(event.result)} · http_status: ${html(event.http_status)}</p>
      <p>catalog_tier: ${html(event.catalog_tier)} · review_state: ${html(event.review_state)} · canonical: false · advisory_boundary: ${html(event.advisory_boundary)}</p>
      ${hashNote}
    </article>
  `;
}

async function selectedRecords() {
  await loadSelectedVendorDetails();
  const vendors = catalogData.vendors.filter((vendor) => selectedVendors.has(vendor.vendor_id));
  const vendorSources = [...selectedVendors].flatMap((vendorId) => {
    const detail = vendorDetailsCache.get(vendorId);
    return detail ? (detail.canonical_sources || []) : [];
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
    release_tag: meta.release_tag,
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
    const header = ["source_id", "vendor_id", "source_type", "title", "source_url", "catalog_tier", "review_state", "advisory_boundary"];
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
