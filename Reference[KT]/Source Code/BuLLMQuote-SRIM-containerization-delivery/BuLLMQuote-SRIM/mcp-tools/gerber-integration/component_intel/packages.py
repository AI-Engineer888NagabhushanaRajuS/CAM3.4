"""Package → placement class / loss / attrition resolution (§A7).

Every BOM line arrives with a free-text footprint string that no two EDA tools
spell the same way. This module normalises it, matches it against
``package_map.yaml``, and stamps the placement class, package family, loss
factor and attrition factor the cost engines need.
"""
from __future__ import annotations

import functools
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from pcba_schemas import BOMLine

logger = logging.getLogger(__name__)

_CONFIG = Path(
    os.environ.get(
        "PCBA_PACKAGE_MAP",
        Path(__file__).resolve().parents[1] / "assembly_cost_engine" / "config" / "package_map.yaml",
    )
)

# Pin count is only meaningful for pinned packages. "LQFP-48" -> 48, but
# "R_0402_1005Metric" must NOT yield 402 and "RES 10K 0402" must not yield 402:
# a chip resistor size code is a size, not a pin count.
_PIN_COUNT = re.compile(r"^[A-Z]+[-_]?(\d{1,4})$")
_PINNED_FAMILIES = {"SOIC", "SOT", "SSOP", "QFP", "QFN", "DFN", "BGA", "UBGA-FINE", "THT"}
_DEFAULT_THT_PINS = 2
_TOKEN = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True)
class PackageInfo:
    family: str
    placement_class: str
    loss_factor: float
    attrition_factor: float
    is_tht: bool = False
    matched: bool = True


@dataclass(frozen=True)
class PackageMap:
    default: PackageInfo
    # (token, PackageInfo) sorted longest-token-first so "0603METRIC" beats "0603"
    rules: Sequence[Tuple[str, PackageInfo]]
    non_placed_prefixes: Sequence[str]
    fine_pitch_mm: float


@functools.lru_cache(maxsize=4)
def load_package_map(path: Optional[str] = None) -> PackageMap:
    cfg_path = Path(path) if path else _CONFIG
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    default = PackageInfo(
        family=raw.get("default_family", "UNKNOWN"),
        placement_class=raw.get("default_class", "PLACE-SMD-STANDARD"),
        loss_factor=float(raw.get("default_loss_factor", 1.02)),
        attrition_factor=float(raw.get("default_attrition_factor", 1.02)),
        matched=False,
    )

    rules: List[Tuple[str, PackageInfo]] = []
    for family, node in (raw.get("families") or {}).items():
        node = node or {}
        info = PackageInfo(
            family=str(family),
            placement_class=node.get("placement_class", default.placement_class),
            loss_factor=float(node.get("loss_factor", default.loss_factor)),
            attrition_factor=float(node.get("attrition_factor", default.attrition_factor)),
            is_tht=bool(node.get("is_tht", False)),
        )
        for token in node.get("match", []) or []:
            rules.append((_normalise(str(token)), info))
    rules.sort(key=lambda kv: len(kv[0]), reverse=True)

    return PackageMap(
        default=default,
        rules=tuple(rules),
        non_placed_prefixes=tuple(raw.get("non_placed_refdes_prefixes") or []),
        fine_pitch_mm=float(raw.get("fine_pitch_mm", 0.50)),
    )


def _normalise(text: str) -> str:
    return _TOKEN.sub("", str(text or "").upper())


def resolve_package(package: str, *, description: str = "", pmap: Optional[PackageMap] = None) -> PackageInfo:
    """Best-effort family match on the footprint, falling back to the description."""
    pmap = pmap or load_package_map()
    for haystack in (_normalise(package), _normalise(description)):
        if not haystack:
            continue
        for token, info in pmap.rules:
            if token and token in haystack:
                return info
    return pmap.default


def is_non_placed(refdes: Sequence[str], pmap: Optional[PackageMap] = None) -> bool:
    """Test points, fiducials and mounting holes cost nothing to place."""
    pmap = pmap or load_package_map()
    if not refdes:
        return False
    prefixes = tuple(p.upper() for p in pmap.non_placed_prefixes)
    if not prefixes:
        return False
    return all(
        re.match(r"^([A-Z]+)", r.upper()) and re.match(r"^([A-Z]+)", r.upper()).group(1) in prefixes
        for r in refdes
    )


def _pin_count(package: str, family: str) -> int:
    """Pins from the footprint string, for pinned families only."""
    if family not in _PINNED_FAMILIES:
        return 0
    # Match on the raw package with separators kept, so "LQFP-48" and "BGA153"
    # both resolve but "R_0402_1005Metric" does not.
    token = re.sub(r"[^A-Za-z0-9_-]+", "", str(package or "")).upper()
    for candidate in (token, token.split("_")[-1] if "_" in token else ""):
        if not candidate:
            continue
        m = _PIN_COUNT.match(candidate)
        if m:
            n = int(m.group(1))
            if 2 <= n <= 2000:
                return n
    return _DEFAULT_THT_PINS if family == "THT" else 0


def enrich_lines(lines: Iterable[BOMLine], *, pmap: Optional[PackageMap] = None) -> List[BOMLine]:
    """Stamp placement class / family / TH flag / pin count onto each line."""
    pmap = pmap or load_package_map()
    out: List[BOMLine] = []
    for line in lines:
        info = resolve_package(line.package, description=line.description, pmap=pmap)
        pins = _pin_count(line.package, info.family)
        out.append(
            line.model_copy(
                update={
                    "placement_class": info.placement_class,
                    "package_family": info.family,
                    "is_tht": info.is_tht,
                    "pin_count": pins or line.pin_count,
                }
            )
        )
    return out


def factors_for(line: BOMLine, pmap: Optional[PackageMap] = None) -> Tuple[float, float]:
    """``(loss_factor, attrition_factor)`` for one enriched BOM line (§A7)."""
    info = resolve_package(line.package, description=line.description, pmap=pmap)
    return info.loss_factor, info.attrition_factor


def moq_multiplier(moq: int, qty_needed: int, *, cap: float = 2.5) -> Tuple[float, bool]:
    """``max(1.0, moq / qty_needed)`` capped at *cap*.

    Returns ``(multiplier, inflated)`` — *inflated* is True when the uncapped
    value exceeded the cap, which flags the line as build-cost-inflated (§A7).
    """
    if qty_needed <= 0 or moq <= 0:
        return 1.0, False
    raw = max(1.0, moq / qty_needed)
    return (cap, True) if raw > cap else (round(raw, 6), False)


def fastmcp_enrich_components(lines: List[dict]) -> dict:
    """SUB_05 enrichment handler."""
    try:
        parsed = [BOMLine(**ln) for ln in lines]
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error_message": str(exc), "lines": []}
    enriched = enrich_lines(parsed)
    unmapped = [ln.mpn or ",".join(ln.refdes) for ln in enriched if ln.package_family == "UNKNOWN"]
    return {
        "success": True,
        "lines": [ln.model_dump(mode="json") for ln in enriched],
        "warnings": (
            [f"{len(unmapped)} line(s) fell back to the default placement class: "
             f"{', '.join(unmapped[:8])}"]
            if unmapped
            else []
        ),
    }
