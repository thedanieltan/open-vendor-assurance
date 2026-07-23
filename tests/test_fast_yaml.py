"""The fast YAML loader is a behaviour-preserving drop-in for yaml.safe_load.

WP-OPENVA-FAST-YAML-LOADER-01.

Parsing the committed records dominates build/validate time; fast_yaml.load uses libyaml's
CSafeLoader when available (~10x faster) and falls back to SafeLoader. These tests assert the
two loaders agree on real repository records (so the speedup cannot change parse results) — the
parity check exercises the CSafeLoader path wherever libyaml is installed (e.g. CI).
"""

from __future__ import annotations

import glob

import yaml

from tools.openva import fast_yaml

# A representative slice across record kinds; enough to catch a loader discrepancy without
# re-parsing the whole tree in the unit test.
_SAMPLE = sorted(
    glob.glob("data/vendors/*/vendor.yaml")[:60]
    + glob.glob("data/vendors/*/sources/*.yaml")[:200]
    + glob.glob("data/vendors/*/candidate_sources/*.yaml")[:200]
    + glob.glob("examples/vendors/*/*.yaml")
)


def test_fast_yaml_matches_safe_load_on_real_records():
    assert _SAMPLE, "expected some committed records to sample"
    for path in _SAMPLE:
        text = open(path, encoding="utf-8").read()
        assert fast_yaml.load(text) == yaml.safe_load(text), path


def test_fast_yaml_handles_scalars_and_empty_documents():
    assert fast_yaml.load("") is None
    assert fast_yaml.load("42") == 42
    assert fast_yaml.load("a: 1\nb: [x, y]\n") == {"a": 1, "b": ["x", "y"]}


def test_using_libyaml_flag_is_boolean():
    assert isinstance(fast_yaml.USING_LIBYAML, bool)
