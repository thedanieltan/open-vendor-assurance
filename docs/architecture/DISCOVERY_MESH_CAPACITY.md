# OpenVA discovery mesh capacity posture

OpenVA does not impose a maximum vendor-catalog size.

The discovery mesh distinguishes between:

- **catalog capacity** — unbounded; every independently resolvable vendor may enter the candidate and admission lifecycle;
- **run partitioning** — operational sharding only, so work can resume and retry independently;
- **per-vendor crawl budgets** — bounded network safety controls for pages, requests, links, response sizes, redirects, and delegated hosts;
- **promotion isolation** — canonical mutations remain independently reviewable and reversible.

A numeric page or request budget is never a catalog-vendor ceiling. Scheduled execution must process the complete eligible vendor set through deterministic shards unless an operator explicitly supplies a temporary `vendor_limit` for diagnostics or incident response.

The crawler may grow to thousands or millions of vendor identity signals. Capacity is governed by queue partitioning, deduplication, backpressure, retry timing, provider yield, and evidence quality—not by an arbitrary catalog-size cap.

This document is operational metadata only. It is not legal, compliance, procurement, security, KYC, AML, audit, certification, or vendor-risk advice.
