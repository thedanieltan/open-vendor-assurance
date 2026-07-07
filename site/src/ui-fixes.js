(() => {
  const THEMES = ["system", "light", "dark"];
  const LABELS = { system: "System", light: "Day", dark: "Night" };
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

  const HUMAN_EXPORT_PRESETS = {
    source_urls: {
      label: "Source URLs",
      columns: ["openva_match", "openva_vendor_name", "openva_domain", "dpa_url", "privacy_notice_url", "subprocessors_url", "security_page_url", "trust_center_url", "status_page_url", "openva_notes"],
    },
    privacy_dpa: {
      label: "Privacy / DPA Review",
      columns: ["openva_match", "openva_vendor_name", "openva_domain", "dpa_url", "privacy_notice_url", "subprocessors_url", "trust_center_url", "openva_notes"],
    },
    security_review: {
      label: "Security Review",
      columns: ["openva_match", "openva_vendor_name", "openva_domain", "security_page_url", "trust_center_url", "status_page_url", "openva_notes"],
    },
    procurement_quick_check: {
      label: "Procurement Quick Check",
      columns: ["openva_match", "openva_vendor_name", "openva_domain", "trust_center_url", "privacy_notice_url", "security_page_url", "openva_notes"],
    },
    minimal_match_only: {
      label: "Minimal Match Only",
      columns: ["openva_match", "openva_vendor_name", "openva_domain", "openva_notes"],
    },
    full_human_export: {
      label: "Full Human Export",
      columns: ["openva_match", "openva_vendor_id", "openva_vendor_name", "openva_domain", "openva_match_basis", "dpa_url", "privacy_notice_url", "subprocessors_url", "security_page_url", "trust_center_url", "status_page_url", "openva_notes"],
    },
  };

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
      .export-preset-control { display: inline-grid; gap: .35rem; align-items: center; font-weight: 700; }
      .export-preset-control select { min-height: 2.65rem; min-width: 15rem; border-radius: 12px; }
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

  function selectedHumanExportPreset() {
    const selector = qs("#human-export-preset");
    return HUMAN_EXPORT_PRESETS[selector && selector.value] || HUMAN_EXPORT_PRESETS.source_urls;
  }

  function installHumanExportPresetSelector() {
    if (qs("#human-export-preset")) return;
    const button = qs("#download-matches-csv");
    if (!button || !button.parentElement) return;
    const wrapper = document.createElement("label");
    wrapper.className = "export-preset-control";
    const select = document.createElement("select");
    select.id = "human-export-preset";
    select.setAttribute("aria-label", "Human CSV export preset");
    Object.entries(HUMAN_EXPORT_PRESETS).forEach(([value, preset]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = preset.label;
      select.appendChild(option);
    });
    wrapper.append("Export preset", select);
    button.parentElement.insertBefore(wrapper, button);
    select.addEventListener("change", () => {
      if (typeof renderLocalMatcher === "function") renderLocalMatcher();
    });
  }

  function sourceUrlMap(summary) {
    const urls = new Map();
    (summary.sources || []).forEach((source) => {
      const sourceType = source.source_type === "subprocessors_list" ? "subprocessors" : source.source_type;
      if (source.source_url && !urls.has(sourceType)) urls.set(sourceType, source.source_url);
    });
    return urls;
  }

  function humanMatchRow(row, inputIndex, vendor, matchBasis, summary = null) {
    const matched = Boolean(vendor);
    const urls = summary ? sourceUrlMap(summary) : new Map();
    return {
      input_index: inputIndex,
      input_vendor_name: row.vendor_name || row.business_entity_name || "",
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

  function installHumanPresetOverrides() {
    if (window.__openvaHumanPresetOverridesInstalled) return;
    window.__openvaHumanPresetOverridesInstalled = true;

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
      return humanMatchRow(row, inputIndex, vendor, matchBasis, await vendorSourceSummary(vendor.vendor_id));
    };

    resultPackCsv = function humanPresetResultPackCsv(inputRows, resultRows) {
      const inputColumns = [];
      inputRows.forEach((row) => {
        Object.keys(row).forEach((key) => {
          if (!inputColumns.includes(key)) inputColumns.push(key);
        });
      });
      const preset = selectedHumanExportPreset();
      const rows = resultRows.map((result, index) => {
        const row = { ...(inputRows[index] || {}) };
        preset.columns.forEach((column) => {
          row[column] = result[column] || "";
        });
        return row;
      });
      return serializeCsv(rows, [...inputColumns, ...preset.columns]);
    };

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

    const baseSetupLocalMatcher = setupLocalMatcher;
    setupLocalMatcher = function setupLocalMatcherWithHumanPresets() {
      baseSetupLocalMatcher();
      installHumanExportPresetSelector();
    };
  }

  installHumanPresetOverrides();
  applyTheme(storedTheme());
  window.addEventListener("DOMContentLoaded", () => {
    installThemeToggle();
    polishCatalogFilters();
    installHumanExportPresetSelector();
  });
})();
