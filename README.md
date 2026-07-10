# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a **public-source-only, metadata-first resolver** for vendor-published assurance references.

Use it to turn vendor names, domains, legal entities, or registration numbers into structured links to public materials such as:

- data processing addenda;
- privacy notices;
- subprocessor lists;
- security and compliance pages;
- trust centers;
- certification reference pages;
- public AI and data terms.

**Browser resolver:** https://thedanieltan.github.io/open-vendor-assurance/

OpenVA returns source-reference metadata. It does not approve, score, certify, rank, or recommend vendors and is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## Get value quickly

### Browser — no installation

Open the browser resolver, paste or upload a CSV, select the source fields you need, and export a source pack.

Your CSV is processed locally in the browser. It is not uploaded to OpenVA.

Accepted identity columns include:

```text
vendor_name
business_entity_name
domain
jurisdiction
registration_number
registered_address
```

At least one of `vendor_name`, `business_entity_name`, `domain`, or `registration_number` is required per row.

### MCP — copy and paste

macOS or Linux:

```bash
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install ./adapters/python/openva_pack_reader ./adapters/python/openva_vendor_inventory_matcher ./integrations/mcp/openva_mcp
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
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public
```

MCP host configuration:

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

### Self-hosted API — Docker

```bash
git clone https://github.com/thedanieltan/open-vendor-assurance.git
cd open-vendor-assurance
docker build -f services/openva_match_service/Dockerfile -t openva-match-service:local .
docker run --rm \
  -p 8000:8000 \
  -v "$PWD:/data/openva-pack:ro" \
  -e OPENVA_PACK_PATH=/data/openva-pack \
  -e OPENVA_SERVICE_API_KEY=replace-with-a-secret \
  openva-match-service:local
```

OpenVA does not currently operate a production central matching service. The repository includes optional, API-key-gated verify transport for self-hosted use, disabled unless configured by the operator.

## What OpenVA ships

OpenVA is a lightweight single-product monorepo containing:

- the public catalog and generated metadata packs;
- browser-local CSV resolution and source lookup;
- Python readers, exporters, and inventory matching adapters;
- a read-only MCP server;
- an optional self-hosted HTTP service;
- discovery, source-maintenance, validation, release, and governance tooling;
- dependency-aware workspace validation across repository components.

The catalog is supporting resolver infrastructure, not a completeness claim. OpenVA v0.1.0 was an infrastructure launch with a seed dataset; catalog breadth and depth continue to grow through public-source discovery and controlled promotion.

## Licensing and public reuse

OpenVA is intended to be freely forked, modified, redistributed, self-hosted, and built upon for commercial or non-commercial use.

- **Software and project documentation:** MIT License — see [`LICENSE`](LICENSE).
- **OpenVA-authored catalog metadata and generated data:** CC0 1.0 Universal — see [`docs/licensing.md`](docs/licensing.md).
- **Vendor documents, trademarks, pages, and other third-party materials:** remain the property of their respective owners and are not licensed by OpenVA.

Forks and substantial software redistributions must retain the MIT notice. CC0-covered catalog metadata has no attribution or share-alike requirement. Do not imply endorsement by OpenVA or by a referenced vendor.

## Start here

For users:

- [Browser resolver](https://thedanieltan.github.io/open-vendor-assurance/)
- [Release downloads](docs/release-downloads.md)
- [Local compiler](docs/local-compiler.md)
- [Resolver API](docs/resolver-api.md)
- [Agent integrations](docs/agent-integrations.md)

For contributors and maintainers:

- [Contributing](CONTRIBUTING.md)
- [Licensing and reuse](docs/licensing.md)
- [Public launch checklist](docs/public-launch-checklist.md)
- [Roadmap](docs/roadmap.md)
- [Triage policy](docs/triage-policy.md)
- [Versioning policy](docs/versioning-policy.md)
- [Release policy](docs/release-policy.md)
- [Release checklist](docs/release-checklist.md)
- [Consumer conformance fixtures](docs/consumer-conformance-fixtures.md)
- [Governance](GOVERNANCE.md)
- [Security](SECURITY.md)

For agents and downstream systems:

- `openva-pack.json`
- `indexes/`
- `schemas/openva/`
- `integrations/mcp/openva_mcp/`
- `docs/agent-export-contract.md`
- `docs/adapter-output-contract.md`

## Contributing vendor and source updates

Use the **Vendor catalog update** GitHub issue form to suggest a vendor, add a public source, or correct factual metadata.

A useful submission includes:

```text
Vendor: Example Vendor
Official website: https://vendor.example
Public source URL: https://vendor.example/legal/dpa
Requested change: Add this public DPA page.
Why authoritative: Published on the vendor's official domain.
```

Submit public URLs only. Do not submit private agreements, credentials, customer-specific terms, authenticated trust-center exports, SOC reports, private certificates, screenshots, copied document text, or materials requiring login, NDA, sales approval, support-ticket access, form submission, or anti-bot bypass.

## Product boundary

OpenVA does:

- resolve bounded vendor identities;
- locate public vendor-published assurance source URLs;
- classify source types and access states;
- preserve provenance and reproducible snapshot identity;
- export consumer-neutral source-reference metadata;
- distinguish found, missing, ambiguous, gated, unavailable, and not-checked states.

OpenVA does not:

- perform raw document mirroring by default;
- collect authenticated trust-center or private-portal materials;
- interpret document substance or customer-specific agreements;
- provide vendor approval, risk scoring, legal conclusions, or procurement recommendations;
- bypass access controls, CAPTCHA, robots policy, login gates, or anti-bot systems.

Users must verify referenced materials directly with the vendor and obtain professional advice where required.

## Validate the repository

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

The validation workflow retains full regression coverage for shared contracts and unowned paths while using the workspace dependency graph to target affected package tests on pull requests.
