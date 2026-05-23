(() => {
  const COUNTRY_NAMES = {
    SG: "Singapore",
    US: "United States",
    GB: "United Kingdom",
    UK: "United Kingdom",
    IE: "Ireland",
    DE: "Germany",
    FR: "France",
    NL: "Netherlands",
    CA: "Canada",
    AU: "Australia",
    IN: "India",
    JP: "Japan",
    KR: "South Korea",
    CN: "China",
    HK: "Hong Kong",
    TW: "Taiwan",
    MY: "Malaysia",
    ID: "Indonesia",
    TH: "Thailand",
    PH: "Philippines",
    VN: "Vietnam",
    EU: "European Union",
  };

  const THEMES = ["system", "light", "dark"];
  const LABELS = {
    system: "System",
    light: "Day",
    dark: "Night",
  };

  const APP_ROUTES = new Set(["home", "catalog", "matcher", "export", "feed"]);

  function storedTheme() {
    const value = localStorage.getItem("openva-theme") || "system";
    return THEMES.includes(value) ? value : "system";
  }

  function applyTheme(value) {
    if (value === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.dataset.theme = value;
    }
    const button = document.querySelector("[data-theme-toggle]");
    if (button) button.textContent = `Mode: ${LABELS[value]}`;
  }

  function installThemeToggle() {
    const nav = document.querySelector(".site-header nav");
    if (!nav || document.querySelector("[data-theme-toggle]")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "theme-toggle";
    button.dataset.themeToggle = "true";
    button.addEventListener("click", () => {
      const current = storedTheme();
      const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
      localStorage.setItem("openva-theme", next);
      applyTheme(next);
    });
    nav.appendChild(button);
    applyTheme(storedTheme());
  }

  function selectedDomCounts() {
    return {
      vendors: document.querySelectorAll("[data-select-vendor]:checked").length,
      sources: document.querySelectorAll("[data-select-source]:checked").length,
    };
  }

  function renderExportFallbackState(mode = "ready") {
    const summary = document.getElementById("selection-summary");
    if (!summary) return;
    const counts = selectedDomCounts();
    const hasSelection = counts.vendors > 0 || counts.sources > 0;

    if (mode === "loading") {
      summary.innerHTML = `
        <div class="summary-strip">
          <span><strong>${counts.vendors}</strong><small>selected public vendors</small></span>
          <span><strong>${counts.sources}</strong><small>selected reviewed sources</small></span>
        </div>
        <div class="detail-panel empty-detail-state">
          <p class="eyebrow">Preparing export</p>
          <h3>Building your selected public metadata export...</h3>
          <p>OpenVA is loading selected records. The download buttons below will use your current selection.</p>
        </div>
      `;
      return;
    }

    if (hasSelection) {
      summary.innerHTML = `
        <div class="summary-strip">
          <span><strong>${counts.vendors}</strong><small>selected public vendors</small></span>
          <span><strong>${counts.sources}</strong><small>selected reviewed sources</small></span>
        </div>
        <div class="detail-panel">
          <p class="eyebrow">Ready to export</p>
          <h3>Your selected records are ready.</h3>
          <p>Use the download buttons below to export selected vendors, reviewed sources, or the combined JSON package.</p>
        </div>
      `;
      return;
    }

    summary.innerHTML = `
      <div class="detail-panel empty-detail-state">
        <p class="eyebrow">No records selected</p>
        <h3>Select vendors before exporting</h3>
        <p>Go back to the catalog, select one or more vendors, then return here to download public metadata.</p>
        <button type="button" class="button" data-route="catalog">Back to catalog</button>
      </div>
    `;
  }

  async function renderExportRouteState() {
    renderExportFallbackState("loading");
    if (typeof window.renderExport !== "function") {
      renderExportFallbackState("ready");
      return;
    }

    try {
      await window.renderExport();
      const summary = document.getElementById("selection-summary");
      if (!summary || !summary.textContent.trim()) renderExportFallbackState("ready");
    } catch (error) {
      console.warn("OpenVA export render failed", error);
      renderExportFallbackState("ready");
    }
  }

  function setInAppView(routeName) {
    const name = APP_ROUTES.has(routeName) ? routeName : "home";
    document.querySelectorAll(".view").forEach((view) => view.classList.add("hidden"));
    const current = document.getElementById(`${name}-view`) || document.getElementById("home-view");
    current.classList.remove("hidden");

    document.querySelectorAll("[data-route]").forEach((control) => {
      if (control.dataset.route === name && control.closest(".site-header")) {
        control.setAttribute("aria-current", "page");
      } else {
        control.removeAttribute("aria-current");
      }
    });

    if (name === "export") renderExportRouteState();
    if (name === "feed" && typeof window.renderFeed === "function") window.renderFeed();
  }

  function normalizeAppRouteControls() {
    document.querySelectorAll('a[href="#home"], a[href="#catalog"], a[href="#matcher"], a[href="#export"], a[href="#feed"]').forEach((link) => {
      const routeName = link.getAttribute("href").slice(1);
      link.dataset.route = routeName;
      link.removeAttribute("href");
      link.setAttribute("role", "button");
      link.setAttribute("tabindex", "0");
    });
  }

  function installInAppRouteControls() {
    normalizeAppRouteControls();
    document.querySelectorAll("[data-route]").forEach((control) => {
      if (control.dataset.inAppRouteInstalled) return;
      control.dataset.inAppRouteInstalled = "true";
      control.addEventListener("click", (event) => {
        const routeName = control.dataset.route;
        if (!APP_ROUTES.has(routeName)) return;
        event.preventDefault();
        setInAppView(routeName);
        document.getElementById("main-content")?.scrollIntoView({ block: "start" });
      });
      control.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const routeName = control.dataset.route;
        if (!APP_ROUTES.has(routeName)) return;
        event.preventDefault();
        setInAppView(routeName);
        document.getElementById("main-content")?.scrollIntoView({ block: "start" });
      });
    });
  }

  function countryLabel(value) {
    if (!value || value === "Unavailable") return value;
    const code = String(value).trim().toUpperCase();
    const name = COUNTRY_NAMES[code];
    return name && name !== code ? `${name} (${code})` : value;
  }

  function improveCountryLabels() {
    document.querySelectorAll("#country-filter option").forEach((option) => {
      if (!option.value || option.dataset.countryExpanded) return;
      option.textContent = countryLabel(option.value);
      option.dataset.countryExpanded = "true";
    });

    document.querySelectorAll(".vendor-card .meta-line").forEach((node) => {
      if (node.dataset.countryExpanded) return;
      const parts = node.textContent.split(" · ");
      if (parts.length >= 3) {
        parts[1] = countryLabel(parts[1]);
        node.textContent = parts.join(" · ");
        node.dataset.countryExpanded = "true";
      }
    });

    document.querySelectorAll("#vendor-detail p").forEach((node) => {
      if (node.dataset.countryExpanded) return;
      const prefix = "Headquarters country: ";
      if (node.textContent.startsWith(prefix)) {
        node.textContent = `${prefix}${countryLabel(node.textContent.slice(prefix.length))}`;
        node.dataset.countryExpanded = "true";
      }
    });
  }

  function compactSnapshotBlocks() {
    document.querySelectorAll("[data-snapshot-disclosure], #vendor-detail .snapshot-box").forEach((node) => {
      if (node.dataset.compacted || !node.textContent.includes("Reviewed catalog snapshot:")) return;
      const raw = node.textContent.replace(/\s+/g, " ").trim();
      const snapshot = raw.match(/Reviewed catalog snapshot: ([^ ]+)/)?.[1] || "current snapshot";
      const date = raw.match(/Catalog date: ([^ ]+)/)?.[1] || "Unavailable";
      const link = node.querySelector("a")?.getAttribute("href") || "https://github.com/thedanieltan/open-vendor-assurance/releases";
      node.innerHTML = `
        <details class="catalog-version">
          <summary>Catalog snapshot: ${date}</summary>
          <p>This identifies the reproducible public metadata snapshot used by the page. Most users can ignore it unless they need auditability.</p>
          <p>Snapshot: <code>${snapshot}</code></p>
          <p><a href="${link}">GitHub Releases</a></p>
        </details>
      `;
      node.dataset.compacted = "true";
    });
  }

  function improveHomeStats() {
    const homeStats = document.getElementById("home-stats");
    if (!homeStats || homeStats.dataset.publicLabelsApplied) return;
    homeStats.querySelectorAll("article").forEach((card) => {
      const label = card.querySelector("strong")?.textContent.trim();
      const value = card.querySelector("p");
      if (label === "Observation feed") card.remove();
      if (label === "Site data contract") card.remove();
      if (label === "Boundary") card.remove();
      if (label === "Snapshot date" && value) card.querySelector("strong").textContent = "Catalog date";
    });
    homeStats.dataset.publicLabelsApplied = "true";
  }

  function improveMatcherEmptyState() {
    const preview = document.getElementById("match-preview");
    if (!preview || preview.dataset.emptyStateApplied || !preview.textContent.includes("No local match results yet")) return;
    preview.classList.add("empty-detail-state");
    preview.innerHTML = `
      <p class="eyebrow">CSV match preview</p>
      <h3>Upload a CSV to preview matches</h3>
      <p>After you run the local matcher, this panel will show matched vendor names, match method, confidence, and available public source types. Your CSV stays in browser memory and is not uploaded to OpenVA.</p>
    `;
    preview.dataset.emptyStateApplied = "true";
  }

  function softenGeneratedTechnicalCopy() {
    document.querySelectorAll("#vendor-detail li, #feed-meta p, #feed-list p").forEach((node) => {
      if (node.dataset.copySoftened) return;
      node.innerHTML = node.innerHTML
        .replaceAll("advisory_boundary:", "boundary:")
        .replaceAll("non_advisory", "public metadata only")
        .replaceAll("catalog_tier:", "record type:")
        .replaceAll("review_state:", "review state:");
      node.dataset.copySoftened = "true";
    });
  }

  function refreshUiFixes() {
    compactSnapshotBlocks();
    improveCountryLabels();
    improveHomeStats();
    improveMatcherEmptyState();
    softenGeneratedTechnicalCopy();
    installInAppRouteControls();
  }

  applyTheme(storedTheme());
  window.addEventListener("DOMContentLoaded", () => {
    installThemeToggle();
    refreshUiFixes();
    setInAppView("home");
    const observer = new MutationObserver(refreshUiFixes);
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
