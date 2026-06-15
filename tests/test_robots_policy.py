"""Tier A: RFC-9309-style robots precedence, enforced by OpenVA's own evaluator.

These pin the policy OpenVA intends, not urllib.robotparser's behavior.
"""

from tools.openva.robots_policy import PARSER_ID, RobotsPolicy

UA = "OpenVA-Discovery"


def policy(text: str) -> RobotsPolicy:
    return RobotsPolicy.parse(text)


def test_specific_allow_overrides_broader_disallow():
    p = policy("User-agent: *\nDisallow: /docs\nAllow: /docs/public\n")
    assert p.can_fetch(UA, "/docs/public/report") is True
    assert p.can_fetch(UA, "/docs/private") is False


def test_longest_matching_rule_wins():
    p = policy("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /a/b/c\n")
    assert p.can_fetch(UA, "/a/b/c/x") is False  # /a/b/c (len 6) wins
    assert p.can_fetch(UA, "/a/b/x") is True  # /a/b (len 4) beats /a (len 2)
    assert p.can_fetch(UA, "/a/x") is False  # only /a matches


def test_user_agent_group_specificity_and_blank_line_boundaries():
    text = (
        "User-agent: *\n"
        "Disallow: /\n"
        "\n"
        "User-agent: openva-discovery\n"
        "Allow: /\n"
        "Disallow: /secret\n"
    )
    p = policy(text)
    assert p.can_fetch(UA, "/page") is True  # named group is more specific
    assert p.can_fetch(UA, "/secret") is False  # /secret (7) beats / (1)
    assert p.can_fetch("RandomBot", "/page") is False  # falls back to * group


def test_equal_length_allow_disallow_precedence_allow_wins():
    assert policy("User-agent: *\nDisallow: /x\nAllow: /x\n").can_fetch(UA, "/x") is True
    # Order-independent: allow still wins when listed first.
    assert policy("User-agent: *\nAllow: /x\nDisallow: /x\n").can_fetch(UA, "/x") is True


def test_percent_encoded_path_handling():
    p = policy("User-agent: *\nDisallow: /a%20b\n")
    assert p.can_fetch(UA, "/a%20b/c") is False
    assert p.can_fetch(UA, "/other") is True


def test_query_is_part_of_the_matched_path():
    p = policy("User-agent: *\nDisallow: /s?secret\n")
    assert p.can_fetch(UA, "https://v.example/s?secret=1") is False
    assert p.can_fetch(UA, "https://v.example/s?ok=1") is True


def test_wildcard_and_end_anchor():
    p = policy("User-agent: *\nDisallow: /*.pdf$\n")
    assert p.can_fetch(UA, "/files/report.pdf") is False
    assert p.can_fetch(UA, "/files/report.pdf?v=1") is True  # $ anchors the end
    assert p.can_fetch(UA, "/files/report.html") is True


def test_empty_disallow_imposes_no_restriction():
    assert policy("User-agent: *\nDisallow:\n").can_fetch(UA, "/anything") is True


def test_unknown_directive_is_ignored_when_valid_rules_exist():
    p = policy("User-agent: *\nCrawl-delay: 10\nDisallow: /x\nSitemap: https://v.example/s.xml\n")
    assert p.can_fetch(UA, "/x") is False
    assert p.can_fetch(UA, "/y") is True
    assert "https://v.example/s.xml" in p.sitemaps


def test_present_but_unparseable_policy_fails_conservatively():
    # Directives present but none recognized -> malformed -> restrictive.
    p = policy("Foo: bar\nBaz: qux\n")
    assert p.malformed is True
    assert p.can_fetch(UA, "/anything") is False


def test_absent_policy_is_not_malformed():
    p = policy("")
    assert p.malformed is False
    assert p.can_fetch(UA, "/anything") is True


def test_parser_id_is_versioned():
    assert RobotsPolicy.parse("").parser_id == PARSER_ID == "openva-robots.v1"
