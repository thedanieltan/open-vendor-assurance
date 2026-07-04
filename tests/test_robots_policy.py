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
    assert p.can_fetch(UA, "/a/b/c/x") is False
    assert p.can_fetch(UA, "/a/b/x") is True
    assert p.can_fetch(UA, "/a/x") is False


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
    assert p.can_fetch(UA, "/page") is True
    assert p.can_fetch(UA, "/secret") is False
    assert p.can_fetch("RandomBot", "/page") is False


def test_equal_length_allow_disallow_precedence_allow_wins():
    assert policy("User-agent: *\nDisallow: /x\nAllow: /x\n").can_fetch(UA, "/x") is True
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
    assert p.can_fetch(UA, "/files/report.pdf?v=1") is True
    assert p.can_fetch(UA, "/files/report.html") is True


def test_empty_disallow_imposes_no_restriction():
    assert policy("User-agent: *\nDisallow:\n").can_fetch(UA, "/anything") is True


def test_crawl_delay_and_unknown_directive_do_not_break_rules():
    p = policy("User-agent: *\nCrawl-delay: 10\nFoo: bar\nDisallow: /x\nSitemap: https://v.example/s.xml\n")
    assert p.can_fetch(UA, "/x") is False
    assert p.can_fetch(UA, "/y") is True
    assert p.crawl_delay(UA) == 10
    assert "https://v.example/s.xml" in p.sitemaps


def test_present_but_unparseable_policy_fails_conservatively():
    p = policy("Foo: bar\nBaz: qux\n")
    assert p.malformed is True
    assert p.can_fetch(UA, "/anything") is False


def test_absent_policy_is_not_malformed():
    p = policy("")
    assert p.malformed is False
    assert p.can_fetch(UA, "/anything") is True


def test_parser_id_is_versioned():
    assert RobotsPolicy.parse("").parser_id == PARSER_ID == "openva-robots.v4"


def test_blank_line_does_not_detach_rule():
    p = policy("User-agent: OpenVA-Discovery\n\nDisallow: /private\n")
    assert p.can_fetch(UA, "/private/x") is False
    assert p.can_fetch(UA, "/public") is True


def test_two_groups_same_token_are_combined():
    text = (
        "User-agent: openva-discovery\n"
        "Disallow: /a\n"
        "\n"
        "User-agent: openva-discovery\n"
        "Disallow: /b\n"
    )
    p = policy(text)
    assert p.can_fetch(UA, "/a") is False
    assert p.can_fetch(UA, "/b") is False
    assert p.can_fetch(UA, "/c") is True


def test_wildcard_group_is_fallback_only_when_no_explicit_group_matches():
    text = "User-agent: *\nDisallow: /x\n\nUser-agent: openva-discovery\nAllow: /\n"
    p = policy(text)
    assert p.can_fetch(UA, "/x") is True
    assert p.can_fetch("OtherBot", "/x") is False


def test_rules_before_first_user_agent_are_ignored():
    p = policy("Disallow: /everything\nUser-agent: *\nAllow: /\n")
    assert p.can_fetch(UA, "/everything") is True


def test_sitemap_and_unknown_records_do_not_terminate_a_group():
    text = (
        "User-agent: openva-discovery\n"
        "Disallow: /a\n"
        "Sitemap: https://v.example/s.xml\n"
        "Crawl-delay: 5\n"
        "Disallow: /b\n"
    )
    p = policy(text)
    assert p.can_fetch(UA, "/a") is False
    assert p.can_fetch(UA, "/b") is False
    assert p.crawl_delay(UA) == 5
    assert "https://v.example/s.xml" in p.sitemaps


def test_percent_encoded_unreserved_normalizes_reserved_stays_encoded():
    p = policy("User-agent: *\nDisallow: /%41dmin\nDisallow: /a%2Fb\n")
    assert p.can_fetch(UA, "/Admin/x") is False
    assert p.can_fetch(UA, "/%41dmin/x") is False
    assert p.can_fetch(UA, "/a%2Fb") is False
    assert p.can_fetch(UA, "/a/b") is True


def test_raw_non_ascii_rule_matches_percent_encoded_uri_and_vice_versa():
    raw_rule = policy("User-agent: *\nDisallow: /資料\n")
    assert raw_rule.can_fetch(UA, "/%E8%B3%87%E6%96%99/report") is False
    assert raw_rule.can_fetch(UA, "/資料/report") is False
    assert raw_rule.can_fetch(UA, "/other") is True

    encoded_rule = policy("User-agent: *\nDisallow: /%E8%B3%87%E6%96%99\n")
    assert encoded_rule.can_fetch(UA, "/資料/report") is False
    assert encoded_rule.can_fetch(UA, "/%E8%B3%87%E6%96%99/report") is False


def test_specificity_is_measured_in_octets_not_code_points():
    p = policy("User-agent: *\nAllow: /資料\nDisallow: /資料/x\n")
    assert p.can_fetch(UA, "/資料/x/y") is False
    assert p.can_fetch(UA, "/資料/z") is True


def test_reserved_octet_stays_encoded_and_distinct_from_decoded():
    p = policy("User-agent: *\nDisallow: /a%2Fb\n")
    assert p.can_fetch(UA, "/a%2Fb") is False
    assert p.can_fetch(UA, "/a/b") is True
