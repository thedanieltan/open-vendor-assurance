# OpenVA crawler identity and access policy

OpenVA performs bounded retrieval of public vendor-assurance sources. It does not operate a general search engine and does not collect content for model training.

## Identities

| User agent | Purpose | Cloudflare behavioral category |
| --- | --- | --- |
| `OpenVA-Discovery` | Read `robots.txt` and same-authority sitemaps to identify candidate assurance URLs | Data Collection; Monitoring & Operations |
| `OpenVA-SourceVerifier/0.1 (+https://github.com/thedanieltan/open-vendor-assurance)` | Check the reachability and metadata of registered public sources | Monitoring & Operations |

Both identities use the same Web Bot Auth key directory and operator identity. Their functions remain separate so website owners can identify the request purpose from ordinary access logs.

## Commitments

OpenVA:

- accesses public HTTP(S) sources only;
- identifies itself deterministically;
- obeys applicable `robots.txt` Allow and Disallow rules;
- applies the largest valid `Crawl-delay` from the most-specific matching group;
- uses bounded request counts, deadlines, redirects, and response sizes;
- does not use logins, cookies, customer portals, form submissions, CAPTCHA solving, WAF evasion, browser impersonation, or alternate identities after a block;
- does not automatically accept pay-per-crawl offers or retry with payment intent;
- treats a block as an access observation, not evidence that a vendor source is invalid;
- does not retain raw fetched documents by default;
- uses fetched material as reference metadata and hashes, not for AI model training.

## Verification taxonomy coverage

Source verification may classify registered public sources across the full source-type vocabulary supported by the catalog schema. Broad semantic coverage is used only to reduce false `not_evaluated_unknown_source_type` results during verification; it does not by itself authorize automated discovery, promotion, or catalog materialization of those source types.

## Web Bot Auth

When configured, OpenVA signs every SSRF-safe verification request with Ed25519 HTTP Message Signatures. The signature covers:

```text
@authority
signature-agent
```

Each redirect hop is revalidated by the existing fetch boundary and receives a new authority-bound signature. Signatures expire after 60 seconds and include a fresh nonce.

Configuration is environment-gated. All three values must be present:

```text
OPENVA_WEB_BOT_AUTH_DIRECTORY_URL
OPENVA_WEB_BOT_AUTH_PUBLIC_JWK_JSON
OPENVA_WEB_BOT_AUTH_PRIVATE_KEY_PEM_B64
```

A partial configuration stops the fetch rather than falling back to malformed or misleading identity headers. No generated key material belongs in Git, workflow artifacts, reports, logs, or issue comments.

## Key directory

The deployment artifact under `infra/cloudflare/openva-web-bot-auth/` serves the required signed JWKS response from a Cloudflare Worker. GitHub Pages is not used for this endpoint because a static file cannot generate the fresh response signature required by Cloudflare.

## Access-result semantics

Cloudflare verification authenticates OpenVA; it does not override a site owner's policy. A site can still block the crawler, restrict its category, apply rate limits, require authentication, or return a pay-per-crawl response.

OpenVA never interprets access failure as assurance evidence. Existing `bot_protected`, `auth_required`, `rate_limited`, and `unreachable` outcomes remain review signals. HTTP `402 Payment Required` must be treated as a non-paying access-policy result once the dedicated taxonomy change is activated; OpenVA must not submit payment automatically.

## Submission checklist

1. Generate a unique Ed25519 key outside the repository.
2. Deploy the Worker and store its signing JWK as a Worker secret.
3. Validate the signed directory response.
4. Configure the matching public JWK, PEM key, and directory URL in the crawler runtime.
5. Test signed requests against Cloudflare's Web Bot Auth test endpoint.
6. Run a bounded OpenVA maintenance smoke test and verify that signatures are regenerated on redirects.
7. Submit the Bot Submission Form using **Request Signature**.
8. Request Data Collection and Monitoring & Operations classification; do not request Training.
9. Retain the ability to rotate the key and update both the Worker secret and crawler runtime atomically.

## Contact

Operational questions and block reports should be filed in the public repository issue tracker. Reports must not include private credentials, customer portal content, generated signing keys, or other secrets.
