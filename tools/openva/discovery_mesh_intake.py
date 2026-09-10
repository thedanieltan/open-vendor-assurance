"""Replay-safe partitioning for OpenVA Discovery Mesh candidate intake.

The Discovery Mesh can produce more candidate records than one GitHub pull request
can review, validate, and merge reliably. This module turns one aggregate artifact
into deterministic repository-sized intake transactions without limiting total
catalog growth. It never writes canonical vendors or sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

SCHEMA_VERSION = "0.1.0"
REPORT_TYPE = "discovery_mesh_intake_manifest"
DEFAULT_TRANSACTION_MAX_FILES = 2_500
DEFAULT_TRANSACTION_MAX_BYTES = 25_000_000
CANDIDATE_PATH_RE = re.compile(
    r"data/vendors/(?P<vendor_id>[a-z0-9][a-z0-9._-]*)/candidate_sources/"
    r"(?P<candidate_id>[a-z0-9][a-z0-9._-]*)\.yaml"
)
BREADTH_PATHS = (
    "maintenance/generated/vendor-breadth-signal-ledger.json",
    "maintenance/generated/vendor-breadth-resolution-queue.json",
    "maintenance/generated/vendor-breadth-candidates.json",
    "maintenance/generated/vendor-breadth-provider-metrics.json",
)


@dataclass(frozen=True)
class ActionRecord:
    action: dict[str, Any]
    path: str
    vendor_id: str
    candidate_id: str
    candidate_bytes: int
    action_bytes: int

    @property
    def estimated_bytes(self) -> int:
        return self.candidate_bytes + self.action_bytes


@dataclass(frozen=True)
class Partition:
    index: int
    digest: str
    records: tuple[ActionRecord, ...]

    @property
    def action_count(self) -> int:
        return len(self.records)

    @property
    def vendor_ids(self) -> tuple[str, ...]:
        return tuple(sorted({record.vendor_id for record in self.records}))

    @property
    def estimated_bytes(self) -> int:
        return sum(record.estimated_bytes for record in self.records)

    @property
    def changed_file_count(self) -> int:
        return self.action_count + 1


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def yaml_text(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def parent_plan_digest(plan: dict[str, Any]) -> str:
    actions = [
        action
        for action in plan.get("actions", []) or []
        if isinstance(action, dict)
    ]
    return "sha256:" + hashlib.sha256(canonical_json_bytes(actions)).hexdigest()


def action_specs(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if plan.get("report_type") != "promotion_plan":
        raise ValueError("expected promotion_plan")
    output: dict[str, dict[str, Any]] = {}
    for action in plan.get("actions", []) or []:
        if not isinstance(action, dict):
            raise ValueError("promotion action must be an object")
        path = str(action.get("path") or "")
        match = CANDIDATE_PATH_RE.fullmatch(path)
        if match is None:
            raise ValueError(f"invalid candidate path in promotion plan: {path!r}")
        if path in output:
            raise ValueError(f"duplicate candidate path in promotion plan: {path}")
        vendor_id = match.group("vendor_id")
        candidate_id = match.group("candidate_id")
        if str(action.get("vendor_id") or "") != vendor_id:
            raise ValueError(f"promotion action vendor mismatch for {path}")
        if str(action.get("candidate_source_id") or "") != candidate_id:
            raise ValueError(f"promotion action candidate mismatch for {path}")
        output[path] = action
    return output


def index_action_records(
    *,
    candidate_ndjson_path: Path,
    plan: dict[str, Any],
) -> list[ActionRecord]:
    specs = action_specs(plan)
    output: list[ActionRecord] = []
    seen: set[str] = set()
    with candidate_ndjson_path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict) or not isinstance(row.get("candidate"), dict):
                raise ValueError(f"invalid candidate NDJSON row {line_number}")
            candidate = row["candidate"]
            vendor_id = str(row.get("vendor_id") or "")
            candidate_id = str(candidate.get("candidate_source_id") or "")
            path = (
                f"data/vendors/{vendor_id}/candidate_sources/"
                f"{candidate_id}.yaml"
            )
            action = specs.get(path)
            if action is None:
                continue
            if path in seen:
                raise ValueError(f"duplicate candidate row for {path}")
            seen.add(path)
            text = yaml_text(candidate)
            output.append(
                ActionRecord(
                    action=action,
                    path=path,
                    vendor_id=vendor_id,
                    candidate_id=candidate_id,
                    candidate_bytes=len(text.encode("utf-8")),
                    action_bytes=len(canonical_json_bytes(action)),
                )
            )
    missing = sorted(set(specs) - seen)
    if missing:
        preview = ", ".join(missing[:10])
        raise ValueError(
            f"{len(missing)} promotion candidates missing from candidate NDJSON: "
            f"{preview}"
        )
    return sorted(output, key=lambda record: (record.vendor_id, record.path))


def materialize_partition(
    *,
    manifest_path: Path,
    partition_id: str,
    candidate_ndjson_path: Path,
    prepared_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    matches = [
        row
        for row in manifest.get("partitions", []) or []
        if isinstance(row, dict) and row.get("partition_id") == partition_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one intake partition {partition_id!r}")
    partition = matches[0]
    kind = str(partition.get("kind") or "")
    allowed_paths = {str(path) for path in partition.get("paths", []) or []}
    source_dir = prepared_root / str(partition.get("directory") or "")
    for path in sorted(allowed_paths):
        prepared = source_dir / path
        if prepared.is_file():
            destination = repository_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prepared, destination)
    if kind == "source":
        candidate_paths = {
            path for path in allowed_paths if CANDIDATE_PATH_RE.fullmatch(path)
        }
        found: set[str] = set()
        with candidate_ndjson_path.open(encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if not isinstance(row, dict) or not isinstance(
                    row.get("candidate"), dict
                ):
                    raise ValueError(f"invalid candidate NDJSON row {line_number}")
                candidate = row["candidate"]
                vendor_id = str(row.get("vendor_id") or "")
                candidate_id = str(candidate.get("candidate_source_id") or "")
                path = (
                    f"data/vendors/{vendor_id}/candidate_sources/"
                    f"{candidate_id}.yaml"
                )
                if path not in candidate_paths:
                    continue
                destination = repository_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(yaml_text(candidate), encoding="utf-8")
                found.add(path)
        missing = sorted(candidate_paths - found)
        if missing:
            raise ValueError(
                "partition candidates missing from NDJSON: "
                + ", ".join(missing[:10])
            )
    return partition


def _fits(
    records: Iterable[ActionRecord],
    *,
    max_files: int,
    max_bytes: int,
) -> bool:
    rows = tuple(records)
    return (
        len(rows) + 1 <= max_files
        and sum(row.estimated_bytes for row in rows) <= max_bytes
    )


def partition_records(
    records: list[ActionRecord],
    *,
    max_files: int = DEFAULT_TRANSACTION_MAX_FILES,
    max_bytes: int = DEFAULT_TRANSACTION_MAX_BYTES,
) -> list[Partition]:
    if max_files < 2:
        raise ValueError(
            "transaction max files must allow one candidate and one plan"
        )
    if max_bytes < 1:
        raise ValueError("transaction max bytes must be positive")
    by_vendor: dict[str, list[ActionRecord]] = defaultdict(list)
    for record in records:
        if record.estimated_bytes > max_bytes:
            raise ValueError(
                f"single candidate exceeds transaction byte budget: {record.path}"
            )
        by_vendor[record.vendor_id].append(record)

    raw: list[list[ActionRecord]] = []
    current: list[ActionRecord] = []

    def flush() -> None:
        nonlocal current
        if current:
            raw.append(current)
            current = []

    for vendor_id in sorted(by_vendor):
        group = by_vendor[vendor_id]
        if _fits(
            [*current, *group],
            max_files=max_files,
            max_bytes=max_bytes,
        ):
            current.extend(group)
            continue
        flush()
        if _fits(group, max_files=max_files, max_bytes=max_bytes):
            current.extend(group)
            continue
        for record in group:
            if not _fits(
                [*current, record],
                max_files=max_files,
                max_bytes=max_bytes,
            ):
                flush()
            current.append(record)
        flush()
    flush()

    partitions: list[Partition] = []
    for index, rows in enumerate(raw, start=1):
        digest = hashlib.sha256(
            "\n".join(record.path for record in rows).encode("utf-8")
        ).hexdigest()[:12]
        partitions.append(
            Partition(index=index, digest=digest, records=tuple(rows))
        )
    return partitions


def partition_plan(
    parent: dict[str, Any],
    partition: Partition,
    *,
    source_run_id: str,
    partition_count: int,
    digest: str,
) -> dict[str, Any]:
    output = {
        key: deepcopy(value)
        for key, value in parent.items()
        if key not in {"actions", "deferred_actions", "skipped_actions"}
    }
    output["actions"] = [
        deepcopy(record.action) for record in partition.records
    ]
    output["deferred_actions"] = []
    output["skipped_actions"] = []
    inputs = dict(output.get("inputs") or {})
    inputs.update(
        {
            "source_discovery_run_id": str(source_run_id),
            "parent_promotion_plan_digest": digest,
            "intake_partition_index": partition.index,
            "intake_partition_count": partition_count,
        }
    )
    output["inputs"] = inputs
    summary = dict(output.get("summary") or {})
    action_types: dict[str, int] = defaultdict(int)
    for record in partition.records:
        action_types[str(record.action.get("action") or "unknown")] += 1
    count = partition.action_count
    summary.update(
        {
            "action_count": count,
            "action_types": dict(sorted(action_types.items())),
            "actions_requiring_human_review": sum(
                1
                for record in partition.records
                if record.action.get("requires_human_review") is True
            ),
            "batch_deferred_action_count": 0,
            "deferred_due_to_cap_count": 0,
            "selected_after_cap_count": count,
            "selected_promotion_action_count": count,
            "skipped_action_count": 0,
            "viable_action_count": count,
            "viable_before_cap_count": count,
            "vendors_with_actions": len(partition.vendor_ids),
        }
    )
    output["summary"] = summary
    output["intake_partition"] = {
        "schema_version": SCHEMA_VERSION,
        "source_run_id": str(source_run_id),
        "parent_plan_digest": digest,
        "partition_index": partition.index,
        "partition_count": partition_count,
        "partition_digest": partition.digest,
        "candidate_file_count": partition.action_count,
        "estimated_transaction_bytes": partition.estimated_bytes,
        "vendor_count": len(partition.vendor_ids),
    }
    return output


def _copy_json(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    value = load_json(source)
    destination.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_intake(
    *,
    artifact_root: Path,
    candidate_ndjson_path: Path,
    promotion_plan_path: Path,
    output_dir: Path,
    source_run_id: str,
    max_files: int = DEFAULT_TRANSACTION_MAX_FILES,
    max_bytes: int = DEFAULT_TRANSACTION_MAX_BYTES,
) -> dict[str, Any]:
    plan = load_json(promotion_plan_path)
    records = index_action_records(
        candidate_ndjson_path=candidate_ndjson_path,
        plan=plan,
    )
    partitions = partition_records(
        records,
        max_files=max_files,
        max_bytes=max_bytes,
    )
    digest = parent_plan_digest(plan)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    manifest_partitions: list[dict[str, Any]] = []
    breadth_paths: list[str] = []
    breadth_root = output_dir / "breadth"
    for relative in BREADTH_PATHS:
        source = artifact_root / relative
        if source.is_file():
            _copy_json(source, breadth_root / relative)
            breadth_paths.append(relative)
    if breadth_paths:
        manifest_partitions.append(
            {
                "partition_id": "breadth",
                "kind": "breadth",
                "branch": (
                    f"agent-discovery-mesh-intake-{source_run_id}-breadth"
                ),
                "title": "Ops: checkpoint discovery mesh breadth",
                "directory": "breadth",
                "paths": breadth_paths,
                "action_count": 0,
                "vendor_count": 0,
                "estimated_transaction_bytes": sum(
                    (breadth_root / path).stat().st_size
                    for path in breadth_paths
                ),
            }
        )

    partition_count = len(partitions)
    for partition in partitions:
        partition_id = f"source-{partition.index:04d}-{partition.digest}"
        partition_root = output_dir / partition_id
        paths = [record.path for record in partition.records]
        plan_name = (
            f"strict-growth-discovery-mesh-promotion-plan-{source_run_id}-"
            f"part-{partition.index:04d}-{partition.digest}.json"
        )
        plan_relative = f"maintenance/generated/{plan_name}"
        plan_output = partition_root / plan_relative
        plan_output.parent.mkdir(parents=True, exist_ok=True)
        plan_output.write_text(
            json.dumps(
                partition_plan(
                    plan,
                    partition,
                    source_run_id=source_run_id,
                    partition_count=partition_count,
                    digest=digest,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        paths.append(plan_relative)
        manifest_partitions.append(
            {
                "partition_id": partition_id,
                "kind": "source",
                "branch": (
                    f"agent-discovery-mesh-intake-{source_run_id}-"
                    f"{partition_id}"
                ),
                "title": "Ops: stage discovery mesh candidates",
                "directory": partition_id,
                "paths": paths,
                "promotion_plan_path": plan_relative,
                "action_count": partition.action_count,
                "vendor_count": len(partition.vendor_ids),
                "estimated_transaction_bytes": (
                    partition.estimated_bytes + plan_output.stat().st_size
                ),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "source_run_id": str(source_run_id),
        "parent_plan_digest": digest,
        "transaction_bounds": {
            "max_changed_files": max_files,
            "max_estimated_bytes": max_bytes,
            "catalog_vendor_count_cap": None,
            "total_action_count_cap": None,
        },
        "summary": {
            "breadth_partition_count": 1 if breadth_paths else 0,
            "source_partition_count": partition_count,
            "total_partition_count": len(manifest_partitions),
            "total_action_count": len(records),
            "candidate_records_available": len(records),
            "vendors_with_actions": len(
                {record.vendor_id for record in records}
            ),
        },
        "partitions": manifest_partitions,
        "posture": {
            "writes_canonical_sources": False,
            "writes_canonical_vendors": False,
            "changes_admission_authority": False,
            "replay_idempotent": True,
            "non_advisory": True,
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-discovery-mesh-intake")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--artifact-root", type=Path, required=True)
    prepare.add_argument("--candidate-ndjson", type=Path, required=True)
    prepare.add_argument("--promotion-plan", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--source-run-id", required=True)
    prepare.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_TRANSACTION_MAX_FILES,
    )
    prepare.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_TRANSACTION_MAX_BYTES,
    )
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--manifest", type=Path, required=True)
    materialize.add_argument("--partition-id", required=True)
    materialize.add_argument("--candidate-ndjson", type=Path, required=True)
    materialize.add_argument("--prepared-root", type=Path, required=True)
    materialize.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        manifest = prepare_intake(
            artifact_root=args.artifact_root,
            candidate_ndjson_path=args.candidate_ndjson,
            promotion_plan_path=args.promotion_plan,
            output_dir=args.output_dir,
            source_run_id=args.source_run_id,
            max_files=args.max_files,
            max_bytes=args.max_bytes,
        )
        print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
    elif args.command == "materialize":
        partition = materialize_partition(
            manifest_path=args.manifest,
            partition_id=args.partition_id,
            candidate_ndjson_path=args.candidate_ndjson,
            prepared_root=args.prepared_root,
            repository_root=args.repository_root,
        )
        print(
            json.dumps(
                {
                    "partition_id": partition["partition_id"],
                    "kind": partition["kind"],
                    "action_count": partition.get("action_count", 0),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
