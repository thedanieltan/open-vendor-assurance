(() => {
  const RESOLVER_VERSION = "browser-parity-v2";
  const IDENTITY_FIELDS = ["vendor_name", "business_entity_name", "domain", "registration_number"];
  const HEADER_ALIASES = Object.freeze({
    vendor: "vendor_name",
    vendor_name: "vendor_name",
    vendorname: "vendor_name",
    supplier: "vendor_name",
    supplier_name: "vendor_name",
    company: "vendor_name",
    company_name: "vendor_name",
    business_entity: "business_entity_name",
    business_entity_name: "business_entity_name",
    business_name: "business_entity_name",
    entity_name: "business_entity_name",
    legal_entity: "business_entity_name",
    legal_entity_name: "business_entity_name",
    legal_name: "business_entity_name",
    domain: "domain",
    vendor_domain: "domain",
    company_domain: "domain",
    website: "domain",
    website_url: "domain",
    web_address: "domain",
    url: "domain",
    jurisdiction: "jurisdiction",
    country: "jurisdiction",
    country_code: "jurisdiction",
    registration_number: "registration_number",
    registration_no: "registration_number",
    registration_id: "registration_number",
    company_number: "registration_number",
    company_registration_number: "registration_number",
    uen: "registration_number",
    registered_address: "registered_address",
    address: "registered_address",
  });

  function scalar(value) {
    return value === null || value === undefined ? "" : String(value).trim();
  }

  // Identity normalization is delegated to the single shared matcher core
  // (openva-matcher-core.js), which mirrors the authoritative Python core. This file must
  // NOT hand-maintain its own normalization, so the browser resolver cannot drift from
  // Python; the Node conformance harness (site/test/resolver-conformance.cjs) proves parity.
  function openvaMatcherCore() {
    const core =
      (typeof globalThis !== "undefined" && globalThis.OpenVAMatcherCore) ||
      (typeof window !== "undefined" && window.OpenVAMatcherCore);
    if (!core) {
      throw new Error("OpenVAMatcherCore (openva-matcher-core.js) must load before ui-fixes.js");
    }
    return core;
  }

  const normalizeName = (value) => openvaMatcherCore().normalizeName(value);
  const stripLegalSuffixes = (value) => openvaMatcherCore().stripLegalSuffixes(value);
  const normalizeDomainValue = (value) => openvaMatcherCore().normalizeDomain(value);
  const normalizeRegistrationNumber = (value) => openvaMatcherCore().normalizeRegistrationNumber(value);
  const normalizeJurisdiction = (value) => openvaMatcherCore().normalizeJurisdiction(value);

  function normalizedHeader(value, index) {
    const key = scalar(value)
      .replace(/^\uFEFF/, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    return HEADER_ALIASES[key] || key || `column_${index + 1}`;
  }

  function delimiterCount(line, delimiter) {
    let count = 0;
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index];
      const next = line[index + 1];
      if (char === '"' && quoted && next === '"') index += 1;
      else if (char === '"') quoted = !quoted;
      else if (!quoted && char === delimiter) count += 1;
    }
    return count;
  }

  function detectDelimiter(content) {
    const firstLine = scalar(content).split(/\r?\n/).find((line) => line.trim()) || "";
    return [[",", delimiterCount(firstLine, ",")], ["\t", delimiterCount(firstLine, "\t")], [";", delimiterCount(firstLine, ";")]]
      .sort((left, right) => right[1] - left[1])[0][0];
  }

  function parseInventoryCsv(content) {
    const input = String(content || "").replace(/^\uFEFF/, "");
    if (!input.trim()) return [];
    const delimiter = detectDelimiter(input);
    const rows = [];
    let row = [];
    let cell = "";
    let quoted = false;

    for (let index = 0; index < input.length; index += 1) {
      const char = input[index];
      const next = input[index + 1];
      if (quoted && char === '"' && next === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = !quoted;
      } else if (!quoted && char === delimiter) {
        row.push(cell);
        cell = "";
      } else if (!quoted && (char === "\n" || char === "\r")) {
        if (char === "\r" && next === "\n") index += 1;
        row.push(cell);
        if (row.some((value) => scalar(value))) rows.push(row);
        row = [];
        cell = "";
      } else {
        cell += char;
      }
    }
    row.push(cell);
    if (row.some((value) => scalar(value))) rows.push(row);
    if (!rows.length) return [];

    const headers = rows[0].map(normalizedHeader);
    return rows.slice(1).map((values) => {
      const output = {};
      headers.forEach((header, index) => {
        const value = values[index] || "";
        if (!(header in output) || (!scalar(output[header]) && scalar(value))) output[header] = value;
      });
      return output;
    });
  }

  function fileReaderText(file) {
    return new Promise((resolve, reject) => {
      if (typeof FileReader !== "function") {
        reject(new Error("FileReader is unavailable in this browser."));
        return;
      }
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(String(reader.result || "")), { once: true });
      reader.addEventListener("error", () => reject(reader.error || new Error("The browser could not read the selected file.")), { once: true });
      reader.addEventListener("abort", () => reject(new DOMException("The local file read was aborted.", "AbortError")), { once: true });
      reader.readAsText(file);
    });
  }

  function isTransientFileReadError(error) {
    return ["NotFoundError", "NotReadableError", "AbortError"].includes(error && error.name);
  }

  async function readLocalTextFile(file) {
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        if (typeof file.text === "function") return await file.text();
        return await fileReaderText(file);
      } catch (error) {
        lastError = error;
        if (!isTransientFileReadError(error) || attempt === 1) break;
        await new Promise((resolve) => window.setTimeout(resolve, 200));
      }
    }
    throw lastError || new Error("The browser could not read the selected file.");
  }

  function localFileReadMessage(file, error) {
    if (isTransientFileReadError(error)) {
      return `The browser lost access to ${file.name}. Save or download it to a local folder, wait for any download or cloud sync to finish, then choose the file again.`;
    }
    return `Could not read ${file.name}: ${error.message || "Unknown file-read error"}`;
  }

  function addVendor(map, key, vendor) {
    if (!key) return;
    const entries = map.get(key) || [];
    if (!entries.some((entry) => entry.vendor_id === vendor.vendor_id)) entries.push(vendor);
    map.set(key, entries);
  }

  function uniqueVendors(entries) {
    const byId = new Map();
    (entries || []).forEach((entry) => {
      const vendor = entry.vendor || entry;
      if (vendor && vendor.vendor_id) byId.set(vendor.vendor_id, vendor);
    });
    return [...byId.values()].sort((left, right) => left.vendor_id.localeCompare(right.vendor_id));
  }

  function buildResolverIndexes() {
    const domainIndex = new Map();
    const nameIndex = new Map();
    const registrationIndex = new Map();
    const officialDomainRows = [];

    catalogData.vendors.forEach((vendor) => {
      (vendor.official_domains || []).forEach((value) => {
        const domain = normalizeDomainValue(value);
        if (!domain) return;
        addVendor(domainIndex, domain, vendor);
        officialDomainRows.push({ domain, vendor });
      });
      [vendor.display_name, vendor.legal_name, vendor.vendor_id, scalar(vendor.vendor_id).replaceAll("-", " ")]
        .flatMap((value) => [normalizeName(value), stripLegalSuffixes(value)])
        .filter(Boolean)
        .forEach((key) => addVendor(nameIndex, key, vendor));
      (vendor.registration_keys || []).forEach((key) => {
        const registrationNumber = normalizeRegistrationNumber(key.registration_number);
        if (!registrationNumber) return;
        const entries = registrationIndex.get(registrationNumber) || [];
        entries.push({ vendor, jurisdiction: normalizeJurisdiction(key.jurisdiction) });
        registrationIndex.set(registrationNumber, entries);
      });
    });

    officialDomainRows.sort((left, right) => right.domain.length - left.domain.length || left.domain.localeCompare(right.domain));
    return { domainIndex, nameIndex, registrationIndex, officialDomainRows };
  }

  function domainCandidates(value, indexes) {
    const domain = normalizeDomainValue(value);
    if (!domain) return { vendors: [], method: null, confidence: null };
    const exact = uniqueVendors(indexes.domainIndex.get(domain));
    if (exact.length) return { vendors: exact, method: "domain_exact", confidence: 1.0 };
    const matches = indexes.officialDomainRows.filter((entry) => domain.endsWith(`.${entry.domain}`));
    if (!matches.length) return { vendors: [], method: null, confidence: null };
    const longest = matches[0].domain.length;
    return {
      vendors: uniqueVendors(matches.filter((entry) => entry.domain.length === longest)),
      method: "domain_subdomain",
      confidence: 0.95,
    };
  }

  function nameCandidates(value, indexes) {
    const keys = [...new Set([normalizeName(value), stripLegalSuffixes(value)].filter(Boolean))];
    return uniqueVendors(keys.flatMap((key) => indexes.nameIndex.get(key) || []));
  }

  function registrationCandidates(row, indexes) {
    const registrationNumber = normalizeRegistrationNumber(row.registration_number);
    if (!registrationNumber) return [];
    const jurisdiction = normalizeJurisdiction(row.jurisdiction);
    const entries = indexes.registrationIndex.get(registrationNumber) || [];
    return uniqueVendors(jurisdiction ? entries.filter((entry) => entry.jurisdiction === jurisdiction) : entries);
  }

  function matchingDecision(row, indexes) {
    const domain = domainCandidates(row.domain, indexes);
    const registrations = registrationCandidates(row, indexes);
    const names = uniqueVendors([
      ...nameCandidates(row.vendor_name, indexes),
      ...nameCandidates(row.business_entity_name, indexes),
    ]);
    const hasIdentity = IDENTITY_FIELDS.some((field) => scalar(row[field]));

    if (!hasIdentity) return { status: "no_match", vendor: null, method: null, confidence: null, note: "No supported identity value was provided." };
    if (domain.vendors.length > 1 || registrations.length > 1 || (!domain.vendors.length && !registrations.length && names.length > 1)) {
      return { status: "ambiguous", vendor: null, method: null, confidence: null, note: "Multiple plausible catalogue vendors matched the supplied identity." };
    }

    const domainVendor = domain.vendors[0] || null;
    const registrationVendor = registrations[0] || null;
    const nameVendor = names.length === 1 ? names[0] : null;
    if (registrationVendor && domainVendor && registrationVendor.vendor_id !== domainVendor.vendor_id) {
      return { status: "ambiguous", vendor: null, method: null, confidence: null, note: "Domain and registration evidence point to different catalogue vendors." };
    }
    if (registrationVendor && nameVendor && registrationVendor.vendor_id !== nameVendor.vendor_id) {
      return { status: "ambiguous", vendor: null, method: null, confidence: null, note: "Name and registration evidence point to different catalogue vendors." };
    }
    if (domainVendor) return { status: "matched", vendor: domainVendor, method: domain.method, confidence: domain.confidence, note: null };
    if (registrationVendor) return { status: "matched", vendor: registrationVendor, method: "registration_number_exact", confidence: 1.0, note: null };
    if (nameVendor) return { status: "matched", vendor: nameVendor, method: "name_exact", confidence: 0.9, note: null };

    const registrationNumber = normalizeRegistrationNumber(row.registration_number);
    const note = registrationNumber && !indexes.registrationIndex.has(registrationNumber)
      ? "The registration number is not indexed in the current public catalogue snapshot."
      : "No catalogue vendor matched the supplied identity.";
    return { status: "no_match", vendor: null, method: null, confidence: null, note };
  }

  async function matchInventoryRowHardened(row, inputIndex, indexes) {
    const decision = matchingDecision(row, indexes);
    let summary = null;
    let sourceLoadNote = null;
    if (decision.vendor) {
      try {
        summary = await vendorSourceSummary(decision.vendor.vendor_id);
      } catch (_error) {
        sourceLoadNote = "Vendor identity matched, but its source-detail shard could not be loaded.";
      }
    }
    const result = browserResultPackRow(row, inputIndex, decision.vendor, summary);
    return {
      ...result,
      input_registration_number: row.registration_number || null,
      match_status: decision.status,
      match_method: decision.method,
      match_confidence: decision.confidence,
      match_note: sourceLoadNote || decision.note,
    };
  }

  function selectedSourceTypesForExport() {
    return [...document.querySelectorAll("#matcher-view [data-source-pack-field]:checked")]
      .map((box) => box.dataset.sourcePackField)
      .filter(Boolean);
  }

  function resolverResultPackCsv(inputRows, resultRows) {
    const inputColumns = [];
    inputRows.forEach((row) => Object.keys(row).forEach((key) => {
      if (!inputColumns.includes(key)) inputColumns.push(key);
    }));
    const sourceColumns = selectedSourceTypesForExport().map((sourceType) => `${sourceType}_url`);
    const columns = [
      ...inputColumns,
      "openva_match_status", "openva_match_method", "openva_match_confidence", "openva_match_note",
      "matched_vendor_name", "official_domain",
      "openva_resolution_status", "openva_result_origin", "openva_live_checked", "openva_checked_at",
      "openva_catalog_publication_status", "openva_resolution_message",
      ...sourceColumns,
    ];
    const rows = resultRows.map((result, index) => {
      const row = { ...(inputRows[index] || {}) };
      row.openva_match_status = result.match_status || "no_match";
      row.openva_match_method = result.match_method || "";
      row.openva_match_confidence = result.match_confidence ?? "";
      row.openva_match_note = result.match_note || "";
      row.matched_vendor_name = result.matched_vendor_name || "";
      row.official_domain = result.official_domain || "";
      row.openva_resolution_status = result.openva_resolution_status || "";
      row.openva_result_origin = result.openva_result_origin || "";
      row.openva_live_checked = result.openva_live_checked ?? "";
      row.openva_checked_at = result.openva_checked_at || "";
      row.openva_catalog_publication_status = result.openva_catalog_publication_status || "";
      row.openva_resolution_message = result.openva_resolution_message || "";
      sourceColumns.forEach((column) => { row[column] = result[column] || ""; });
      return row;
    });
    return serializeCsv(rows, columns);
  }

  function inputIdentityLabel(row) {
    return row.input_vendor_name || row.input_domain || row.input_registration_number || "Unavailable";
  }

  function renderResolverResults() {
    const total = localMatchRows.length;
    const matched = localMatchRows.filter((row) => row.match_status === "matched").length;
    const ambiguous = localMatchRows.filter((row) => row.match_status === "ambiguous").length;
    const unmatched = total - matched - ambiguous;
    const summaryNode = document.getElementById("match-summary");
    if (summaryNode) {
      summaryNode.innerHTML = [["Rows processed", total], ["Matched rows", matched], ["Ambiguous rows", ambiguous], ["No-match rows", unmatched], ["Processing boundary", "Browser-local"]]
        .map(([label, value]) => `<article><strong>${html(label)}</strong><p>${html(value)}</p></article>`).join("");
    }

    const previewNode = document.getElementById("match-preview");
    if (!previewNode) return;
    previewNode.innerHTML = localMatchRows.length
      ? `<table><thead><tr><th>Input vendor</th><th>Status</th><th>Matched vendor</th><th>Official domain</th><th>Recorded public source URLs</th><th>Match note</th></tr></thead><tbody>${localMatchRows.slice(0, 20).map((row) => {
          const urls = Object.entries(row.source_urls || {}).filter(([, url]) => Boolean(url)).map(([sourceType, url]) => `${sourceTypeLabel(sourceType)}: ${url}`);
          return `<tr><td>${html(inputIdentityLabel(row))}</td><td>${html(row.match_status || "no_match")}</td><td>${html(row.matched_vendor_name || "")}</td><td>${html(row.official_domain || "")}</td><td>${html(urls.join("; "))}</td><td>${html(row.match_note || "")}</td></tr>`;
        }).join("")}</tbody></table><p>Preview shows up to 20 rows. Downloads include every input row and an explicit match status.</p>`
      : "<p>No local match results yet.</p>";
  }

  function setupResolver() {
    const fileInput = document.getElementById("inventory-file");
    const runButton = document.getElementById("run-local-match");
    const clearButton = document.getElementById("clear-local-match");
    const csvButton = document.getElementById("download-matches-csv");
    const jsonButton = document.getElementById("download-matches-json");
    const statusNode = document.getElementById("matcher-status");
    if (!fileInput || !runButton || !clearButton || !csvButton || !jsonButton || !statusNode) return;
    if (fileInput.dataset.openvaResolverVersion === RESOLVER_VERSION) return;
    fileInput.dataset.openvaResolverVersion = RESOLVER_VERSION;
    runButton.disabled = true;

    fileInput.addEventListener("change", async (event) => {
      const file = event.target.files[0];
      localMatchRows = [];
      runButton.disabled = true;
      if (!file) {
        localInventoryRows = [];
        statusNode.textContent = "No CSV selected. Your file will be processed locally and is not uploaded to OpenVA.";
        renderResolverResults();
        return;
      }

      statusNode.textContent = `Reading ${file.name} locally...`;
      try {
        const content = await readLocalTextFile(file);
        const parsedRows = parseInventoryCsv(content);
        const availableFields = new Set(parsedRows.flatMap((row) => Object.keys(row)));
        const recognized = IDENTITY_FIELDS.filter((field) => availableFields.has(field));
        localInventoryRows = parsedRows;
        if (!parsedRows.length) {
          statusNode.textContent = `${file.name} contains a header but no data rows, or could not be parsed as comma-, tab-, or semicolon-delimited text.`;
        } else if (!recognized.length) {
          statusNode.textContent = `No supported identity column was found in ${file.name}. Use vendor_name, business_entity_name, domain, or registration_number; common headers such as Company and Website are also accepted.`;
        } else {
          runButton.disabled = false;
          statusNode.textContent = `${parsedRows.length} row(s) loaded locally from ${file.name}. Recognized identity field(s): ${recognized.join(", ")}.`;
        }
      } catch (error) {
        localInventoryRows = [];
        fileInput.value = "";
        statusNode.textContent = localFileReadMessage(file, error);
      }
      renderResolverResults();
    });

    runButton.addEventListener("click", async () => {
      if (!localInventoryRows.length) {
        statusNode.textContent = "Choose a CSV containing at least one vendor identity row before running resolution.";
        return;
      }
      runButton.disabled = true;
      statusNode.textContent = "Resolving locally against the current OpenVA vendor index...";
      try {
        const indexes = buildResolverIndexes();
        localMatchRows = await Promise.all(localInventoryRows.map((row, index) => matchInventoryRowHardened(row, index, indexes)));

        const liveToggle = document.getElementById("enable-live-resolution");
        const liveEnabled = Boolean(liveToggle && liveToggle.checked);
        const pending = [];
        localMatchRows.forEach((row) => {
          if (row.match_status === "matched") return;
          if (row.match_status === "ambiguous") {
            Object.assign(row, buildAmbiguousFields(row.match_note));
            return;
          }
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
          statusNode.textContent = `Checking ${pending.length} unmatched vendor(s) with a supplied domain against live public sources (bounded, opt-in, duplicate domains reused)...`;
          await resolveLivePending(pending, selectedLiveSourceTypes());
        }

        const matched = localMatchRows.filter((row) => row.match_status === "matched").length;
        const ambiguous = localMatchRows.filter((row) => row.match_status === "ambiguous").length;
        const unmatched = localMatchRows.length - matched - ambiguous;
        statusNode.textContent = `${localMatchRows.length} row(s) resolved locally: ${matched} matched, ${ambiguous} ambiguous, ${unmatched} no match. No inventory data was uploaded.${liveEnabled ? " Unmatched vendors with a supplied domain were checked against live public sources." : ""}`;
      } catch (error) {
        localMatchRows = [];
        statusNode.textContent = `Resolution failed before producing results: ${error.message}`;
      } finally {
        runButton.disabled = false;
      }
      renderResolverResults();
    });

    clearButton.addEventListener("click", () => {
      localInventoryRows = [];
      localMatchRows = [];
      fileInput.value = "";
      runButton.disabled = true;
      statusNode.textContent = "Local inventory data cleared from browser memory.";
      renderResolverResults();
    });
    csvButton.addEventListener("click", () => download("compiled-vendors.csv", resolverResultPackCsv(localInventoryRows, localMatchRows), "text/csv"));
    jsonButton.addEventListener("click", () => download("compiled-vendors.json", JSON.stringify(localMatchRows, null, 2) + "\n", "application/json"));
    renderResolverResults();
  }

  function replaceResolverControls() {
    ["inventory-file", "run-local-match", "clear-local-match", "download-matches-csv", "download-matches-json"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.replaceWith(node.cloneNode(true));
    });
  }

  function ensureResolverInstalled() {
    try {
      if (!catalogData || !catalogData.vendors) return false;
    } catch (_error) {
      return false;
    }
    const fileInput = document.getElementById("inventory-file");
    if (!fileInput) return false;
    if (fileInput.dataset.openvaResolverVersion === RESOLVER_VERSION) return true;
    replaceResolverControls();
    setupResolver();
    return true;
  }

  try { normalizeForMatch = normalizeName; } catch (_error) { window.normalizeForMatch = normalizeName; }
  try { normalizeDomain = normalizeDomainValue; } catch (_error) { window.normalizeDomain = normalizeDomainValue; }
  try { parseCsv = parseInventoryCsv; } catch (_error) { window.parseCsv = parseInventoryCsv; }
  try { buildLocalMatchIndexes = buildResolverIndexes; } catch (_error) { window.buildLocalMatchIndexes = buildResolverIndexes; }
  try { matchInventoryRow = matchInventoryRowHardened; } catch (_error) { window.matchInventoryRow = matchInventoryRowHardened; }
  try { renderLocalMatcher = renderResolverResults; } catch (_error) { window.renderLocalMatcher = renderResolverResults; }
  try { resultPackCsv = resolverResultPackCsv; } catch (_error) { window.resultPackCsv = resolverResultPackCsv; }
  try { setupLocalMatcher = setupResolver; } catch (_error) { window.setupLocalMatcher = setupResolver; }

  const THEMES = ["system", "light", "dark"];
  const LABELS = { system: "System", light: "Day", dark: "Night" };
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

  function storedTheme() {
    const value = localStorage.getItem("openva-theme") || "system";
    return THEMES.includes(value) ? value : "system";
  }

  function applyTheme(value) {
    if (value === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = value;
    const button = qs("[data-theme-toggle]");
    if (button) button.textContent = `Mode: ${LABELS[value]}`;
  }

  function installThemeToggle() {
    const nav = qs(".site-header nav");
    if (!nav || qs("[data-theme-toggle]")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "theme-toggle";
    button.dataset.themeToggle = "true";
    button.addEventListener("click", () => {
      const next = THEMES[(THEMES.indexOf(storedTheme()) + 1) % THEMES.length];
      localStorage.setItem("openva-theme", next);
      applyTheme(next);
    });
    nav.appendChild(button);
    applyTheme(storedTheme());
  }

  function installCatalogFilterStyles() {
    if (qs("#catalog-filter-polish-styles")) return;
    const style = document.createElement("style");
    style.id = "catalog-filter-polish-styles";
    style.textContent = `
      #catalog-filters.catalog-filter-console { display: grid; grid-template-columns: minmax(280px, 2fr) repeat(4, minmax(145px, 1fr)); gap: .85rem; align-items: stretch; padding: 1rem; border-radius: 22px; background: linear-gradient(135deg, var(--product-surface), var(--product-surface-soft)); }
      #catalog-filters.catalog-filter-console label { display: grid; gap: .45rem; min-width: 0; padding: .72rem; border: 1px solid var(--product-border); border-radius: 16px; background: var(--product-surface); color: var(--product-ink); box-shadow: var(--product-shadow-soft); }
      #catalog-filters.catalog-filter-console label:focus-within { border-color: var(--product-primary); box-shadow: var(--product-focus), var(--product-shadow-soft); }
      #catalog-filters.catalog-filter-console .filter-label-text { color: var(--product-muted); font-size: .72rem; font-weight: 800; letter-spacing: .075em; line-height: 1; text-transform: uppercase; }
      #catalog-filters.catalog-filter-console .filter-label-hint { color: var(--product-muted); font-size: .78rem; line-height: 1.3; }
      #catalog-filters.catalog-filter-console input, #catalog-filters.catalog-filter-console select { width: 100%; min-height: 2.85rem; margin: 0; border: 1px solid transparent; border-radius: 12px; background: var(--product-bg-soft); color: var(--product-ink); font-size: .96rem; }
      #catalog-filters.catalog-filter-console input:focus, #catalog-filters.catalog-filter-console select:focus { border-color: var(--product-primary); background: var(--product-surface); box-shadow: none; outline: none; }
      #catalog-filters.catalog-filter-console .catalog-search-filter { padding: .85rem; border-color: rgba(29,78,216,.24); }
      #catalog-filters.catalog-filter-console .catalog-search-filter input { min-height: 3.15rem; font-size: 1.05rem; }
      @media (max-width: 980px) { #catalog-filters.catalog-filter-console { grid-template-columns: repeat(2, minmax(0,1fr)); } #catalog-filters.catalog-filter-console .catalog-search-filter { grid-column: 1 / -1; } }
      @media (max-width: 620px) { #catalog-filters.catalog-filter-console { grid-template-columns: 1fr; padding: .75rem; } }
    `;
    document.head.appendChild(style);
  }

  function polishCatalogFilters() {
    const form = qs("#catalog-filters");
    if (!form || form.dataset.catalogFilterPolished) return;
    installCatalogFilterStyles();
    form.classList.add("catalog-filter-console");
    qsa("label", form).forEach((label, index) => {
      const control = qs("input, select", label);
      if (!control) return;
      const rawLabel = [...label.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent.trim()).find(Boolean) || "Filter";
      const title = document.createElement("span");
      title.className = "filter-label-text";
      title.textContent = rawLabel === "Search public vendors" ? "Vendor search" : rawLabel;
      label.textContent = "";
      label.append(title, control);
      if (index === 0) {
        label.classList.add("catalog-search-filter");
        control.setAttribute("placeholder", "Search by vendor, legal name, or domain");
        const helper = document.createElement("span");
        helper.className = "filter-label-hint";
        helper.textContent = "Name, legal entity, or domain";
        label.append(helper);
      }
    });
    form.dataset.catalogFilterPolished = "true";
  }

  function installSponsorLink() {
    const links = qs("footer .footer-links");
    if (!links || qs("[data-openva-sponsor]", links)) return;
    const sponsor = document.createElement("a");
    sponsor.href = "https://github.com/sponsors/thedanieltan";
    sponsor.textContent = "Support OpenVA";
    sponsor.title = "Voluntary sponsorship helps fund catalog growth, verification, infrastructure, and maintenance.";
    sponsor.dataset.openvaSponsor = "true";
    links.appendChild(sponsor);
  }

  function installWhenReady() {
    if (ensureResolverInstalled()) return;
    window.setTimeout(installWhenReady, 50);
  }

  applyTheme(storedTheme());
  window.addEventListener("DOMContentLoaded", () => {
    installThemeToggle();
    polishCatalogFilters();
    installSponsorLink();
    installWhenReady();
  });
})();
