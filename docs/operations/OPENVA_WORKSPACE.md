# OpenVA workspace operating model

OpenVA is maintained as a **single-product, multi-component repository**. The workspace control plane adds package awareness and dependency-aware validation without introducing Nx, Turborepo, Pants, Bazel, or another external monorepo framework.

## Authority and boundaries

- `tools/openva/workspace.yaml` is the component and dependency manifest.
- `tools/openva/workspace.py` validates the manifest and calculates affected components.
- `.github/workflows/validate.yml` remains the single validation authority.
- `workspace-affected-tests` remains the required status aggregator for workspace validation.
- Component-scoped plans run only the selected Python tests and install only their dependency chain.
- Full-suite plans are delegated to the existing parallel regression shards rather than a second monolithic `pytest tests` invocation.
- Shared catalog, schema, generated-contract, and core-tool changes continue to fail safe to full regression coverage whenever the workspace planner is activated.
- Files that are not owned by a declared component continue to fail safe to full regression coverage.
- Google Sheets JavaScript tests remain in the dedicated Node lane; the workspace Python plan does not send `.mjs` files to pytest.

## Component model

The manifest identifies:

- shared catalog and schema contracts;
- root OpenVA tooling;
- the pack reader;
- CSV, JSONL, and SQLite exporters;
- the vendor inventory matcher;
- the HTTP match service;
- the MCP integration;
- the browser site;
- the Google Sheets integration;
- operational-ledger governance;
- distribution-positioning contracts;
- hosted-deployment contracts;
- repository and workflow controls.

Dependencies are directional. A change to a dependency affects its reverse dependents. For example, a pack-reader change affects exporters, the matcher, MCP, the match service, Google Sheets, and hosted-deployment contract validation. A leaf MCP change remains MCP-scoped but still installs the pack reader and matcher first.

Specialised governance suites retain their own ownership. A change to `validate.yml` runs workflow and scope-policy checks, but does not pull unrelated hosted-deployment or product-positioning drift suites. Those suites still run when their corresponding source, workflow, schema, or documentation surfaces change.

## Pull-request execution

Pull-request workspace validation has three stages:

1. `workspace-plan` checks out full history, validates the manifest, compares the pull-request base and head, and publishes a machine-readable plan.
2. A non-full-suite plan runs through `workspace-component-tests`, which installs affected packages in dependency order and executes only the selected tests.
3. A full-suite plan runs through the six `full-regression-shards` in parallel. The shards install MCP or match-service dependencies only where required.

The `workspace-affected-tests` required status aggregator succeeds only when the selected execution path succeeds. It preserves the existing protected context while removing the duplicate monolithic full-suite job.

Pushes to `main` continue to run the same full regression shards.

## Conservative fallback

The planner selects full regression coverage when:

- no changed files are supplied;
- a changed file is not owned by any component;
- a shared contract or core-tool component is affected;
- the manifest cannot produce a valid targeted plan.

A planner error fails the required aggregator. It never silently skips validation.

## Acceptance

Implementation acceptance requires:

- manifest validation passes;
- dependency ordering and reverse-dependent tests pass;
- a leaf-package fixture produces a targeted plan;
- a shared-contract fixture produces a full-suite plan;
- targeted plans run component-scoped tests;
- full-suite plans run parallel regression shards on pull requests;
- the required workspace status reflects the delegated path result;
- existing validation and governance checks remain green.

This rationalization removes duplicate execution but does not remove a regression boundary. Retiring specialised validation lanes remains a separate decision requiring measured evidence.
