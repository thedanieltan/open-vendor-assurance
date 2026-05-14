from tools.openva.pack import pack_digest, verify_pack_integrity


def test_pack_integrity_passes_for_current_pack():
    assert verify_pack_integrity() == []


def test_pack_digest_is_sha256_prefixed():
    digest = pack_digest()
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
