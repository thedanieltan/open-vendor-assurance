"""OpenVA capability manifest: single source of truth + generator + freshness guard.

WP-OPENVA-CAPABILITY-CONTRACT.

`config/openva-capabilities.yaml` is authoritative. This module:
  * exposes typed accessors over the manifest;
  * generates downstream artifacts (`site/src/generated/openva-capabilities.generated.js`);
  * `check` fails closed when any live surface or generated artifact drifts from the manifest.

Surfaces locked to the manifest (fail closed on drift):
  1. config/controlled-vocabulary.yaml   -> source_types (ordered) + source_type_labels
  2. candidate-source schema enum        -> source_types (ordered)
  3. SOURCE_TYPE_REGISTRY (source_discovery) -> availability.discovery_supported (set)
  4. browser resolver-source-availability.js -> source_types (ordered) + browser_default_selected (set)
  5. resolver_result_pack.RESULT_PACK_VERSION -> contracts.result_pack_version
  6. generated JS artifact                -> byte-identical to a fresh generation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config" / "openva-capabilities.yaml"
GENERATED_JS_PATH = ROOT / "site" / "src" / "generated" / "openva-capabilities.generated.js"
VOCAB_PATH = ROOT / "config" / "controlled-vocabulary.yaml"
SCHEMA_PATH = ROOT / "schemas" / "openva" / "candidate-source.schema.json"
BROWSER_JS_PATH = ROOT / "site" / "src" / "resolver-source-availability.js"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("capability manifest must be a mapping")
    return data


def source_type_ids(manifest: dict[str, Any]) -> list[str]:
    return [str(entry["id"]) for entry in manifest["source_types"]]


def source_type_labels(manifest: dict[str, Any]) -> dict[str, str]:
    return {str(entry["id"]): str(entry["label"]) for entry in manifest["source_types"]}


def availability(manifest: dict[str, Any], key: str) -> list[str]:
    return [str(x) for x in manifest.get("availability", {}).get(key, [])]


def _extract_js_string_list(text: str, declaration: str) -> list[str]:
    """Extract the string literals from `const NAME = [ ... ]` / `new Set([ ... ])`."""
    idx = text.find(declaration)
    if idx == -1:
        raise ValueError("declaration not found: " + declaration)
    open_idx = text.find("[", idx)
    close_idx = text.find("]", open_idx)
    if open_idx == -1 or close_idx == -1:
        raise ValueError("array literal not found for: " + declaration)
    body = text[open_idx + 1 : close_idx]
    return re.findall(r'"([^"]+)"', body)


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
def render_generated_js(manifest: dict[str, Any]) -> str:
    ids = source_type_ids(manifest)
    labels = source_type_labels(manifest)
    contracts = manifest["contracts"]

    def js_str_array(values: list[str], indent: str) -> str:
        lines = [indent + "  " + json.dumps(v) + "," for v in values]
        return "[\n" + "\n".join(lines) + "\n" + indent + "]"

    label_lines = [
        '      ' + json.dumps(k) + ": " + json.dumps(labels[k]) + "," for k in ids
    ]
    avail = manifest.get("availability", {})
    parts = [
        "// GENERATED FILE — DO NOT EDIT.",
        "// Source: config/openva-capabilities.yaml",
        "// Regenerate: python -m tools.openva.capabilities generate",
        "(() => {",
        '  "use strict";',
        "  const CAPABILITIES = Object.freeze({",
        "    manifest_version: " + json.dumps(str(manifest["manifest_version"])) + ",",
        "    contracts: Object.freeze({",
        "      schema_version: " + json.dumps(str(contracts["schema_version"])) + ",",
        "      resolver_contract_version: "
        + json.dumps(str(contracts["resolver_contract_version"]))
        + ",",
        "      result_pack_version: "
        + json.dumps(str(contracts["result_pack_version"]))
        + ",",
        "    }),",
        "    source_types: Object.freeze(" + js_str_array(ids, "    ") + "),",
        "    source_type_labels: Object.freeze({",
        "\n".join(label_lines),
        "    }),",
        "    availability: Object.freeze({",
        "      discovery_supported: Object.freeze("
        + js_str_array([str(x) for x in avail.get("discovery_supported", [])], "      ")
        + "),",
        "      browser_default_selected: Object.freeze("
        + js_str_array([str(x) for x in avail.get("browser_default_selected", [])], "      ")
        + "),",
        "      live_resolver_supported: Object.freeze("
        + js_str_array([str(x) for x in avail.get("live_resolver_supported", [])], "      ")
        + "),",
        "    }),",
        "  });",
        '  if (typeof window !== "undefined") { window.OPENVA_CAPABILITIES = CAPABILITIES; }',
        '  if (typeof module !== "undefined" && module.exports) { module.exports = CAPABILITIES; }',
        "})();",
        "",
    ]
    return "\n".join(parts)


def generate(manifest: dict[str, Any] | None = None) -> None:
    manifest = manifest or load_manifest()
    GENERATED_JS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_JS_PATH.write_text(render_generated_js(manifest), encoding="utf-8")


# --------------------------------------------------------------------------- #
# freshness / consistency (fail closed)
# --------------------------------------------------------------------------- #
def check(manifest: dict[str, Any] | None = None) -> list[str]:
    manifest = manifest or load_manifest()
    problems: list[str] = []
    ids = source_type_ids(manifest)
    labels = source_type_labels(manifest)

    # 1. controlled-vocabulary.yaml
    vocab = yaml.safe_load(VOCAB_PATH.read_text(encoding="utf-8"))
    if list(vocab.get("source_types", [])) != ids:
        problems.append("controlled-vocabulary.yaml source_types differ from manifest (ordered)")
    if {str(k): str(v) for k, v in (vocab.get("source_type_labels") or {}).items()} != labels:
        problems.append("controlled-vocabulary.yaml source_type_labels differ from manifest")

    # 2. candidate-source schema enum
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    enum = schema["properties"]["source_type_candidate"]["enum"]
    if list(enum) != ids:
        problems.append("candidate-source schema enum differs from manifest (ordered)")

    # 3. SOURCE_TYPE_REGISTRY (discovery_supported, set semantics)
    from tools.openva.source_discovery import SOURCE_TYPE_REGISTRY

    if set(SOURCE_TYPE_REGISTRY) != set(availability(manifest, "discovery_supported")):
        problems.append(
            "SOURCE_TYPE_REGISTRY keys differ from availability.discovery_supported"
        )

    # 4. browser arrays
    js = BROWSER_JS_PATH.read_text(encoding="utf-8")
    browser_all = _extract_js_string_list(js, "const CONTROLLED_SOURCE_TYPES")
    if browser_all != ids:
        problems.append("browser CONTROLLED_SOURCE_TYPES differ from manifest (ordered)")
    browser_default = _extract_js_string_list(js, "const DEFAULT_SELECTED_TYPES")
    if set(browser_default) != set(availability(manifest, "browser_default_selected")):
        problems.append(
            "browser DEFAULT_SELECTED_TYPES differ from availability.browser_default_selected"
        )

    # 5. result pack version
    from tools.openva.resolver_result_pack import RESULT_PACK_VERSION

    if str(RESULT_PACK_VERSION) != str(manifest["contracts"]["result_pack_version"]):
        problems.append(
            "RESULT_PACK_VERSION (%s) != manifest contracts.result_pack_version (%s)"
            % (RESULT_PACK_VERSION, manifest["contracts"]["result_pack_version"])
        )

    # 6. generated artifact freshness
    expected = render_generated_js(manifest)
    actual = GENERATED_JS_PATH.read_text(encoding="utf-8") if GENERATED_JS_PATH.exists() else ""
    if actual != expected:
        problems.append(
            "generated artifact is stale: run `python -m tools.openva.capabilities generate`"
        )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVA capability manifest tool")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="regenerate downstream artifacts from the manifest")
    sub.add_parser("check", help="fail closed if any surface or artifact drifts from the manifest")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    if args.command == "generate":
        generate(manifest)
        print("Generated %s from %s" % (GENERATED_JS_PATH.relative_to(ROOT), MANIFEST_PATH.name))
        return 0
    problems = check(manifest)
    if problems:
        print("Capability manifest consistency FAILED:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print("Capability manifest consistent across all locked surfaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
