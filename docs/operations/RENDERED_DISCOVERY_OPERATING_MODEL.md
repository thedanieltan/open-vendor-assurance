# Selective rendered discovery operating model

## Status separation

- **Worker implementation:** merged through PR #729. The detector, offline browser boundary, rendered shard runner, differential metrics, and focused tests are present on `main`.
- **Scheduled deployment:** this work package installs the Playwright Python binding and selects the rendered shard runner in `discovery-mesh.yml`.
- **Live acceptance:** remains open until an actual workflow run records the rendered differential described below. Green repository checks establish implementation correctness; they do not establish production yield.

## Purpose

OpenVA's bounded static HTTP, sitemap, and HTML-link discovery remains the primary lane. The browser fallback is considered only for fetched public pages that have no useful static locator evidence and exhibit deterministic JavaScript-shell signals, including:

- a JavaScript-required `noscript` message;
- an SPA root accompanied by scripts;
- known framework markers;
- script-heavy, low-text shell content;
- a high-value assurance path with no static candidates.

This prevents the cost and attack surface of running Chromium against every page.

## Browser and network boundary

The GitHub-hosted Ubuntu image already supplies Chromium. Each discovery shard installs only the pinned Playwright Python binding and explicitly resolves the runner's Chromium executable. It does not download a separate browser bundle per shard.

The browser context is offline. The worker prefetches the entry document through OpenVA's existing DNS-pinned `SafeFetcher`, loads those bytes into Chromium, and intercepts browser subrequests. Permitted requests are fulfilled with bytes returned by the same safe fetch boundary. The worker blocks:

- off-authority requests;
- non-GET requests;
- images, media, and fonts;
- service workers and downloads;
- responses, total bytes, requests, pages, rendered HTML, and elapsed rendering beyond configured bounds.

Authentication, customer portals, form submission, CAPTCHA handling, WAF evasion, browser impersonation, and third-party script execution remain outside the permitted lane.

## Evidence and mutation boundary

Rendered links remain noncanonical locator signals. Official-domain locators pass through the existing source verifier. Delegated-host links remain first-party-attested, unverified signals. The rendered runner does not directly write canonical vendor or source records, and `candidate-promotion-pr.yml` remains the sole canonical mutation authority.

No rendering outcome is a vendor-quality, compliance, legal, procurement, audit, security, or risk conclusion.

## Differential evidence

Every aggregate run writes `reports/discovery-mesh/rendered-discovery-differential.json`, covering:

- JavaScript-fallback eligible pages;
- pages rendered and render failures;
- browser requests fulfilled and blocked;
- browser bytes fulfilled;
- rendered locator signals;
- rendered candidates that pass the existing verifier;
- vendors with eligible pages;
- vendors with at least one verified rendered candidate;
- deterministic eligibility-reason counts.

The report compares incremental rendered discovery against the bounded static HTML baseline. It is uploaded with the ordinary discovery-mesh evidence and summarized in the workflow step summary.

## Live acceptance gates

A production run is accepted for the rendered lane only when all of the following are recorded from the merged deployment revision:

1. The workflow uses the configured full-catalog shard matrix and no scheduled vendor limit.
2. Every shard resolves the hosted Chromium executable and starts the rendered runner.
3. Static discovery still executes before rendering.
4. The differential report is emitted and uploaded.
5. The report contains all declared counters and posture fields.
6. Browser direct-network posture remains false and rendered signals remain noncanonical.
7. At least one deterministic fixture or real public page demonstrates JavaScript-only link recovery; a zero-yield production run remains valid evidence but does not prove improved coverage.
8. Any rendered candidate enters the existing verification, promotion-plan, candidate-intake, release, and canonical-mutation path unchanged.
9. Render failures remain access observations and do not create unavailable-source or vendor-quality conclusions.
10. The acceptance record cites the workflow run ID, commit SHA, differential artifact, totals, and any resulting candidate-intake or promotion PRs.

## Tuning

Tune rendering from measured differential yield, not from arbitrary catalog caps. Per-page and per-vendor browser limits may change when evidence supports the change. Catalog breadth remains uncapped, and no tuning may weaken source authority, identity resolution, verification, promotion, release, quorum, or automerge controls.
