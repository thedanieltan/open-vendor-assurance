# OpenVA Bot Operating Model

This document defines the OpenVA Bot Operating Model as the automation governance layer above the Workflow Operating Model. The workflow model describes the current loops. This bot model defines authority, queues, commands, failure handling, exception ownership, observability, and retirement rules for those loops.

WP9 does not implement chat-ops execution, dashboard automation, Prow/Tide-style merge automation, or workflow retirement. It defines the command surface and machine-readable contracts that later implementation work must follow.

Status: Bot Automation v1 (WP9 through WP27) is complete and this operating model is active. The first live chat-ops mutation surface is `/openva hold` and `/openva unhold`, constrained to the `openva-hold` label on the current issue or pull request (see `docs/operations/BOT_CHATOPS_EXECUTION.md`). All other commands remain report-only, local-audit-only, or denied. The closeout record is `docs/operations/BOT_AUTOMATION_V1_CLOSEOUT.md`.

OpenVA bot power is proportional to source certainty. Discovery may propose; controlled promotion writes. Report-only lanes must not mutate catalog truth. Unknown or undeclared bot lanes are deny-by-default, and unknown or undeclared write paths are deny-by-default. Write-capable lanes require explicit authority contract entries.

Workflow retirement must happen only after classification under this bot operating model.

## Authority Model

The authority contract is `docs/operations/contracts/bot-authority.yaml`.

Bot authority is lane-scoped. A lane is allowed to do only what its contract declares:

- write branches
- open PRs
- label PRs
- enable auto-merge
- merge PRs
- write catalog truth
- touch specific paths
- use specific token permissions

The default posture is deny-by-default:

- undeclared lanes are denied
- undeclared write paths are denied
- discovery lanes may not write catalog truth
- report-only lanes may not write catalog truth
- support lanes are not strict-growth authority
- legacy report lanes are consolidation candidates, not authority expansion paths

The strict-growth lane remains narrow: catalog growth discovery proposes candidates and promotion actions, while `candidate-promotion-pr.yml` is the controlled promotion path for reviewed evidence. Source repair uses committed reviewed evidence and remains separate from catalog growth.

The `bot_dashboard_issue_sync` lane is visibility-only authority. It may render the bot dashboard and, after explicit maintainer input, create or update only the persistent OpenVA Bot Dashboard issue. It must not write catalog truth, mutate PRs, dispatch workflows, label PRs, change automerge state, or grant authority to any catalog growth, promotion actions, source repair, reviewed evidence, strict-growth, or controlled promotion path.

## Bot Constitution And Release Gates

`config/bot-constitution.yaml` holds the deny-first, higher-order invariants that every lane and work package must respect. It complements the per-lane authority contract: `bot-authority.yaml` owns write/label/merge permissions, while the constitution owns the boundary invariants (public-source-only, no advisory/scoring/ranking output, SHA-256-only OpenVA digests, no raw-document mirroring, every machine-created claim reversible, no automation writing directly to `main`, and the separation-of-duty rules deferred to WP36/WP37).

Each constitution rule carries an explicit `enforcement` classification:

- `machine_enforced` — a named gate in `tools/openva/release_gates.py` rejects a real violation, proven by a negative fixture in `tests/test_release_gates.py`;
- `contract_enforced` — enforced by a workflow/authority contract and its existing test;
- `deferred` — not yet authoritative; the named owning work package (WP36/WP37) will implement enforcement. A deferred rule is never relied on as if enforced.

The consolidated release gate (`python -m tools.openva.release_gates check`) is the single authority gate that composes existing validators and the machine-enforced constitution rules. It runs in two explicit profiles: `pr` (deterministic committed-repository checks only, wired into `validate.yml`) and `release` (adds runtime-evidence gates and fails closed on missing, malformed, or stale required evidence, wired into `release-candidate.yml`). Thresholds live in `config/release-gates.yaml`, never in code. Later automerge jobs call the same gate so every merge path enforces the same authority boundary.

