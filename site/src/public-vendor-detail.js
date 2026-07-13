(() => {
  const PUBLIC_VENDOR_DETAIL_VERSION = "references-only-v1";

  function referenceRows(sources) {
    if (!sources.length) {
      return '<tr><td colspan="3">No public source URL is currently recorded.</td></tr>';
    }
    return sources
      .filter((source) => source && source.source_url)
      .sort((left, right) => {
        const leftKey = `${sourceTypeLabel(left.source_type)} ${left.title || ""} ${left.source_url}`;
        const rightKey = `${sourceTypeLabel(right.source_type)} ${right.title || ""} ${right.source_url}`;
        return leftKey.localeCompare(rightKey);
      })
      .map((source) => {
        const title = source.title || source.source_url;
        return `
          <tr>
            <td>${html(sourceTypeLabel(source.source_type))}</td>
            <td class="source-reference-cell">
              <a href="${html(source.source_url)}" target="_blank" rel="noopener noreferrer">${html(title)}</a>
              <small>${html(source.source_url)}</small>
            </td>
            <td class="source-select-cell">
              <label><input type="checkbox" data-select-source="${html(source.source_id)}" ${selectedSources.has(source.source_id) ? "checked" : ""}> Select</label>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  renderVendorDetail = async function renderPublicVendorDetail(vendorId) {
    const detailPanel = document.getElementById("vendor-detail");
    detailPanel.innerHTML = '<p class="eyebrow">Loading</p><h3>Loading vendor references...</h3>';
    try {
      const detail = await loadVendorDetail(vendorId);
      const vendor = detail.vendor;
      const sources = detailSourceRecords(detail);
      const domains = (vendor.official_domains || [])
        .map((domain) => `<a href="https://${html(domain)}" target="_blank" rel="noopener noreferrer">${html(domain)}</a>`)
        .join(" · ");

      detailPanel.innerHTML = `
        <p class="eyebrow">Vendor references</p>
        <h3>${html(vendor.display_name)}</h3>
        ${domains ? `<p class="vendor-domains">${domains}</p>` : ""}
        <div class="vendor-reference-table-wrap">
          <table class="vendor-reference-table">
            <thead>
              <tr><th>Source type</th><th>Reference</th><th>Export</th></tr>
            </thead>
            <tbody>${referenceRows(sources)}</tbody>
          </table>
        </div>
      `;

      detailPanel.querySelectorAll("[data-select-source]").forEach((box) => {
        box.addEventListener("change", (event) => {
          const sourceId = event.target.dataset.selectSource;
          event.target.checked ? selectedSources.add(sourceId) : selectedSources.delete(sourceId);
          renderCatalogSummary();
          renderExport();
        });
      });
    } catch (error) {
      detailPanel.innerHTML = `<p class="eyebrow">Vendor references</p><h3>Could not load vendor references</h3><p>${html(error.message)}</p>`;
    }
  };

  window.OPENVA_PUBLIC_VENDOR_DETAIL_VERSION = PUBLIC_VENDOR_DETAIL_VERSION;
})();
