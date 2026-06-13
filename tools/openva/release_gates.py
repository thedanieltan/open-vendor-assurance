"""WP35 consolidated source-intelligence release gates.

An aggregate release-gate decision that COMPOSES existing validators; it does
not reimplement them. Composes: validate (canonical records, cross-refs,
quality, drift, prohibited language), agent_export (build + digest), the
agent-export schema, release_artifacts (manifest), advisory_wording (the single
prohibited-vocabulary contract), observation_ledger (committed coverage and
freshness against the SLA), and release_source_health (consumed as one gate in
the release profile, never recomputed here).

Two explicit execution profiles (selected with --profile, never inferred from
whether an artifact happens to exist):

    pr       deterministic committed-repository checks only. No network, no
             dependency on Actions artifacts. May read the committed observation
             ledger and compute coverage/freshness against the SLA.

    release  pr checks PLUS runtime-evidence gates. Required runtime evidence
             must be supplied explicitly (e.g. --source-health-readiness);
             missing, malformed, or stale required evidence FAILS CLOSED.
             Artifact absence never silently downgrades a release check to
             warning-only.

Outputs release-gates.json + release-gates-summary.md and an aggregate exit
code so callers (validate.yml, release-candidate.yml, and later automerge jobs)
enforce the same authority gate.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.openva.indexes import ROOT

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "release_gates_report"
DEFAULT_CONFIG = ROOT / "config" / "release-gates.yaml"
DEFAULT_LEDGER_DIR = ROOT / "maintenance" / "source-observations" / "events"

PROFILE_PR = "pr"
PROFILE_RELEASE = "release"
PROFILES = (PROFILE_PR, PROFILE_RELEASE)

# Gate categories drive whether a failure blocks, and which config toggle
# governs that. `core` gates always block in enforce mode.
CAT_CORE = "core"
CAT_FRESHNESS = "freshness"
CAT_CONSTITUTION = "constitution"
CAT_SOURCE_HEALTH = "source_health"
CAT_INFO = "info"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_WARN = "warn"
STATUS_SKIP = "skip"


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected release-gates config mapping")
    return data


def load_constitution(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError(f"{path}: expected constitution mapping with a rules list")
    return data


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class GateResult:
    gate_id: str
    category: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class GateContext:
    root: Path
    ledger_dir: Path
    config: dict[str, Any]
    profile: str
    now: datetime
    commit_sha: str
    source_health_readiness_path: Path | None = None
    source_health_policy: str = "enforce"


# --------------------------------------------------------------------------- #
# Pure checkers (each machine-enforced rule has a directly testable violation
# path that does not require a full export build).
# --------------------------------------------------------------------------- #
def find_self_certifying_or_private_leaks(documents: dict[str, dict[str, Any]]) -> list[str]:
    """Self-certifying / private fields must never appear in any export."""
    from tools.openva.source_health_public_snapshot import SELF_CERTIFYING_FIELDS

    forbidden = set(SELF_CERTIFYING_FIELDS)
    leaks: list[str] = []

    def walk(node: Any, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in forbidden:
                    leaks.append(f"{where}: self-certifying field leaked: {key}")
                walk(value, f"{where}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}[{index}]")

    for rel, doc in sorted(documents.items()):
        walk(doc, rel)
    return leaks


def find_advisory_terms(documents: dict[str, dict[str, Any]], terms: list[str]) -> list[str]:
    """Prohibited advisory/scoring/ranking vocabulary in any export text."""
    from tools.openva.advisory_wording import prohibited_terms_in_text

    findings: list[str] = []
    for rel, doc in sorted(documents.items()):
        text = json.dumps(doc, ensure_ascii=False)
        for term in prohibited_terms_in_text(text, terms):
            findings.append(f"{rel}: prohibited advisory wording: {term}")
    return findings


def find_missing_non_advisory_doctrine(documents: dict[str, dict[str, Any]]) -> list[str]:
    """Every export must assert its non-advisory doctrine."""
    findings: list[str] = []
    for rel, doc in sorted(documents.items()):
        if doc.get("not_advice") is not True:
            findings.append(f"{rel}: missing not_advice: true")
    return findings


def find_digest_mismatches(
    documents: dict[str, dict[str, Any]],
    index_doc: dict[str, Any] | None,
) -> list[str]:
    """Recompute each export's SHA-256 digest and verify advertised digests."""
    from tools.openva.agent_export import payload_digest

    findings: list[str] = []
    for rel, doc in sorted(documents.items()):
        snapshot = doc.get("snapshot")
        if not isinstance(snapshot, dict) or "digest" not in snapshot:
            findings.append(f"{rel}: missing snapshot digest")
            continue
        advertised = snapshot["digest"]
        if not isinstance(advertised, str) or not advertised.startswith("sha256:"):
            findings.append(f"{rel}: digest is not sha256: {advertised!r}")
            continue
        recomputed = payload_digest(doc)
        if advertised != recomputed:
            findings.append(f"{rel}: digest mismatch (advertised {advertised}, recomputed {recomputed})")

    if isinstance(index_doc, dict):
        pointers: list[dict[str, Any]] = list((index_doc.get("exports") or {}).values())
        pointers += list(index_doc.get("vendor_exports") or [])
        for pointer in pointers:
            rel = pointer.get("path")
            advertised = pointer.get("digest")
            doc = documents.get(rel)
            if doc is None:
                findings.append(f"root index advertises missing export: {rel}")
                continue
            actual = doc.get("snapshot", {}).get("digest")
            if advertised != actual:
                findings.append(f"root index digest mismatch for {rel}: {advertised} != {actual}")
    return findings


