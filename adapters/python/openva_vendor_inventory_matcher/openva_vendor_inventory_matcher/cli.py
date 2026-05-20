from __future__ import annotations

import argparse
from pathlib import Path

from .matcher import match_inventory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Match a vendor inventory CSV to OpenVA vendor records.")
    parser.add_argument("--pack", required=True, type=Path, help="OpenVA pack directory or openva-pack.json")
    parser.add_argument("--input", required=True, type=Path, help="Customer vendor inventory CSV")
    parser.add_argument("--out", required=True, type=Path, help="Path to write enriched CSV output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    match_inventory(args.pack, args.input, args.out)
    return 0
