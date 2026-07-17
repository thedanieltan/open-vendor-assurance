from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlparse

from tools.openva.vendor_breadth_replenishment import (
    VIBE_CODER_SAAS_DIRECTORY_PROVIDER,
    collect_signals,
    curated_vibe_coder_directory_specs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DIRECTORY_DIR = REPO_ROOT / "tools" / "openva" / "data" / "vibe-coder-saas"
EXPECTED_COLUMNS = {
    "id",
    "display_name",
    "official_domain",
    "country",
    "listing_url",
    "description",
}
KNOWN_CATEGORY_TAGS = {
    "ai_platform",
    "analytics_bi",
    "cloud_infrastructure",
    "collaboration_software",
    "content_management",
    "customer_engagement",
    "customer_support",
    "data_platform",
    "database",
    "developer_platform",
    "ecommerce_platform",
    "financial_infrastructure",
    "identity_access",
    "marketing_technology",
    "observability",
    "payments",
    "productivity_software",
    "security",
}
REQUIRED_ECOSYSTEM_TAGS = {
    "ai_platform",
    "analytics_bi",
    "cloud_infrastructure",
    "content_management",
    "customer_engagement",
    "database",
    "developer_platform",
    "ecommerce_platform",
    "identity_access",
    "observability",
    "payments",
    "security",
}


def load_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    paths = sorted(DIRECTORY_DIR.glob("*.csv"))
    assert paths
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert set(reader.fieldnames or []) == EXPECTED_COLUMNS
            rows.extend(dict(row) for row in reader)
    return rows


def category_tags(row: dict[str, str]) -> set[str]:
    prefix, separator, raw_tags = row["description"].partition(";")
    assert prefix == "developer SaaS"
    assert separator == ";"
    return {value.strip() for value in raw_tags.split(",") if value.strip()}


def test_directory_is_broad_unique_and_machine_readable() -> None:
    rows = load_rows()
    assert len(rows) >= 200  # Regression floor, not a catalogue or discovery cap.

    ids = [row["id"] for row in rows]
    domains = [row["official_domain"] for row in rows]
    assert len(ids) == len(set(ids))
    assert len(domains) == len(set(domains))

    observed_tags: set[str] = set()
    for row in rows:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", row["id"])
        assert row["display_name"].strip()
        assert re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", row["official_domain"])
        assert re.fullmatch(r"[A-Z]{2}", row["country"])
        parsed = urlparse(row["listing_url"])
        assert parsed.scheme == "https"
        assert (parsed.hostname or "").removeprefix("www.") == row["official_domain"]
        tags = category_tags(row)
        assert tags
        assert tags <= KNOWN_CATEGORY_TAGS
        observed_tags.update(tags)

    assert REQUIRED_ECOSYSTEM_TAGS <= observed_tags


def test_directory_is_a_default_noncanonical_breadth_feed() -> None:
    specifications = curated_vibe_coder_directory_specs(REPO_ROOT)
    assert len(specifications) >= 4

    signals, skipped = collect_signals(directory_feeds=specifications)
    assert skipped == []
    assert len(signals) == len(load_rows())
    assert {row["provider"] for row in signals} == {
        VIBE_CODER_SAAS_DIRECTORY_PROVIDER
    }
    assert all(row["not_advice"] is True for row in signals)
    assert all(row["source_kind"] == "public_directory" for row in signals)
