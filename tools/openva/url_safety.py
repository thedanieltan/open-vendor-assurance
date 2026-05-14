from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
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
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        failures.append(f"URL scheme {parsed.scheme or '<missing>'} is not allowed")
        return failures

    host = normalize_host(parsed.hostname)
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
