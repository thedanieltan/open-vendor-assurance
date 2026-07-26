# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a public-source-only, metadata-first resolver for vendor-published assurance references.

**Use OpenVA in your browser:** https://thedanieltan.github.io/open-vendor-assurance/

OpenVA helps users turn a vendor list into a review sheet of public vendor assurance URLs. Upload a CSV, resolve vendors against indexed public-source records, and export selected source-reference columns without installing Python, Docker, or developer tooling.

OpenVA records factual locator metadata about public vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product. It does not approve, score, certify, monitor, or assess vendors.

## Get value quickly

### Browser users — no install

Open:

```text
https://thedanieltan.github.io/open-vendor-assurance/
```

Then upload or paste a CSV with at least one of:

```text
vendor_name
domain
business_entity_name
registration_number
```

Export the review workbook or CSV when matching is complete.

### MCP users — copy/paste install

Use this when your agent host supports MCP.

macOS / Linux:

```bash
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install ./adapters/python/openva_pack_reader ./adapters/python/openva_vendor_inventory_matcher ./integrations/mcp/openva_mcp
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public --verify
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public
```

Windows PowerShell:

```powershell
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install ./adapters/python/openva_pack_reader ./adapters/python/openva_vendor_inventory_matcher ./integrations/mcp/openva_mcp
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public --verify
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public
```

MCP host config:

```json
{
  "mcpServers": {
    "openva": {
      "command": "openva-mcp",
      "args": ["--base-url", "https://thedanieltan.github.io/open-vendor-assurance/public"]
    }
  }
}
```

If your MCP host cannot find `openva-mcp`, use the absolute path inside the virtual environment:

```text
/path/to/open-vendor-assurance/.venv/bin/openva-mcp
```

## Free data source distribution

OpenVA can also be shared as a free public-source metadata dataset.

Repo-side publishing assets are available in:

- `docs/free-data-source-distribution.md`
- `docs/huggingface-dataset-card.md`
- `docs/kaggle-dataset-metadata.json`
- `docs/zenodo-metadata.json`
- `docs/dataset-citation.cff`
- `docs/open-data-directory-listing.md`

Use those files to mirror OpenVA to Hugging Face Datasets, Kaggle Datasets, Zenodo, and open-data directories while keeping GitHub as the source of truth.
