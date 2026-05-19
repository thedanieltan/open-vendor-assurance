from tools.openva.pack import REQUIRED_INDEX_KEYS, REQUIRED_REGISTRY_OUTPUT_KEYS, pack_digest, verify_pack_integrity


def test_pack_integrity_passes_for_current_pack():
    assert verify_pack_integrity() == []


def test_pack_digest_is_sha256_prefixed():
    digest = pack_digest()
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_pack_contract_requires_registry_outputs():
    assert "vendor_search" in REQUIRED_INDEX_KEYS
    assert "source_coverage" in REQUIRED_INDEX_KEYS
    assert REQUIRED_REGISTRY_OUTPUT_KEYS == {"vendor_manifests"}