def find_raw_content_dirs(root: Path) -> list[str]:
    from tools.openva.validate import RAW_CONTENT_DIR_NAMES

    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() and path.name in RAW_CONTENT_DIR_NAMES:
            findings.append(f"{path.relative_to(root).as_posix()}: raw-content directory not allowed by default")
    return findings


def find_single_bot_canonicalizations(root: Path, min_independent_supporters: int) -> list[str]:
    """WP37: every committed promotion (machine_provisional -> active) decision
    must carry an independent quorum. A `promote` decision is a violation if the
    deciding bot is the discovery bot, the deciding bot is its sole supporter, or
    fewer than the configured number of independent supporters back it. No single
    bot may create canonical truth by itself."""
    decisions_dir = root / "maintenance" / "machine-decisions"
    from tools.openva.machine_decisions import load_decisions

    findings: list[str] = []
    for record in load_decisions(decisions_dir):
        if record.get("decision") != "promote":
            continue
        decision_id = str(record.get("decision_id") or "(missing)")
        deciding = str(record.get("deciding_bot") or "")
        discovery = str(record.get("discovery_bot") or "")
        supporting = [str(bot) for bot in record.get("supporting_bots") or []]
        independent = sorted({bot for bot in supporting if bot != deciding})
        if deciding and discovery and deciding == discovery:
            findings.append(f"{decision_id}: deciding_bot == discovery_bot")
        if not independent:
            findings.append(f"{decision_id}: deciding_bot is the sole supporter")
        elif len(independent) < min_independent_supporters:
            findings.append(
                f"{decision_id}: only {len(independent)} independent supporter(s) (< {min_independent_supporters})"
            )
    return findings


def find_rollback_author_violations(root: Path) -> list[str]:
    """WP38b: a Level-5 rollback may never be authored by the bot that created
    the state it reverts. Every committed rollback decision must have a deciding
    bot (reverser) different from its discovery bot (the original author)."""
    decisions_dir = root / "maintenance" / "machine-decisions"
    from tools.openva.machine_decisions import load_decisions

    findings: list[str] = []
    for record in load_decisions(decisions_dir):
        if record.get("decision") != "rollback":
            continue
        decision_id = str(record.get("decision_id") or "(missing)")
        reverser = str(record.get("deciding_bot") or "")
        author = str(record.get("discovery_bot") or "")
        if reverser and author and reverser == author:
            findings.append(f"{decision_id}: rollback reverser == author ({reverser})")
    return findings


def find_irreversible_machine_records(
    root: Path,
    marker_fields: list[str],
    reversal_fields: list[str],
) -> list[str]:
    """Records carrying a machine-generation marker must carry a reversal ref."""
    markers = set(marker_fields)
    reversals = set(reversal_fields)
    findings: list[str] = []
    for path in sorted(root.glob("data/vendors/**/*.yaml")):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            continue
        provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
        keys = set(record) | set(provenance)
        if keys & markers and not (keys & reversals):
            rel = path.relative_to(root).as_posix()
            findings.append(f"{rel}: machine-generated record has no reversal reference")
    return findings


