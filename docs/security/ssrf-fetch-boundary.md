# SSRF Fetch Boundary Inventory

Operational/security metadata only. Not legal, compliance, procurement, security,
KYC, AML, audit, or vendor-risk advice.

OpenVA performs live network fetches of **public vendor sources** in several
lanes (verification, discovery, submission/contribution intake, observation). To
prevent server-side request forgery (SSRF), every reachable live fetch must go
through the shared safe boundary, bound to the relevant vendor authority. This
document is the authoritative inventory of every live-fetch entry point and its
status, so the hardened surface — and any deliberate deferral — is auditable.

## The safe boundary

| Component | Role |
| --- | --- |
| `tools/openva/safe_fetch.py` (`SafeFetcher` / `build_safe_fetcher`) | DNS-resolved + pinned IP, private/loopback/mixed-answer rejection, same-authority per-hop redirect revalidation, bounded bytes, single whole-exchange monotonic deadline, no cookies/credentials. |
| `tools/openva/safe_verify.py` (`build_safe_verify_fetcher`) | Verify-mode adapter returning `source_verification.FetchResult`, bound to a vendor's `official_domains`. |
| `tools/openva/url_safety.py` (`is_blocked_ip`, `validate_url_safety`) | IP classification (incl. IPv4-mapped and NAT64-embedded IPv4 extraction); static URL pre-check. `is_blocked_ip` runs on **every** DNS-resolved address inside the boundary, independent of the same-authority gate. |

**Authority binding** is the lane's strongest available domain set: catalog
vendor `official_domains` (resolved from the source record's path-adjacent
`vendor.yaml`), the submitted/matched domains plus the target host for pre-catalog
submissions, or a fail-closed result when no authority can be resolved. An empty
authority list is **never** passed to `build_safe_verify_fetcher` (that would
coerce same-authority to `None` and disable the gate); a fail-closed
`FetchResult(http_status=None)` is returned instead.

## Hardened lanes (route through the safe boundary)

| Lane | Entry point | Authority source |
| --- | --- | --- |
| Source verification CLI / report | `source_verification.verify_source` / `build_source_verification_report` (default `fetcher=None` → `safe_fetcher_for_source_path`) | path-adjacent `vendor.yaml` |
| Source preflight | `source_preflight.default_verifier` → `verify_source` | path-adjacent `vendor.yaml` |
| PR source-accessibility (CI: `agent-weighted-review.yml`) | `automation_rules.source_accessibility` (`fetcher=None`) | per-record `vendor.yaml` |
| New-vendor / legal-entity rules | `automation_rules.new_vendor_rules`, `legal_entity_promotion_rules` (`fetcher=None`) | vendor record `official_domains` |
| Source discovery (CI: `source-maintenance-report.yml`, `catalog-growth-discovery.yml`) | `source_discovery.discover_for_vendor` / `build_discovery_report` / `build_vendor_candidate_discovery_report` (`fetcher=None`) | vendor `official_domains` |
| Sitemap discovery | `catalog_growth_discovery_queue` (`_production_fetcher_factory` / `_production_verify_fetcher_factory`) | vendor `official_domains` (already safe) |
| Submitted-source verification (CI: `submitted-source-verification.yml`) | `submission_verify.verify_submission` (`fetcher=None` under `--network-check`) | submitted/matched domains + target host |
| Contribution intake (CI: `contribution-intake-agent.yml`) | `contribution_intake.intake_decision` (`fetcher=None` under `--network-check`) | matched vendor `official_domains` |
| Unified vendor resolution (catalogue-first, live-refresh-on-use) | `vendor_resolution.py` (`resolve_vendor_sources` / `resolve_inventory` + CLI) — live-refresh fetches go through `default_fetcher_factory` → `build_safe_verify_fetcher`, and fail closed via `validate_url_safety` | resolved vendor `official_domains` |

The unified resolver (`vendor_resolution.py`) is the request-driven live-refresh
path; it reuses this same boundary rather than a separate fetch primitive, and the
`url_safety` IPv4-mapped/NAT64 hardening below strengthens it transitively.

## Deferred / accepted-narrow (tracked)

| Entry point | Reachable today? | Reason deferred | Plan |
| --- | --- | --- | --- |
| `observe.fetch_public` (CI: `observe-report.yml`, scheduled) | Yes, but over **committed catalog** `source_url`s only (lowest attacker control — a malicious URL must already be merged through the hardened PR gates). | Routing through the safe boundary changes the observation lane's result vocabulary (`size_limited`/`bot_protected`) and byte semantics; `resolve_dns=True` alone adds real-DNS dependency to unit tests. Both destabilise the observation lane and warrant a dedicated change. | Dedicated observation-lane hardening: route `fetch_public` through `build_safe_verify_fetcher` bound to the source's vendor `official_domains`, mapping `FetchResult` → the observation result vocabulary, with updated `tests/test_observe.py`. |
| `source_review_decisions.verify_replacement_url` (raw `fetch_url`) | No — `validate-sheet` is invoked by no committed workflow. | Not a production exposure today. | Harden when the validated-repair `validate-sheet` workflow is wired. |
| `submission_bridge.build_new_vendor_candidate` / `verify_source_url` (raw `fetch_url`) | No — `submission_bridge` appears in no committed workflow. | Not a production exposure today; queued for wiring under ACT-02. | Harden **with** the ACT-02 intake wiring (before it goes live), binding to the submission's claimed domains + target host. |
| `contribution_intake._safe_intake_fetcher` authority set | Yes (hardened) but **narrowed** to `official_domains` only. | The upstream `is_authoritative_url` gate also accepts official-publisher-exception domains; binding the fetcher to `official_domains` only is strictly narrower. The one live exception (google-workspace → cloud.google.com) is coincidentally a subdomain of an official domain, so it passes. | Fail-closed-safe today (a non-subdomain exception source would be refused → routed to human review, never an SSRF). Broaden to mirror `is_authoritative_url`'s exception domains when a non-subdomain exception is introduced. |

## Out of scope (not live source fetches)

- `bot_dashboard_issue.py` / `bot_telemetry` `urlopen` — authenticated GitHub REST API (`api.github.com`), not arbitrary-source fetch.
- `services/` `httpx` — a `pyproject` declaration with no live call site in the verification/intake/discovery path.
- `examples/*.sh` — smoke scripts invoked by no workflow.