## Command Surface

OpenVA commands are planned maintainer-facing controls. WP9 defines vocabulary, authority, and audit expectations only. It does not implement slash-command parsing or execution.

| Command | Purpose | Allowed actor | Affected lane | Side effect class | Audit requirement | Implementation status |
|---|---|---|---|---|---|---|
| `/openva retry-source-preflight` | Re-run source accessibility and source-role checks for a blocked candidate. | maintainer or source-maintainer | `catalog_growth_promotion`, `source_repair` | report or PR comment update only until implemented lane authority exists | link to source-health run, candidate id, and previous failure code | planned |
| `/openva defer-candidate` | Move a candidate out of immediate promotion consideration. | maintainer or reviewer | `catalog_growth_discovery`, `catalog_growth_promotion` | dashboard/control issue state update | candidate id, reason, expiry or recheck date | planned |
| `/openva promote-reviewed-plan` | Request controlled promotion for a reviewed plan already committed under `maintenance/reviewed/`. | maintainer | `catalog_growth_promotion` | controlled PR branch and PR creation | reviewed plan path, source-health evidence, promotion action count, preflight result | planned |
| `/openva explain-strict-growth` | Explain why a PR or candidate is or is not eligible for strict-growth automation. | maintainer, reviewer, contributor | `pr_safety`, `catalog_growth_promotion` | report/comment only | PR or candidate id, labels, changed paths, failed gate if any | local-audit-only (WP21) |
| `/openva quarantine-source` | Mark a source as unsafe for automated use until reviewed. | maintainer or source-maintainer | `source_maintenance_report`, `source_repair` | dashboard/control issue state update; no catalog truth mutation | source URL, vendor id when known, reason, owner, expiry | planned |
| `/openva recheck-final-url` | Recheck redirect target and canonical final URL evidence. | maintainer or source-maintainer | `catalog_growth_promotion`, `source_repair` | report/comment update only until controlled repair/promotion is approved | original URL, final URL, source-health run, redirect evidence | planned |
| `/openva hold` | Pause bot action for a PR, candidate, lane, or global queue. | maintainer | all declared lanes | PR label, dashboard/control issue state, or global pause switch | scope, reason, owner, recheck date | live (WP27, `openva-hold` label on current issue/PR only) |
| `/openva unhold` | Remove a prior hold after the blocking condition is resolved. | maintainer | all declared lanes | PR label or dashboard/control issue state | scope, resolving evidence, owner approval | live (WP27, `openva-hold` label on current issue/PR only) |

Commands that would create PRs, write branches, mutate catalog truth, or affect auto-merge require an explicit lane entry in `bot-authority.yaml`. Report-only commands must not mutate catalog truth.

## Queue And Dashboard Model

OpenVA should maintain a durable bot dashboard/control issue or generated report rather than scattering state across transient workflow comments.

The dashboard should show:

- strict-growth ready candidates
- deferred candidates
- review-required candidates
- source-health failures
- redirect deferrals
- coverage gaps
- stale backlog items
- last successful catalog-growth run
- last failed run
- next safe action

Each dashboard item should include the lane id, candidate or PR id, current failure code when blocked, owner, next action, and stale-evidence deadline. The dashboard is advisory until a later implementation creates automation for it. Report-only dashboard updates do not mutate catalog truth.

Dashboard issue sync publishes the dashboard as a durable control issue. Scheduled dashboard issue workflow runs remain dry-run/report-only; real issue updates require explicit maintainer input and are limited to the persistent dashboard issue.

The next safe action must be derived from lane authority and failure taxonomy. For example, a candidate with `source_preflight_failure` may be retried after fresh source-health evidence, while a PR with `permission_policy_denial` must stop the lane until a maintainer resolves the authority mismatch.

## Throttling And Schedules

The queue policy is `docs/operations/contracts/bot-queue-policy.yaml`.

Bot PR noise is controlled with:

