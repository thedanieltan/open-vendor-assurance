let catalogData = null;
let feedData = null;
let visibleVendors = [];
const selectedVendors = new Set();
const selectedSources = new Set();

const CORE_COVERAGE = ["dpa", "privacy_notice", "security_page", "subprocessors_list", "trust_center"];

function text(value) {
  return value === null || value === undefined || value === "" ? "Unavailable" : String(value);
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
    <strong>Reviewed catalog snapshot: ${text(meta.catalog_snapshot_identity)}</strong><br>
    Catalog date: ${text(meta.catalog_snapshot_date)}<br>
    This catalog is a read-only view of an OpenVA public metadata snapshot, not a live monitoring feed.
    For the latest reproducible pack, check <a href="${meta.github_releases_url}">GitHub Releases</a>.
    ${meta.release_tag ? `Release tag: ${meta.release_tag}` : `Commit SHA: ${text(meta.commit_sha)}`}
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
  document.getElementById("home-stats").innerHTML = [
    ["Reviewed catalog snapshot", meta.catalog_snapshot_identity],
    ["Catalog snapshot date", meta.catalog_snapshot_date],
    ["Latest observation feed timestamp", feedTimestamp],
    ["Vendor count", meta.vendor_count],
    ["Source count", meta.source_count],
    ["Non-advisory boundary", "non_advisory"],
  ].map(([label, value]) => `<article><strong>${label}</strong><p>${text(value)}</p></article>`).join("");
}

function optionList(values, label) {
  const unique = [...new Set(values.filter(Boolean))].sort();
  return [`<option value="">${label}</option>`, ...unique.map((value) => `<option value="${value}">${value}</option>`)].join("");
}

function setupFilters() {
  const sourceTypes = catalogData.sources.map((source) => source.source_type);
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

function renderCatalog() {
  visibleVendors = catalogData.vendors.filter(vendorMatches);
  document.getElementById("vendor-list").innerHTML = visibleVendors.map((vendor) => `
    <article class="vendor-card">
      <label><input type="checkbox" data-select-vendor="${vendor.vendor_id}" ${selectedVendors.has(vendor.vendor_id) ? "checked" : ""}> Select public vendor metadata</label>
      <h4><button class="secondary" type="button" data-open-vendor="${vendor.vendor_id}">${text(vendor.display_name)}</button></h4>
      <div class="meta-line">${text(vendor.legal_name)} · ${text(vendor.headquarters_country)} · ${text(vendor.catalog_status)}</div>
      <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${item}</span>`).join("")}</div>
    </article>
  `).join("");
  document.querySelectorAll("[data-select-vendor]").forEach((box) => {
    box.addEventListener("change", (event) => {
      const vendorId = event.target.dataset.selectVendor;
      event.target.checked ? selectedVendors.add(vendorId) : selectedVendors.delete(vendorId);
      renderExport();
    });
  });
  document.querySelectorAll("[data-open-vendor]").forEach((button) => {
    button.addEventListener("click", () => renderVendorDetail(button.dataset.openVendor));
  });
}

function renderVendorDetail(vendorId) {
  const vendor = catalogData.vendors.find((item) => item.vendor_id === vendorId);
  const sources = catalogData.sources.filter((source) => source.vendor_id === vendorId);
  const candidates = catalogData.candidate_sources.filter((source) => source.vendor_id === vendorId);
  const unavailable = catalogData.unavailable_sources.filter((source) => source.vendor_id === vendorId);
  document.getElementById("vendor-detail").innerHTML = `
    <h3>${text(vendor.display_name)}</h3>
    <p class="meta-line">${text(vendor.legal_name)} · vendor_id: ${vendor.vendor_id}</p>
    <p>Catalog status: ${text(vendor.catalog_status)}</p>
    <p>Official domains: ${(vendor.official_domains || []).map((domain) => `<code>${domain}</code>`).join(" ") || "Unavailable"}</p>
    <p>Headquarters country: ${text(vendor.headquarters_country)}</p>
    <p>Vendor categories: ${(vendor.vendor_categories || []).join(", ") || "Unavailable"}</p>
    <div class="snapshot-box">${snapshotDisclosure()}</div>
    <h4>Source coverage summary</h4>
    <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${item}</span>`).join("")}</div>
    <h4>Canonical source records</h4>
    <ul class="source-list">${sources.map(sourceTemplate).join("") || "<li>No reviewed source records.</li>"}</ul>
    <h4>Candidate source records, non-canonical</h4>
    <ul class="source-list">${candidates.map(candidateTemplate).join("") || "<li>No candidate source records.</li>"}</ul>
    <h4>Unavailable source notes, non-advisory</h4>
    <ul class="source-list">${unavailable.map((item) => `<li>${text(item.source_type)} · ${text(item.unavailability_status || item.status)} · advisory_boundary: ${item.advisory_boundary}</li>`).join("") || "<li>No unavailable source notes.</li>"}</ul>
    <h4>Related observation events</h4>
    <p>Live observation feed events are shown separately from reviewed catalog records. No related live observation events are available yet.</p>
  `;
  document.querySelectorAll("[data-select-source]").forEach((box) => {
    box.addEventListener("change", (event) => {
      const sourceId = event.target.dataset.selectSource;
      event.target.checked ? selectedSources.add(sourceId) : selectedSources.delete(sourceId);
      renderExport();
    });
  });
}

