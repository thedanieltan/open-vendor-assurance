"""OpenVA vendor inventory matcher.

``match_inventory`` is imported lazily so that consumers needing only the pure
matching ``core`` (e.g. the MCP adapter) do not pull in the CSV/pack stack.
"""

from typing import Any

__all__ = ["match_inventory"]


def __getattr__(name: str) -> Any:
    if name == "match_inventory":
        from openva_vendor_inventory_matcher.matcher import match_inventory

        return match_inventory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
