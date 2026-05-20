from __future__ import annotations

import argparse
from pathlib import Path

from .exporter import export_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export an OpenVA pack to JSONL files.")
    parser.add_argument("--pack", required=True, type=Path, help="OpenVA pack directory or openva-pack.json")
    parser.add_argument("--out", required=True, type=Path, help="Directory to write JSONL files into")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    export_jsonl(args.pack, args.out)
    return 0
