from __future__ import annotations

import hashlib
import re
from html import unescape


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalize_text(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sha256_normalized_text(data: bytes, content_type: str | None = None) -> str:
    encoding = "utf-8"
    text = data.decode(encoding, errors="replace")
    normalized = normalize_text(text)
    return sha256_bytes(normalized.encode("utf-8"))
