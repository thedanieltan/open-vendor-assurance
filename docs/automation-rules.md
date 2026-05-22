# Automation Rules

OpenVA automation converts routine human-review prompts into machine-executable rules or precise escalation criteria.

Agents follow these rules in an advisory-first rollout. A passing rule means the record may move to the next automated state. An escalation flag means the PR or queue item must surface for human review and must not be auto-merged.

## Rule Set A: New Vendor Records

A new vendor record may auto-promote to `catalog_status: stub` when all checks pass:

- `vendor_id` is globally unique.
- `official_domains` contains at least one domain.
- Each domain has WHOIS/RDAP evidence of existence, with registrar present and no known expiry.
- At least one `public_entrypoints` URL returns HTTP 200 or redirects with 301/302 to a public URL.
- No `official_domain` appears on another vendor record.
- `vendor_categories` includes at least one value from `config/category-taxonomy.yaml`.
- `source_policy.public_sources_only` is `true`.
- `not_advice: true` is present where the schema supports it.
- Schema validation passes.

Escalate when:

- A domain conflicts with another vendor record.
- A domain appears in `config/domain-blocklist.yaml` as CDN, reseller, white-label, gated, or login-wall infrastructure.
- `vendor_categories` includes `financial_services`, `healthcare`, or `government`.
- Any domain or public entrypoint returns HTTP 403 or a bot-protection signal.
- Legal name contains regulated terms such as Bank, Insurance, or Hospital.

Promotion from `stub` to `canonical` additionally requires:

- At least one source record with `source_authority_class` of `public_registry`, `public_authority`, or `vendor_published`.
- That source URL passes accessibility checks.
- Human approval or a 72-hour community veto window with no objection.

## Rule Set B: Source Records

A new source record may auto-promote to `review_state: auto_validated` when all checks pass:

- `source_url` returns HTTP 200 and is not behind an auth wall.
- The URL does not require login, CAPTCHA, or form submission.
- `source_type` is in the controlled vocabulary.
- `source_authority_class` is present and valid.
- `access_class` is `public_web`.
- `rights_class` is `metadata_only`.
- `not_advice` is `true`.
- `provenance.publisher` is present.
- `provenance.collected_at` is present and parseable.
- No raw document content is committed.
- Schema validation passes.
- `vendor_id` resolves to an existing vendor record.

Escalate when:

- URL returns 403, 429 after retry, or bot-protection headers.
- URL redirects more than three hops.
- `source_type` is not in the current controlled vocabulary.
- Content-Type suggests a document download rather than a web page.
- URL domain does not match an official domain or approved publisher exception.
- `source_language` is not `en`.
- `summary_en` contains prohibited advisory terms.

## Rule Set C: Entity Mentions

An entity mention may auto-promote to `resolution.status: matched_to_entity` when:

- `observed_name` matches a canonical legal entity `legal_name` exactly after case-folding and whitespace normalization.
- The matched entity `vendor_id` matches the mention `vendor_id`.
- `appears_in_source_id` resolves to an existing source.
- `assertion_source` is `vendor_published`.
- Schema validation passes.

Automation records this match provenance:

```yaml
match_method: legal_name_exact
matched_by: agent
match_confidence: high
matched_at: <observation timestamp>
match_source_ids:
  - <verification_source_id of matched entity>
```

Escalate when:

- `observed_name` matches no canonical entity exactly.
- `observed_name` matches multiple canonical entities.
- The mention and entity are cross-vendor.
- `observed_name` contains regulated legal terms.

## Rule Set D: Legal Entity Promotion

A legal entity may auto-promote from `catalog_status: stub` to `catalog_status: canonical` when:

- At least one `verification_source_id` resolves to a source with `source_authority_class: public_registry` or `public_authority`.
- That source URL returns HTTP 200.
- `legal_name` is present and non-empty.
- `jurisdiction` is a valid ISO 3166-1 alpha-2 code.
- `vendor_id` resolves to an existing vendor record.
- No `lifecycle_events` include `dissolved` or `merged` without `successor_entity_ids`.
- Schema validation passes.
- A 72-hour community veto window passes with no objection.

Escalate when:

- Verification source requires login or CAPTCHA.
- `registration_number` does not match a known jurisdiction pattern, such as Singapore UEN.
- `legal_name` differs from vendor `display_name` by more than 40 percent after normalization.
- Parent entity is in a different jurisdiction with no public explanation.

## Rule Set E: Wording And Advisory Boundary

The prohibited term scanner runs on every PR touching catalog records, docs, indexes, or adapter output.

Block advisory merge readiness when prohibited terms appear in:

- Catalog YAML field values, excluding source IDs and URLs.
- Generated index values.
- Adapter output field names or values.
- Docs outside an explicitly labelled negation or example-of-what-not-to-write context.

Warn, without blocking advisory score, when the term appears only in:

- A quoted vendor-published source title.
- A test fixture explicitly labelled invalid, negative, or calibration-only.
- `DISCLAIMER.md` or policy files in a clear negation context.

The scanner must be structured, not raw grep. It parses YAML/JSON, knows field paths, and is calibrated by committed pass/fail/ambiguous fixtures. Exemptions are narrow typed rules, not broad string matches.

## Rule Set F: Freshness And Observation

The scheduled observation agent runs weekly at first, then daily for high-priority vendors after the observation ledger is stable.

For each source with `access_class: public_web`, the observer:

- Fetches `source_url` with a compliant user-agent.
- Records HTTP status, final URL, and response headers.
- Computes SHA-256 of normalized response text when reachable.
- Compares the hash with the latest prior observation.
- Writes an observation with `catalog_tier: observation` and `review_state: auto_observed`.

Observation results:

- `reachable`
- `unreachable`
- `redirect_changed`
- `content_changed`
- `bot_protected`
- `auth_required`

Escalate when:

- `content_changed` and `source_type` is `dpa` or `privacy_notice`.
- Source is `unreachable` for three consecutive observations.
- `final_url` differs from `source_url`.
- HTTP status is 401 or 403.

Automation may update without human review:

- `freshness_status: current` to `stale`.
- `next_review_by` date.
- Observation record append.

## Governance Safeguard

No agent or validator score may override the policy hard gate. Changes to `GOVERNANCE.md`, `SECURITY.md`, `docs/automation-rules.md`, `docs/weighted-merge-policy.md`, or `policy/**` require explicit human approval from an org admin account.

This safeguard is enforced through CODEOWNERS expectations, workflow policy tests, and validator escalation. Branch protection enforces the admin approval outside repository code.
