(() => {
  const CATALOG_DONOR_ALIGNMENT_VERSION = "trusty-vendor-scan-v1";

  const style = document.createElement("style");
  style.id = "openva-catalog-donor-alignment";
  style.textContent = `
    .vendor-card {
      gap: .55rem !important;
      padding: 1rem !important;
      border-radius: var(--donor-radius-lg) !important;
      background: var(--donor-surface) !important;
      box-shadow: none !important;
    }
    .vendor-card:hover {
      border-color: color-mix(in oklch, var(--donor-brand) 58%, var(--donor-border)) !important;
      box-shadow: var(--donor-shadow-sm) !important;
    }
    .vendor-card h4 {
      display: flex !important;
      align-items: flex-start !important;
      justify-content: space-between !important;
      gap: .75rem !important;
    }
    .vendor-card__name {
      min-width: 0;
      color: var(--donor-fg) !important;
      font-size: 1rem !important;
      font-weight: 600 !important;
      line-height: 1.25 !important;
      letter-spacing: -.015em;
      overflow-wrap: anywhere;
    }
    .vendor-card__header-actions {
      display: inline-flex !important;
      flex: 0 0 auto;
      align-items: center !important;
      justify-content: flex-end !important;
      gap: .4rem !important;
    }
    .vendor-card__selection-state {
      display: inline-flex !important;
      align-items: center !important;
      gap: .38rem !important;
      border: 0 !important;
      border-radius: 0 !important;
      background: transparent !important;
      color: var(--donor-muted) !important;
      padding: 0 !important;
      font-size: .69rem !important;
      font-weight: 400 !important;
      line-height: 1.2 !important;
      box-shadow: none !important;
    }
    .vendor-card__selection-state::before {
      content: "";
      display: grid;
      width: .88rem;
      height: .88rem;
      place-items: center;
      border: 1px solid var(--donor-border);
      border-radius: .2rem;
      background: var(--donor-surface);
      color: var(--donor-primary-fg);
      font-size: .62rem;
      font-weight: 600;
      line-height: 1;
    }
    .vendor-card.is-selected {
      border-color: var(--donor-brand) !important;
      background: var(--donor-surface) !important;
      box-shadow: 0 0 0 1px color-mix(in oklch, var(--donor-brand) 40%, transparent) !important;
    }
    .vendor-card.is-selected .vendor-card__selection-state {
      color: var(--donor-brand) !important;
    }
    .vendor-card.is-selected .vendor-card__selection-state::before {
      content: "✓";
      border-color: var(--donor-brand);
      background: var(--donor-brand);
    }
    .vendor-card__footer {
      position: relative;
      z-index: 3;
      display: flex;
      min-height: 1.9rem;
      align-items: center;
      justify-content: flex-end;
      margin-top: .05rem;
      pointer-events: none;
    }
    .vendor-card__view-links {
      position: relative !important;
      z-index: 4 !important;
      display: inline-flex !important;
      width: auto !important;
      min-width: 0 !important;
      max-width: none !important;
      min-height: 2rem !important;
      align-items: center !important;
      justify-content: flex-end !important;
      border: 0 !important;
      border-radius: 0 !important;
      background: transparent !important;
      color: var(--donor-muted) !important;
      padding: .3rem 0 .2rem .55rem !important;
      font-size: .72rem !important;
      font-weight: 400 !important;
      line-height: 1.2 !important;
      text-decoration: none !important;
      white-space: nowrap;
      box-shadow: none !important;
      opacity: 1;
      transform: none !important;
      pointer-events: auto !important;
    }
    .vendor-card__view-links:hover {
      border: 0 !important;
      background: transparent !important;
      color: var(--donor-brand) !important;
      box-shadow: none !important;
      opacity: 1 !important;
      transform: none !important;
    }
    .vendor-card:has(.vendor-card__select-hit:focus-visible),
    .vendor-card:has(.vendor-card__view-links:focus-visible) {
      outline: 2px solid var(--donor-ring) !important;
      outline-offset: 2px !important;
    }
    @media (hover: hover) and (pointer: fine) {
      .vendor-card__view-links { opacity: 0; }
      .vendor-card:hover .vendor-card__view-links,
      .vendor-card:focus-within .vendor-card__view-links { opacity: 1; }
    }

    .vendor-reference-list {
      gap: .5rem !important;
    }
    .vendor-reference-card {
      grid-template-columns: minmax(0, 1fr) auto !important;
      gap: .3rem .75rem !important;
      border: 1px solid var(--donor-border) !important;
      border-radius: var(--donor-radius) !important;
      background: var(--donor-surface) !important;
      padding: .7rem !important;
      box-shadow: none !important;
    }
    .vendor-reference-card__type {
      color: var(--donor-muted) !important;
      font-size: .66rem !important;
      font-weight: 500 !important;
      letter-spacing: .08em !important;
    }
    .vendor-reference-card__link {
      color: var(--donor-fg) !important;
      font-size: .78rem !important;
      font-weight: 500 !important;
      line-height: 1.35 !important;
      text-decoration: none !important;
    }
    .vendor-reference-card__link:hover {
      color: var(--donor-brand) !important;
    }
    .vendor-reference-card__url {
      color: var(--donor-muted) !important;
      font-size: .65rem !important;
      line-height: 1.45 !important;
    }
    .vendor-reference-card__select {
      grid-column: 2 !important;
      grid-row: 1 / span 3 !important;
      align-self: start !important;
      min-height: auto !important;
      border: 0 !important;
      margin: 0 !important;
      padding: .08rem 0 0 !important;
      color: var(--donor-muted) !important;
      font-size: .67rem !important;
      font-weight: 400 !important;
    }

    .catalog-detail-scrim {
      background: rgba(15, 27, 61, .22) !important;
    }
    @media (max-width: 1000px) {
      .catalog-layout #vendor-detail.catalog-detail-drawer {
        width: min(92dvw, 32rem) !important;
        border-left: 1px solid var(--donor-border) !important;
        border-radius: var(--donor-radius-xl) 0 0 var(--donor-radius-xl) !important;
        background: var(--donor-surface) !important;
        padding: 0 1rem 1rem !important;
        box-shadow: var(--donor-shadow) !important;
      }
      .catalog-layout #vendor-detail.catalog-detail-drawer .catalog-detail-close {
        position: sticky !important;
        top: 0 !important;
        z-index: 4 !important;
        width: calc(100% + 2rem) !important;
        min-height: 3rem !important;
        justify-content: flex-start !important;
        margin: 0 -1rem 1rem !important;
        border: 0 !important;
        border-bottom: 1px solid var(--donor-border) !important;
        border-radius: 0 !important;
        background: color-mix(in oklch, var(--donor-surface) 94%, transparent) !important;
        color: var(--donor-muted) !important;
        padding: .72rem 1rem !important;
        font-size: .75rem !important;
        font-weight: 500 !important;
        box-shadow: none !important;
        opacity: 1 !important;
        transform: none !important;
        backdrop-filter: blur(12px);
      }
      .catalog-layout #vendor-detail.catalog-detail-drawer .catalog-detail-close:hover {
        background: var(--donor-accent) !important;
        color: var(--donor-fg) !important;
      }
    }
    @media (max-width: 420px) {
      .catalog-layout #vendor-detail.catalog-detail-drawer {
        width: 100dvw !important;
        border-left: 0 !important;
        border-radius: 0 !important;
      }
      .vendor-card h4 {
        display: flex !important;
      }
      .vendor-card__header-actions {
        justify-content: flex-end !important;
      }
      .vendor-card__view-links {
        width: auto !important;
      }
      .vendor-reference-card {
        grid-template-columns: minmax(0, 1fr) auto !important;
      }
      .vendor-reference-card__select {
        grid-column: 2 !important;
        grid-row: 1 / span 3 !important;
      }
    }
  `;
  document.head.appendChild(style);

  function alignVendorCard(card) {
    if (!card || card.dataset.donorAlignmentApplied === "true") return;
    const detailButton = card.querySelector(".vendor-card__view-links");
    if (!detailButton) return;

    let footer = card.querySelector(".vendor-card__footer");
    if (!footer) {
      footer = document.createElement("div");
      footer.className = "vendor-card__footer";
      card.appendChild(footer);
    }
    detailButton.textContent = "View links →";
    footer.appendChild(detailButton);
    card.dataset.donorAlignmentApplied = "true";
  }

  function alignVendorCards() {
    document.querySelectorAll("[data-vendor-card]").forEach(alignVendorCard);
  }

  function observeVendorCards() {
    const list = document.getElementById("vendor-list");
    if (!list || list.dataset.donorAlignmentObserved === "true") return;
    list.dataset.donorAlignmentObserved = "true";
    new MutationObserver(() => window.queueMicrotask(alignVendorCards)).observe(list, {
      childList: true,
      subtree: true,
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    observeVendorCards();
    alignVendorCards();
  });

  window.OPENVA_CATALOG_DONOR_ALIGNMENT_VERSION = CATALOG_DONOR_ALIGNMENT_VERSION;
})();