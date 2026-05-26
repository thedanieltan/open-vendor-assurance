# P0 Source Cleanup Runbook

This runbook describes the OpenVA P0 source cleanup loop for broken or unavailable public source links.

The loop is intentionally conservative. It must not invent vendor URLs, mass-repair the catalog, or move ambiguous records into strict repair PRs. When a vendor does not publish an accessible public source, the correct state is source unavailable / no replacement, not a guessed URL.

## When To Run Source Maintenance

Run `source-maintenance-report` when:

- A source-trust cleanup cycle starts.
- A source repair batch has merged and maintainers need before/after counts.
- A maintainer needs a fresh view of unavailable, ambiguous, soft-404, or quality-risk source records.
- A scheduled maintenance run indicates source health has drifted.

Use the workflow on `main`:

```bash
gh workflow run source-maintenance-report.yml --ref main
```

After the run completes, download `openva-source-maintenance-report` and inspect the source repair artifacts.

## Reading The Artifacts

`source-repair-sweep-summary.md` gives the high-level state:

- `strict_repair_ready_count`: rows that may feed a small reviewed repair batch.
- `human_review_required_count`: rows that are not safe for automatic repair.
- `no_replacement_found_count`: rows where no verified public vendor-controlled replacement was found.
- `p0_remaining_count`: confirmed hard unavailable records, when derivable.
- soft-404, redirect-drift, access-ambiguous, and quality counts.

`source-repair-sweep-human-review.csv` is the reviewer queue for ambiguous or quality-risk records. These rows may include access-blocked endpoints, possible mismatches, inferred URLs, soft 404s, and canonical drift. They must not enter strict repair PRs.

`source-repair-sweep-no-replacement.csv` lists records where no verified public vendor-controlled replacement exists. These should remain unavailable / not available unless a maintainer verifies that the vendor later published a usable public source.

`source-repair-batch-plan.json` is the strict batch candidate plan. It is the only artifact that can feed reviewed P0 repair validation. If `repairs` is empty, no repair PR should be generated.

## When Strict Repair Ready Is Greater Than Zero

If `strict_repair_ready_count > 0` and `source-repair-batch-plan.json` contains repairs:

1. Confirm the batch is capped at 10 records.
2. Validate the batch using the existing P0 repair validation flow.
3. Commit the reviewed validation artifact under `maintenance/reviewed/`.
4. Use `source-repair-pr` to create a small `Catalog: repair` PR.
5. Inspect changed source YAML and generated index/dist changes.
6. Verify replacements are final canonical URLs.
7. Verify there is no `soft_404_detected`, redirect canonical drift, access ambiguity, weak semantic match, inferred URL, or source-type ambiguity.
8. Merge only after human review.

## When Strict Repair Ready Is Zero

If `strict_repair_ready_count = 0` or `source-repair-batch-plan.json` has zero repairs:

- Do not create a reviewed validation artifact.
- Do not run `source-repair-pr`.
- Do not generate a catalog mutation PR.
- Produce or refresh the source review triage handoff.
- Route records to manual review or no-replacement handling.

Zero strict repairs means the current sweep did not find any row that satisfied all strict P0 repair criteria. The correct action is triage, not mutation.

## Why Source Repair PR Must Not Run On Empty Batches

`source-repair-pr` applies reviewed repair plans to catalog source YAML. Running it when `source-repair-batch-plan.json` has zero repairs creates operational noise and can obscure the important truth state: there are no safe automatic repairs in the current sweep.

An empty strict batch means no source URL replacement has passed the strict gate. The repair PR workflow must remain reserved for small, audited, human-reviewed repair batches.

## Why Non-Strict Rows Must Not Enter Repair PRs

`human_review_required` and `no_replacement_found` rows are explicitly outside the strict repair lane.

- `human_review_required` means the source needs manual interpretation before replacement.
- `no_replacement_found` means no verified public vendor-controlled replacement exists.

Moving these rows into repair PRs would risk invented URLs, semantic mismatches, pre-redirect URLs, soft 404s, or replacing a source that the vendor does not publicly publish.

## Handling Ambiguous States

Treat these states as non-strict:

- `soft_not_found`: HTTP 200 is not enough. Confirm the page content is real, relevant, and not a soft 404.
- `redirect_canonical_drift`: verify the final canonical URL and store that final URL only after review.
- `access_ambiguous`: do not infer validity when access is blocked or unclear.
- `bot_protected`: record that the endpoint may exist, but content and semantics are not verified.
- `forbidden_unknown`: review manually; do not assume vendor authority or content match.
- `gated_or_login_required`: exclude from public-source repair unless a public source exists.
- `possible_mismatch`: verify the content matches the expected source type.
- `homepage_or_generic_redirect`: find a specific source URL, or leave unresolved.
- `suspect_inferred_url`: confirm the URL is real, public, vendor-controlled, and semantically correct.

## No Invented URLs

Do not synthesize likely paths such as `/legal/dpa`, `/subprocessors`, `/security`, or `/trust` as replacements. Discovery may report candidates, but candidates remain review material until verified.

If no public vendor-controlled source is available, preserve the unavailable/no-replacement state.

## Truth-State Distinctions

Strict repair:

- Confirmed hard P0 source.
- Public replacement exists.
- Replacement is vendor-controlled or approved exception.
- Replacement is semantically strong.
- Replacement final URL is canonical.
- No soft 404, access ambiguity, inferred URL, source-type ambiguity, or self-certifying fields.

Manual review:

- A source or replacement may exist, but content, access, authority, canonical URL, or semantic match is uncertain.

Source unavailable / no replacement:

- The original source appears unavailable and no verified public vendor-controlled replacement exists.
- This is not a claim that the vendor is wrong; it records that OpenVA has no usable public source at this time.

## Definition Of Done

A P0 cleanup cycle is done when:

- `source-maintenance-report` has been run on current `main`.
- Strict repair-ready rows are either repaired through small reviewed PRs or explicitly deferred.
- Empty strict batches stop without repair PR generation.
- Human-review rows are exported to a reviewer triage handoff.
- No-replacement rows are surfaced without invented URLs.
- No Layer 2C, ambiguous, soft-404, access-blocked, weak-match, redirect-drifted, or no-replacement row is automatically repaired.
- The final summary reports before/after counts for confirmed P0, `not_found`, `soft_not_found`, `human_review_required`, `no_replacement_found`, and `strict_repair_ready`.
- The public source health snapshot has been regenerated by source maintenance.
