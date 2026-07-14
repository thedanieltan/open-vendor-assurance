(() => {
  const CATALOG_CARD_INTERACTIONS_VERSION = "explicit-view-links-v2";
  const baseRenderCatalog = renderCatalog;
  const baseRenderVendorDetail = renderVendorDetail;

  const style = document.createElement("style");
  style.id = "openva-catalog-card-interactions";
  style.textContent = `
    html,
    body {
      width: 100%;
      max-width: 100%;
      overflow-x: clip !important;
    }
    .site-header,
    .site-header > *,
    .site-header nav,
    main,
    .view,
    .catalog-workspace-room,
    .catalog-layout,
    .catalog-layout > *,
    .catalog-list-panel,
    .vendor-list,
    .vendor-card,
    #vendor-detail {
      min-width: 0 !important;
      max-width: 100%;
    }
    .vendor-card {
      position: relative;
      cursor: pointer;
      overflow: hidden;
    }
    .vendor-card > label {
      display: none !important;
    }
    .vendor-card > :not(.vendor-card__select-hit) {
      position: relative;
      z-index: 2;
      pointer-events: none;
    }
    .vendor-card h4 {
      display: grid !important;
      grid-template-columns: minmax(0, 1fr) auto !important;
      align-items: flex-start !important;
      gap: .75rem !important;
    }
    .vendor-card__name {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .vendor-card__header-actions {
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      gap: .45rem;
      pointer-events: none;
    }
    .vendor-card__view-links {
      position: relative !important;
      z-index: 4 !important;
      display: inline-flex !important;
      align-items: center;
      justify-content: center;
      min-width: 0 !important;
      min-height: 2.55rem !important;
      max-width: none !important;
      padding: .48rem .72rem !important;
      white-space: nowrap;
      pointer-events: auto !important;
    }
    .vendor-card__select-hit {
      position: absolute;
      inset: 0;
      z-index: 1;
      width: 100%;
      height: 100%;
      margin: 0;
      border: 0;
      border-radius: inherit;
      background: transparent;
      color: transparent;
      cursor: pointer;
    }
    .vendor-card .meta-line,
    .vendor-card .pill-row,
    .vendor-card__selection-state {
      pointer-events: none;
    }
    .vendor-card__selection-state {
      flex: 0 0 auto;
      border: 1px solid var(--donor-border, #d9e0e8);
      border-radius: 999px;
      background: var(--donor-surface-muted, #f4f6f9);
      color: var(--donor-muted, #64748b);
      padding: .16rem .48rem;
      font-size: .65rem;
      font-weight: 600;
      line-height: 1.2;
      white-space: nowrap;
    }
    .vendor-card.is-selected {
      border-color: var(--donor-brand, #3456a5) !important;
      background: color-mix(in oklch, var(--donor-brand, #3456a5) 5%, var(--donor-surface, #fff)) !important;
    }
    .vendor-card.is-selected .vendor-card__selection-state {
      border-color: color-mix(in oklch, var(--donor-brand, #3456a5) 42%, var(--donor-border, #d9e0e8));
      background: color-mix(in oklch, var(--donor-brand, #3456a5) 12%, var(--donor-surface, #fff));
      color: var(--donor-brand, #3456a5);
    }
    .vendor-card:has(.vendor-card__select-hit:focus-visible),
    .vendor-card:has(.vendor-card__view-links:focus-visible) {
      outline: 2px solid var(--donor-ring, #4667b2) !important;
      outline-offset: 2px !important;
    }
    .vendor-reference-list {
      display: grid;
      gap: .7rem;
      width: 100%;
      min-width: 0;
    }
    .vendor-reference-card {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: .35rem .75rem;
      min-width: 0;
      border: 1px solid var(--donor-border, #d9e0e8);
      border-radius: var(--donor-radius-lg, .75rem);
      background: var(--donor-surface, #fff);
      padding: .85rem;
    }
    .vendor-reference-card__type {
      grid-column: 1;
      margin: 0;
      color: var(--donor-muted, #64748b) !important;
      font-size: .68rem;
      font-weight: 600;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .vendor-reference-card__link {
      grid-column: 1;
      min-width: 0;
      overflow-wrap: anywhere;
      font-weight: 600;
    }
    .vendor-reference-card__url {
      grid-column: 1;
      min-width: 0;
      margin: 0;
      color: var(--donor-muted, #64748b);
      font-family: "JetBrains Mono", ui-monospace, monospace;
      font-size: .69rem;
      overflow-wrap: anywhere;
    }
    .vendor-reference-card__select {
      grid-column: 2;
      grid-row: 1 / span 3;
      align-self: center;
      display: inline-flex;
      align-items: center;
      min-height: 2.75rem;
      gap: .4rem;
      color: var(--donor-muted, #64748b);
      font-size: .72rem;
      white-space: nowrap;
    }
    .catalog-detail-scrim {
      position: fixed;
      inset: 0;
      z-index: 90;
      background: rgba(15, 23, 42, .44);
      opacity: 0;
      pointer-events: none;
      transition: opacity 180ms ease;
    }
    body.catalog-drawer-open .catalog-detail-scrim {
      opacity: 1;
      pointer-events: auto;
    }
    @keyframes openva-catalog-sheet-in {
      from { transform: translateX(100%); }
      to { transform: translateX(0); }
    }
    @media (max-width: 1000px) {
      .catalog-layout #vendor-detail.catalog-detail-drawer {
        position: fixed !important;
        inset: 0 0 0 auto !important;
        z-index: 100 !important;
        display: block !important;
        width: min(94dvw, 34rem) !important;
        max-width: 100dvw !important;
        height: 100dvh !important;
        max-height: 100dvh !important;
        overflow-x: hidden !important;
        overflow-y: auto !important;
        overscroll-behavior: contain;
        margin: 0 !important;
        border: 0 !important;
        border-left: 1px solid var(--donor-border, #d9e0e8) !important;
        border-radius: var(--donor-radius-xl, 1rem) 0 0 var(--donor-radius-xl, 1rem) !important;
        background: var(--donor-surface, #fff) !important;
        padding: 0 1rem 1.25rem !important;
        box-shadow: -18px 0 48px rgba(15, 23, 42, .2) !important;
        animation: openva-catalog-sheet-in 180ms ease-out;
        touch-action: pan-y;
      }
      .catalog-layout #vendor-detail.catalog-detail-drawer .catalog-detail-close {
        top: 0;
        width: calc(100% + 2rem) !important;
        min-height: 3.5rem !important;
        justify-content: flex-start !important;
        margin: 0 -1rem 1rem !important;
        border-width: 0 0 1px !important;
        border-radius: 0 !important;
        padding: .9rem 1rem !important;
      }
      .vendor-card__view-links {
        min-height: 2.75rem !important;
      }
      .vendor-reference-card {
        grid-template-columns: minmax(0, 1fr);
      }
      .vendor-reference-card__select {
        grid-column: 1;
        grid-row: auto;
        justify-self: stretch;
        justify-content: flex-start;
        min-height: 2.9rem;
        border-top: 1px solid var(--donor-border, #d9e0e8);
        margin-top: .25rem;
        padding-top: .55rem;
      }
    }
    @media (max-width: 420px) {
      .catalog-layout #vendor-detail.catalog-detail-drawer {
        width: 100dvw !important;
        border-left: 0 !important;
        border-radius: 0 !important;
      }
      .vendor-card h4 {
        grid-template-columns: minmax(0, 1fr) !important;
      }
      .vendor-card__header-actions {
        justify-content: space-between;
      }
      .vendor-card__view-links {
        flex: 0 0 auto;
      }
    }
    @supports not (overflow: clip) {
      html,
      body { overflow-x: hidden !important; }
    }
  `;
  document.head.appendChild(style);

  function selectionState(card, checkbox, selectionButton, vendorName) {
    const selected = Boolean(checkbox && checkbox.checked);
    card.classList.toggle("is-selected", selected);
    selectionButton.setAttribute("aria-pressed", String(selected));
    selectionButton.setAttribute(
      "aria-label",
      selected
        ? `Remove ${vendorName} from the public metadata export`
        : `Select ${vendorName} public metadata`,
    );
    const state = card.querySelector(".vendor-card__selection-state");
    if (state) state.textContent = selected ? "Selected" : "Select";
  }

  function buildCardControls(card, detailButton) {
    const heading = detailButton.closest("h4");
    const vendorName = detailButton.textContent.trim();
    if (!heading || !vendorName) return null;

    const name = document.createElement("span");
    name.className = "vendor-card__name";
    name.textContent = vendorName;

    const actions = document.createElement("span");
    actions.className = "vendor-card__header-actions";

    const state = document.createElement("span");
    state.className = "vendor-card__selection-state";
    state.setAttribute("aria-hidden", "true");

    detailButton.classList.add("vendor-card__view-links");
    detailButton.textContent = "View links";
    detailButton.setAttribute("aria-label", `View public links for ${vendorName}`);

    actions.append(state, detailButton);
    heading.replaceChildren(name, actions);

    const selectionButton = document.createElement("button");
    selectionButton.type = "button";
    selectionButton.className = "vendor-card__select-hit";
    selectionButton.textContent = `Select ${vendorName}`;
    card.prepend(selectionButton);

    return { selectionButton, vendorName };
  }

  function enhanceVendorCard(card) {
    if (!card || card.dataset.cardInteractionEnhanced === "true") return;
    const checkbox = card.querySelector("[data-select-vendor]");
    const detailButton = card.querySelector("[data-open-vendor]");
    if (!checkbox || !detailButton) return;

    const controls = buildCardControls(card, detailButton);
    if (!controls) return;

    card.dataset.cardInteractionEnhanced = "true";
    controls.selectionButton.addEventListener("click", () => {
      checkbox.checked = !checkbox.checked;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      selectionState(card, checkbox, controls.selectionButton, controls.vendorName);
    });
    checkbox.addEventListener("change", () => {
      selectionState(card, checkbox, controls.selectionButton, controls.vendorName);
    });
    selectionState(card, checkbox, controls.selectionButton, controls.vendorName);
  }

  function enhanceVendorCards() {
    document.querySelectorAll("[data-vendor-card]").forEach(enhanceVendorCard);
  }

  function observeVendorList() {
    const list = document.getElementById("vendor-list");
    if (!list || list.dataset.cardInteractionObserved === "true") return;
    list.dataset.cardInteractionObserved = "true";
    const observer = new MutationObserver(() => enhanceVendorCards());
    observer.observe(list, { childList: true });
  }

  function transformReferenceTable() {
    const panel = document.getElementById("vendor-detail");
    const wrapper = panel && panel.querySelector(".vendor-reference-table-wrap");
    if (!wrapper || wrapper.dataset.referenceCardsApplied === "true") return;
    wrapper.dataset.referenceCardsApplied = "true";

    const rows = [...wrapper.querySelectorAll("tbody tr")];
    const list = document.createElement("div");
    list.className = "vendor-reference-list";

    rows.forEach((row) => {
      const cells = [...row.querySelectorAll("td")];
      const card = document.createElement("article");
      card.className = "vendor-reference-card";
      if (cells.length < 3) {
        card.textContent = row.textContent.trim();
        list.appendChild(card);
        return;
      }

      const type = document.createElement("p");
      type.className = "vendor-reference-card__type";
      type.textContent = cells[0].textContent.trim();
      card.appendChild(type);

      const link = cells[1].querySelector("a");
      if (link) {
        link.classList.add("vendor-reference-card__link");
        card.appendChild(link);
      }
      const url = cells[1].querySelector("small");
      if (url) {
        url.classList.add("vendor-reference-card__url");
        card.appendChild(url);
      }
      const select = cells[2].querySelector("label");
      if (select) {
        select.classList.add("vendor-reference-card__select");
        card.appendChild(select);
      }
      list.appendChild(card);
    });

    wrapper.replaceWith(list);
  }

  function ensureScrim() {
    let scrim = document.querySelector(".catalog-detail-scrim");
    if (scrim) return scrim;
    scrim = document.createElement("div");
    scrim.className = "catalog-detail-scrim";
    scrim.setAttribute("aria-hidden", "true");
    scrim.addEventListener("click", () => {
      const close = document.querySelector(".catalog-detail-close");
      if (close) close.click();
    });
    document.body.appendChild(scrim);
    return scrim;
  }

  function renderCatalogWithCardInteractions() {
    baseRenderCatalog();
    observeVendorList();
    enhanceVendorCards();
  }

  async function renderVendorDetailAsCards(vendorId) {
    ensureScrim();
    await baseRenderVendorDetail(vendorId);
    transformReferenceTable();
  }

  try {
    renderCatalog = renderCatalogWithCardInteractions;
    renderVendorDetail = renderVendorDetailAsCards;
  } catch (_error) {
    window.renderCatalog = renderCatalogWithCardInteractions;
    window.renderVendorDetail = renderVendorDetailAsCards;
  }

  window.addEventListener("DOMContentLoaded", () => {
    ensureScrim();
    observeVendorList();
    enhanceVendorCards();
  });

  window.OPENVA_CATALOG_CARD_INTERACTIONS_VERSION = CATALOG_CARD_INTERACTIONS_VERSION;
})();
