import { generateKeyPairSync } from "node:crypto";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const outputDirectory = join(import.meta.dirname, "generated");
mkdirSync(outputDirectory, { recursive: true, mode: 0o700 });

const { publicKey, privateKey } = generateKeyPairSync("ed25519");
const privatePem = privateKey.export({ type: "pkcs8", format: "pem" });
const privateJwk = privateKey.export({ format: "jwk" });
const publicJwk = publicKey.export({ format: "jwk" });

if (
  privateJwk.kty !== "OKP" ||
  privateJwk.crv !== "Ed25519" ||
  typeof privateJwk.d !== "string" ||
  typeof privateJwk.x !== "string" ||
  publicJwk.kty !== "OKP" ||
  publicJwk.crv !== "Ed25519" ||
  publicJwk.x !== privateJwk.x
) {
  throw new Error("Node generated an unexpected or mismatched Ed25519 key pair");
}

const privatePemPath = join(outputDirectory, "openva-web-bot-auth-private.pem");
const privateJwkPath = join(outputDirectory, "openva-web-bot-auth-private.jwk.json");
const publicJwkPath = join(outputDirectory, "openva-web-bot-auth-public.jwk.json");
const privatePemBase64Path = join(outputDirectory, "openva-web-bot-auth-private.pem.b64");

writeFileSync(privatePemPath, privatePem, { mode: 0o600 });
writeFileSync(privateJwkPath, `${JSON.stringify(privateJwk)}\n`, { mode: 0o600 });
writeFileSync(publicJwkPath, `${JSON.stringify(publicJwk)}\n`, { mode: 0o600 });
writeFileSync(privatePemBase64Path, `${Buffer.from(privatePem).toString("base64")}\n`, { mode: 0o600 });

for (const path of [privatePemPath, privateJwkPath, publicJwkPath, privatePemBase64Path]) {
  chmodSync(path, 0o600);
}

console.log("Generated one matching Ed25519 identity under infra/cloudflare/openva-web-bot-auth/generated/.");
console.log("Treat every generated file as secret until the public JWK is copied into a runtime variable.");
console.log("Never commit or paste the private PEM, private JWK, or PEM base64 into an issue or pull request.");
