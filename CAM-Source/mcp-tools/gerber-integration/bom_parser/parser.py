"""SUB_05 — XLSX / CSV / TSV BOM + CPL ingestion with column heuristics.

Column detection is header-name based with a fallback positional guess; refdes
ranges (``R1-R4``) and comma lists (``R1,R2,R3``) both expand. A line with no
MPN is kept — it still costs assembly labour even when it cannot be sourced.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pcba_schemas import BOMLine

logger = logging.getLogger(__name__)

# §A15 SS-EXTRACT-BOM column_heuristics — first match wins, checked in order.
_COLUMN_ALIASES: Dict[str, Sequence[str]] = {
    "refdes": ("refdes", "reference", "references", "designator", "designators",
               "ref des", "ref", "part reference", "component"),
    "qty": ("qty", "quantity", "qnty", "count", "qty per board", "quantity per pcb"),
    "mpn": ("mpn", "manufacturer part number", "mfr part", "mfg part number",
            "manufacturer p/n", "part number", "mfr. no", "mfr no", "mpn1", "vendor part"),
    "package": ("package", "footprint", "case", "case/package", "pattern", "pkg",
                "case code", "smd package"),
    "description": ("description", "desc", "comment", "value", "part description"),
    "manufacturer": ("manufacturer", "mfr", "mfg", "manufacture", "brand", "vendor"),
    "dnp": ("dnp", "dni", "do not populate", "fitted", "populate", "install", "no stuff"),
    "alt_mpn": ("alt mpn", "alternate", "alternate mpn", "second source", "substitute"),
}

_TRUE = {"1", "true", "yes", "y", "dnp", "dni", "x", "do not populate", "no stuff"}
_FALSE = {"0", "false", "no", "n", "", "fitted", "populate"}

# R1-R4 / R1..R4 / R1 - R4 / "R1 to R4"
_RANGE = re.compile(r"^([A-Za-z]+)(\d+)(?:-|\.\.)(?:([A-Za-z]+))?(\d+)$")
_SPLIT = re.compile(r"[,;/\s]+")
# A whitespace-padded range separator has to collapse BEFORE the list split, or
# "R1 to R4" tokenises to R1 / TO / R4 and invents a designator called "TO".
_RANGE_SEP = re.compile(r"\s*(?:-|\.\.|\bto\b)\s*(?=[A-Za-z]*\d)", re.IGNORECASE)


@dataclass
class BOMParseResult:
    lines: List[BOMLine] = field(default_factory=list)
    source: str = ""
    warnings: List[str] = field(default_factory=list)
    success: bool = True
    error_message: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source": self.source,
            "lines": [ln.model_dump(mode="json") for ln in self.lines],
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


# ── refdes ──────────────────────────────────────────────────────────────────


def expand_refdes(raw: str) -> List[str]:
    """``"R1-R4, C1 C2"`` → ``["R1","R2","R3","R4","C1","C2"]``.

    A range whose endpoints have different prefixes, or runs longer than 4096,
    is left as the literal token — an unexpandable range is a data problem, not
    a licence to allocate a million strings.
    """
    if not raw:
        return []
    normalised = _RANGE_SEP.sub("-", raw.strip())
    out: List[str] = []
    for token in (t.strip() for t in _SPLIT.split(normalised)):
        if not token:
            continue
        m = _RANGE.match(token)
        if not m:
            out.append(token.upper())
            continue
        prefix, start, end_prefix, end = m.groups()
        if end_prefix and end_prefix.upper() != prefix.upper():
            out.append(token.upper())
            continue
        lo, hi = int(start), int(end)
        if hi < lo or hi - lo > 4096:
            out.append(token.upper())
            continue
        out.extend(f"{prefix.upper()}{n}" for n in range(lo, hi + 1))
    # de-dup, preserve order
    seen: set[str] = set()
    return [r for r in out if not (r in seen or seen.add(r))]


# ── header mapping ──────────────────────────────────────────────────────────


def _normalise(header: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(header or "").strip().lower()).strip()


def _map_headers(headers: Sequence[str]) -> Dict[str, int]:
    norm = [_normalise(h) for h in headers]
    mapping: Dict[str, int] = {}
    for field_name, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            for idx, h in enumerate(norm):
                if idx in mapping.values():
                    continue
                if h == alias:
                    mapping[field_name] = idx
                    break
            if field_name in mapping:
                break
        if field_name in mapping:
            continue
        # substring fallback — "Mfr Part Number #1" style headers
        for alias in aliases:
            for idx, h in enumerate(norm):
                if idx in mapping.values():
                    continue
                if alias in h:
                    mapping[field_name] = idx
                    break
            if field_name in mapping:
                break
    return mapping


def _truthy_dnp(value: str, header: str) -> bool:
    v = str(value or "").strip().lower()
    if _normalise(header) in ("fitted", "populate", "install"):
        return v in _FALSE and v != ""  # inverted column: "no" means DNP
    return v in _TRUE


# ── readers ─────────────────────────────────────────────────────────────────


def _read_rows(path: Path) -> Tuple[List[str], List[List[str]]]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return _read_xlsx(path)
    return _read_delimited(path)


def _read_delimited(path: Path) -> Tuple[List[str], List[List[str]]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return [], []
    # CSV exports carry title blocks too, not just XLSX - same skip both ways.
    header_idx = _find_header_row(rows)
    return rows[header_idx], rows[header_idx + 1:]


def _read_xlsx(path: Path) -> Tuple[List[str], List[List[str]]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows: List[List[str]] = []
    for row in ws.iter_rows(values_only=True):
        cells = ["" if c is None else str(c).strip() for c in row]
        if any(cells):
            rows.append(cells)
    wb.close()
    if not rows:
        return [], []
    header_idx = _find_header_row(rows)
    return rows[header_idx], rows[header_idx + 1:]


def _find_header_row(rows: Sequence[Sequence[str]]) -> int:
    """Altium and friends prepend a title block — the header is the first row
    that maps at least two known columns."""
    for idx, row in enumerate(rows[:20]):
        mapping = _map_headers(row)
        if len(mapping) >= 2 and ("refdes" in mapping or "mpn" in mapping):
            return idx
    return 0


# ── public API ──────────────────────────────────────────────────────────────


def parse_bom(source: str | Path) -> BOMParseResult:
    """Parse one BOM file into `BOMLine`s. Never raises."""
    path = Path(source)
    result = BOMParseResult(source=path.name)
    try:
        headers, rows = _read_rows(path)
    except Exception as exc:  # noqa: BLE001
        return BOMParseResult(
            source=path.name, success=False, error_message=f"{type(exc).__name__}: {exc}"
        )

    if not headers:
        return BOMParseResult(source=path.name, success=False, error_message="BOM file is empty")

    mapping = _map_headers(headers)
    if "refdes" not in mapping and "mpn" not in mapping:
        return BOMParseResult(
            source=path.name,
            success=False,
            error_message=(
                f"No recognisable BOM columns in {path.name} — expected a reference-designator "
                f"or part-number column, saw: {', '.join(str(h) for h in headers[:8])}"
            ),
        )
    missing = [f for f in ("mpn", "package", "qty") if f not in mapping]
    if missing:
        result.warnings.append(f"{path.name}: no column found for {', '.join(missing)}")

    def cell(row: Sequence[str], key: str) -> str:
        idx = mapping.get(key)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "").strip()

    for n, row in enumerate(rows, start=2):
        refdes = expand_refdes(cell(row, "refdes"))
        mpn = cell(row, "mpn").upper()
        if not refdes and not mpn:
            continue

        qty_raw = cell(row, "qty")
        try:
            qty = int(float(qty_raw)) if qty_raw else len(refdes) or 1
        except ValueError:
            qty = len(refdes) or 1
            result.warnings.append(f"{path.name} row {n}: unreadable qty '{qty_raw}', used {qty}")
        if refdes and qty != len(refdes):
            # The refdes list is the authority — a stale qty column is common.
            result.warnings.append(
                f"{path.name} row {n}: qty {qty} disagrees with {len(refdes)} refdes, using refdes"
            )
            qty = len(refdes)

        dnp_idx = mapping.get("dnp")
        dnp = bool(
            dnp_idx is not None
            and _truthy_dnp(cell(row, "dnp"), headers[dnp_idx] if dnp_idx < len(headers) else "")
        )
        description = cell(row, "description")
        if not dnp and "dnp" in description.lower().split():
            dnp = True

        result.lines.append(
            BOMLine(
                refdes=refdes,
                qty_per_board=max(0, qty),
                package=cell(row, "package"),
                mpn=mpn,
                alt_mpns=[a.upper() for a in expand_refdes(cell(row, "alt_mpn"))] if "alt_mpn" in mapping else [],
                manufacturer=cell(row, "manufacturer"),
                description=description,
                dnp=dnp,
            )
        )

    if not result.lines:
        return BOMParseResult(
            source=path.name, success=False, error_message=f"No BOM rows parsed from {path.name}"
        )
    return result


def parse_bom_files(paths: Iterable[str | Path]) -> BOMParseResult:
    """Merge every BOM file in the data pack; the first that parses wins, the
    rest are appended with a warning so nothing is silently dropped."""
    merged = BOMParseResult()
    for p in paths:
        one = parse_bom(p)
        if not one.success:
            merged.warnings.append(one.error_message or f"{Path(p).name}: unparsable")
            continue
        merged.source = merged.source or one.source
        merged.lines.extend(one.lines)
        merged.warnings.extend(one.warnings)
    if not merged.lines:
        merged.success = False
        merged.error_message = "No BOM file in the data pack could be parsed"
    return merged


# ── CPL / centroid ──────────────────────────────────────────────────────────

_CPL_ALIASES = {
    "refdes": ("designator", "refdes", "ref", "reference", "part", "component"),
    "layer": ("layer", "side", "tb", "top/bottom", "layer name"),
    "nozzle": ("nozzle", "feeder", "place method", "method"),
}


def parse_cpl(source: str | Path) -> Dict[str, Any]:
    """Read a pick-and-place / centroid file → per-refdes side + hand flag.

    The SMT point count in §A6 SUB_08 comes from here, not from the BOM: the
    CPL is what the machine actually places.
    """
    path = Path(source)
    try:
        headers, rows = _read_rows(path)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error_message": f"{type(exc).__name__}: {exc}", "placements": {}}
    if not headers:
        return {"success": False, "error_message": "CPL file is empty", "placements": {}}

    norm = [_normalise(h) for h in headers]
    idx: Dict[str, int] = {}
    for key, aliases in _CPL_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                idx[key] = norm.index(alias)
                break
        else:
            for alias in aliases:
                hit = next((i for i, h in enumerate(norm) if alias in h), None)
                if hit is not None:
                    idx[key] = hit
                    break

    if "refdes" not in idx:
        return {
            "success": False,
            "error_message": f"No designator column in {path.name}",
            "placements": {},
        }

    placements: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        ref = str(row[idx["refdes"]] or "").strip().upper() if idx["refdes"] < len(row) else ""
        if not ref:
            continue
        layer_raw = ""
        if "layer" in idx and idx["layer"] < len(row):
            layer_raw = str(row[idx["layer"]] or "").strip().lower()
        side = "bottom" if layer_raw.startswith(("b", "bot")) else "top"
        nozzle = ""
        if "nozzle" in idx and idx["nozzle"] < len(row):
            nozzle = str(row[idx["nozzle"]] or "").strip().lower()
        placements[ref] = {"side": side, "nozzle": nozzle, "hand": nozzle == "hand"}

    return {
        "success": True,
        "source": path.name,
        "placements": placements,
        "sides": sorted({p["side"] for p in placements.values()}),
    }


def fastmcp_extract_bom_components(bom_paths: List[str], cpl_paths: Optional[List[str]] = None) -> dict:
    """SUB_05 handler — BOM lines plus the CPL placement map."""
    bom = parse_bom_files(bom_paths)
    out = bom.as_dict()
    if cpl_paths:
        merged: Dict[str, Any] = {}
        sides: set[str] = set()
        for p in cpl_paths:
            cpl = parse_cpl(p)
            if cpl.get("success"):
                merged.update(cpl["placements"])
                sides.update(cpl.get("sides", []))
            else:
                out["warnings"].append(cpl.get("error_message", "CPL unreadable"))
        out["placements"] = merged
        out["sides_populated"] = len(sides) or 1
    return out