function sourceTemplate(source) {
  return `
    <li>
      <label><input type="checkbox" data-select-source="${source.source_id}" ${selectedSources.has(source.source_id) ? "checked" : ""}> Select source</label>
      <strong>${text(source.source_type)}</strong> · <a href="${source.source_url}" target="_blank" rel="noreferrer">${text(source.title)}</a><br>
      language: ${text(source.source_language)} · authority: ${text(source.source_authority_class)} · access: ${text(source.access_class)} · rights: ${text(source.rights_class)}<br>
      provenance.collected_at: ${text(source.provenance && source.provenance.collected_at)} · catalog_tier: ${source.catalog_tier} · review_state: ${source.review_state} · advisory_boundary: ${source.advisory_boundary}
    </li>
  `;
}

function candidateTemplate(candidate) {
  return `<li>${text(candidate.source_type_candidate)} · ${text(candidate.candidate_url)} · canonical: false · catalog_tier: ${candidate.catalog_tier} · review_state: ${candidate.review_state} · advisory_boundary: ${candidate.advisory_boundary}</li>`;
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
    <p>Latest feed generated timestamp: ${text(feedData.generated_at)}</p>
    <p>Feed source commit/workflow identifier: ${text(feedData.source_commit)} / ${text(feedData.workflow)}</p>
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
      <h4>${text(event.event_type)}</h4>
      <p>${text(event.vendor_id)} · ${text(event.source_id)} · ${text(event.source_type)} · ${text(event.observed_at)}</p>
      <p>result: ${text(event.result)} · http_status: ${text(event.http_status)}</p>
      <p>catalog_tier: ${text(event.catalog_tier)} · review_state: ${text(event.review_state)} · canonical: false · advisory_boundary: ${text(event.advisory_boundary)}</p>
      ${hashNote}
    </article>
  `;
}

function selectedRecords() {
  const vendors = catalogData.vendors.filter((vendor) => selectedVendors.has(vendor.vendor_id));
  const vendorIds = new Set(vendors.map((vendor) => vendor.vendor_id));
  const sources = catalogData.sources.filter((source) => selectedSources.has(source.source_id) || vendorIds.has(source.vendor_id));
  return { vendors, sources };
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

function renderExport() {
  const records = selectedRecords();
  document.getElementById("selection-summary").innerHTML = `
    <p>Selected public vendors: ${records.vendors.length}</p>
    <p>Selected reviewed source records: ${records.sources.length}</p>
    <pre>${JSON.stringify(exportMetadata(), null, 2)}</pre>
  `;
}

function setupExport() {
  document.getElementById("download-vendors-csv").addEventListener("click", () => {
    const rows = selectedRecords().vendors;
    const header = ["vendor_id", "display_name", "legal_name", "catalog_status", "headquarters_country", "official_domains", "vendor_categories"];
    const csv = [header.join(","), ...rows.map((row) => header.map((key) => csvCell(row[key])).join(","))].join("\n");
    download("openva-selected-vendors.csv", csv + "\n", "text/csv");
  });
  document.getElementById("download-sources-csv").addEventListener("click", () => {
    const rows = selectedRecords().sources;
    const header = ["source_id", "vendor_id", "source_type", "title", "source_url", "catalog_tier", "review_state", "advisory_boundary"];
    const csv = [header.join(","), ...rows.map((row) => header.map((key) => csvCell(row[key])).join(","))].join("\n");
    download("openva-selected-sources.csv", csv + "\n", "text/csv");
  });
  document.getElementById("download-json").addEventListener("click", () => {
    const records = selectedRecords();
    download("openva-selected-records.json", JSON.stringify({ meta: exportMetadata(), ...records }, null, 2) + "\n", "application/json");
  });
}

function route() {
  const name = (location.hash || "#home").slice(1);
  document.querySelectorAll(".view").forEach((view) => view.classList.add("hidden"));
  const current = document.getElementById(`${name}-view`) || document.getElementById("home-view");
  current.classList.remove("hidden");
  if (name === "export") renderExport();
  if (name === "feed") renderFeed();
}

async function init() {
  const [catalogResponse, feedResponse] = await Promise.all([
    fetch("data/catalog-data.json"),
    fetch("data/observation-feed.json"),
  ]);
  catalogData = await catalogResponse.json();
  feedData = await feedResponse.json();
  renderSnapshotDisclosures();
  renderHome();
  setupFilters();
  setupExport();
  renderCatalog();
  renderFeed();
  document.getElementById("feed-filters").addEventListener("input", renderFeed);
  window.addEventListener("hashchange", route);
  route();
}

init();
