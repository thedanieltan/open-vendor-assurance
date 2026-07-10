"""Lightweight workspace inventory and dependency-aware test planning for OpenVA.

This module deliberately avoids introducing a third-party monorepo framework. The
repository remains one product, while independently buildable components and their
shared contracts are declared in ``tools/openva/workspace.yaml``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("workspace.yaml")
SUPPORTED_VERSION = 1


class WorkspaceError(ValueError):
    """Raised when the workspace manifest or requested plan is invalid."""


@dataclass(frozen=True)
class Component:
    component_id: str
    kind: str
    manifests: tuple[str, ...]
    change_patterns: tuple[str, ...]
    test_patterns: tuple[str, ...]
    dependencies: tuple[str, ...]
    install_path: str | None = None
    full_suite: bool = False


@dataclass(frozen=True)
class Workspace:
    version: int
    fallback: str
    components: Mapping[str, Component]


@dataclass(frozen=True)
class WorkspacePlan:
    changed_files: tuple[str, ...]
    direct_components: tuple[str, ...]
    affected_components: tuple[str, ...]
    build_order: tuple[str, ...]
    install_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    unmatched_files: tuple[str, ...]
    full_suite: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "changed_files": list(self.changed_files),
            "direct_components": list(self.direct_components),
            "affected_components": list(self.affected_components),
            "build_order": list(self.build_order),
            "install_paths": list(self.install_paths),
            "test_paths": list(self.test_paths),
            "unmatched_files": list(self.unmatched_files),
            "full_suite": self.full_suite,
            "reason": self.reason,
        }


def _string_tuple(value: Any, *, field: str, component_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise WorkspaceError(f"{component_id}.{field} must be a list of non-empty strings")
    return tuple(value)


def _normalise_repo_path(value: str) -> str:
    value = value.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise WorkspaceError(f"invalid repository-relative path: {value!r}")
    return path.as_posix()


def _matches(path: str, pattern: str) -> bool:
    path = _normalise_repo_path(path)
    pattern = pattern.replace("\\", "/").strip()
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if not pattern:
        return False
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)


def load_workspace(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    root: Path = ROOT,
    require_files: bool = True,
) -> Workspace:
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"workspace manifest not found: {manifest_path}") from exc
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"invalid workspace YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise WorkspaceError("workspace manifest must be a mapping")
    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise WorkspaceError(
            f"unsupported workspace version {version!r}; expected {SUPPORTED_VERSION}"
        )
    fallback = raw.get("fallback", "full_suite")
    if fallback not in {"full_suite", "error"}:
        raise WorkspaceError("fallback must be 'full_suite' or 'error'")

    raw_components = raw.get("components")
    if not isinstance(raw_components, dict) or not raw_components:
        raise WorkspaceError("workspace.components must be a non-empty mapping")

    components: dict[str, Component] = {}
    for component_id, payload in raw_components.items():
        if not isinstance(component_id, str) or not component_id:
            raise WorkspaceError("component ids must be non-empty strings")
        if not isinstance(payload, dict):
            raise WorkspaceError(f"component {component_id} must be a mapping")
        kind = payload.get("kind")
        if not isinstance(kind, str) or not kind:
            raise WorkspaceError(f"{component_id}.kind must be a non-empty string")
        component = Component(
            component_id=component_id,
            kind=kind,
            manifests=_string_tuple(
                payload.get("manifests", []), field="manifests", component_id=component_id
            ),
            change_patterns=_string_tuple(
                payload.get("change_patterns"),
                field="change_patterns",
                component_id=component_id,
            ),
            test_patterns=_string_tuple(
                payload.get("test_patterns", []),
                field="test_patterns",
                component_id=component_id,
            ),
            dependencies=_string_tuple(
                payload.get("dependencies", []),
                field="dependencies",
                component_id=component_id,
            ),
            install_path=payload.get("install_path"),
            full_suite=bool(payload.get("full_suite", False)),
        )
        if not component.change_patterns:
            raise WorkspaceError(f"{component_id}.change_patterns must not be empty")
        if component.install_path is not None and not isinstance(component.install_path, str):
            raise WorkspaceError(f"{component_id}.install_path must be a string or null")
        components[component_id] = component

    workspace = Workspace(version=version, fallback=fallback, components=components)
    validate_workspace(workspace, root=root, require_files=require_files)
    return workspace


def _visit_dependencies(
    component_id: str,
    components: Mapping[str, Component],
    temporary: set[str],
    permanent: set[str],
    order: list[str],
) -> None:
    if component_id in permanent:
        return
    if component_id in temporary:
        raise WorkspaceError(f"workspace dependency cycle includes {component_id}")
    temporary.add(component_id)
    for dependency in components[component_id].dependencies:
        _visit_dependencies(dependency, components, temporary, permanent, order)
    temporary.remove(component_id)
    permanent.add(component_id)
    order.append(component_id)


def topological_order(workspace: Workspace, component_ids: Iterable[str] | None = None) -> tuple[str, ...]:
    requested = set(component_ids or workspace.components)
    unknown = requested - set(workspace.components)
    if unknown:
        raise WorkspaceError(f"unknown components: {', '.join(sorted(unknown))}")

    closure = set(requested)
    pending = list(requested)
    while pending:
        component_id = pending.pop()
        for dependency in workspace.components[component_id].dependencies:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)

    order: list[str] = []
    temporary: set[str] = set()
    permanent: set[str] = set()
    for component_id in workspace.components:
        if component_id in closure:
            _visit_dependencies(component_id, workspace.components, temporary, permanent, order)
    return tuple(order)


def _expand_test_patterns(root: Path, patterns: Iterable[str]) -> tuple[str, ...]:
    output: set[str] = set()
    for pattern in patterns:
        normalised = pattern.replace("\\", "/")
        if any(character in normalised for character in "*?["):
            for path in root.glob(normalised):
                if path.is_file():
                    output.add(path.relative_to(root).as_posix())
        else:
            path = root / normalised
            if path.exists():
                output.add(normalised)
    return tuple(sorted(output))


def validate_workspace(
    workspace: Workspace,
    *,
    root: Path = ROOT,
    require_files: bool = True,
) -> None:
    component_ids = set(workspace.components)
    for component in workspace.components.values():
        unknown = set(component.dependencies) - component_ids
        if unknown:
            raise WorkspaceError(
                f"{component.component_id} has unknown dependencies: {', '.join(sorted(unknown))}"
            )
        if component.component_id in component.dependencies:
            raise WorkspaceError(f"{component.component_id} cannot depend on itself")
        for pattern in component.change_patterns:
            _normalise_repo_path(pattern.replace("*", "placeholder").replace("?", "q"))
        for manifest in component.manifests:
            manifest = _normalise_repo_path(manifest)
            if require_files and not (root / manifest).is_file():
                raise WorkspaceError(
                    f"{component.component_id} manifest does not exist: {manifest}"
                )
        if component.install_path is not None:
            install_path = _normalise_repo_path(component.install_path)
            if require_files and not (root / install_path).is_dir():
                raise WorkspaceError(
                    f"{component.component_id} install path does not exist: {install_path}"
                )
        if require_files and component.test_patterns and not _expand_test_patterns(
            root, component.test_patterns
        ):
            raise WorkspaceError(
                f"{component.component_id} test patterns do not match repository files"
            )
    topological_order(workspace)


def _reverse_dependents(workspace: Workspace) -> dict[str, set[str]]:
    reverse = {component_id: set() for component_id in workspace.components}
    for component in workspace.components.values():
        for dependency in component.dependencies:
            reverse[dependency].add(component.component_id)
    return reverse


def _dependent_closure(workspace: Workspace, component_ids: Iterable[str]) -> set[str]:
    reverse = _reverse_dependents(workspace)
    affected = set(component_ids)
    pending = list(component_ids)
    while pending:
        component_id = pending.pop()
        for dependent in reverse[component_id]:
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)
    return affected


def plan_workspace(
    workspace: Workspace,
    changed_files: Iterable[str],
    *,
    root: Path = ROOT,
) -> WorkspacePlan:
    changed = tuple(sorted({_normalise_repo_path(path) for path in changed_files if path.strip()}))
    if not changed:
        direct = set(workspace.components)
        affected = set(workspace.components)
        reason = "no changed files supplied; conservative full-suite plan"
        unmatched: tuple[str, ...] = ()
    else:
        direct = set()
        unmatched_items: list[str] = []
        for path in changed:
            matched = {
                component.component_id
                for component in workspace.components.values()
                if any(_matches(path, pattern) for pattern in component.change_patterns)
                or any(_matches(path, pattern) for pattern in component.test_patterns)
            }
            if matched:
                direct.update(matched)
            else:
                unmatched_items.append(path)
        unmatched = tuple(sorted(unmatched_items))
        if unmatched:
            if workspace.fallback == "error":
                raise WorkspaceError(
                    "changed files are not owned by the workspace: " + ", ".join(unmatched)
                )
            direct = set(workspace.components)
            affected = set(workspace.components)
            reason = "unowned changed files triggered conservative full-suite fallback"
        else:
            affected = _dependent_closure(workspace, direct)
            reason = "dependency-aware affected-component plan"

    full_suite = any(workspace.components[item].full_suite for item in affected)
    if full_suite:
        test_paths = ("tests",)
        affected = set(workspace.components)
        reason = "shared component change requires the full repository suite"
    else:
        patterns = [
            pattern
            for component_id in affected
            for pattern in workspace.components[component_id].test_patterns
        ]
        test_paths = _expand_test_patterns(root, patterns)
        if not test_paths:
            raise WorkspaceError("affected components resolved to no test paths")

    build_order = topological_order(workspace, affected)
    install_paths = tuple(
        dict.fromkeys(
            workspace.components[component_id].install_path
            for component_id in build_order
            if workspace.components[component_id].install_path is not None
        )
    )
    return WorkspacePlan(
        changed_files=changed,
        direct_components=tuple(sorted(direct)),
        affected_components=tuple(component_id for component_id in build_order if component_id in affected),
        build_order=build_order,
        install_paths=install_paths,
        test_paths=test_paths,
        unmatched_files=unmatched,
        full_suite=full_suite,
        reason=reason,
    )


def changed_files_from_git(base_ref: str, head_ref: str = "HEAD", *, root: Path = ROOT) -> tuple[str, ...]:
    command = ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref, head_ref]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise WorkspaceError(f"unable to calculate git diff: {detail.strip()}") from exc
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _write_github_output(path: Path, plan: WorkspacePlan) -> None:
    payload = plan.as_dict()
    lines = [
        f"full_suite={'true' if plan.full_suite else 'false'}",
        "components=" + json.dumps(payload["affected_components"], separators=(",", ":")),
        "install_paths=" + json.dumps(payload["install_paths"], separators=(",", ":")),
        "test_paths=" + json.dumps(payload["test_paths"], separators=(",", ":")),
        "plan=" + json.dumps(payload, sort_keys=True, separators=(",", ":")),
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate the workspace manifest")

    list_parser = subparsers.add_parser("list", help="list workspace components")
    list_parser.add_argument("--json", action="store_true", dest="as_json")

    plan_parser = subparsers.add_parser("plan", help="produce an affected-component test plan")
    plan_parser.add_argument("--changed-file", action="append", default=[])
    plan_parser.add_argument("--changed-files-file", type=Path)
    plan_parser.add_argument("--base-ref")
    plan_parser.add_argument("--head-ref", default="HEAD")
    plan_parser.add_argument("--github-output", type=Path)
    plan_parser.add_argument("--pretty", action="store_true")
    return parser


def _read_changed_files(args: argparse.Namespace) -> tuple[str, ...]:
    changed = list(args.changed_file)
    if args.changed_files_file:
        changed.extend(
            line.strip()
            for line in args.changed_files_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if args.base_ref:
        changed.extend(changed_files_from_git(args.base_ref, args.head_ref, root=args.root))
    return tuple(changed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        workspace = load_workspace(args.manifest, root=args.root)
        if args.command == "validate":
            print(json.dumps({"valid": True, "component_count": len(workspace.components)}))
            return 0
        if args.command == "list":
            components = [
                {
                    "id": component.component_id,
                    "kind": component.kind,
                    "dependencies": list(component.dependencies),
                    "install_path": component.install_path,
                }
                for component in workspace.components.values()
            ]
            if args.as_json:
                print(json.dumps(components, indent=2, sort_keys=True))
            else:
                for component in components:
                    print(component["id"])
            return 0
        if args.command == "plan":
            plan = plan_workspace(workspace, _read_changed_files(args), root=args.root)
            if args.github_output:
                _write_github_output(args.github_output, plan)
            print(json.dumps(plan.as_dict(), indent=2 if args.pretty else None, sort_keys=True))
            return 0
        parser.error(f"unsupported command: {args.command}")
    except (WorkspaceError, OSError) as exc:
        print(f"workspace error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
