from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}

# NAT64 / IPv4-in-IPv6 embeddings can smuggle a private or loopback IPv4 inside a
# globally-scoped IPv6 literal or DNS answer. Some stdlib versions classify the
# carrier IPv6 address as global and would NOT reject it on scope flags alone, so
# we extract the embedded IPv4 and re-check it explicitly. This is version-
# independent defence-in-depth: it can only ever add a rejection, never remove one.
# Only IPv4-mapped (::ffff:0:0/96) and NAT64 (64:ff9b::/96 well-known, plus the
# local-use /48) carriers are parsed here; other IPv4-in-IPv6 forms (6to4 2002::/16,
# Teredo, deprecated IPv4-compatible) are left to the stdlib scope flags and to
# is_blocked_ip running on every DNS-resolved address inside the fetch boundary.
_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")  # RFC 6052 well-known prefix
# RFC 8215 local-use NAT64 prefix: its translation target is network-configuration
# dependent, so it is treated as unsafe wholesale rather than parsed.
_BLOCKED_V6_NETWORKS = (ipaddress.ip_network("64:ff9b:1::/48"),)


def _embedded_ipv4(ip: ipaddress._BaseAddress) -> ipaddress.IPv4Address | None:
    if not isinstance(ip, ipaddress.IPv6Address):
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64_WELL_KNOWN:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    # An IPv4 smuggled inside an IPv6 carrier (v4-mapped or NAT64) is blocked iff
    # the embedded IPv4 itself is blocked.
    embedded = _embedded_ipv4(ip)
    if embedded is not None and is_blocked_ip(embedded):
        return True
    if isinstance(ip, ipaddress.IPv6Address) and any(ip in net for net in _BLOCKED_V6_NETWORKS):
        return True
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    return host.strip().lower().rstrip(".")


def validate_url_safety(url: str, *, resolve_dns: bool = False) -> list[str]:
    failures: list[str] = []
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme
        raw_host = parsed.hostname  # raises ValueError on malformed IPv6 brackets
        _port = parsed.port  # raises ValueError on an out-of-range port
    except ValueError:
        # A malformed URL (bad IPv6 literal, out-of-range port) is treated as
        # unsafe rather than raising, so callers reject it as a bounded failure.
        return ["URL is malformed"]

    if scheme not in ALLOWED_SCHEMES:
        failures.append(f"URL scheme {scheme or '<missing>'} is not allowed")
        return failures

    host = normalize_host(raw_host)
    if not host:
        failures.append("URL host is missing")
        return failures

    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        failures.append(f"URL host {host} is blocked")
        return failures

    if is_ip_literal(host):
        ip = ipaddress.ip_address(host.strip("[]"))
        if is_blocked_ip(ip):
            failures.append(f"URL host {host} resolves to blocked IP range")
        return failures

    if resolve_dns:
        try:
            for result in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(result[4][0])
                if is_blocked_ip(ip):
                    failures.append(f"URL host {host} resolves to blocked IP {ip}")
        except socket.gaierror:
            failures.append(f"URL host {host} could not be resolved")

    return failures


def is_safe_public_url(url: str, *, resolve_dns: bool = False) -> bool:
    return validate_url_safety(url, resolve_dns=resolve_dns) == []
