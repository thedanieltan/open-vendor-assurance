# OpenVA workspace operating model

OpenVA is maintained as a **single-product, multi-component repository**. The workspace control plane adds package awareness and dependency-aware validation without introducing Nx, Turborepo, Pants, Bazel, or another external monorepo framework.

## Authority and boundaries

- `tools/openva/workspace.yaml` is the component and dependency manifest.
- `tools/openva/workspace.py` validates the manifest and calculates affected components.
- `.github/workflows/validate.yml` remains the single validation authority.
- Existing named validation lanes remain active and authoritative during the initial workspace rollout.
- The workspace lane is additive. It must not suppress an existing required lane merely because its own affected plan is narrower.
- Shared catalog, schema, generated-contract, and core-tool changes fail safe to the full Python suite.
- Files that are not owned by a declared component fail safe to the full Python suite.
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

The `workspace-affected-tests` job:

1. checks out full Git history;
2. validates the workspace manifest;
3. compares the pull-request base and head commits;
4. writes a machine-readable affected-component plan to the job summary;
5. installs affected local packages in dependency order;
6. runs the selected Python tests.

The lane runs on pull requests. Pushes to `main` retain the existing full sharded regression suite.

## Conservative fallback

The planner selects the full suite when:

- no changed files are supplied;
- a changed file is not owned by any component;
- a shared contract or core-tool component is affected;
- the manifest cannot produce a valid test plan.

A planner error fails the job. It never silently skips validation.

## Rollout and acceptance

Implementation acceptance requires:

- manifest validation passes;
- dependency ordering and reverse-dependent tests pass;
- a leaf-package fixture produces a targeted plan;
- a shared-contract fixture produces a full-suite plan;
- a policy workflow fixture selects workflow and scope-policy tests without unrelated drift suites;
- specialised governance fixtures retain their corresponding tests;
- `validate.yml` executes the planner on a real pull request;
- existing validation and governance checks remain green.

Replacing or removing existing validation lanes is a separate future decision and requires measured CI evidence. This work does not make that change.