- global pause switch label: `openva-bot-paused`
- max open catalog-growth PRs
- max open source-repair PRs
- max bot PRs per day and per week
- lane batch sizing
- cooldown after failure
- source-host rate limits
- vendor-domain concurrency limits
- stale evidence invalidation
- schedule windows

Strict-growth promotion should prefer one open catalog-growth PR at a time. Source repair should prefer one open repair PR at a time. Support agent PRs are bounded and do not create strict-growth authority. Fresh source evidence is required before controlled promotion; stale evidence must be invalidated rather than reused.

## Failure Taxonomy

The failure taxonomy is `docs/operations/contracts/bot-failure-taxonomy.yaml`.

| Code | Operating meaning |
|---|---|
| `source_preflight_failure` | Source accessibility, source role, or source certainty could not be validated. |
| `redirect_canonicalization_failure` | Final URL or redirect authority is unclear. |
| `duplicate_url_failure` | Candidate overlaps an existing catalog source or queued candidate. |
| `terminology_contract_failure` | Output uses deprecated or non-OpenVA terminology. |
| `schema_validation_failure` | Contract, catalog, or generated artifact shape is invalid. |
| `generated_drift_failure` | Deterministic generated outputs do not match source files. |
| `workflow_input_compatibility_failure` | Workflow inputs are incompatible with current contract expectations. |
| `automerge_lane_mismatch` | Labels, paths, or PR state do not match the strict-growth automerge lane. |
| `external_fetch_instability` | External fetches are unstable, rate-limited, blocked, or inconsistent. |
| `stale_evidence_failure` | Evidence is older than the lane's stale-evidence limit. |
| `permission_policy_denial` | Requested action exceeds declared lane authority or token posture. |

Each failure class declares retry eligibility, retry policy, escalation target, hardening issue behavior, candidate deferral behavior, and lane-stop behavior.

## Exception Ownership

Exception ownership is required when source certainty is below the threshold for autonomous action.

| Exception | Owner role | Review checklist | Decision artifact | Expiry or recheck rule | Promotion path after approval |
|---|---|---|---|---|---|
| Cross-authority redirect | source-maintainer | confirm source owner, redirect target, final URL, and authority relationship | reviewed redirect note under `maintenance/reviewed/` or dashboard decision record | recheck before promotion if older than stale-evidence limit | controlled promotion or source repair after reviewed evidence |
| Possible legal-entity relationship | catalog-maintainer | confirm vendor entity, parent/subsidiary relationship, source scope, and public evidence | reviewed evidence record | expires when entity evidence changes or after scheduled recheck | controlled promotion with reviewed evidence |
| Ambiguous source-role coverage claim | source-maintainer | confirm whether source supports trust, security, privacy, status, or compliance claim | reviewed source-role decision | recheck when source page changes or evidence stales | source repair or controlled promotion |
| Vendor domain mismatch | catalog-maintainer | compare candidate domain, vendor identity, redirects, and authoritative source | reviewed domain decision | recheck before promotion if unresolved for more than one cycle | controlled promotion only after identity approval |
| Bot-protected page | source-maintainer | determine if public evidence is available without privileged access, scraping bypass, or trust portal login | source access decision | recheck on next source-health run | defer, quarantine, or promote only with public reviewed evidence |
| Source only available through trust portal | maintainer | confirm portal access posture, public alternative availability, and whether evidence can be represented | portal-source exception record | expires at next release readiness review | report-only unless public reviewed evidence supports promotion |

Exceptions that change catalog truth must flow through reviewed evidence and controlled promotion or source repair. They must not be applied directly from raw reviewer input, dashboard comments, or report-only lanes.

## Policy Simulation Before Activation

Any new or changed bot lane, write-authority expansion, destructive cleanup, or workflow retirement must run policy simulation before activation.

Required simulation outputs:

- dry-run mode
- sample PR generation
- policy diff
- blast-radius estimate
- expected action count
- failure-mode preview
- maintainer approval checklist

