from ipaddress import ip_address

from tools.openva.url_safety import (
    _embedded_ipv4,
    is_blocked_ip,
    is_safe_public_url,
    validate_url_safety,
)


def test_allows_https_public_domain():
    assert is_safe_public_url("https://example.com/trust")


def test_rejects_javascript_scheme():
    assert validate_url_safety("javascript:alert(1)")


def test_malformed_url_is_classified_as_unsafe_not_raised():
    # Bad IPv6 brackets and out-of-range ports must be a bounded failure, never an
    # escaping ValueError from urlparse attribute access.
    assert validate_url_safety("https://[:::]/x") == ["URL is malformed"]
    assert validate_url_safety("https://[gg::1]/x") == ["URL is malformed"]
    assert validate_url_safety("https://example.com:99999/x") == ["URL is malformed"]
    assert not is_safe_public_url("https://[:::]/x")


def test_rejects_file_scheme():
    assert validate_url_safety("file:///etc/passwd")


def test_rejects_localhost():
    assert validate_url_safety("http://localhost:8000/private")


def test_rejects_loopback_ip():
    assert validate_url_safety("http://127.0.0.1/private")


def test_rejects_private_ipv4():
    assert validate_url_safety("http://10.0.0.5/metadata")


def test_rejects_link_local_metadata_ip():
    assert validate_url_safety("http://169.254.169.254/latest/meta-data")


def test_rejects_ipv6_loopback():
    assert validate_url_safety("http://[::1]/private")


# --- embedded-IPv4-in-IPv6 SSRF smuggling -----------------------------------
# A private/loopback IPv4 hidden inside an IPv6 carrier (v4-mapped ::ffff:a.b.c.d
# or NAT64 64:ff9b::a.b.c.d) must still be blocked: is_blocked_ip extracts the
# embedded IPv4 and re-checks it, so the carrier cannot smuggle it past the gate.


def test_v4_mapped_loopback_is_blocked():
    assert is_blocked_ip(ip_address("::ffff:127.0.0.1")) is True


def test_v4_mapped_private_is_blocked():
    assert is_blocked_ip(ip_address("::ffff:10.0.0.1")) is True


def test_nat64_well_known_carrying_loopback_is_blocked():
    # 64:ff9b::7f00:1 embeds 127.0.0.1 in the low 32 bits of the NAT64 prefix.
    assert is_blocked_ip(ip_address("64:ff9b::7f00:1")) is True


def test_nat64_well_known_carrying_private_is_blocked():
    # 64:ff9b::a00:1 embeds 10.0.0.1.
    assert is_blocked_ip(ip_address("64:ff9b::a00:1")) is True


def test_nat64_local_use_prefix_is_blocked_wholesale():
    # RFC 8215 64:ff9b:1::/48 local-use prefix is blocked wholesale (its
    # translation target is network-configuration dependent), regardless of the
    # embedded IPv4.
    assert is_blocked_ip(ip_address("64:ff9b:1::a00:1")) is True


def test_ordinary_public_addresses_are_not_over_blocked():
    # The embedded-IPv4 re-check only ever ADDS a rejection; it must not start
    # blocking ordinary public addresses (v4 or v6).
    assert is_blocked_ip(ip_address("8.8.8.8")) is False
    assert is_blocked_ip(ip_address("2001:4860:4860::8888")) is False


def test_embedded_ipv4_extraction_is_load_bearing():
    # Direct coverage of the new extraction helper. The is_blocked_ip assertions
    # above pass on this interpreter's stdlib alone (its scope flags already cover
    # these carriers), so they do not prove the new code runs. These assertions DO
    # fail if _embedded_ipv4 is removed or broken, locking in the version-
    # independent extraction that other interpreters rely on.
    from ipaddress import IPv4Address

    assert _embedded_ipv4(ip_address("::ffff:10.0.0.1")) == IPv4Address("10.0.0.1")
    assert _embedded_ipv4(ip_address("64:ff9b::a00:1")) == IPv4Address("10.0.0.1")
    assert _embedded_ipv4(ip_address("64:ff9b::808:808")) == IPv4Address("8.8.8.8")
    # Non-carrier addresses (plain v4, ordinary public v6) extract nothing.
    assert _embedded_ipv4(ip_address("8.8.8.8")) is None
    assert _embedded_ipv4(ip_address("2001:4860:4860::8888")) is None
