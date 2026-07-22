from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_prohibited_terms(path: Path | None = None) -> list[str]:
    config_path = path or ROOT / "config" / "prohibited-claims.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return [str(term).lower() for term in config.get("prohibited_terms", [])]


def term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9_-])" + re.escape(term) + r"(?![a-z0-9_-])")


def prohibited_terms_in_text(text: Any, terms: list[str] | None = None) -> list[str]:
    lower = str(text or "").lower()
    return [term for term in terms or load_prohibited_terms() if term_pattern(term).search(lower)]
