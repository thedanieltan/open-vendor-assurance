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
- percent-encoded unreserved octets are normalized before comparison; reserved
  and non-ASCII octets are compared as percent-encoded.

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

PARSER_ID = "openva-robots.v2"

_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PCT = re.compile(r"%([0-9a-fA-F]{2})")


def _normalize_percent(value: str) -> str:
    """Decode percent-encoded unreserved octets; keep reserved/non-ASCII encoded.

    RFC 3986 / RFC 9309 path comparison: %41 ('A') is equivalent to 'A', but a
    reserved octet such as %2F ('/') stays encoded (uppercased).
    """

    def repl(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return _PCT.sub(repl, value)


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
    # is a meta-character, not a path octet).
    length = len(normalized)
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