# --------------------------------------------------------------------------- #
# Export build (shared once by the runner; gates may also build standalone)
# --------------------------------------------------------------------------- #
def build_export_documents(ctx: GateContext) -> dict[str, dict[str, Any]]:
    """Build the agent export tree deterministically into a temp dir and read
    every file back as {relative_path: document}."""
    from tools.openva.agent_export import build_agent_exports

    with tempfile.TemporaryDirectory(prefix="openva-release-gates-") as tmp:
        out = Path(tmp)
        build_agent_exports(
            root=ctx.root,
            out_dir=out,
            commit_sha=ctx.commit_sha,
            generated_at="2026-01-01T00:00:00Z",  # pinned: digests exclude snapshot
            ledger_dir=ctx.ledger_dir,
        )
        return {
            path.relative_to(out).as_posix(): json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(out.rglob("*.json"))
        }


# --------------------------------------------------------------------------- #
# Freshness / coverage from the committed ledger
# --------------------------------------------------------------------------- #
def compute_freshness(ctx: GateContext) -> dict[str, Any]:
    from tools.openva.observation_ledger import (
        build_freshness_report,
        build_latest_index,
        load_ledger_baseline,
        load_sla_config,
        source_records_by_id,
    )

    baseline = load_ledger_baseline(ctx.ledger_dir)
    latest = build_latest_index([], baseline, generated_at="2026-01-01T00:00:00Z")
    source_records = source_records_by_id(ctx.root)
    sla = load_sla_config()
    report = build_freshness_report(latest, sla, now=ctx.now, source_records=source_records)
    return {
        "report": report,
        "baseline_source_ids": set(baseline),
        "all_source_ids": set(source_records),
        "source_types": {sid: rec.get("source_type") for sid, rec in source_records.items()},
    }


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #
def gate_catalog_validation(ctx: GateContext) -> GateResult:
    """Canonical records validate; generated pack/indexes/dist are drift-free;
    no prohibited advisory wording in records. Runs against the real repo only
    (validate operates on the package ROOT)."""
    if ctx.root != ROOT:
        return GateResult(
            "catalog_validation", CAT_CORE, STATUS_SKIP,
            "skipped: validate runs against the package ROOT only",
        )
    from tools.openva import validate as validate_mod

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = validate_mod.validate_all()
    if code == 0:
        return GateResult("catalog_validation", CAT_CORE, STATUS_PASS, "catalog validation passed")
    details = [line for line in buffer.getvalue().splitlines() if line.strip()]
    return GateResult("catalog_validation", CAT_CORE, STATUS_FAIL, "catalog validation failed", details[-25:])


def gate_exports_build(ctx: GateContext, documents: dict[str, dict[str, Any]] | None) -> GateResult:
    if documents is None:
        return GateResult("exports_build", CAT_CORE, STATUS_FAIL, "agent exports failed to build")
    return GateResult("exports_build", CAT_CORE, STATUS_PASS, f"built {len(documents)} export file(s)")


def gate_exports_schema(ctx: GateContext, documents: dict[str, dict[str, Any]]) -> GateResult:
    import jsonschema

    schema_rel = (ctx.config.get("exports") or {}).get("schema_path", "schemas/openva/agent-export.schema.json")
    schema = json.loads((ROOT / schema_rel).read_text(encoding="utf-8"))
    defs = schema["$defs"]

    def def_for(rel: str) -> str:
        if rel == "openva-agent-index.json":
            return "agent_index"
        if rel == "vendors/index.json":
            return "vendors_index"
        if rel == "sources/index.json":
            return "sources_index"
        if rel == "observations/latest.json":
            return "observations_latest"
        if rel == "changes/latest.json":
            return "changes_latest"
        return "vendor_export"

    failures: list[str] = []
    for rel, doc in sorted(documents.items()):
        subschema = {"$ref": f"#/$defs/{def_for(rel)}", "$defs": defs}
        try:
            jsonschema.validate(doc, subschema)
        except jsonschema.ValidationError as error:
            failures.append(f"{rel}: {error.message}")
    if failures:
        return GateResult("exports_schema_valid", CAT_CORE, STATUS_FAIL, "export schema validation failed", failures[:25])
    return GateResult("exports_schema_valid", CAT_CORE, STATUS_PASS, "all exports validate against schema")


