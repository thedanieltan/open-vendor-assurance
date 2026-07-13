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
