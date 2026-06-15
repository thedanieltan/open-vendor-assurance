import json
from pathlib import Path

import jsonschema
import pytest

from tools.openva.source_authority import (
    CORROBORATING_METHODS,
    establishes_authority,
    is_on_official_domain,
    validate_authority,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_SCHEMA = json.loads((ROOT / "schemas/openva/candidate-record.schema.json").read_text(encoding="utf-8"))
SOURCE_SCHEMA = json.loads((ROOT / "schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))


def authority_subschema() -> dict:
    return {"$ref": "#/$defs/authority", "$defs": CANDIDATE_SCHEMA["$defs"]}


def test_official_domain_match_handles_subdomains_and_www():
    assert is_on_official_domain("https://trust.example.com/x", ["example.com"])
    assert is_on_official_domain("https://www.example.com/x", ["example.com"])
    assert not is_on_official_domain("https://example.com.evil.test/x", ["example.com"])
    assert not is_on_official_domain("https://other.test/x", ["example.com"])


def test_only_strong_establishes_authority():
    assert establishes_authority({"class": "strong", "method": "official_domain_link", "target_url": "x", "observed_at": "t"})
    assert not establishes_authority({"class": "corroborating", "method": "cname_corroboration", "target_url": "x", "observed_at": "t"})
    assert not establishes_authority(None)


def test_on_domain_same_official_domain_is_valid():
    a = {"class": "strong", "method": "same_official_domain", "target_url": "https://example.com/security", "observed_at": "2026-06-15T00:00:00Z"}
    assert validate_authority(a, ["example.com"]) == []


def test_off_domain_requires_strong_content_anchored_method():
    base = {"target_url": "https://vendor.trust-provider.example/x", "observed_at": "2026-06-15T00:00:00Z"}
    # Strong + official_domain_link is allowed off-domain.
    assert validate_authority({**base, "class": "strong", "method": "official_domain_link"}, ["example.com"]) == []
    # same_official_domain cannot prove an off-domain target.
    assert validate_authority({**base, "class": "strong", "method": "same_official_domain"}, ["example.com"])
    # Corroboration alone cannot prove an off-domain target.
    assert validate_authority({**base, "class": "corroborating", "method": "cname_corroboration"}, ["example.com"])


@pytest.mark.parametrize("method", CORROBORATING_METHODS)
def test_corroboration_cannot_be_strong_schema_and_invariant(method):
    bad = {"class": "strong", "method": method, "target_url": "https://example.com/x", "observed_at": "2026-06-15T00:00:00Z"}
    # Schema rejects it.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, authority_subschema())
    # Invariant also rejects it.
    assert validate_authority(bad, ["example.com"])


def test_schema_accepts_well_formed_authority_on_candidate_and_source():
    good = {
        "class": "strong",
        "method": "official_domain_redirect",
        "source_url": "https://example.com/security",
        "target_url": "https://example.trust.example/p",
        "observed_at": "2026-06-15T00:00:00Z",
    }
    jsonschema.validate(good, authority_subschema())
    # The source schema embeds the same object under canonical_confidence.
    cc = SOURCE_SCHEMA["properties"]["canonical_confidence"]["properties"]["authority"]
    jsonschema.validate(good, {**cc})