def gate_exports_digest(ctx: GateContext, documents: dict[str, dict[str, Any]]) -> GateResult:
    index = documents.get("openva-agent-index.json")
    findings = find_digest_mismatches(documents, index)
    if findings:
        return GateResult("exports_digest_integrity", CAT_CONSTITUTION, STATUS_FAIL, "export digest integrity failed", findings[:25])
    return GateResult("exports_digest_integrity", CAT_CONSTITUTION, STATUS_PASS, "every export digest recomputes (sha256)")


def gate_exports_advisory(ctx: GateContext, documents: dict[str, dict[str, Any]]) -> GateResult:
    from tools.openva.advisory_wording import load_prohibited_terms

    findings = find_advisory_terms(documents, load_prohibited_terms())
    if findings:
        return GateResult("exports_advisory_clean", CAT_CONSTITUTION, STATUS_FAIL, "prohibited advisory wording in exports", findings[:25])
    return GateResult("exports_advisory_clean", CAT_CONSTITUTION, STATUS_PASS, "no prohibited advisory wording in exports")


def gate_exports_leakage(ctx: GateContext, documents: dict[str, dict[str, Any]]) -> GateResult:
    findings = find_self_certifying_or_private_leaks(documents)
    if findings:
        return GateResult("exports_leakage_clean", CAT_CONSTITUTION, STATUS_FAIL, "private/self-certifying leakage in exports", findings[:25])
    return GateResult("exports_leakage_clean", CAT_CONSTITUTION, STATUS_PASS, "no private/gated/self-certifying leakage in exports")


def gate_exports_non_advisory(ctx: GateContext, documents: dict[str, dict[str, Any]]) -> GateResult:
    findings = find_missing_non_advisory_doctrine(documents)
    if findings:
        return GateResult("exports_non_advisory_doctrine", CAT_CONSTITUTION, STATUS_FAIL, "exports missing non-advisory doctrine", findings[:25])
    return GateResult("exports_non_advisory_doctrine", CAT_CONSTITUTION, STATUS_PASS, "every export asserts non-advisory doctrine")


def gate_no_raw_mirroring(ctx: GateContext) -> GateResult:
    findings = find_raw_content_dirs(ctx.root)
    if findings:
        return GateResult("no_raw_mirroring", CAT_CONSTITUTION, STATUS_FAIL, "raw-content directories present", findings[:25])
    return GateResult("no_raw_mirroring", CAT_CONSTITUTION, STATUS_PASS, "no raw-content directories")


def gate_reversible_provenance(ctx: GateContext) -> GateResult:
    cfg = ctx.config.get("reversibility") or {}
    findings = find_irreversible_machine_records(
        ctx.root,
        list(cfg.get("machine_marker_fields") or []),
        list(cfg.get("reversal_fields") or []),
    )
    if findings:
        return GateResult("reversible_provenance", CAT_CONSTITUTION, STATUS_FAIL, "machine-created records without reversal", findings[:25])
    return GateResult("reversible_provenance", CAT_CONSTITUTION, STATUS_PASS, "all machine-created claims carry a reversal path")


def gate_quorum_promotion_independence(ctx: GateContext) -> GateResult:
    """Machine-enforced: no single bot may create canonical truth. Every
    committed promotion decision must carry an independent quorum with
    separation of duties."""
    cfg = ctx.config.get("quorum_promotion") or {}
    min_supporters = int(cfg.get("min_independent_supporting_bots", 2))
    findings = find_single_bot_canonicalizations(ctx.root, min_supporters)
    if findings:
        return GateResult(
            "quorum_promotion_independence", CAT_CONSTITUTION, STATUS_FAIL,
            "promotion decision(s) lack an independent quorum", findings[:25],
        )
    return GateResult(
        "quorum_promotion_independence", CAT_CONSTITUTION, STATUS_PASS,
        "every promotion decision carries an independent quorum (separation of duties)",
    )


def gate_rollback_reverser_not_author(ctx: GateContext) -> GateResult:
    """Machine-enforced: a Level-5 rollback may never be authored by the bot that
    created the state it reverts (reverser != author)."""
    findings = find_rollback_author_violations(ctx.root)
    if findings:
        return GateResult(
            "rollback_reverser_not_author", CAT_CONSTITUTION, STATUS_FAIL,
            "rollback decision(s) authored by the original state's author", findings[:25],
        )
    return GateResult(
        "rollback_reverser_not_author", CAT_CONSTITUTION, STATUS_PASS,
        "every rollback decision is authored by a bot other than the original author",
    )


