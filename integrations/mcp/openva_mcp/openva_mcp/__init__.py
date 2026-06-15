"""Local-first, read-only MCP server over the OpenVA public export contract.

This package is a consumer adapter. It is not catalog authority, a hosted SaaS
service, a risk engine, or a write path. It reads the static, digest-verifiable
agent export tree (`openva-agent-index.json` and the per-vendor / index / latest
exports) and exposes a fixed set of read-only tools. It never mutates the
catalog, never requires a GitHub write token, and never emits advisory
conclusions.
"""

from openva_mcp.snapshot import (
    Snapshot,
    SnapshotError,
    SnapshotIntegrityError,
    SnapshotUnsupportedSchemaError,
)

__all__ = [
    "Snapshot",
    "SnapshotError",
    "SnapshotIntegrityError",
    "SnapshotUnsupportedSchemaError",
]

__version__ = "0.1.0"
