"""Deterministic robots.txt policy evaluator for OpenVA discovery.

urllib.robotparser does not reliably implement RFC 9309 longest-match
precedence, so OpenVA implements and tests the semantics it relies on directly:

- a group is one or more consecutive user-agent lines followed by rules;
- blank lines and sitemap/unknown records do not terminate a group;
- rules before the first user-agent line are ignored;
- every group matching the most-specific product token is combined;
- the ``*`` group is used only when no explicit group matches;
- the longest matching path wins and an equal-length tie prefers Allow;
- ``*`` matches any sequence and a trailing ``$`` anchors the path end;
- an empty Disallow imposes no restriction;
- comparison and specificity are octet-based after URI normalization.

OpenVA also records the widely deployed, non-standard ``Crawl-delay``
directive. A delay is applicable only when it occurs inside a user-agent group.
When multiple equally specific groups match, OpenVA applies the largest valid
delay so group splitting cannot weaken origin pacing.

A present-but-unparseable robots file remains restrictive under OpenVA policy.
Robots directives are operating policy for this fetch lane, never evidence about
a source URL. The parser identifier is versioned so policy changes are visible in
discovery metadata.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

PARSER_ID = "openva-robots.v4"

_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PCT = re.compile(r"%([0-9a-fA-F]{2})")
_MAX_CRAWL_DELAY_SECONDS = 86_400.0


def _percent_encode_non_ascii(value: str) -> str:
    """Encode raw non-ASCII characters as their UTF-8 percent octets."""
    out: list[str] = []
    for char in value:
        if ord(char) < 0x80:
            out.append(char)
        else:
            out.append("".join(f"%{byte:02X}" for byte in char.encode("utf-8")))
    return "".join(out)


def _normalize_percent(value: str) -> str:
    """Return the octet-canonical form used for robots path comparison."""

    def repl(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return _PCT.sub(repl, _percent_encode_non_ascii(value))


def _octet_length(normalized: str) -> int:
    """Measure a normalized rule path in octets; each ``%XX`` is one octet."""
    return len(_PCT.sub("\x00", normalized))


@dataclass(frozen=True)
class _Rule:
    allow: bool
    path: str
    regex: re.Pattern[str]
    length: int


@dataclass(frozen=True)
class _Group:
    agents: frozenset[str]
    rules: tuple[_Rule, ...]
    crawl_delays: tuple[float, ...]


def _compile(path: str) -> tuple[re.Pattern[str], int]:
    end_anchor = path.endswith("$")
    core = path[:-1] if end_anchor else path
    normalized = _normalize_percent(core)
    # The end anchor is metadata, not a path octet. A wildcard counts as one
    # octet for the repository's established specificity rule.
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


def _parse_crawl_delay(value: str) -> float | None:
    try:
        delay = float(value)
    except ValueError:
        return None
    if not math.isfinite(delay) or delay < 0 or delay > _MAX_CRAWL_DELAY_SECONDS:
        return None
    return delay


class RobotsPolicy:
    """Parsed robots.txt with RFC-9309 matching and conservative crawl pacing."""

    def __init__(self, groups: list[_Group], sitemaps: list[str], malformed: bool):
        self.groups = groups
        self.sitemaps = sitemaps
        self.malformed = malformed
        self.parser_id = PARSER_ID

    @classmethod
    def parse(cls, text: str) -> "RobotsPolicy":
        groups: list[_Group] = []
        sitemaps: list[str] = []
        current_agents: set[str] = set()
        current_rules: list[_Rule] = []
        current_delays: list[float] = []
        seen_directive = 0
        recognized = 0
        seen_first_agent = False

        def close() -> None:
            nonlocal current_agents, current_rules, current_delays
            if current_agents:
                groups.append(
                    _Group(
                        frozenset(current_agents),
                        tuple(current_rules),
                        tuple(current_delays),
                    )
                )
            current_agents, current_rules, current_delays = set(), [], []

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            field, sep, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()
            if not sep:
                continue
            seen_directive += 1
            if field == "user-agent":
                recognized += 1
                seen_first_agent = True
                if current_rules or current_delays:
                    close()
                current_agents.add(value.lower())
            elif field in ("allow", "disallow"):
                recognized += 1
                if not seen_first_agent:
                    continue
                regex, length = _compile(value)
                current_rules.append(_Rule(field == "allow", value, regex, length))
            elif field == "crawl-delay":
                # A delay without a preceding user-agent has no group to govern.
                # Ignore it exactly as rules before the first user-agent are
                # ignored; do not let it make an otherwise unparseable file valid.
                if not seen_first_agent:
                    continue
                delay = _parse_crawl_delay(value)
                if delay is not None:
                    recognized += 1
                    current_delays.append(delay)
            elif field == "sitemap":
                recognized += 1
                if value:
                    sitemaps.append(value)
        close()
        malformed = seen_directive > 0 and recognized == 0
        return cls(groups, sitemaps, malformed)

    @staticmethod
    def _score(agents: frozenset[str], user_agent: str) -> int:
        ua = user_agent.lower()
        best = -1
        for agent in agents:
            if agent == "*":
                best = max(best, 0)
            elif ua == agent or ua.startswith(agent):
                best = max(best, len(agent))
        return best

    def _matching_groups(self, user_agent: str) -> list[_Group]:
        scores = [(self._score(group.agents, user_agent), group) for group in self.groups]
        best_score = max((score for score, _ in scores), default=-1)
        if best_score < 0:
            return []
        return [group for score, group in scores if score == best_score]

    def _rules_for(self, user_agent: str) -> list[_Rule]:
        combined: list[_Rule] = []
        for group in self._matching_groups(user_agent):
            combined.extend(group.rules)
        return combined

    def crawl_delay(self, user_agent: str) -> float | None:
        """Return the largest delay from the most-specific matching group(s)."""
        delays = [
            delay
            for group in self._matching_groups(user_agent)
            for delay in group.crawl_delays
        ]
        return max(delays) if delays else None

    def can_fetch(self, user_agent: str, url_or_path: str) -> bool:
        if self.malformed:
            return False
        path = _path_of(url_or_path)
        best: tuple[int, bool] | None = None
        for rule in self._rules_for(user_agent):
            if not rule.path:
                continue
            if rule.regex.match(path):
                if (
                    best is None
                    or rule.length > best[0]
                    or (rule.length == best[0] and rule.allow and not best[1])
                ):
                    best = (rule.length, rule.allow)
        return True if best is None else best[1]