def gate_artifact_manifest(ctx: GateContext) -> GateResult:
    """The release artifact manifest must build and validate. release-artifacts.json
    is a release-time artifact, not committed, and the aggregate gate runs before
    the workflow's `release_artifacts build` step, so this gate asserts the
    manifest builds deterministically. Committed generated drift (pack, indexes,
    dist) is covered by catalog_validation; the workflow's dedicated
    `release_artifacts check` step verifies currency after build."""
    from tools.openva.release_artifacts import build_manifest

    try:
        manifest = build_manifest()
    except Exception as error:  # noqa: BLE001 - surface any build failure as a gate failure
        return GateResult("release_artifact_manifest", CAT_CORE, STATUS_FAIL, "release artifact manifest failed to build", [str(error)])
    return GateResult("release_artifact_manifest", CAT_CORE, STATUS_PASS, f"manifest builds ({manifest['artifact_count']} artifacts)")


def gate_full_baseline(ctx: GateContext, freshness: dict[str, Any]) -> GateResult:
    if not (ctx.config.get("freshness") or {}).get("require_full_baseline", True):
        return GateResult("full_baseline_readiness", CAT_FRESHNESS, STATUS_SKIP, "full-baseline gate disabled in config")
    missing = sorted(freshness["all_source_ids"] - freshness["baseline_source_ids"])
    total = len(freshness["all_source_ids"])
    observed = len(freshness["all_source_ids"] & freshness["baseline_source_ids"])
    if missing:
        return GateResult(
            "full_baseline_readiness", CAT_FRESHNESS, STATUS_FAIL,
            f"observation baseline incomplete: {observed}/{total} sources observed",
            [f"no committed observation: {sid}" for sid in missing[:25]],
        )
    return GateResult("full_baseline_readiness", CAT_FRESHNESS, STATUS_PASS, f"full baseline: {observed}/{total} sources observed")


def gate_observation_freshness(ctx: GateContext, freshness: dict[str, Any]) -> GateResult:
    if not (ctx.config.get("freshness") or {}).get("forbid_expired", True):
        return GateResult("observation_freshness", CAT_FRESHNESS, STATUS_SKIP, "expired-freshness gate disabled in config")
    rows = freshness["report"]["sources"]
    expired = [r for r in rows if r["freshness"]["status"] == "expired"]
    stale = [r for r in rows if r["freshness"]["status"] == "stale"]
    if expired:
        return GateResult(
            "observation_freshness", CAT_FRESHNESS, STATUS_FAIL,
            f"{len(expired)} source(s) past expired SLA",
            [f"expired: {r['source_id']} ({r['freshness']['age_days']}d)" for r in expired[:25]],
        )
    if stale:
        return GateResult(
            "observation_freshness", CAT_FRESHNESS, STATUS_WARN,
            f"{len(stale)} source(s) stale (within expired SLA)",
            [f"stale: {r['source_id']} ({r['freshness']['age_days']}d)" for r in stale[:25]],
        )
    return GateResult("observation_freshness", CAT_FRESHNESS, STATUS_PASS, "no expired or stale observations")


def gate_high_priority_freshness(ctx: GateContext, freshness: dict[str, Any]) -> GateResult:
    priority_types = set((ctx.config.get("freshness") or {}).get("high_priority_source_types") or [])
    if not priority_types:
        return GateResult("high_priority_freshness", CAT_FRESHNESS, STATUS_SKIP, "no high-priority source types configured")
    rows = [r for r in freshness["report"]["sources"] if r.get("source_type") in priority_types]
    out_of_sla = [r for r in rows if not r["freshness"]["observed_within_sla"]]
    if out_of_sla:
        return GateResult(
            "high_priority_freshness", CAT_FRESHNESS, STATUS_FAIL,
            f"{len(out_of_sla)} high-priority source(s) outside SLA",
            [f"{r['source_id']} ({r['source_type']}, {r['freshness']['status']})" for r in out_of_sla[:25]],
        )
    return GateResult("high_priority_freshness", CAT_FRESHNESS, STATUS_PASS, f"all {len(rows)} high-priority sources within SLA")


