"""SUB_05 enrichment — package → placement class, loss/attrition, MOQ (§A7)."""
from component_intel.packages import (
    PackageInfo,
    PackageMap,
    enrich_lines,
    factors_for,
    fastmcp_enrich_components,
    is_non_placed,
    load_package_map,
    moq_multiplier,
    resolve_package,
)

__all__ = [
    "PackageInfo",
    "PackageMap",
    "enrich_lines",
    "factors_for",
    "fastmcp_enrich_components",
    "is_non_placed",
    "load_package_map",
    "moq_multiplier",
    "resolve_package",
]
