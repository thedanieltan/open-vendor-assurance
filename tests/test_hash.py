from tools.openva.hash import normalize_text, sha256_bytes, sha256_normalized_text


def test_sha256_bytes_is_stable():
    assert sha256_bytes(b"openva") == "sha256:e5782b9ed80f80987e9322049bcaf7b8f7e46b78a0a220a4f0b035a7de800b33"


def test_normalize_text_strips_markup_and_whitespace():
    html = "<html><body><h1>Hello</h1>   <script>ignore()</script><p>World</p></body></html>"
    assert normalize_text(html) == "Hello World"


def test_normalized_text_hash_ignores_markup_noise():
    left = b"<html><body><h1>Hello</h1><p>World</p></body></html>"
    right = b"<div>Hello   World</div>"
    assert sha256_normalized_text(left) == sha256_normalized_text(right)
