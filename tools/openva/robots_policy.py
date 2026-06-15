"""Deterministic robots.txt policy evaluator for the subset OpenVA discovery uses.

urllib.robotparser does not reliably implement RFC 9309 longest-match precedence
(an open CPython issue), so OpenVA cannot delegate crawl decisions to it. This
module implements the precedence OpenVA intends and tests it directly:

- most-specific user-agent group wins (longest matching product token; else ``*``);
- within the group, the matching rule with the longest path wins;
- on an equal-length Allow/Disallow tie, Allow wins (least restrictive);
- ``*`` matches any sequence, a trailing ``$`` anchors the path end;
- an empty Disallow imposes no restriction;
- blank lines and a new user-agent block end a group;
- unknown or malformed directives are ignored; a present-but-unparseable file is
  treated as restrictive (conservative), distinct from an absent file.

robots is operating policy for this fetch lane, never evidence about the URL.
The evaluator is versioned (PARSER_ID) so a behavior change is an explicit policy
change recorded in discovery metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

PARSER_ID = "openva-robots.v1"


@dataclass(frozen=True)
class _Rule:
    allow: bool
    path: str
    regex: re.Pattern[str]
    length: int


def _compile(path: str) -> tuple[re.Pattern[str], int]:
    end_anchor = path.endswith("$")
    core = path[:-1] if end_anchor else path
    # RFC 9309 specificity is the octet length of the rule path (the end-anchor
    # is a meta-character, not a path octet).
    length = len(core)
    regex = "^" + re.escape(core).replace(r"\*", ".*") + ("$" if end_anchor else "")
    return re.compile(regex), length


def _path_of(url_or_path: str) -> str:
    if "://" in url_or_path:
        parts = urlsplit(url_or_path)
        path = parts.path or "/"
        return path + (f"?{parts.query}" if parts.query else "")
    return url_or_path or "/"


class RobotsPolicy:
    """Parsed robots.txt with RFC-9309-style longest-match evaluation."""

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
        recognized = 0
        seen_directive = 0

        def close() -> None:
            nonlocal current_agents, current_rules
            if current_agents or current_rules:
                groups.append((current_agents, current_rules))
            current_agents, current_rules = set(), []

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                close()
                continue
            field, sep, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()
            if not sep:
                continue  # malformed directive line: ignore
            seen_directive += 1
            if field == "user-agent":
                recognized += 1
                if current_rules:  # a new group starts when a UA follows rules
                    close()
                current_agents.add(value.lower())
            elif field in ("allow", "disallow"):
                recognized += 1
                regex, length = _compile(value)
                current_rules.append(_Rule(field == "allow", value, regex, length))
            elif field == "sitemap":
                recognized += 1
                if value:
                    sitemaps.append(value)
            # unknown directive: ignored
        close()
        # A present file with directives but none recognized is treated as
        # malformed (conservative), distinct from an absent file.
        malformed = seen_directive > 0 and recognized == 0
        return cls(groups, sitemaps, malformed)

    def _group_for(self, user_agent: str) -> list[_Rule]:
        ua = user_agent.lower()
        best_rules: list[_Rule] | None = None
        best_score = -1
        star_rules: list[_Rule] | None = None
        for agents, rules in self.groups:
            for agent in agents:
                if agent == "*":
                    if star_rules is None:
                        star_rules = rules
                    continue
                if ua == agent or ua.startswith(agent):
                    if len(agent) > best_score:
                        best_score = len(agent)
                        best_rules = rules
        if best_rules is not None:
            return best_rules
        return star_rules or []

    def can_fetch(self, user_agent: str, url_or_path: str) -> bool:
        if self.malformed:
            return False  # conservative: an unparseable policy suppresses fetching
        path = _path_of(url_or_path)
        best: tuple[int, bool] | None = None
        for rule in self._group_for(user_agent):
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
