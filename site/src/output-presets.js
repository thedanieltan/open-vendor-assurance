const HUMAN_EXPORT_PRESETS = {
  source_urls: {
    label: "Source URLs",
    columns: [
      "openva_match",
      "openva_vendor_name",
      "openva_domain",
      "dpa_url",
      "privacy_notice_url",
      "subprocessors_url",
      "security_page_url",
      "trust_center_url",
      "status_page_url",
      "openva_notes",
    ],
  },
  privacy_dpa: {
    label: "Privacy / DPA Review",
    columns: [
      "openva_match",
      "openva_vendor_name",
      "openva_domain",
      "dpa_url",
      "privacy_notice_url",
      "subprocessors_url",
      "trust_center_url",
      "openva_notes",
    ],
  },
  security_review: {
    label: "Security Review",
    columns: [
      "openva_match",
      "openva_vendor_name",
      "openva_domain",
      "security_page_url",
      "trust_center_url",
      "status_page_url",
      "openva_notes",
    ],
  },
  procurement_quick_check: {
    label: "Procurement Quick Check",
    columns: [
      "openva_match",
      "openva_vendor_name",
      "openva_domain",
      "trust_center_url",
      "privacy_notice_url",
      "security_page_url",
      "openva_notes",
    ],
  },
  minimal_match_only: {
    label: "Minimal Match Only",
    columns: [
      "openva_match",
      "openva_vendor_name",
      "openva_domain",
      "openva_notes",
    ],
  },
  full_human_export: {
    label: "Full Human Export",
    columns: [
      "openva_match",
      "openva_vendor_id",
      "openva_vendor_name",
      "openva_domain",
      "openva_match_basis",
      "dpa_url",
      "privacy_notice_url",
      "subprocessors_url",
      "security_page_url",
      "trust_center_url",
      "status_page_url",
      "openva_notes",
    ],
  },
};

function selectedHumanExportPreset() {
  const selector = document.getElementById("human-export-preset");
  return HUMAN_EXPORT_PRESETS[selector && selector.value] || HUMAN_EXPORT_PRESETS.source_urls;
}

function injectHumanExportPresetSelector() {
  if (document.getElementById("human-export-preset")) return;
  const downloadButton = document.getElementById("download-matches-csv");
  if (!downloadButton || !downloadButton.parentElement) return;

  const wrapper = document.createElement("label");
  wrapper.className = "export-preset-control";
  wrapper.innerHTML = `
    Export preset
    <select id="human-export-preset" aria-label="Human CSV export preset">
      ${Object.entries(HUMAN_EXPORT_PRESETS).map(([value, preset]) => `<option value="${html(value)}">${html(preset.label)}</option>`).join("")}
    </select>
  `;
  downloadButton.parentElement.insertBefore(wrapper, downloadButton);
}

function sourceUrlMap(summary) {
  const urls = new Map();
  (summary.sources || []).forEach((source) => {
    const rawType = source.source_type;
    const sourceType = rawType === "subprocessors_list" ? "subprocessors" : rawType;
    if (source.source_url && !urls.has(sourceType)) urls.set(sourceType, source.source_url);
  });
  return urls;
}

function humanMatchRow(row, inputIndex, vendor, matchBasis, summary = null) {
  const matched = Boolean(vendor);
  const urls = summary ? sourceUrlMap(summary) : new Map();
  const inputVendorName = row.vendor_name || row.business_entity_name || "";
  return {
    input_index: inputIndex,
    input_vendor_name: inputVendorName,
    input_domain: row.domain || "",
    openva_match: matched ? "match" : "no_match",
    openva_vendor_id: matched ? vendor.vendor_id : "",
    openva_vendor_name: matched ? vendor.display_name : "",
    openva_domain: matched ? officialDomain(vendor) || "" : "",
    openva_match_basis: matched ? matchBasis : "",
    dpa_url: matched ? urls.get("dpa") || "" : "",
    privacy_notice_url: matched ? urls.get("privacy_notice") || "" : "",
    subprocessors_url: matched ? urls.get("subprocessors") || "" : "",
    security_page_url: matched ? urls.get("security_page") || "" : "",
    trust_center_url: matched ? urls.get("trust_center") || "" : "",
    status_page_url: matched ? urls.get("status_page") || "" : "",
    openva_notes: matched ? `Matched by ${matchBasis}.` : "No indexed OpenVA match.",
  };
}

