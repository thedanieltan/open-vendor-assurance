"""Operational risk classification for generated catalog PR diff shapes.

This module classifies PR *change-control* risk only. It does not classify
vendors, sources, compliance posture, security posture, procurement suitability,
or any other advisory property.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from tools.openva.paths import normalize_repo_path

LATEST_OBSERVATIONS_PATH = "maintenance/source-observations/latest-observations.json"


class GeneratedCatalogPrRiskClass(StrEnum):
    LOW_RISK = "LOW_RISK"
    HIGH_RISK = "HIGH_RISK"


@dataclass(frozen=True)
class GeneratedCatalogPrRiskResult:
    risk_class: GeneratedCatalogPrRiskClass
    reasons: tuple[str, ...]
    changed_paths: tuple[str, ...]
    unexpected_paths: tuple[str, ...]

    @property
    def low_risk(self) -> bool:
        return self.risk_class == GeneratedCatalogPrRiskClass.LOW_RISK


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def is_vendor_catalog_record_path(path: str) -> bool:
    """Return true for the bounded canonical vendor catalog record surface."""
    normalized = normalize_repo_path(path)
    parts = _parts(normalized)
    if len(parts) == 4:
        return (
            parts[0] == "data"
            and parts[1] == "vendors"
            and bool(parts[2])
            and parts[3] == "vendor.yaml"
        )
    if len(parts) == 5:
        filename = PurePosixPath(parts[4])
        return (
            parts[0] == "data"
            and parts[1] == "vendors"
            and bool(parts[2])
            and parts[3] in {"sources", "artifacts", "changes"}
            and filename.suffix in {".yaml", ".yml"}
            and bool(filename.stem)
        )
    return False


def is_generated_index_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return normalized.startswith("indexes/") and len(normalized) > len("indexes/")


def is_generated_dist_vendor_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    parts = _parts(normalized)
    filename = PurePosixPath(parts[2]) if len(parts) == 3 else PurePosixPath("")
    return (
        len(parts) == 3
        and parts[0] == "dist"
        and parts[1] == "vendors"
        and filename.suffix == ".json"
        and bool(filename.stem)
    )


def is_generated_catalog_pr_low_risk_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return (
        normalized == "openva-pack.json"
        or normalized == LATEST_OBSERVATIONS_PATH
        or is_vendor_catalog_record_path(normalized)
        or is_generated_index_path(normalized)
        or is_generated_dist_vendor_path(normalized)
    )


def classify_generated_catalog_pr_risk(
    changed_paths: list[str] | tuple[str, ...],
) -> GeneratedCatalogPrRiskResult:
    """Classify a generated candidate-promotion catalog PR by changed paths.

    The low-risk class is intentionally narrow: canonical vendor catalog records,
    deterministic generated index/dist outputs, `openva-pack.json`, and the exact
    committed latest-observations baseline. Any other path fails closed to
    HIGH_RISK so later automerge gates can refuse it.
    """
    paths = tuple(sorted({normalize_repo_path(path) for path in changed_paths if normalize_repo_path(path)}))
    if not paths:
        return GeneratedCatalogPrRiskResult(
            GeneratedCatalogPrRiskClass.HIGH_RISK,
            ("no_changed_paths",),
            (),
            (),
        )

    unexpected = tuple(path for path in paths if not is_generated_catalog_pr_low_risk_path(path))
    if unexpected:
        return GeneratedCatalogPrRiskResult(
            GeneratedCatalogPrRiskClass.HIGH_RISK,
            tuple(f"unexpected_path:{path}" for path in unexpected),
            paths,
            unexpected,
        )

    return GeneratedCatalogPrRiskResult(
        GeneratedCatalogPrRiskClass.LOW_RISK,
        (),
        paths,
        (),
    )


def read_paths_file(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig") as handle:
        return [line.strip() for line in handle if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify generated catalog PR diff risk.")
    parser.add_argument("--paths-file", required=True)
    args = parser.parse_args(argv)

    result = classify_generated_catalog_pr_risk(read_paths_file(args.paths_file))
    print(f"risk_class={result.risk_class.value}")
    for reason in result.reasons:
        print(f"reason={reason}")
    for path in result.unexpected_paths:
        print(f"unexpected_path={path}")
    return 0 if result.low_risk else 1


if __name__ == "__main__":
    raise SystemExit(main())
