# Selective rendered discovery operating model

## Status separation

- **Worker implementation:** merged through PR #729. The detector, offline browser boundary, rendered shard runner, differential metrics, and focused tests are present on `main`.
- **Scheduled deployment:** merged through PR #730. The daily Discovery Mesh selects the rendered shard runner and retains the static lane as its primary path.
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

## Read-only deployment smoke

A merge to `main` that changes the discovery workflow or rendered-discovery worker triggers a bounded deployment smoke. The smoke uses one shard and a five-vendor diagnostic limit, publishes the same differential evidence, and skips the candidate-intake branch and pull-request steps. It is therefore read-only with respect to repository and canonical catalog state.

Before public-site discovery begins, the hosted smoke runs deterministic real-Chromium fixtures that verify JavaScript execution through the intercepted safe-fetch boundary and rejection of an off-authority browser request. This separates browser/runtime deployment acceptance from whether the five sampled public vendors happen to contain a JavaScript-dependent assurance page.

A newer push smoke cancels any older in-progress push smoke in the same concurrency group. Scheduled and manually dispatched runs are not cancelled by this rule. The diagnostic profile therefore validates only the latest deployed crawler revision instead of serializing obsolete deployment probes.

The smoke limit is not a catalog breadth policy. Daily scheduled runs and ordinary manual runs continue to use the configured full-catalog shard matrix with no scheduled vendor limit. The push smoke exists only to verify a newly merged crawler deployment in the hosted runner environment.

When the push smoke reaches the aggregate acceptance boundary, it resolves the pull request associated with the merge commit and posts a durable evidence comment containing the run ID, commit SHA, health status, diagnostic profile, artifact name, mutation posture, and complete rendered differential. The comment uses the workflow's existing pull-request authority and does not add another workflow or repository mutation path.

## Live acceptance gates

The read-only post-merge smoke establishes hosted deployment acceptance when all of the following are recorded:

1. The run cites the merged deployment commit and uses the push-smoke one-shard, five-vendor diagnostic profile.
2. Chromium is resolved from the hosted runner.
3. The real-Chromium JavaScript-execution and off-authority-blocking fixtures pass.
4. Static public-site discovery executes before selective rendering.
5. The differential report is emitted and uploaded.
6. The report contains all declared counters and posture fields.
7. Browser direct-network posture remains false and rendered signals remain noncanonical.
8. Candidate-intake preparation is skipped for the push event.
9. The acceptance evidence is posted to the associated merged pull request with the workflow run ID, commit SHA, differential artifact, and totals.

Full-catalog production acceptance remains distinct and requires a scheduled or manually dispatched uncapped run:

1. The workflow uses the configured full-catalog shard matrix and no scheduled vendor limit.
2. Every shard completes or reports a visible failure.
3. The full-catalog differential report is emitted and uploaded.
4. At least one deterministic fixture or real public page demonstrates JavaScript-only link recovery; a zero-yield run remains valid operational evidence but does not prove improved coverage.
5. Any rendered candidate enters the existing verification, promotion-plan, candidate-intake, release, and canonical-mutation path unchanged.
6. Render failures remain access observations and do not create unavailable-source or vendor-quality conclusions.
7. The acceptance record cites the workflow run ID, commit SHA, differential artifact, totals, and any resulting candidate-intake or promotion PRs.

## Tuning

Tune rendering from measured differential yield, not from arbitrary catalog caps. Per-page and per-vendor browser limits may change when evidence supports the change. Catalog breadth remains uncapped, and no tuning may weaken source authority, identity resolution, verification, promotion, release, quorum, or automerge controls.
