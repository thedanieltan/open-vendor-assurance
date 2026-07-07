# Local-First Resolution Doctrine

OpenVA is local-first resolution infrastructure. It is not a SaaS, not a
hosted CSV processor, and not an operated resolver service.

OpenVA defines:

- a versioned resolver/result-pack contract;
- a reference engine that consumers run themselves;
- a community index of candidate hints, never an oracle.

OpenVA does not process user vendor inventories.

Live resolution executes on the consumer side: CLI, local engine, MCP server,
or forked deployment. The consumer environment owns runtime execution, network
egress, credentials for its own environment, logs, retention, and operational
controls.

The public/community index is hint-only. It records candidate locators and
public metadata that may help a resolver decide what to check, but it must not
be treated as authoritative evidence. Community hints, vendor assertions, and
cached locators remain unverified candidate inputs until the consumer performs a
live resolver run.

Final truth comes only from a live resolver run performed by the consumer
environment. Static browsing, cached index lookup, and community hints can
prepare candidate inputs; they do not establish verified outcomes.

OpenVA owns the shape of the answer, not the runtime. The result pack is the
product boundary: a consumer-run resolver emits the OpenVA result-pack contract
so downstream systems can inspect identity, candidate basis, verification basis,
source outcomes, timestamps, and the non-advisory boundary deterministically.

Canonical boundary phrase: result pack is the product boundary.

A hosted OpenVA resolver or hosted OpenVA API is explicitly out of scope unless
a future ADR reverses this doctrine. Until then, do not build hosted APIs,
accounts, billing, BYOK, server-side CSV uploads, or a live worker operated by
OpenVA.

Operational metadata only. Nothing in this doctrine is legal, compliance,
procurement, security, KYC, AML, audit, vendor-risk, approval, suitability, or
recommendation advice.
