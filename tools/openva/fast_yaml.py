"""Fast, safe YAML loading for the hot record-loading paths.

Parsing dominates the build: loading the ~7,400 committed record YAMLs is ~99% of
`build_indexes` (and the bulk of `validate`), and it runs on every PR. `yaml.safe_load` always
uses the pure-Python `SafeLoader` even when libyaml is installed, so the C speedup is left on
the table. This module uses `CSafeLoader` when libyaml is available (≈10x faster on this tree)
and falls back to the pure-Python `SafeLoader` otherwise.

Both are YAML-1.1 safe loaders with identical results for the repository's records, so `load`
is a behaviour-preserving drop-in for `yaml.safe_load`. Where libyaml is absent (e.g. a distro
PyYAML without the C extension), behaviour and speed are exactly as before.
"""

from __future__ import annotations

from typing import Any

import yaml

try:  # libyaml-backed loader; present in the manylinux PyYAML wheels used in CI
    from yaml import CSafeLoader as _Loader
except ImportError:  # pragma: no cover - environment without the libyaml C extension
    from yaml import SafeLoader as _Loader

#: True when the fast libyaml loader is active (informational; not required for correctness).
USING_LIBYAML = _Loader.__name__ == "CSafeLoader"


def load(stream: Any) -> Any:
    """Parse a YAML document from a string or file object (drop-in for yaml.safe_load)."""
    return yaml.load(stream, Loader=_Loader)
