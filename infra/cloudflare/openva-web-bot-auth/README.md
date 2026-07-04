# OpenVA Web Bot Auth directory

This Cloudflare Worker serves OpenVA's signed HTTP Message Signatures key directory at:

```text
/.well-known/http-message-signatures-directory
```

It is intentionally independent of the static GitHub Pages site because Cloudflare requires the directory response itself to carry fresh `Signature` and `Signature-Input` headers.

## Generate an Ed25519 key

Generate the key locally. Do not commit generated key material.

```bash
openssl genpkey -algorithm ed25519 -out openva-web-bot-auth.pem
```

Convert the key to a private JWK using a trusted local tool that preserves `kty`, `crv`, `x`, and `d`. The Worker's `OPENVA_SIGNING_JWK` secret must contain that JSON object. The Worker publishes only `kty`, `crv`, and `x`; it never returns `d`.

## Deploy

```bash
cd infra/cloudflare/openva-web-bot-auth
npx wrangler secret put OPENVA_SIGNING_JWK
npx wrangler deploy
```

Confirm both endpoints:

```bash
curl -i https://<worker-host>/.well-known/http-message-signatures-directory
curl -i https://<worker-host>/healthz
```

The directory response must have:

- status `200`;
- `Content-Type: application/http-message-signatures-directory+json`;
- `Signature` and `Signature-Input` headers;
- a JWKS body containing one Ed25519 public key.

Validate the endpoint with Cloudflare's `http-signature-directory` tooling before applying to Verified Bots.

## Configure the crawler

Set these only in the scheduled runtime, never in the repository:

```text
OPENVA_WEB_BOT_AUTH_DIRECTORY_URL=https://<worker-host>/.well-known/http-message-signatures-directory
OPENVA_WEB_BOT_AUTH_PUBLIC_JWK_JSON={"kty":"OKP","crv":"Ed25519","x":"..."}
OPENVA_WEB_BOT_AUTH_PRIVATE_KEY_PEM_B64=<base64-of-openva-web-bot-auth.pem>
```

The public JWK and PEM must describe the same Ed25519 key. OpenVA fails closed on partial configuration. When all variables are absent, existing unsigned behavior is preserved.

## Cloudflare submission

In the Cloudflare dashboard, open **Manage Account → Configurations → Bot Submission Form** and select **Request Signature**. Submit the directory URL and both OpenVA user agents. Describe the crawler as public-source assurance metadata collection and monitoring, with reference-only content use, no AI training, no access-control bypass, no automatic payment, and no raw-document retention.
