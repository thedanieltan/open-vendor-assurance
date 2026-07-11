"""Single authoritative accessor for human-facing source-type labels.

Machine source-type keys (``dpa``, ``subprocessors_list``, ...) are
compatibility-sensitive contract identifiers and are never renamed. Every
human-facing surface — browser UI data, static vendor pages, help text,
documentation tables, workbook legends, search filters, and search-engine
metadata — must obtain its display wording through this module so exactly
one label mapping exists in the repository
(``config/controlled-vocabulary.yaml`` -> ``source_type_labels``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_VOCAB_PATH = ROOT / "config" / "controlled-vocabulary.yaml"


@lru_cache(maxsize=1)
def _vocabulary() -> dict:
    return yaml.safe_load(_VOCAB_PATH.read_text(encoding="utf-8"))


def source_type_labels() -> dict[str, str]:
    """Return the machine-key -> human-facing label map, validated for drift.

    Raises ``ValueError`` when the label map and the ``source_types``
    vocabulary disagree, so a missing or orphaned label fails builds instead
    of silently dropping a source type from human-facing surfaces.
    """
    vocab = _vocabulary()
    source_types = list(vocab.get("source_types") or [])
    labels = dict(vocab.get("source_type_labels") or {})
    missing = [key for key in source_types if key not in labels]
    orphaned = [key for key in labels if key not in source_types]
    if missing:
        raise ValueError(f"source types missing a human-facing label: {missing}")
    if orphaned:
        raise ValueError(f"labels defined for unknown source types: {orphaned}")
    blank = [key for key, value in labels.items() if not str(value or "").strip()]
    if blank:
        raise ValueError(f"source types with a blank human-facing label: {blank}")
    return {key: str(labels[key]) for key in source_types}


def source_type_label(source_type: str) -> str:
    """Return the display label for one machine key (key itself if unknown).

    Unknown keys fall back to the machine key so factual output degrades
    readably instead of raising inside rendering paths.
    """
    return source_type_labels().get(source_type, source_type)
