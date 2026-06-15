"""Deterministic robots.txt policy evaluator for OpenVA discovery.

urllib.robotparser does not reliably implement RFC 9309 longest-match
precedence (an open CPython issue), so OpenVA cannot delegate crawl decisions to
it. This module implements the RFC 9309 semantics OpenVA relies on and tests
them directly:

- a group is one or more consecutive user-agent lines followed by rules; a group
  ends only at the next user-agent line that follows a rule, or at EOF;
- blank lines and sitemap/unknown records do NOT terminate a group;
- rules appearing before the first user-agent line are ignored;
- all groups matching the crawler's most-specific product token are combined;
- the ``*`` group is the fallback only when no explicit group matches;
- within the combined rules the longest matching path wins; an equal-length
  Allow/Disallow tie prefers Allow (least restrictive);
- ``*`` matches any sequence, a trailing ``$`` anchors the path end;
- an empty Disallow imposes no restriction;
- comparison is octet-based (RFC 3986 / RFC 9309): raw non-ASCII characters in
  both rule paths and target URIs are first encoded to their UTF-8 percent
  octets, percent-encoded unreserved octets are then decoded, and reserved /
  non-ASCII octets are compared as (upper-cased) percent-encoding. Specificity
  (longest-match precedence) is measured in octets, not Python code points.

OpenVA policy extension (NOT from RFC 9309): a present-but-unparseable robots
file (directives present, none recognized) is treated as restrictive, distinct
from an absent file which imposes no restriction. The evaluator is versioned
(PARSER_ID) so a parsing-policy change is an explicit, recorded policy change.
robots is operating policy for this fetch lane, never evidence about a URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# v3: raw non-ASCII characters are encoded to their UTF-8 percent octets before
# comparison (in both rule paths and target URIs), and specificity is measured in
# octets rather than Python code points.
PARSER_ID = "openva-robots.v3"

_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PCT = re.compile(r"%([0-9a-fA-F]{2})")


def _percent_encode_non_ascii(value: str) -> str:
    """Encode every raw non-ASCII character as its UTF-8 percent octets.

    A literal ``資`` becomes ``%E8%B3%87`` so it compares equal to a server URI
    that is already percent-encoded. ASCII (including an existing ``%XX`` escape)
    passes through untouched here and is canonicalized by ``_normalize_percent``.
    """

    out: list[str] = []
    for char in value:
        if ord(char) < 0x80:
            out.append(char)
        else:
            out.append("".join(f"%{byte:02X}" for byte in char.encode("utf-8")))
    return "".join(out)


def _normalize_percent(value: str) -> str:
    """Octet-canonical form: encode raw non-ASCII, then fold unreserved escapes.

    RFC 3986 / RFC 9309 path comparison is octet-based: ``%41`` ('A') is
    equivalent to 'A', a reserved octet such as ``%2F`` ('/') stays encoded
    (upper-cased), and a raw non-ASCII character is equivalent to its UTF-8
    percent octets (``資`` == ``%E8%B3%87``). Encoding raw non-ASCII first makes
    the comparison symmetric whichever form the rule or the URI used.
    """

    def repl(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return _PCT.sub(repl, _percent_encode_non_ascii(value))


def _octet_length(normalized: str) -> int:
    """Length of an octet-canonical path in octets (each ``%XX`` is one octet)."""

    return len(_PCT.sub("\x00", normalized))


@dataclass(frozen=True)
class _Rule:
    allow: bool
    path: str
    regex: re.Pattern[str]
    length: int


def _compile(path: str) -> tuple[re.Pattern[str], int]:
    end_anchor = path.endswith("$")
    core = path[:-1] if end_anchor else path
    normalized = _normalize_percent(core)
    # RFC 9309 specificity is the octet length of the rule path (the end anchor
    # is a meta-character, not a path octet); a wildcard ``*`` counts as one.
    length = _octet_length(normalized)
    regex = "^" + re.escape(normalized).replace(r"\*", ".*") + ("$" if end_anchor else "")
    return re.compile(regex), length


def _path_of(url_or_path: str) -> str:
    if "://" in url_or_path:
        parts = urlsplit(url_or_path)
        path = parts.path or "/"
        path = path + (f"?{parts.query}" if parts.query else "")
    else:
        path = url_or_path or "/"
    return _normalize_percent(path)


class RobotsPolicy:
    """Parsed robots.txt with RFC-9309 grouping and longest-match evaluation."""

    def __init__(self, groups: list[tuple[set[str], list[_Rule]]], sitemaps: list[str], malformed: bool):
        self.groups = groups
        self.sitemaps = sitemaps
        self.malformed = malformed
        self.parser_id = PARSER_ID

    @classmethod
    def parse(cls, text: str) -> "RobotsPolicy":
        groups: list[tuple[set[str], list[_Rule]]] = []
        sitemaps: list[str] = []
        current_agents: set[str] = set()
        current_rules: list[_Rule] = []
        seen_directive = 0
        recognized = 0
        seen_first_agent = False

        def close() -> None:
            nonlocal current_agents, current_rules
            if current_agents:  # a group needs at least one user-agent line
                groups.append((current_agents, current_rules))
            current_agents, current_rules = set(), []

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue  # blank lines do NOT terminate a group
            field, sep, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()
            if not sep:
                continue  # malformed directive line: ignore
            seen_directive += 1
            if field == "user-agent":
                recognized += 1
                seen_first_agent = True
                if current_rules:  # a user-agent after rules starts a new group
                    close()
                current_agents.add(value.lower())
            elif field in ("allow", "disallow"):
                recognized += 1
                if not seen_first_agent:
                    continue  # rules before the first user-agent are ignored
                regex, length = _compile(value)
                current_rules.append(_Rule(field == "allow", value, regex, length))
            elif field == "sitemap":
                recognized += 1
                if value:
                    sitemaps.append(value)
            # unknown directive: ignored; does not terminate the group
        close()
        malformed = seen_directive > 0 and recognized == 0
        return cls(groups, sitemaps, malformed)

    def _rules_for(self, user_agent: str) -> list[_Rule]:
        ua = user_agent.lower()

        def score(agents: set[str]) -> int:
            best = -1
            for agent in agents:
                if agent == "*":
                    best = max(best, 0)
                elif ua == agent or ua.startswith(agent):
                    best = max(best, len(agent))
            return best

        best_score = max((score(agents) for agents, _ in self.groups), default=-1)
        if best_score < 0:
            return []
        # Combine the rules of every group at the best specificity (same token).
        # The wildcard group (score 0) only contributes when no explicit group
        # matched, because then best_score is 0.
        combined: list[_Rule] = []
        for agents, rules in self.groups:
            if score(agents) == best_score:
                combined.extend(rules)
        return combined

    def can_fetch(self, user_agent: str, url_or_path: str) -> bool:
        if self.malformed:
            return False  # OpenVA policy extension: unparseable -> conservative
        path = _path_of(url_or_path)
        best: tuple[int, bool] | None = None
        for rule in self._rules_for(user_agent):
            if not rule.path:  # empty Disallow / Allow imposes no restriction
                continue
            if rule.regex.match(path):
                if (
                    best is None
                    or rule.length > best[0]
                    or (rule.length == best[0] and rule.allow and not best[1])
                ):
                    best = (rule.length, rule.allow)
        return True if best is None else best[1]
