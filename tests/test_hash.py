from tools.openva.hash import normalize_text, sha256_bytes, sha256_normalized_text


def test_sha256_bytes_is_stable():
    assert sha256_bytes(b"openva") == "sha256:ed6fda20724384fb8cc7520f10cf4c4993114297d869f07741d0c7e2a2591469"


def test_normalize_text_strips_markup_and_whitespace():
    html = "<html><body><h1>Hello</h1>   <script>ignore()</script><p>World</p></body></html>"
    assert normalize_text(html) == "Hello World"


def test_normalized_text_hash_ignores_markup_noise():
    left = b"<html><body><h1>Hello</h1><p>World</p></body></html>"
    right = b"<div>Hello   World</div>"
    assert sha256_normalized_text(left) == sha256_normalized_text(right)
