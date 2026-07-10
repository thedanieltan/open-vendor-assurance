(() => {
  const originalNormalizeForMatch = window.normalizeForMatch;
  if (typeof originalNormalizeForMatch === "function") {
    window.normalizeForMatch = (value) => {
      if (value === null || value === undefined || String(value).trim() === "") return "";
      return originalNormalizeForMatch(value);
    };
  }

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

  applyTheme(storedTheme());
  window.addEventListener("DOMContentLoaded", () => {
    installThemeToggle();
    polishCatalogFilters();
  });
})();