The policy diff must compare old and new lane authority, token permissions, allowed paths, labels, schedule, queue limits, and stale-evidence rules. Retirement simulation must classify the workflow under the retirement statuses below before disabling or deleting anything.

## Observability Metrics

OpenVA should maintain a bot-ops scorecard with:

- bot PRs opened
- bot PRs merged
- bot PRs failed before creation
- bot PRs closed
- human interventions per PR
- average time to merge
- failure reasons by class
- candidate conversion rate
- source preflight failure rate
- redirect canonicalization rate
- deferred backlog age
- review backlog age

Metrics should be grouped by lane id and failure code. The scorecard should distinguish discovery proposals, promotion actions, source repair, reviewed evidence handoffs, strict-growth PR safety outcomes, and publication outputs.

## Retirement And Sunset Rules

Workflow retirement is not part of WP9. Future retirement must happen only after classification under the bot operating model.

| Status | Meaning | Allowed triggers | Write permissions | Required labels | Retirement evidence |
|---|---|---|---|---|---|
| `active` | Current lane with declared authority and operating owner. | declared workflow triggers | only declared lane permissions | lane-specific labels when required | current contract entry and passing tests |
| `shadow_report_only` | Report-only lane used for comparison or migration evidence. | schedule or manual | no catalog truth writes | none unless PR comments are emitted | comparison report and owner decision |
| `deprecated_callable` | Callable for a bounded compatibility period. | manual only unless explicitly justified | no new write authority | maintainer approval label if any write state occurs | migration plan, replacement lane, sunset date |
| `quarantined` | Temporarily blocked from normal operation because authority, source certainty, or permissions are unsafe. | maintainer manual only | denied unless exception is approved | `openva-bot-paused` or equivalent hold | quarantine reason and reactivation checklist |
| `retired` | Removed from active operation after replacement or deprecation evidence is complete. | none | none | none | retirement PR, passing workflow inventory tests, retained audit trail |

Deprecated callable workflows must not become new authority expansion paths. Quarantined workflows must stop before mutation unless a maintainer records an exception.

## Security And Permission Posture

OpenVA bot security follows least privilege by lane:

- Use `GITHUB_TOKEN` unless a future contract explicitly authorizes a bot/app token.
- **Autonomous-merge token:** a PR opened with the default `GITHUB_TOKEN` does not trigger downstream workflows (the `agent-automerge` lanes), so an autonomous PR never self-merges. The PR-opening workflows (`observation-ledger-append-pr.yml`, `candidate-promotion-pr.yml`, `source-repair-pr.yml`) therefore create PRs with `${{ secrets.OPENVA_AUTOMERGE_TOKEN || github.token }}`. `OPENVA_AUTOMERGE_TOKEN` must be a least-privilege workflow-triggering token (a GitHub App installation token or a fine-scoped PAT with `contents:write` + `pull-requests:write` on this repo); until it is set, the workflows fall back to `github.token` and the opened PR waits for a maintainer to enable its automerge run. This token only authorizes PR creation/labeling; merge still requires the lane's checks and the release gate to pass.
- Do not add write scopes that are not required by the lane.
- Discovery and report-only lanes use read permissions except for issue/comment reporting when declared.
- Controlled promotion and source repair may write PR branches and open PRs only through declared workflows.
- PR safety may label, enable auto-merge, and merge only when labels, paths, checks, and strict-growth policy match.
- Labels that unlock write authority require maintainer action unless a contract explicitly allows automation to apply them.
- Automation may apply informational labels only when the lane contract allows PR labeling.
- Path boundaries are mandatory for branch-writing lanes.
- Permission-sensitive actions require an audit artifact.

Forbidden without a future authority contract:

- direct pushes to `main`
- catalog truth mutation from discovery
- catalog truth mutation from report-only lanes
- slash-command execution that creates or merges PRs
- retirement, deletion, disabling, or renaming of workflows
- widening auto-merge beyond declared strict-growth lanes
