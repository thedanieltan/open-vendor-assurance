(() => {
  const COUNTRY_NAMES = { SG: "Singapore", US: "United States", GB: "United Kingdom", UK: "United Kingdom", IE: "Ireland", DE: "Germany", FR: "France", NL: "Netherlands", CA: "Canada", AU: "Australia", IN: "India", JP: "Japan", KR: "South Korea", CN: "China", HK: "Hong Kong", TW: "Taiwan", MY: "Malaysia", ID: "Indonesia", TH: "Thailand", PH: "Philippines", VN: "Vietnam", EU: "European Union" };
  const THEMES = ["system", "light", "dark"];
  const LABELS = { system: "System", light: "Day", dark: "Night" };
  const ROUTES = new Set(["home", "catalog", "matcher", "export", "feed"]);
  let installedRoutes = false;

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
      #catalog-filters.catalog-filter-console {
        display: grid;
        grid-template-columns: minmax(280px, 2fr) repeat(4, minmax(145px, 1fr));
        gap: 0.85rem;
        align-items: stretch;
        padding: 1rem;
        border-radius: 22px;
        background:
          radial-gradient(circle at 100% 0%, rgba(59, 130, 246, 0.10), transparent 18rem),
          linear-gradient(135deg, var(--product-surface), var(--product-surface-soft));
      }

      #catalog-filters.catalog-filter-console label {
        display: grid;
        gap: 0.45rem;
        min-width: 0;
        padding: 0.72rem;
        border: 1px solid var(--product-border);
        border-radius: 16px;
        background: var(--product-surface);
        color: var(--product-ink);
        box-shadow: var(--product-shadow-soft);
      }

      #catalog-filters.catalog-filter-console label:focus-within {
        border-color: var(--product-primary);
        box-shadow: var(--product-focus), var(--product-shadow-soft);
      }

      #catalog-filters.catalog-filter-console .filter-label-text {
        color: var(--product-muted);
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.075em;
        line-height: 1;
        text-transform: uppercase;
      }

      #catalog-filters.catalog-filter-console .filter-label-hint {
        color: var(--product-muted);
        font-size: 0.78rem;
        line-height: 1.3;
      }

      #catalog-filters.catalog-filter-console input,
      #catalog-filters.catalog-filter-console select {
        width: 100%;
        min-height: 2.85rem;
        margin: 0;
        border: 1px solid transparent;
        border-radius: 12px;
        background: var(--product-bg-soft);
        color: var(--product-ink);
        font-size: 0.96rem;
      }

      #catalog-filters.catalog-filter-console input::placeholder {
        color: color-mix(in srgb, var(--product-muted) 76%, transparent);
      }

      #catalog-filters.catalog-filter-console input:focus,
      #catalog-filters.catalog-filter-console select:focus {
        border-color: var(--product-primary);
        background: var(--product-surface);
        box-shadow: none;
        outline: none;
      }

      #catalog-filters.catalog-filter-console .catalog-search-filter {
        padding: 0.85rem;
        border-color: rgba(29, 78, 216, 0.24);
        background:
          linear-gradient(135deg, color-mix(in srgb, var(--product-surface) 86%, var(--product-primary)), var(--product-surface));
      }

      #catalog-filters.catalog-filter-console .catalog-search-filter input {
        min-height: 3.15rem;
        font-size: 1.05rem;
      }

      @media (max-width: 980px) {
        #catalog-filters.catalog-filter-console {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        #catalog-filters.catalog-filter-console .catalog-search-filter {
          grid-column: 1 / -1;
        }
      }

      @media (max-width: 620px) {
        #catalog-filters.catalog-filter-console {
          grid-template-columns: 1fr;
          padding: 0.75rem;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function polishCatalogFilters() {
    installCatalogFilterStyles();
    const form = qs("#catalog-filters");
    if (!form || form.dataset.catalogFilterPolished) return;
    form.classList.add("catalog-filter-console");
    form.setAttribute("aria-label", "Catalog search and filters");

    qsa("label", form).forEach((label, index) => {
      const control = qs("input, select", label);
      if (!control) return;
      const rawLabel = [...label.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent.trim())
        .find(Boolean) || control.getAttribute("aria-label") || "Filter";
      const labelText = rawLabel === "Search public vendors" ? "Vendor search" : rawLabel;
      const hint = index === 0 ? "Name, legal entity, or domain" : "Refine visible records";
      label.textContent = "";
      const title = document.createElement("span");
      title.className = "filter-label-text";
      title.textContent = labelText;
      const helper = document.createElement("span");
      helper.className = "filter-label-hint";
      helper.textContent = hint;
      label.append(title, control);
      if (index === 0) {
        label.classList.add("catalog-search-filter");
        control.setAttribute("placeholder", "Search by vendor, legal name, or domain");
        label.append(helper);
      }
    });

    form.dataset.catalogFilterPolished = "true";
  }

  function cleanUrl() {
    if (location.hash) history.replaceState(null, "", `${location.pathname}${location.search}`);
  }

  function routeName(control) {
    if (!control) return "";
    if (control.dataset.route) return control.dataset.route;
    const href = control.getAttribute("href") || "";
    return href.startsWith("#") ? href.slice(1) : "";
  }

  function selectedCounts() {
    return {
      vendors: qsa("[data-select-vendor]:checked").length,
      sources: qsa("[data-select-source]:checked").length,
    };
  }

  function showView(name) {
    const route = ROUTES.has(name) && name !== "export" ? name : "home";
    qsa(".view").forEach((view) => view.classList.add("hidden"));
    (qs(`#${route}-view`) || qs("#home-view"))?.classList.remove("hidden");
    qs("#export-view")?.classList.add("hidden");
    qsa("[data-route]").forEach((control) => {
      if (control.dataset.route === route && control.closest(".site-header")) control.setAttribute("aria-current", "page");
      else control.removeAttribute("aria-current");
    });
    if (route === "feed" && typeof window.renderFeed === "function") window.renderFeed();
    cleanUrl();
  }

  function ensureCatalogExportPanel() {
    let panel = qs("#catalog-export-panel");
    if (panel) return panel;
    const catalog = qs("#catalog-view");
    if (!catalog) return null;
    panel = document.createElement("section");
    panel.id = "catalog-export-panel";
    panel.className = "section-card catalog-export-panel hidden";
    panel.setAttribute("aria-live", "polite");
    panel.innerHTML = `
      <div class="section-heading-lite">
        <p class="eyebrow">Export workflow</p>
        <h3>Review selected public metadata</h3>
        <p>Export is part of the catalog workflow. Select vendors above, review the counts here, then download the public metadata you need.</p>
      </div>
      <div id="catalog-export-summary"></div>
      <div class="actions">
        <button type="button" class="button" data-export-download="download-vendors-csv">Download selected vendors CSV</button>
        <button type="button" class="button secondary-button" data-export-download="download-sources-csv">Download selected sources CSV</button>
        <button type="button" class="button secondary-button" data-export-download="download-json">Download selected records JSON</button>
        <button type="button" class="button secondary-button" data-route="catalog">Continue reviewing catalog</button>
      </div>`;
    catalog.appendChild(panel);
    qsa("[data-export-download]", panel).forEach((button) => {
      button.addEventListener("click", () => qs(`#${button.dataset.exportDownload}`)?.click());
    });
    return panel;
  }

  function renderCatalogExportPanel() {
    const panel = ensureCatalogExportPanel();
    const target = qs("#catalog-export-summary");
    if (!panel || !target) return;
    const counts = selectedCounts();
    const hasSelection = counts.vendors > 0 || counts.sources > 0;
    target.innerHTML = hasSelection ? `
      <div class="summary-strip">
        <span><strong>${counts.vendors}</strong><small>selected public vendors</small></span>
        <span><strong>${counts.sources}</strong><small>selected reviewed sources</small></span>
      </div>
      <div class="detail-panel">
        <p class="eyebrow">Ready to export</p>
        <h3>Your selected public metadata is ready.</h3>
        <p>Use the download buttons below. This export contains public OpenVA metadata only and does not determine vendor suitability, compliance, risk, or procurement approval.</p>
      </div>` : `
      <div class="detail-panel empty-detail-state">
        <p class="eyebrow">No records selected</p>
        <h3>Select vendors before exporting</h3>
        <p>Use the checkboxes in the catalog list or source records. Export controls are available after you select at least one vendor or source.</p>
      </div>`;
  }

  function openExportWorkflow() {
    showView("catalog");
    const panel = ensureCatalogExportPanel();
    renderCatalogExportPanel();
    panel?.classList.remove("hidden");
    panel?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function activateRoute(name) {
    if (name === "export") openExportWorkflow();
    else {
      showView(name);
      if (name !== "catalog") qs("#catalog-export-panel")?.classList.add("hidden");
      qs("#main-content")?.scrollIntoView({ block: "start" });
    }
  }

  function normalizeRouteControls() {
    qsa('a[href="#home"], a[href="#catalog"], a[href="#matcher"], a[href="#export"], a[href="#feed"]').forEach((link) => {
      link.dataset.route = routeName(link);
      link.removeAttribute("href");
      link.setAttribute("role", "button");
      link.setAttribute("tabindex", "0");
    });
    qsa('.site-header [data-route="export"]').forEach((control) => {
      control.hidden = true;
      control.setAttribute("aria-hidden", "true");
    });
  }

  function interceptRoute(event) {
    const control = event.target.closest('[data-route], a[href^="#"]');
    const name = routeName(control);
    if (!ROUTES.has(name)) return;
    event.preventDefault();
    event.stopPropagation();
    activateRoute(name);
    cleanUrl();
  }

  function installRoutes() {
    normalizeRouteControls();
    ensureCatalogExportPanel();
    if (installedRoutes) return;
    document.addEventListener("click", interceptRoute, true);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") interceptRoute(event);
    }, true);
    window.addEventListener("hashchange", () => {
      const name = (location.hash || "").slice(1);
      if (ROUTES.has(name)) activateRoute(name);
    }, true);
    installedRoutes = true;
  }

  function countryLabel(value) {
    if (!value || value === "Unavailable") return value;
    const code = String(value).trim().toUpperCase();
    return COUNTRY_NAMES[code] && COUNTRY_NAMES[code] !== code ? `${COUNTRY_NAMES[code]} (${code})` : value;
  }

  function improveCountryLabels() {
    qsa("#country-filter option").forEach((option) => {
      if (!option.value || option.dataset.countryExpanded) return;
      option.textContent = countryLabel(option.value);
      option.dataset.countryExpanded = "true";
    });
    qsa(".vendor-card .meta-line").forEach((node) => {
      if (node.dataset.countryExpanded) return;
      const parts = node.textContent.split(" · ");
      if (parts.length >= 3) {
        parts[1] = countryLabel(parts[1]);
        node.textContent = parts.join(" · ");
        node.dataset.countryExpanded = "true";
      }
    });
    qsa("#vendor-detail p").forEach((node) => {
      if (node.dataset.countryExpanded) return;
      const prefix = "Headquarters country: ";
      if (node.textContent.startsWith(prefix)) {
        node.textContent = `${prefix}${countryLabel(node.textContent.slice(prefix.length))}`;
        node.dataset.countryExpanded = "true";
      }
    });
  }

  function compactSnapshotBlocks() {
    qsa("[data-snapshot-disclosure], #vendor-detail .snapshot-box").forEach((node) => {
      if (node.dataset.compacted || !node.textContent.includes("Reviewed catalog snapshot:")) return;
      const raw = node.textContent.replace(/\s+/g, " ").trim();
      const snapshot = raw.match(/Reviewed catalog snapshot: ([^ ]+)/)?.[1] || "current snapshot";
      const date = raw.match(/Catalog date: ([^ ]+)/)?.[1] || "Unavailable";
      const link = qs("a", node)?.getAttribute("href") || "https://github.com/thedanieltan/open-vendor-assurance/releases";
      node.innerHTML = `<details class="catalog-version"><summary>Catalog snapshot: ${date}</summary><p>This identifies the reproducible public metadata snapshot used by the page. Most users can ignore it unless they need auditability.</p><p>Snapshot: <code>${snapshot}</code></p><p><a href="${link}">GitHub Releases</a></p></details>`;
      node.dataset.compacted = "true";
    });
  }

  function improveHomeStats() {
    const homeStats = qs("#home-stats");
    if (!homeStats || homeStats.dataset.publicLabelsApplied) return;
    qsa("article", homeStats).forEach((card) => {
      const label = qs("strong", card)?.textContent.trim();
      if (["Observation feed", "Site data contract", "Boundary"].includes(label)) card.remove();
      if (label === "Snapshot date") qs("strong", card).textContent = "Catalog date";
    });
    homeStats.dataset.publicLabelsApplied = "true";
  }

  function improveMatcherEmptyState() {
    const preview = qs("#match-preview");
    if (!preview || preview.dataset.emptyStateApplied || !preview.textContent.includes("No local match results yet")) return;
    preview.classList.add("empty-detail-state");
    preview.innerHTML = `<p class="eyebrow">CSV match preview</p><h3>Upload a CSV to preview matches</h3><p>After you run the local matcher, this panel will show matched vendor names, match method, confidence, and available public source types. Your CSV stays in browser memory and is not uploaded to OpenVA.</p>`;
    preview.dataset.emptyStateApplied = "true";
  }

  function softenGeneratedTechnicalCopy() {
    qsa("#vendor-detail li, #feed-meta p, #feed-list p").forEach((node) => {
      if (node.dataset.copySoftened) return;
      node.innerHTML = node.innerHTML
        .replaceAll("advisory_boundary:", "boundary:")
        .replaceAll("non_advisory", "public metadata only")
        .replaceAll("catalog_tier:", "record type:")
        .replaceAll("review_state:", "review state:");
      node.dataset.copySoftened = "true";
    });
  }

  function refresh() {
    compactSnapshotBlocks();
    improveCountryLabels();
    polishCatalogFilters();
    improveHomeStats();
    improveMatcherEmptyState();
    softenGeneratedTechnicalCopy();
    installRoutes();
    renderCatalogExportPanel();
  }

  applyTheme(storedTheme());
  window.addEventListener("DOMContentLoaded", () => {
    const initialRoute = (location.hash || "").slice(1);
    installThemeToggle();
    refresh();
    if (ROUTES.has(initialRoute)) setTimeout(() => activateRoute(initialRoute), 350);
    else showView("home");
    cleanUrl();
    new MutationObserver(refresh).observe(document.body, { childList: true, subtree: true });
  });
})();