def gate_agent_export_observation_state(ctx: GateContext, freshness: dict[str, Any]) -> GateResult:
    max_age = (ctx.config.get("freshness") or {}).get("agent_export_max_observation_age_days")
    if not max_age:
        return GateResult("agent_export_observation_state", CAT_FRESHNESS, STATUS_SKIP, "observation-state-age gate disabled in config")
    ages = [r["freshness"]["age_days"] for r in freshness["report"]["sources"] if r["freshness"]["age_days"] is not None]
    if not ages:
        return GateResult("agent_export_observation_state", CAT_FRESHNESS, STATUS_FAIL, "no observation ages available")
    newest = min(ages)
    if newest > max_age:
        return GateResult(
            "agent_export_observation_state", CAT_FRESHNESS, STATUS_FAIL,
            f"newest observation is {newest}d old (> {max_age}d tolerance)",
        )
    return GateResult("agent_export_observation_state", CAT_FRESHNESS, STATUS_PASS, f"newest observation {newest}d old (<= {max_age}d)")


def gate_material_change_surfaced(ctx: GateContext, documents: dict[str, dict[str, Any]]) -> GateResult:
    """The latest material change per source is surfaced into the generated
    changes export.

    The changes export (changes/latest.json) is a latest-event-per-source
    projection (built from the ledger baseline), not an all-events log. So the
    gate verifies the latest committed event for each source — when it is a
    material change — is present in the export. Superseded historical material
    events remain in the committed append-only ledger (the durable record of
    change); they are not expected in the latest-state export, and a newer
    non-material observation legitimately supersedes them.
    """
    from tools.openva.observation_ledger import load_ledger_baseline

    baseline = load_ledger_baseline(ctx.ledger_dir)  # latest committed event per source
    material = [
        event for event in baseline.values()
        if event.get("change_class") in {"material_possible", "material_confirmed"}
    ]
    changes = documents.get("changes/latest.json", {})
    surfaced_ids = {(row.get("source_id"), row.get("observation_id")) for row in changes.get("sources", [])}
    missing = [
        event for event in material
        if (event.get("source_id"), event.get("observation_id")) not in surfaced_ids
    ]
    if missing:
        return GateResult(
            "material_change_surfaced", CAT_CORE, STATUS_FAIL,
            f"{len(missing)} latest material change(s) not surfaced into changes export",
            [f"{event.get('source_id')} / {event.get('observation_id')}" for event in missing[:25]],
        )
    return GateResult("material_change_surfaced", CAT_CORE, STATUS_PASS, f"all {len(material)} latest material changes surfaced")


def gate_source_posture(ctx: GateContext, freshness: dict[str, Any]) -> GateResult:
    """Committed-ledger broken-source count (informational; the authoritative
    broken-source hard fail is confirmed-P0 in the release source-health gate)."""
    cfg = ctx.config.get("source_posture") or {}
    broken_statuses = set(cfg.get("broken_health_statuses") or [])
    report = freshness["report"]
    # latest health is on the latest index, not the freshness report; recompute
    from tools.openva.observation_ledger import load_ledger_baseline

    baseline = load_ledger_baseline(ctx.ledger_dir)
    broken = sorted(
        sid for sid, entry in baseline.items()
        if str(entry.get("source_health_status")) in broken_statuses
    )
    if broken:
        return GateResult(
            "source_posture", CAT_INFO, STATUS_WARN,
            f"{len(broken)} source(s) unreachable in latest committed observation",
            [f"unreachable: {sid}" for sid in broken[:25]],
        )
    return GateResult("source_posture", CAT_INFO, STATUS_PASS, "no unreachable sources in latest committed observations")


def gate_source_health_readiness(ctx: GateContext) -> GateResult:
    """Release-profile gate: CONSUME the readiness artifact produced by
    release_source_health (the single producer). Required evidence; missing,
    malformed, or stale fails closed."""
    cfg = ctx.config.get("source_health") or {}
    required = bool(cfg.get("required_in_release", True))
    path = ctx.source_health_readiness_path
    if path is None or not path.exists():
        if required:
            return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_FAIL,
                              "source-health readiness artifact missing (required in release profile)")
        return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_SKIP, "source-health readiness not supplied")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_FAIL,
                          "source-health readiness artifact malformed", [str(error)])
    if data.get("report_type") != "release_source_health_readiness":
        return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_FAIL,
                          f"unexpected readiness report_type: {data.get('report_type')!r}")
    # staleness: fail closed if older than configured tolerance
    max_age_hours = cfg.get("max_readiness_age_hours")
    generated_at = data.get("generated_at")
    if max_age_hours and generated_at:
        try:
            generated = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            age_hours = max(0.0, (ctx.now - generated).total_seconds() / 3600)
            if age_hours > float(max_age_hours):
                return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_FAIL,
                                  f"source-health readiness is stale ({age_hours:.1f}h > {max_age_hours}h)")
        except ValueError:
            return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_FAIL,
                              "source-health readiness generated_at is not parseable")
    status = data.get("status")
    failures = data.get("failures") or []
    if status == "blocked" or failures:
        return GateResult(
            "source_health_readiness", CAT_SOURCE_HEALTH, STATUS_FAIL,
            "source-health readiness reports blocking failures",
            [str(f.get("message", f)) for f in failures][:25],
        )
    if status == "warning":
        return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_WARN, "source-health readiness has warnings")
    return GateResult("source_health_readiness", CAT_SOURCE_HEALTH, STATUS_PASS, "source-health readiness is ready")


