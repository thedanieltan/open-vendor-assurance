const DIRECTORY_PATH = "/.well-known/http-message-signatures-directory";
const encoder = new TextEncoder();

function b64(bytes) {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function b64url(bytes) {
  return b64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function digestId(jwk) {
  const canonical = JSON.stringify({ crv: "Ed25519", kty: "OKP", x: jwk.x });
  return b64url(await crypto.subtle.digest("SHA-256", encoder.encode(canonical)));
}

async function directory(request, env) {
  if (!env.OPENVA_SIGNING_JWK) return new Response("not configured", { status: 503 });
  const signingJwk = JSON.parse(env.OPENVA_SIGNING_JWK);
  if (signingJwk.kty !== "OKP" || signingJwk.crv !== "Ed25519" || !signingJwk.x) {
    return new Response("invalid signing configuration", { status: 503 });
  }
  const published = { kty: "OKP", crv: "Ed25519", x: signingJwk.x };
  const keyId = await digestId(published);
  const created = Math.floor(Date.now() / 1000);
  const expires = created + 60;
  const nonce = b64(crypto.getRandomValues(new Uint8Array(32)));
  const authority = new URL(request.url).host;
  const params = `("@authority";req);alg="ed25519";keyid="${keyId}";nonce="${nonce}";tag="http-message-signatures-directory";created=${created};expires=${expires}`;
  const signatureBase = `"@authority";req: ${authority}\n"@signature-params": ${params}`;
  const key = await crypto.subtle.importKey("jwk", signingJwk, { name: "Ed25519" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("Ed25519", key, encoder.encode(signatureBase));
  return new Response(JSON.stringify({ keys: [published] }), {
    headers: {
      "Content-Type": "application/http-message-signatures-directory+json",
      "Cache-Control": "public, max-age=86400",
      "Signature-Input": `openva-directory=${params}`,
      "Signature": `openva-directory=:${b64(signature)}:`,
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET") return new Response("method not allowed", { status: 405 });
    if (url.pathname === DIRECTORY_PATH) return directory(request, env);
    if (url.pathname === "/healthz") return new Response("ok");
    return new Response("not found", { status: 404 });
  },
};
