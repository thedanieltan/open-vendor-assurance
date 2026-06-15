"""Load and digest-verify an OpenVA agent export tree.

Two data modes are supported:

- **pinned_local** — an operator-supplied export tree or extracted agent-export release bundle on disk.
- **hosted_static** — the public agent index and export tree fetched over HTTP.

Integrity is the central invariant. Every export carries a ``snapshot`` block
with a ``digest`` computed as ``sha256`` over the file's canonical JSON
*excluding* the snapshot block (the agent export convention). The root index
additionally lists the digest of every other file. A file is only ever
represented as verified once its recomputed digest matches both its own
snapshot block and the index's listed digest. A mismatch fails closed
(``SnapshotIntegrityError``) rather than returning unverified data as if it
were trustworthy.

Remote reads may fall back to a previously cached snapshot only when the exact
cached snapshot identity (commit + digest) is disclosed on every result.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

SUPPORTED_SCHEMA_VERSION = "0.1.0"

AGENT_INDEX_FILE = "openva-agent-index.json"
VENDORS_INDEX_FILE = "vendors/index.json"
SOURCES_INDEX_FILE = "sources/index.json"
OBSERVATIONS_LATEST_FILE = "observations/latest.json"
CHANGES_LATEST_FILE = "changes/latest.json"

# Logical name -> path, for the files the root index lists in its `exports` map.
# This is the exact required set: the root index must declare these and only
# these named exports.
INDEX_EXPORTS = {
    "vendors_index": VENDORS_INDEX_FILE,
    "sources_index": SOURCES_INDEX_FILE,
    "observations_latest": OBSERVATIONS_LATEST_FILE,
    "changes_latest": CHANGES_LATEST_FILE,
}

VENDOR_EXPORT_PREFIX = "vendors/"
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


class SnapshotError(Exception):
    """Base class for snapshot load/verify failures."""


class SnapshotIntegrityError(SnapshotError):
    """A digest did not match — the snapshot is not trustworthy."""


class SnapshotUnsupportedSchemaError(SnapshotError):
    """The export schema_version is outside the supported range."""


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_digest(payload: dict[str, Any]) -> str:
    """Digest over a payload excluding its own snapshot block."""
    material = {key: value for key, value in payload.items() if key != "snapshot"}
    return "sha256:" + hashlib.sha256(canonical_json(material)).hexdigest()


class SnapshotSource(Protocol):
    """A read-only byte source for a single export tree."""

    mode: str

    def read_bytes(self, rel_path: str) -> bytes: ...

    def identity(self) -> str: ...


def _safe_rel(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if Path(rel_path).is_absolute() or ".." in parts:
        raise SnapshotError(f"unsafe export path: {rel_path}")
    return rel_path


class LocalSnapshotSource:
    """Read an export tree from a directory on disk."""

    mode = "pinned_local"

    def __init__(self, root: str | Path):
        root = Path(root)
        # Accept either the export root itself or a release dir whose exports
        # live under public/ (the layout the site build publishes).
        if (root / AGENT_INDEX_FILE).is_file():
            self.root = root
        elif (root / "public" / AGENT_INDEX_FILE).is_file():
            self.root = root / "public"
        else:
            raise SnapshotError(f"{root}: no {AGENT_INDEX_FILE} found (looked in ./ and ./public/)")

    def read_bytes(self, rel_path: str) -> bytes:
        # resolve() follows symlinks, so a symlink escaping the snapshot root
        # resolves outside it and is rejected by the containment check.
        path = (self.root / _safe_rel(rel_path)).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise SnapshotError(f"export path escapes snapshot root: {rel_path}")
        if not path.is_file():
            raise SnapshotError(f"missing export file: {rel_path}")
        return path.read_bytes()

    def identity(self) -> str:
        return str(self.root)


def _validate_base_url(base_url: str) -> str:
    """Validate a hosted-mode base URL and normalize its trailing slash.

    Only http/https are accepted; `file:` access is confined to pinned-local
    mode (LocalSnapshotSource). Embedded credentials and fragments are rejected
    so the base URL stays plain operator configuration.
    """
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https"):
        raise SnapshotError(f"hosted base URL must be http(s): {base_url!r}")
    if parts.username or parts.password:
        raise SnapshotError("hosted base URL must not embed credentials")
    if parts.fragment:
        raise SnapshotError("hosted base URL must not contain a fragment")
    if not parts.netloc:
        raise SnapshotError(f"hosted base URL has no host: {base_url!r}")
    return base_url if base_url.endswith("/") else base_url + "/"


def _http_fetch(url: str, *, timeout: float = 30.0) -> bytes:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - https base URL, read-only GET
        return response.read()


class RemoteSnapshotSource:
    """Read an export tree from a hosted base URL.

    `fetch` is injectable so the network layer can be replaced in tests. An
    optional local cache directory provides a disclosed fallback when a remote
    read fails; any file served from cache sets `last_read_from_cache`.
    """

    mode = "hosted_static"

    def __init__(
        self,
        base_url: str,
        *,
        fetch: Callable[[str], bytes] = _http_fetch,
        cache_dir: str | Path | None = None,
    ):
        self.base_url = _validate_base_url(base_url)
        self._fetch = fetch
        self.cache_dir = Path(cache_dir) if cache_dir else None
        # Per-read flag (reset on every read) plus the set of paths ever served
        # from cache, so a result can disclose any cache use precisely.
        self.last_read_from_cache = False
        self.cached_paths: set[str] = set()

    def read_bytes(self, rel_path: str) -> bytes:
        rel_path = _safe_rel(rel_path)
        url = urljoin(self.base_url, rel_path)
        self.last_read_from_cache = False
        try:
            data = self._fetch(url)
        except Exception as exc:  # network/HTTP failure: try the disclosed cache
            cached = self._read_cache(rel_path)
            if cached is None:
                raise SnapshotError(f"remote fetch failed for {rel_path}: {exc}") from exc
            self.last_read_from_cache = True
            self.cached_paths.add(rel_path)
            return cached
        self._write_cache(rel_path, data)
        return data

    def _cache_path(self, rel_path: str) -> Path | None:
        return (self.cache_dir / rel_path) if self.cache_dir else None

    def _read_cache(self, rel_path: str) -> bytes | None:
        path = self._cache_path(rel_path)
        if path and path.is_file():
            return path.read_bytes()
        return None

    def _write_cache(self, rel_path: str, data: bytes) -> None:
        path = self._cache_path(rel_path)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def identity(self) -> str:
        return self.base_url


@dataclass(frozen=True)
class FileVerification:
    path: str
    expected_digest: str | None
    computed_digest: str
    self_digest: str
    match: bool


@dataclass
class Snapshot:
    """A loaded, integrity-checked export tree."""

    source: SnapshotSource
    agent_index: dict[str, Any]
    from_cache: bool = False
    _cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        return self.source.mode

    @property
    def commit_sha(self) -> str:
        return str(self.agent_index.get("snapshot", {}).get("commit_sha", ""))

    @property
    def digest(self) -> str:
        return str(self.agent_index.get("snapshot", {}).get("digest", ""))

    @property
    def generated_at(self) -> str:
        return str(self.agent_index.get("snapshot", {}).get("generated_at", ""))

    @classmethod
    def load(cls, source: SnapshotSource) -> "Snapshot":
        agent_index = _load_json(source, AGENT_INDEX_FILE)
        _require_supported_schema(agent_index, AGENT_INDEX_FILE)
        # The root index proves its own integrity via its self-digest.
        declared = str(agent_index.get("snapshot", {}).get("digest", ""))
        computed = payload_digest(agent_index)
        if declared != computed:
            raise SnapshotIntegrityError(
                f"{AGENT_INDEX_FILE}: self digest mismatch (declared {declared}, computed {computed})"
            )
        _validate_root_index(agent_index)
        from_cache = bool(getattr(source, "last_read_from_cache", False))
        return cls(source=source, agent_index=agent_index, from_cache=from_cache)

    # --- verified loaders -------------------------------------------------

    def _required_paths(self) -> set[str]:
        return set(INDEX_EXPORTS.values()) | set(self.vendor_export_paths().values())

    def _expected_digest(self, rel_path: str) -> str:
        for entry in self.agent_index.get("exports", {}).values():
            if entry.get("path") == rel_path:
                return str(entry["digest"])
        for entry in self.agent_index.get("vendor_exports", []):
            if entry.get("path") == rel_path:
                return str(entry["digest"])
        # A required export must be linked from the root index; never treat a
        # missing required digest as "optional" and skip the cross-check.
        raise SnapshotIntegrityError(f"{rel_path}: not linked from the agent index")

    def load_verified(self, rel_path: str) -> dict[str, Any]:
        if rel_path in self._cache:
            return self._cache[rel_path]
        document = _load_json(self.source, rel_path)
        _require_supported_schema(document, rel_path)
        computed = payload_digest(document)
        declared = str(document.get("snapshot", {}).get("digest", ""))
        expected = self._expected_digest(rel_path)  # raises if not linked
        if computed != declared:
            raise SnapshotIntegrityError(f"{rel_path}: self digest mismatch")
        if computed != expected:
            raise SnapshotIntegrityError(
                f"{rel_path}: digest does not match the agent index ({computed} != {expected})"
            )
        self.from_cache = self.from_cache or bool(getattr(self.source, "last_read_from_cache", False))
        self._cache[rel_path] = document
        return document

    def vendors_index(self) -> dict[str, Any]:
        return self.load_verified(VENDORS_INDEX_FILE)

    def sources_index(self) -> dict[str, Any]:
        return self.load_verified(SOURCES_INDEX_FILE)

    def observations_latest(self) -> dict[str, Any]:
        return self.load_verified(OBSERVATIONS_LATEST_FILE)

    def changes_latest(self) -> dict[str, Any]:
        return self.load_verified(CHANGES_LATEST_FILE)

    def vendor_export(self, vendor_id: str) -> dict[str, Any] | None:
        for entry in self.agent_index.get("vendor_exports", []):
            if entry.get("vendor_id") == vendor_id:
                return self.load_verified(entry["path"])
        return None

    def vendor_export_paths(self) -> dict[str, str]:
        return {
            entry["vendor_id"]: entry["path"]
            for entry in self.agent_index.get("vendor_exports", [])
            if entry.get("vendor_id") and entry.get("path")
        }

    # --- snapshot-level metadata & verification ---------------------------

    def provenance(self) -> dict[str, Any]:
        """Snapshot identity that every tool result must carry."""
        return {
            "mode": self.mode,
            "source": self.source.identity(),
            "commit_sha": self.commit_sha,
            "digest": self.digest,
            "generated_at": self.generated_at,
            "schema_version": self.agent_index.get("schema_version"),
            "from_cache": self.from_cache,
            "not_advice": True,
        }

    def verify(self) -> dict[str, Any]:
        """Recompute, schema-check, and cross-check every export in the tree.

        Schema enforcement is part of verification, not just digest comparison:
        an unsupported schema_version raises ``SnapshotUnsupportedSchemaError``
        (which the CLI turns into a non-zero exit) rather than reporting ok.
        """
        results: list[FileVerification] = [self._verify_one(AGENT_INDEX_FILE, self.agent_index, self.digest)]
        for rel_path in list(INDEX_EXPORTS.values()) + list(self.vendor_export_paths().values()):
            document = _load_json(self.source, rel_path)
            _require_supported_schema(document, rel_path)
            self.from_cache = self.from_cache or bool(getattr(self.source, "last_read_from_cache", False))
            results.append(self._verify_one(rel_path, document, self._expected_digest(rel_path)))
        ok = all(item.match for item in results)
        return {
            "ok": ok,
            "commit_sha": self.commit_sha,
            "digest": self.digest,
            "generated_at": self.generated_at,
            "files": [item.__dict__ for item in results],
            "from_cache": self.from_cache,
            "not_advice": True,
        }

    @staticmethod
    def _verify_one(rel_path: str, document: dict[str, Any], expected: str | None) -> FileVerification:
        computed = payload_digest(document)
        self_digest = str(document.get("snapshot", {}).get("digest", ""))
        # For the root index `expected` is its own self-digest; for the rest it
        # is the index-listed digest. Both must match the recomputed value.
        match = computed == self_digest and (expected is None or computed == expected)
        return FileVerification(rel_path, expected, computed, self_digest, match)


def _load_json(source: SnapshotSource, rel_path: str) -> dict[str, Any]:
    try:
        document = json.loads(source.read_bytes(rel_path))
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{rel_path}: invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SnapshotError(f"{rel_path}: expected a JSON object")
    return document


def _require_supported_schema(document: dict[str, Any], rel_path: str) -> None:
    version = document.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise SnapshotUnsupportedSchemaError(
            f"{rel_path}: unsupported schema_version {version!r} (supported: {SUPPORTED_SCHEMA_VERSION})"
        )


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(DIGEST_RE.match(value))


def _validate_root_index(agent_index: dict[str, Any]) -> None:
    """Enforce completeness and linkage of the root index.

    The named ``exports`` map must contain exactly the required entries, each at
    its expected path with a valid digest; vendor exports must have unique ids
    and unique safe paths of the form ``vendors/{vendor_id}.json`` with valid
    digests. A malformed root index is an integrity failure, not a soft warning.
    """
    exports = agent_index.get("exports")
    if not isinstance(exports, dict):
        raise SnapshotIntegrityError("agent index: exports map missing or not an object")
    if set(exports) != set(INDEX_EXPORTS):
        raise SnapshotIntegrityError(
            f"agent index: exports must be exactly {sorted(INDEX_EXPORTS)} (got {sorted(exports)})"
        )
    for name, expected_path in INDEX_EXPORTS.items():
        entry = exports.get(name) or {}
        if entry.get("path") != expected_path:
            raise SnapshotIntegrityError(f"agent index: export {name} must point to {expected_path}")
        if not _valid_digest(entry.get("digest")):
            raise SnapshotIntegrityError(f"agent index: export {name} has an invalid digest")

    vendor_exports = agent_index.get("vendor_exports")
    if not isinstance(vendor_exports, list):
        raise SnapshotIntegrityError("agent index: vendor_exports missing or not a list")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for entry in vendor_exports:
        vendor_id = entry.get("vendor_id") if isinstance(entry, dict) else None
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(vendor_id, str) or not vendor_id:
            raise SnapshotIntegrityError("agent index: vendor export missing vendor_id")
        if vendor_id in seen_ids:
            raise SnapshotIntegrityError(f"agent index: duplicate vendor_id {vendor_id}")
        seen_ids.add(vendor_id)
        if not isinstance(path, str):
            raise SnapshotIntegrityError(f"agent index: vendor export {vendor_id} missing path")
        try:
            _safe_rel(path)
        except SnapshotError as exc:
            raise SnapshotIntegrityError(f"agent index: vendor export {vendor_id} has unsafe path") from exc
        if path != f"{VENDOR_EXPORT_PREFIX}{vendor_id}.json":
            raise SnapshotIntegrityError(f"agent index: vendor export path {path} does not match id {vendor_id}")
        if path in seen_paths:
            raise SnapshotIntegrityError(f"agent index: duplicate vendor export path {path}")
        seen_paths.add(path)
        if not _valid_digest(entry.get("digest")):
            raise SnapshotIntegrityError(f"agent index: vendor export {vendor_id} has an invalid digest")