def gate_constitution(ctx: GateContext, prior: list[GateResult]) -> GateResult:
    """Aggregate the machine-enforced constitution rules: pass iff every
    machine-enforced rule's backing gate passed. Also asserts the constitution
    file is internally consistent (every machine rule names a real gate)."""
    constitution_rel = ctx.config.get("constitution_path", "config/bot-constitution.yaml")
    constitution = load_constitution(ROOT / constitution_rel)
    by_id = {r.gate_id: r for r in prior}
    machine_rules = [
        rule for rule in constitution["rules"]
        if (rule.get("enforcement") or {}).get("state") == "machine_enforced"
    ]
    problems: list[str] = []
    for rule in machine_rules:
        gate_id = (rule.get("enforcement") or {}).get("gate_id")
        result = by_id.get(gate_id)
        if result is None:
            problems.append(f"{rule.get('id')}: machine rule names unknown gate {gate_id!r}")
        elif result.status == STATUS_FAIL:
            problems.append(f"{rule.get('id')}: gate {gate_id} failed")
    if problems:
        return GateResult("constitution", CAT_CONSTITUTION, STATUS_FAIL, "constitution rule(s) violated", problems[:25])
    return GateResult("constitution", CAT_CONSTITUTION, STATUS_PASS, f"all {len(machine_rules)} machine-enforced constitution rules pass")


# --------------------------------------------------------------------------- #
# Runner / aggregation
# --------------------------------------------------------------------------- #
def _category_blocks(category: str, config: dict[str, Any], source_health_policy: str) -> bool:
    if config.get("mode") != "enforce":
        return False
    if category == CAT_INFO:
        return False
    if category == CAT_FRESHNESS:
        return config.get("freshness_gates") == "enforce"
    if category == CAT_CONSTITUTION:
        return config.get("constitution_enforcement") == "enforce"
    if category == CAT_SOURCE_HEALTH:
        return source_health_policy == "enforce"
    return True  # CAT_CORE


def run_gates(ctx: GateContext) -> list[GateResult]:
    results: list[GateResult] = []
    results.append(gate_catalog_validation(ctx))

    documents: dict[str, dict[str, Any]] | None
    try:
        documents = build_export_documents(ctx)
    except Exception:  # noqa: BLE001 - build failure is itself a gate failure
        documents = None
    results.append(gate_exports_build(ctx, documents))
    if documents is not None:
        results.append(gate_exports_schema(ctx, documents))
        results.append(gate_exports_digest(ctx, documents))
        results.append(gate_exports_advisory(ctx, documents))
        results.append(gate_exports_leakage(ctx, documents))
        results.append(gate_exports_non_advisory(ctx, documents))

    results.append(gate_no_raw_mirroring(ctx))
    results.append(gate_reversible_provenance(ctx))
    results.append(gate_quorum_promotion_independence(ctx))
    results.append(gate_rollback_reverser_not_author(ctx))
    results.append(gate_artifact_manifest(ctx))

    freshness = compute_freshness(ctx)
    results.append(gate_full_baseline(ctx, freshness))
    results.append(gate_observation_freshness(ctx, freshness))
    results.append(gate_high_priority_freshness(ctx, freshness))
    results.append(gate_agent_export_observation_state(ctx, freshness))
    if documents is not None:
        results.append(gate_material_change_surfaced(ctx, documents))
    results.append(gate_source_posture(ctx, freshness))

    if ctx.profile == PROFILE_RELEASE:
        results.append(gate_source_health_readiness(ctx))

    results.append(gate_constitution(ctx, results))
    return results


