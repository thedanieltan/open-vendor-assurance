"""WP37 independent bot quorum for autonomous promotion.

Narrow, independently-testable reviewers built by COMPOSING existing OpenVA
primitives, plus an orchestrator that clears a machine_provisional vendor for
promotion to active only through an independent quorum with separation of
duties. No single bot may discover, decide, and merge the same claim:

  * reviewers (authority level 2) cast a clear/challenge verdict over committed
    evidence and hold no write, decision, or merge authority on their own;
  * the deciding bot (level 3) records the promotion decision only when an
    independent quorum supports it, the deciding bot is not the discovery bot,
    and the deciding bot is not the sole supporter;
  * the merge authority (level 4, the pr_safety lane) is a separate lane.

Two reviewers built from the same module are NOT independent. The adversarial
reviewer defaults to CHALLENGE and clears only on positive evidence.

Reviewers operate on COMMITTED evidence only (catalog records, the committed
observation ledger, the vendor-match index, and the linked materialization
decision); they perform no network fetches, so the quorum is deterministic and
testable in CI. The release gate is run once by the workflow and its decision is
consumed here as one reviewer.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice. Bots route change; they never interpret its
legal, security, compliance, or procurement meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from tools.openva.advisory_wording import prohibited_terms_in_text
from tools.openva.catalog_growth_eligibility import normalize_domain, normalize_name
from tools.openva.strict_growth_redirects import host_matches_domain, hostname, official_domains_from_vendor
from tools.openva.url_safety import is_safe_public_url

VERDICT_CLEAR = "clear"
VERDICT_CHALLENGE = "challenge"

REVIEWER_LEVEL = 2
DECIDING_LEVEL = 3

# Observation event classes that represent an open material / domain-drift
# challenge when they are the latest committed event for a source.
MATERIAL_CHANGE_CLASSES = {"material_possible", "material_confirmed", "access_changed", "redirect_changed"}

# Source health statuses that mean a source is not publicly available right now.
UNAVAILABLE_HEALTH = {"unreachable", "blocked", "login_required", "not_found"}

# Source roles that do not count as a useful, distinct assurance source role.
GENERIC_SOURCE_ROLES = {"homepage", "generic_homepage"}

# Stable reviewer/deciding bot identifiers (distinct ids -> distinct bots).
IDENTITY_RESOLVER_BOT = "quorum-identity-resolver"
DOMAIN_AUTHORITY_BOT = "quorum-domain-authority-reviewer"
SOURCE_VERIFIER_BOT = "quorum-source-verifier"
DUPLICATE_MATCH_BOT = "quorum-duplicate-match-reviewer"
ADVERSARIAL_BOT = "quorum-adversarial-reviewer"
RELEASE_GATE_BOT = "quorum-release-gate-reviewer"
DECIDING_BOT = "quorum-promotion-decider"


@dataclass(frozen=True)
class ReviewVerdict:
    bot_id: str
    module: str
    level: int
    verdict: str
    reasons: tuple[str, ...] = ()

    @property
    def cleared(self) -> bool:
        return self.verdict == VERDICT_CLEAR


@dataclass
class PromotionSubject:
    """All COMMITTED evidence a quorum needs, decoupled from the filesystem so
    reviewers are pure and unit-testable."""

    vendor: dict[str, Any]
    sources: list[dict[str, Any]]
    events: list[dict[str, Any]]
    materialization_decision: dict[str, Any] | None
    other_vendor_domains: set[str] = field(default_factory=set)
    other_vendor_names: set[str] = field(default_factory=set)
    match_index_items: list[dict[str, Any]] = field(default_factory=list)
    now: datetime | None = None
    thresholds: dict[str, Any] = field(default_factory=dict)

    @property
    def vendor_id(self) -> str:
        return str(self.vendor.get("vendor_id") or "")

    def min_useful_source_roles(self) -> int:
        return int(self.thresholds.get("min_useful_source_roles", 2))


# --------------------------------------------------------------------------- #
# Observation helpers (committed ledger, latest-event-per-source)
# --------------------------------------------------------------------------- #
def latest_event_per_source(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        source_id = str(event.get("source_id") or "")
        if not source_id:
            continue
        current = latest.get(source_id)
        if current is None or str(event.get("observed_at") or "") >= str(current.get("observed_at") or ""):
            latest[source_id] = event
    return latest


def open_challenge_reasons(events: list[dict[str, Any]]) -> list[str]:
    """A source has an open material / domain-drift challenge when its latest
    committed event is a material change or still flags review required."""
    reasons: list[str] = []
    for source_id, event in sorted(latest_event_per_source(events).items()):
        if str(event.get("change_class") or "") in MATERIAL_CHANGE_CLASSES:
            reasons.append(f"open_material_change:{source_id}:{event.get('change_class')}")
        elif str(event.get("event_type") or "") in MATERIAL_CHANGE_CLASSES:
            reasons.append(f"open_material_change:{source_id}:{event.get('event_type')}")
        elif (event.get("review_signal") or {}).get("required") is True:
            reasons.append(f"open_review_signal:{source_id}:{(event.get('review_signal') or {}).get('reason')}")
    return reasons


# --------------------------------------------------------------------------- #
# Reviewers (each is a pure function of the subject -> a single verdict)
# --------------------------------------------------------------------------- #
def review_identity(subject: PromotionSubject) -> ReviewVerdict:
    vendor = subject.vendor
    reasons: list[str] = []
    domains = {
        normalize_domain(value)
        for key in ("official_domains", "public_entrypoints", "previous_domains")
        for value in vendor.get(key, []) or []
        if normalize_domain(value)
    }
    if not domains:
        reasons.append("identity_missing_official_domain")
    name = normalize_name(vendor.get("display_name"))
    if not name:
        reasons.append("identity_missing_display_name")
    collisions = domains & subject.other_vendor_domains
    for domain in sorted(collisions):
        reasons.append(f"identity_collision:domain:{domain}")
    if name and name in subject.other_vendor_names:
        reasons.append(f"identity_collision:name:{name}")
    verdict = VERDICT_CLEAR if not reasons else VERDICT_CHALLENGE
    return ReviewVerdict(IDENTITY_RESOLVER_BOT, "identity_resolver", REVIEWER_LEVEL, verdict, tuple(reasons))


def review_domain_authority(subject: PromotionSubject) -> ReviewVerdict:
    vendor = subject.vendor
    reasons: list[str] = []
    official = official_domains_from_vendor(vendor)
    if not official:
        reasons.append("no_official_domain")
    for source in subject.sources:
        url = str(source.get("source_url") or "")
        source_id = str(source.get("source_id") or url)
        if not url:
            reasons.append(f"source_missing_url:{source_id}")
            continue
        if not is_safe_public_url(url):
            reasons.append(f"unsafe_source_url:{source_id}")
            continue
        host = hostname(url)
        if not any(host_matches_domain(host, domain) for domain in official):
            reasons.append(f"source_host_outside_authority:{source_id}:{host}")
    verdict = VERDICT_CLEAR if not reasons else VERDICT_CHALLENGE
    return ReviewVerdict(DOMAIN_AUTHORITY_BOT, "domain_authority", REVIEWER_LEVEL, verdict, tuple(reasons))


def useful_source_roles(sources: list[dict[str, Any]]) -> set[str]:
    return {
        str(source.get("source_type") or "")
        for source in sources
        if str(source.get("source_type") or "") and str(source.get("source_type")) not in GENERIC_SOURCE_ROLES
    }


def review_sources(subject: PromotionSubject) -> ReviewVerdict:
    reasons: list[str] = []
    roles = useful_source_roles(subject.sources)
    minimum = subject.min_useful_source_roles()
    if len(roles) < minimum:
        reasons.append(f"insufficient_useful_source_roles:{len(roles)}<{minimum}")
    latest = latest_event_per_source(subject.events)
    observed_source_ids = {str(s.get("source_id") or "") for s in subject.sources}
    for source_id in sorted(observed_source_ids):
        event = latest.get(source_id)
        if event is None:
            reasons.append(f"source_never_observed:{source_id}")
            continue
        if str(event.get("source_health_status") or "") in UNAVAILABLE_HEALTH:
            reasons.append(f"source_unavailable:{source_id}:{event.get('source_health_status')}")
    verdict = VERDICT_CLEAR if not reasons else VERDICT_CHALLENGE
    return ReviewVerdict(SOURCE_VERIFIER_BOT, "source_verifier", REVIEWER_LEVEL, verdict, tuple(reasons))


def _name_tokens(value: str) -> set[str]:
    return {token for token in normalize_name(value).split() if token}


def _fuzzy_name_match(a: str, b: str) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return True
    ta, tb = _name_tokens(na), _name_tokens(nb)
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard >= 0.8


def review_duplicates(subject: PromotionSubject) -> ReviewVerdict:
    vendor = subject.vendor
    reasons: list[str] = []
    domains = {
        normalize_domain(value)
        for key in ("official_domains", "public_entrypoints")
        for value in vendor.get(key, []) or []
        if normalize_domain(value)
    }
    name = str(vendor.get("display_name") or "")
    for item in subject.match_index_items:
        if str(item.get("vendor_id") or "") == subject.vendor_id:
            continue
        other_domains = {normalize_domain(d) for d in item.get("official_domains", []) or [] if normalize_domain(d)}
        shared = domains & other_domains
        for domain in sorted(shared):
            reasons.append(f"duplicate_domain:{domain}:{item.get('vendor_id')}")
        if _fuzzy_name_match(name, str(item.get("display_name") or "")):
            reasons.append(f"fuzzy_name_match:{item.get('vendor_id')}")
    verdict = VERDICT_CLEAR if not reasons else VERDICT_CHALLENGE
    return ReviewVerdict(DUPLICATE_MATCH_BOT, "duplicate_match", REVIEWER_LEVEL, verdict, tuple(reasons))


def _advisory_text_findings(subject: PromotionSubject) -> list[str]:
    findings: list[str] = []
    texts = [subject.vendor.get("display_name"), subject.vendor.get("notes")]
    for source in subject.sources:
        texts.extend([source.get("title_native"), source.get("title")])
    for value in texts:
        for term in prohibited_terms_in_text(value):
            findings.append(f"advisory_wording:{term}")
    return findings


def review_adversarial(subject: PromotionSubject) -> ReviewVerdict:
    """Default = CHALLENGE. Clears only on positive evidence that there is
    nothing to challenge."""
    reasons: list[str] = []
    if subject.vendor.get("catalog_status") != "machine_provisional":
        reasons.append(f"not_machine_provisional:{subject.vendor.get('catalog_status')}")
    decision = subject.materialization_decision
    if not decision:
        reasons.append("missing_materialization_decision")
    else:
        if str(decision.get("decision")) != "materialize_provisional":
            reasons.append(f"unexpected_materialization_decision:{decision.get('decision')}")
        if decision.get("deciding_bot") and decision.get("deciding_bot") == decision.get("discovery_bot"):
            reasons.append("materialization_separation_of_duty_violation")
    if not (subject.vendor.get("reversal") or {}).get("reference"):
        reasons.append("missing_reversal_reference")
    reasons.extend(open_challenge_reasons(subject.events))
    reasons.extend(_advisory_text_findings(subject))
    verdict = VERDICT_CLEAR if not reasons else VERDICT_CHALLENGE
    return ReviewVerdict(ADVERSARIAL_BOT, "adversarial", REVIEWER_LEVEL, verdict, tuple(reasons))


def review_release_gate(subject: PromotionSubject, release_gate_decision: str) -> ReviewVerdict:
    if release_gate_decision == "pass":
        return ReviewVerdict(RELEASE_GATE_BOT, "release_gate", REVIEWER_LEVEL, VERDICT_CLEAR)
    return ReviewVerdict(
        RELEASE_GATE_BOT, "release_gate", REVIEWER_LEVEL, VERDICT_CHALLENGE,
        (f"release_gate_decision:{release_gate_decision}",),
    )


# --------------------------------------------------------------------------- #
# Separation of duty + quorum
# --------------------------------------------------------------------------- #
def independent_supporting_modules(verdicts: list[ReviewVerdict]) -> set[str]:
    """Distinct modules among clearing reviewers. Two reviewers built from the
    same module collapse to one — they are not independent."""
    return {v.module for v in verdicts if v.cleared}


def separation_of_duty_reasons(
    *,
    deciding_bot: str,
    discovery_bot: str,
    supporting_bot_ids: list[str],
    independent_module_count: int,
    min_independent_modules: int,
) -> list[str]:
    reasons: list[str] = []
    if deciding_bot and discovery_bot and deciding_bot == discovery_bot:
        reasons.append("separation_of_duty:deciding_bot == discovery_bot")
    supporters_excluding_deciding = [b for b in supporting_bot_ids if b != deciding_bot]
    if supporting_bot_ids and not supporters_excluding_deciding:
        reasons.append("separation_of_duty:deciding_bot is the sole supporter")
    if independent_module_count < min_independent_modules:
        reasons.append(
            f"insufficient_independent_supporting_modules:{independent_module_count}<{min_independent_modules}"
        )
    return reasons


@dataclass(frozen=True)
class QuorumResult:
    decision: str  # "promote" | "reject"
    verdicts: tuple[ReviewVerdict, ...]
    supporting_bots: tuple[str, ...]
    independent_modules: tuple[str, ...]
    challenges: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def promote(self) -> bool:
        return self.decision == "promote"


DEFAULT_REVIEWERS: tuple[Callable[[PromotionSubject], ReviewVerdict], ...] = (
    review_identity,
    review_domain_authority,
    review_sources,
    review_duplicates,
    review_adversarial,
)


def run_quorum(
    subject: PromotionSubject,
    *,
    release_gate_decision: str,
    deciding_bot: str = DECIDING_BOT,
    discovery_bot: str | None = None,
    reviewers: tuple[Callable[[PromotionSubject], ReviewVerdict], ...] = DEFAULT_REVIEWERS,
) -> QuorumResult:
    if discovery_bot is None:
        discovery_bot = str((subject.materialization_decision or {}).get("discovery_bot") or "")

    verdicts: list[ReviewVerdict] = [reviewer(subject) for reviewer in reviewers]
    verdicts.append(review_release_gate(subject, release_gate_decision))

    challenges: list[str] = []
    for verdict in verdicts:
        if not verdict.cleared:
            challenges.extend(f"{verdict.module}:{reason}" for reason in (verdict.reasons or ("challenge",)))

    supporting_bots = sorted({v.bot_id for v in verdicts if v.cleared})
    modules = independent_supporting_modules(verdicts)
    min_modules = int(subject.thresholds.get("min_independent_supporting_modules", 2))

    reasons = list(challenges)
    reasons.extend(
        separation_of_duty_reasons(
            deciding_bot=deciding_bot,
            discovery_bot=discovery_bot,
            supporting_bot_ids=supporting_bots,
            independent_module_count=len(modules),
            min_independent_modules=min_modules,
        )
    )
    decision = "promote" if not reasons else "reject"
    return QuorumResult(
        decision=decision,
        verdicts=tuple(verdicts),
        supporting_bots=tuple(supporting_bots),
        independent_modules=tuple(sorted(modules)),
        challenges=tuple(challenges),
        reasons=tuple(reasons),
    )
