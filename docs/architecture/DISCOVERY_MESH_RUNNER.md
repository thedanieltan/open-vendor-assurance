# Discovery mesh runner architecture

The runner executes the discovery mesh over the full eligible catalog using deterministic partitions. No default vendor-count limit is applied.

Each worker:

1. selects its stable catalog shard;
2. discovers missing source types through the bounded HTML graph crawler;
3. verifies same-authority locator candidates;
4. emits delegated-host locators separately for further authority verification;
5. extracts subprocessor relationship identity signals;
6. writes report artifacts only.

The aggregate phase deduplicates worker output and may stage noncanonical `candidate_sources` records. It never creates canonical sources. Canonical mutation remains owned by `candidate-promotion-pr` and its existing validation, source preflight, release-gate, and automerge controls.

Scale is achieved by adding shards and workers, not by limiting catalog breadth.
