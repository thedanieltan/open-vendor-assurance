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
          <summary>Catalog version: ${date}</summary>
          <p>This identifies the public metadata snapshot used by the page. Most users can ignore it unless they need reproducible records.</p>
          <p>Snapshot: <code>${snapshot}</code></p>
          <p><a href="${link}">GitHub Releases</a></p>
        </details>
      `;
      node.dataset.compacted = "true";
    });
  }

  function refreshUiFixes() {
    compactSnapshotBlocks();
    improveCountryLabels();
  }

  applyTheme(storedTheme());
  window.addEventListener("DOMContentLoaded", () => {
    installThemeToggle();
    refreshUiFixes();
    const observer = new MutationObserver(refreshUiFixes);
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