matchInventoryRow = async function matchInventoryRowWithHumanPresets(row, inputIndex, indexes) {
  const domain = normalizeDomain(row.domain || "");
  const vendorName = normalizeForMatch(row.vendor_name || "");
  const businessName = normalizeForMatch(row.business_entity_name || "");
  let vendor = null;
  let matchBasis = "";

  if (domain && indexes.domainIndex.has(domain)) {
    vendor = indexes.domainIndex.get(domain);
    matchBasis = "indexed_domain";
  } else if (vendorName && indexes.nameIndex.has(vendorName)) {
    vendor = indexes.nameIndex.get(vendorName);
    matchBasis = "indexed_vendor_name";
  } else if (businessName && indexes.nameIndex.has(businessName)) {
    vendor = indexes.nameIndex.get(businessName);
    matchBasis = "indexed_business_entity_name";
  }

  if (!vendor) return humanMatchRow(row, inputIndex, null, "");

  const summary = await vendorSourceSummary(vendor.vendor_id);
  return humanMatchRow(row, inputIndex, vendor, matchBasis, summary);
};

function flattenHumanPresetRows(inputRows, resultRows) {
  const preset = selectedHumanExportPreset();
  return resultRows.map((result, index) => {
    const row = { ...(inputRows[index] || {}) };
    preset.columns.forEach((column) => {
      row[column] = result[column] || "";
    });
    return row;
  });
}

resultPackCsv = function humanPresetResultPackCsv(inputRows, resultRows) {
  const inputColumns = [];
  inputRows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!inputColumns.includes(key)) inputColumns.push(key);
    });
  });
  const presetColumns = selectedHumanExportPreset().columns;
  return serializeCsv(flattenHumanPresetRows(inputRows, resultRows), [...inputColumns, ...presetColumns]);
};

const originalRenderLocalMatcher = renderLocalMatcher;
renderLocalMatcher = function renderLocalMatcherWithHumanPresets() {
  const total = localMatchRows.length;
  const matched = localMatchRows.filter((row) => row.openva_match === "match").length;
  const unmatched = total - matched;
  const preset = selectedHumanExportPreset();

  document.getElementById("match-summary").innerHTML = [
    ["Rows processed", total],
    ["Matched rows", matched],
    ["Unmatched rows", unmatched],
    ["Export preset", preset.label],
    ["Processing boundary", "browser-local; not uploaded to OpenVA"],
  ].map(([label, value]) => `<article><strong>${html(label)}</strong><p>${html(value)}</p></article>`).join("");

  document.getElementById("match-preview").innerHTML = localMatchRows.length
    ? `<table><thead><tr><th>Input vendor</th><th>OpenVA match</th><th>Matched vendor</th><th>Domain</th><th>Source URLs</th><th>Notes</th></tr></thead><tbody>${
        localMatchRows.slice(0, 20).map((row) => `
          <tr>
            <td>${html(row.input_vendor_name || row.input_domain || "Unavailable")}</td>
            <td>${html(row.openva_match || "no_match")}</td>
            <td>${html(row.openva_vendor_name || "")}</td>
            <td>${html(row.openva_domain || "")}</td>
            <td>${html([row.dpa_url, row.privacy_notice_url, row.subprocessors_url, row.security_page_url, row.trust_center_url, row.status_page_url].filter(Boolean).join("; "))}</td>
            <td>${html(row.openva_notes || "")}</td>
          </tr>
        `).join("")
      }</tbody></table><p>Preview shows up to 20 rows. CSV export preserves your original columns and appends the selected OpenVA preset columns.</p>`
    : "<p>No local match results yet.</p>";
};

const originalSetupLocalMatcher = setupLocalMatcher;
setupLocalMatcher = function setupLocalMatcherWithHumanPresets() {
  originalSetupLocalMatcher();
  injectHumanExportPresetSelector();
  const selector = document.getElementById("human-export-preset");
  if (selector) selector.addEventListener("change", renderLocalMatcher);
};