def build_report(ctx: GateContext, results: list[GateResult]) -> dict[str, Any]:
    gate_rows = []
    blocking_failures = 0
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_WARN: 0, STATUS_SKIP: 0}
    for result in results:
        blocks = _category_blocks(result.category, ctx.config, ctx.source_health_policy)
        is_blocking_failure = blocks and result.status == STATUS_FAIL
        if is_blocking_failure:
            blocking_failures += 1
        counts[result.status] = counts.get(result.status, 0) + 1
        gate_rows.append({
            "gate_id": result.gate_id,
            "category": result.category,
            "status": result.status,
            "blocking": blocks,
            "summary": result.summary,
            "details": result.details,
        })
    decision = "blocked" if blocking_failures else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": ctx.profile,
        "mode": ctx.config.get("mode"),
        "freshness_gates": ctx.config.get("freshness_gates"),
        "constitution_enforcement": ctx.config.get("constitution_enforcement"),
        "source_health_policy": ctx.source_health_policy,
        "decision": decision,
        "posture": {
            "network_fetch_performed": False,
            "writes_repository_state": False,
            "opens_pull_requests": False,
            "mutates_catalog": False,
            "enables_automerge": False,
            "non_advisory": True,
        },
        "summary": {
            "gate_count": len(results),
            "passed": counts[STATUS_PASS],
            "failed": counts[STATUS_FAIL],
            "warned": counts[STATUS_WARN],
            "skipped": counts[STATUS_SKIP],
            "blocking_failures": blocking_failures,
        },
        "gates": gate_rows,
        "not_advice": True,
    }


def render_summary_md(report: dict[str, Any]) -> str:
    lines = [
        "# OpenVA Release Gates",
        "",
        "Aggregate source-intelligence release-gate decision. Operational metadata only; "
        "not legal, compliance, procurement, security, audit, or vendor-risk advice.",
        "",
        f"- Profile: `{report['profile']}`",
        f"- Mode: `{report['mode']}`",
        f"- Decision: **{report['decision']}**",
        f"- Gates: {report['summary']['passed']} passed, {report['summary']['failed']} failed, "
        f"{report['summary']['warned']} warned, {report['summary']['skipped']} skipped "
        f"({report['summary']['blocking_failures']} blocking).",
        "",
        "| Gate | Category | Status | Blocking | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for gate in report["gates"]:
        lines.append(
            f"| `{gate['gate_id']}` | {gate['category']} | {gate['status']} | "
            f"{'yes' if gate['blocking'] else 'no'} | {gate['summary']} |"
        )
    failing = [g for g in report["gates"] if g["blocking"] and g["status"] == "fail"]
    if failing:
        lines += ["", "## Blocking failures", ""]
        for gate in failing:
            lines.append(f"### `{gate['gate_id']}` — {gate['summary']}")
            for detail in gate["details"]:
                lines.append(f"- {detail}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-release-gates")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    parser.add_argument("--source-health-readiness", type=Path, default=None)
    parser.add_argument(
        "--source-health-policy",
        choices=["enforce", "report_only"],
        default="enforce",
        help="release profile: govern whether the source-health gate blocks",
    )
    parser.add_argument("--commit-sha", default="0" * 40)
    parser.add_argument("--now", default=None, help="ISO-8601 override for deterministic tests")
    parser.add_argument("--out-json", type=Path, default=Path("release-gates.json"))
    parser.add_argument("--out-md", type=Path, default=Path("release-gates-summary.md"))
    parser.add_argument("--enforce", action="store_true", help="exit non-zero on a blocking decision")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else datetime.now(UTC)
    )
    ctx = GateContext(
        root=ROOT,
        ledger_dir=args.ledger_dir,
        config=config,
        profile=args.profile,
        now=now,
        commit_sha=args.commit_sha,
        source_health_readiness_path=args.source_health_readiness,
        source_health_policy=args.source_health_policy,
    )

    results = run_gates(ctx)
    report = build_report(ctx, results)
    args.out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_md.write_text(render_summary_md(report), encoding="utf-8")
    print(render_summary_md(report))

    # The pr profile always enforces its deterministic committed-state gates.
    effective_enforce = args.enforce or args.profile == PROFILE_PR
    if effective_enforce and report["decision"] == "blocked":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
