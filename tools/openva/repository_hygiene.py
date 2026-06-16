"""Repository hygiene checks for construction-process residue.

OpenVA legitimately contains bot workflows, agent exports, MCP integration,
automation contracts, and vendor records for AI companies. Those are product
and catalog content. This checker targets a narrower class of residue that does
not belong in the public repository: model attribution, shared chat/session
links, construction transcripts, and tool-branded working branch names.

Published history is not rewritten by this tool. CI checks the current tree and
the commits introduced by the current change.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

# These files contain the checker rules and their regression fixtures, so their
# literal test strings are excluded from the repository-content scan.
SELF_EXCLUDED_PATHS = {
    "tools/openva/repository_hygiene.py",
    "tests/test_repository_hygiene.py",
}

TOOL_BRANCH_PREFIXES = (
    "chatgpt/",
    "claude/",
    "codex/",
    "copilot/",
    "cursor/",
    "gemini/",
    "qwen/",
)


@dataclass(frozen=True)
class PatternRule:
    code: str
    pattern: re.Pattern[str]


RULES = (
    PatternRule(
        "model_coauthor_attribution",
        re.compile(
            r"(?im)^co-authored-by:\s*.*\b(?:anthropic|chatgpt|claude|codex|copilot|gemini|gpt(?:-?\d+)?|openai|qwen)\b"
        ),
    ),
    PatternRule(
        "model_generation_attribution",
        re.compile(
            r"(?i)\b(?:created|drafted|generated|reviewed|written)\s+(?:by|using|with)\s+"
            r"(?:an?\s+ai(?:\s+model)?|anthropic|chatgpt|claude|codex|copilot|gemini|gpt(?:-?\d+)?|openai|qwen)\b"
        ),
    ),
    PatternRule(
        "model_session_reference",
        re.compile(
            r"(?i)\b(?:chatgpt|claude|codex|copilot|gemini|qwen)\s+"
            r"(?:chat|conversation|prompt|session|transcript)\b"
        ),
    ),
    PatternRule(
        "shared_conversation_url",
        re.compile(
            r"(?i)https?://(?:chat\.openai\.com|chatgpt\.com|claude\.ai)/(?:share|shared)/[^\s)>]+"
        ),
    ),
    PatternRule(
        "tool_branch_in_commit_message",
        re.compile(
            r"(?i)\bfrom\s+\S*/(?:chatgpt|claude|codex|copilot|cursor|gemini|qwen)/\S+"
        ),
    ),
)


@dataclass(frozen=True)
class Violation:
    location: str
    code: str
    excerpt: str

    def render(self) -> str:
        return f"{self.location}: {self.code}: {self.excerpt}"


def scan_text(text: str, *, location: str) -> list[Violation]:
    violations: list[Violation] = []
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            excerpt = " ".join(match.group(0).split())[:180]
            violations.append(Violation(f"{location}:{line}", rule.code, excerpt))
    return violations


def branch_name_violations(branch_name: str | None) -> list[Violation]:
    if not branch_name:
        return []
    normalized = branch_name.removeprefix("refs/heads/").strip().lower()
    if any(normalized.startswith(prefix) for prefix in TOOL_BRANCH_PREFIXES):
        return [
            Violation(
                "branch",
                "tool_branded_branch_name",
                branch_name,
            )
        ]
    return []


def _run_git(args: Iterable[str], *, root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def tracked_files(root: Path = ROOT) -> list[Path]:
    output = _run_git(("ls-files", "-z"), root=root)
    return [root / value for value in output.split("\0") if value]


def scan_tracked_tree(root: Path = ROOT) -> list[Violation]:
    violations: list[Violation] = []
    for path in tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in SELF_EXCLUDED_PATHS or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        violations.extend(scan_text(text, location=relative))
    return violations


def _valid_revision(revision: str, *, root: Path) -> bool:
    if not revision or set(revision) == {"0"}:
        return False
    try:
        _run_git(("rev-parse", "--verify", f"{revision}^{{commit}}"), root=root)
    except subprocess.CalledProcessError:
        return False
    return True


def commit_range(base: str | None, head: str, *, root: Path = ROOT) -> str:
    if base and _valid_revision(base, root=root):
        return f"{base}..{head}"
    if _valid_revision(f"{head}^", root=root):
        return f"{head}^..{head}"
    return head


def scan_commit_messages(
    *, base: str | None, head: str = "HEAD", root: Path = ROOT
) -> list[Violation]:
    revision_range = commit_range(base, head, root=root)
    output = _run_git(
        ("log", "--format=%H%x1f%B%x1e", revision_range),
        root=root,
    )
    violations: list[Violation] = []
    for record in output.split("\x1e"):
        if not record.strip() or "\x1f" not in record:
            continue
        commit_sha, message = record.split("\x1f", 1)
        violations.extend(
            scan_text(message.strip(), location=f"commit:{commit_sha.strip()}")
        )
    return violations


def check(
    *,
    root: Path = ROOT,
    base: str | None = None,
    head: str = "HEAD",
    head_ref: str | None = None,
) -> list[Violation]:
    violations = scan_tracked_tree(root)
    violations.extend(scan_commit_messages(base=base, head=head, root=root))
    violations.extend(branch_name_violations(head_ref))
    return sorted(violations, key=lambda item: (item.location, item.code, item.excerpt))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openva-repository-hygiene")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--root", type=Path, default=ROOT)
    check_parser.add_argument("--base")
    check_parser.add_argument("--head", default="HEAD")
    check_parser.add_argument("--head-ref")
    args = parser.parse_args(argv)

    if args.command == "check":
        violations = check(
            root=args.root.resolve(),
            base=args.base,
            head=args.head,
            head_ref=args.head_ref,
        )
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        if violations:
            print(
                f"repository hygiene failed with {len(violations)} violation(s)",
                file=sys.stderr,
            )
            return 1
        print("repository hygiene passed")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
