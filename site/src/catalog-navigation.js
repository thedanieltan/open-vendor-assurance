(() => {
  const CATALOG_NAVIGATION_VERSION = "pagination-drawer-v1";
  const DESKTOP_PAGE_SIZE = 25;
  const COMPACT_PAGE_SIZE = 10;
  const COMPACT_QUERY = "(max-width: 1000px)";

  let currentPage = 1;
  let currentPageVendors = [];
  let activeVendorId = null;
  let pendingVendorId = null;
  let lastVendorTrigger = null;
  let restoringHistory = false;

  const baseSetupFilters = setupFilters;
  const baseRenderVendorDetail = renderVendorDetail;

  const style = document.createElement("style");
  style.textContent = `
    .catalog-page-status {
      margin: .8rem 0 0;
      color: var(--donor-muted, #64748b);
      font-size: .78rem;
    }
    .catalog-pagination {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: .75rem;
      margin-top: 1rem;
      padding-top: 1rem;
      border-top: 1px solid var(--donor-border, #d9e0e8);
    }
    .catalog-pagination__pages {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: .3rem;
    }
    .catalog-pagination button {
      min-width: 2.35rem !important;
      min-height: 2.2rem !important;
      padding: .45rem .65rem !important;
    }
    .catalog-pagination button[aria-current="page"] {
      border-color: var(--donor-primary, #172554) !important;
      background: var(--donor-primary, #172554) !important;
      color: var(--donor-primary-fg, #fff) !important;
    }
    .catalog-pagination__ellipsis {
      padding: 0 .2rem;
      color: var(--donor-muted, #64748b);
    }
    .vendor-card.is-active {
      border-color: var(--donor-brand, #3456a5) !important;
      box-shadow: 0 0 0 2px color-mix(in oklch, var(--donor-brand, #3456a5) 18%, transparent) !important;
    }
    .catalog-detail-close {
      display: none !important;
    }
    @media (max-width: 1000px) {
      body.catalog-drawer-open { overflow: hidden !important; }
      .catalog-layout #vendor-detail { display: none; }
      .catalog-layout #vendor-detail.catalog-detail-drawer {
        position: fixed !important;
        inset: 0 !important;
        z-index: 100 !important;
        display: block !important;
        width: 100% !important;
        max-width: none !important;
        max-height: none !important;
        overflow: auto !important;
        margin: 0 !important;
        border: 0 !important;
        border-radius: 0 !important;
        background: var(--donor-surface, #fff) !important;
        padding: 1rem !important;
        box-shadow: none !important;
      }
      .catalog-detail-close {
        position: sticky;
        top: 0;
        z-index: 2;
        display: inline-flex !important;
        margin: 0 0 1rem !important;
        background: var(--donor-surface, #fff) !important;
      }
      .catalog-pagination {
        align-items: stretch;
      }
      .catalog-pagination > button {
        flex: 1 1 8rem;
      }
      .catalog-pagination__pages {
        order: -1;
        width: 100%;
        justify-content: center;
      }
    }
  `;
  document.head.appendChild(style);

  function isCompact() {
    return typeof window.matchMedia === "function" && window.matchMedia(COMPACT_QUERY).matches;
  }

  function pageSize() {
    return isCompact() ? COMPACT_PAGE_SIZE : DESKTOP_PAGE_SIZE;
  }

  function positiveInteger(value, fallback = 1) {
    const parsed = Number.parseInt(value || "", 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  }

  function filterValue(id) {
    const node = document.getElementById(id);
    return node ? node.value.trim() : "";
  }

  function applyUrlState() {
    const params = new URLSearchParams(window.location.search);
    const values = {
      "search-input": params.get("q") || "",
      "source-type-filter": params.get("source") || "",
      "country-filter": params.get("country") || "",
      "category-filter": params.get("category") || "",
    };
    Object.entries(values).forEach(([id, value]) => {
      const node = document.getElementById(id);
      if (node) node.value = value;
    });
    currentPage = positiveInteger(params.get("page"), 1);
    activeVendorId = params.get("vendor") || null;
    pendingVendorId = activeVendorId;
  }

  function catalogUrl() {
    const params = new URLSearchParams();
    const query = filterValue("search-input");
    const source = filterValue("source-type-filter");
    const country = filterValue("country-filter");
    const category = filterValue("category-filter");
    if (query) params.set("q", query);
    if (source) params.set("source", source);
    if (country) params.set("country", country);
    if (category) params.set("category", category);
    if (currentPage > 1) params.set("page", String(currentPage));
    if (activeVendorId) params.set("vendor", activeVendorId);
    const queryString = params.toString();
    return `${window.location.pathname}${queryString ? `?${queryString}` : ""}#catalog`;
  }

  function syncUrl(mode = "replace") {
    if (restoringHistory) return;
    const next = catalogUrl();
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next === current) return;
    if (mode === "push") window.history.pushState({ openvaCatalog: true }, "", next);
    else window.history.replaceState({ openvaCatalog: true }, "", next);
  }

  function ensureCatalogControls() {
    const list = document.getElementById("vendor-list");
    if (!list) return;
    let status = document.getElementById("catalog-page-status");
    if (!status) {
      status = document.createElement("p");
      status.id = "catalog-page-status";
      status.className = "catalog-page-status";
      status.setAttribute("aria-live", "polite");
      list.insertAdjacentElement("beforebegin", status);
    }
    let pagination = document.getElementById("catalog-pagination");
    if (!pagination) {
      pagination = document.createElement("nav");
      pagination.id = "catalog-pagination";
      pagination.className = "catalog-pagination";
      pagination.setAttribute("aria-label", "Catalog pages");
      list.insertAdjacentElement("afterend", pagination);
    }
  }

  function pageNumbers(totalPages) {
    const values = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
    return [...values].filter((value) => value >= 1 && value <= totalPages).sort((a, b) => a - b);
  }

  function goToPage(page, mode = "push") {
    const totalPages = Math.max(1, Math.ceil(visibleVendors.length / pageSize()));
    const nextPage = Math.min(Math.max(1, page), totalPages);
    if (nextPage === currentPage) return;
    currentPage = nextPage;
    activeVendorId = null;
    pendingVendorId = null;
    closeDetail({ clearVendor: false, restoreFocus: false });
    syncUrl(mode);
    renderCatalog();
    const panel = document.querySelector(".catalog-list-panel");
    if (panel) panel.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function renderPagination() {
    ensureCatalogControls();
    const status = document.getElementById("catalog-page-status");
    const pagination = document.getElementById("catalog-pagination");
    const size = pageSize();
    const total = visibleVendors.length;
    const totalPages = Math.max(1, Math.ceil(total / size));
    const start = total ? (currentPage - 1) * size + 1 : 0;
    const end = Math.min(currentPage * size, total);
    status.textContent = total
      ? `Showing vendors ${start}–${end} of ${total}. Page ${currentPage} of ${totalPages}.`
      : "No vendors match the current filters.";

    if (totalPages <= 1) {
      pagination.innerHTML = "";
      pagination.hidden = true;
      return;
    }
    pagination.hidden = false;
    const pages = pageNumbers(totalPages);
    let previous = 0;
    const pageButtons = pages.map((page) => {
      const ellipsis = previous && page - previous > 1
        ? '<span class="catalog-pagination__ellipsis" aria-hidden="true">…</span>'
        : "";
      previous = page;
      return `${ellipsis}<button type="button" class="secondary" data-catalog-page="${page}" ${page === currentPage ? 'aria-current="page"' : ""} aria-label="Go to catalog page ${page}">${page}</button>`;
    }).join("");
    pagination.innerHTML = `
      <button type="button" class="secondary" data-catalog-page="${currentPage - 1}" ${currentPage === 1 ? "disabled" : ""}>Previous</button>
      <span class="catalog-pagination__pages">${pageButtons}</span>
      <button type="button" class="secondary" data-catalog-page="${currentPage + 1}" ${currentPage === totalPages ? "disabled" : ""}>Next</button>
    `;
    pagination.querySelectorAll("[data-catalog-page]").forEach((button) => {
      button.addEventListener("click", () => goToPage(positiveInteger(button.dataset.catalogPage, currentPage)));
    });
  }

  function renderVendorCards() {
    const list = document.getElementById("vendor-list");
    if (!visibleVendors.length) {
      currentPageVendors = [];
      list.innerHTML = '<article class="event-card"><h3>No vendors match these filters.</h3><p>Try clearing one filter or searching by vendor name, legal name, vendor ID, or official domain.</p></article>';
      return;
    }
    const size = pageSize();
    const totalPages = Math.max(1, Math.ceil(visibleVendors.length / size));
    currentPage = Math.min(Math.max(1, currentPage), totalPages);
    const start = (currentPage - 1) * size;
    currentPageVendors = visibleVendors.slice(start, start + size);
    list.innerHTML = currentPageVendors.map((vendor) => `
      <article class="vendor-card ${vendor.vendor_id === activeVendorId ? "is-active" : ""}" data-vendor-card="${html(vendor.vendor_id)}">
        <label><input type="checkbox" data-select-vendor="${html(vendor.vendor_id)}" ${selectedVendors.has(vendor.vendor_id) ? "checked" : ""}> Select public vendor metadata</label>
        <h4><button class="secondary" type="button" data-open-vendor="${html(vendor.vendor_id)}">${html(vendor.display_name)}</button></h4>
        <div class="meta-line">${html(vendor.legal_name)} · ${html(vendor.headquarters_country)} · ${html(vendor.catalog_status)}</div>
        <div class="pill-row">${(vendor.source_types || []).map((item) => `<span class="pill">${html(sourceTypeLabel(item))}</span>`).join("")}</div>
      </article>
    `).join("");
  }

  function bindVendorCards() {
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
        lastVendorTrigger = button;
        activeVendorId = button.dataset.openVendor;
        pendingVendorId = null;
        document.querySelectorAll("[data-vendor-card]").forEach((card) => {
          card.classList.toggle("is-active", card.dataset.vendorCard === activeVendorId);
        });
        syncUrl("push");
        await renderVendorDetail(activeVendorId);
      });
    });
  }

  function updateSelectionActions() {
    const pageButton = document.getElementById("select-visible");
    if (pageButton) pageButton.textContent = `Select this page (${currentPageVendors.length})`;
    const allButton = document.getElementById("select-all-filtered");
    if (allButton) {
      allButton.textContent = `Select all filtered (${visibleVendors.length})`;
      allButton.disabled = visibleVendors.length === 0;
    }
  }

  function renderPaginatedCatalog() {
    visibleVendors = catalogData.vendors.filter(vendorMatches);
    const totalPages = Math.max(1, Math.ceil(visibleVendors.length / pageSize()));
    currentPage = Math.min(Math.max(1, currentPage), totalPages);
    renderVendorCards();
    renderCatalogSummary();
    renderPagination();
    updateSelectionActions();
    bindVendorCards();

    if (pendingVendorId) {
      const vendorIndex = visibleVendors.findIndex((vendor) => vendor.vendor_id === pendingVendorId);
      if (vendorIndex >= 0) {
        const neededPage = Math.floor(vendorIndex / pageSize()) + 1;
        if (neededPage !== currentPage) {
          currentPage = neededPage;
          syncUrl("replace");
          renderPaginatedCatalog();
          return;
        }
        const vendorId = pendingVendorId;
        pendingVendorId = null;
        window.setTimeout(() => renderVendorDetail(vendorId), 0);
      } else {
        pendingVendorId = null;
        activeVendorId = null;
        syncUrl("replace");
      }
    }
  }

  function ensureDetailCloseButton() {
    const panel = document.getElementById("vendor-detail");
    if (!panel) return null;
    let button = panel.querySelector(".catalog-detail-close");
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "secondary catalog-detail-close";
      button.textContent = "Back to results";
      button.addEventListener("click", () => closeDetail());
      panel.prepend(button);
    }
    return button;
  }

  function openDetailDrawer() {
    if (!isCompact()) return;
    const panel = document.getElementById("vendor-detail");
    const closeButton = ensureDetailCloseButton();
    panel.classList.add("catalog-detail-drawer");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", "Vendor references");
    document.body.classList.add("catalog-drawer-open");
    window.setTimeout(() => closeButton && closeButton.focus(), 0);
  }

  function closeDetail({ clearVendor = true, restoreFocus = true } = {}) {
    const panel = document.getElementById("vendor-detail");
    if (!panel) return;
    panel.classList.remove("catalog-detail-drawer");
    panel.removeAttribute("role");
    panel.removeAttribute("aria-modal");
    panel.removeAttribute("aria-label");
    document.body.classList.remove("catalog-drawer-open");
    if (clearVendor) {
      activeVendorId = null;
      pendingVendorId = null;
      syncUrl("replace");
      document.querySelectorAll("[data-vendor-card]").forEach((card) => card.classList.remove("is-active"));
    }
    if (restoreFocus && lastVendorTrigger && document.contains(lastVendorTrigger)) lastVendorTrigger.focus();
  }

  async function renderVendorDetailWithDrawer(vendorId) {
    activeVendorId = vendorId;
    await baseRenderVendorDetail(vendorId);
    ensureDetailCloseButton();
    openDetailDrawer();
  }

  function installSelectionActions() {
    const pageButton = document.getElementById("select-visible");
    if (pageButton) {
      pageButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        currentPageVendors.forEach((vendor) => selectedVendors.add(vendor.vendor_id));
        renderPaginatedCatalog();
        renderExport();
      }, true);
    }
    const actions = document.querySelector(".catalog-actions");
    if (actions && !document.getElementById("select-all-filtered")) {
      const allButton = document.createElement("button");
      allButton.type = "button";
      allButton.id = "select-all-filtered";
      allButton.className = "secondary-button";
      allButton.addEventListener("click", () => {
        if (!visibleVendors.length) return;
        const accepted = window.confirm(`Select all ${visibleVendors.length} vendors matching the current filters?`);
        if (!accepted) return;
        visibleVendors.forEach((vendor) => selectedVendors.add(vendor.vendor_id));
        renderPaginatedCatalog();
        renderExport();
      });
      pageButton.insertAdjacentElement("afterend", allButton);
    }
  }

  function setupPaginatedFilters() {
    baseSetupFilters();
    applyUrlState();
    ensureCatalogControls();
    installSelectionActions();
    const form = document.getElementById("catalog-filters");
    if (form) {
      form.addEventListener("input", () => {
        currentPage = 1;
        activeVendorId = null;
        pendingVendorId = null;
        closeDetail({ clearVendor: false, restoreFocus: false });
        syncUrl("replace");
      }, true);
    }
  }

  try {
    setupFilters = setupPaginatedFilters;
    renderCatalog = renderPaginatedCatalog;
    renderVendorDetail = renderVendorDetailWithDrawer;
  } catch (_error) {
    window.setupFilters = setupPaginatedFilters;
    window.renderCatalog = renderPaginatedCatalog;
    window.renderVendorDetail = renderVendorDetailWithDrawer;
  }

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("catalog-drawer-open")) closeDetail();
  });

  window.addEventListener("resize", () => {
    const panel = document.getElementById("vendor-detail");
    if (!isCompact() && panel && panel.classList.contains("catalog-detail-drawer")) {
      closeDetail({ clearVendor: false, restoreFocus: false });
    }
    if (catalogData) renderPaginatedCatalog();
  });

  window.addEventListener("popstate", () => {
    if (!catalogData) return;
    restoringHistory = true;
    applyUrlState();
    restoringHistory = false;
    closeDetail({ clearVendor: false, restoreFocus: false });
    renderPaginatedCatalog();
  });

  window.OPENVA_CATALOG_NAVIGATION_VERSION = CATALOG_NAVIGATION_VERSION;
  window.OPENVA_CATALOG_PAGE_SIZES = Object.freeze({ desktop: DESKTOP_PAGE_SIZE, compact: COMPACT_PAGE_SIZE });
})();
