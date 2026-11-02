"""Fill the PCBA checklist from a data pack, with evidence for every row.

Four sources, in descending order of trust:

    gerber / drill / paste   measured off the artwork itself
    doc_scan                 parsed from fab notes, README or a fab drawing
    bom / cpl                read from the BOM or pick-and-place file
    pack                     a property of the pack (e.g. an ODB++ payload)

A row that none of them can answer is recorded ``ABSENT`` with a null value.
It is never filled with a plausible default: the pricing engine still needs
*something* to price against, so that assumption travels in
``pricing_fallback`` where it cannot be mistaken for an extracted fact.
"""
from __future__ import annotations

import functools
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from pcba_schemas import (
    BOMLine,
    ChecklistExtraction,
    ChecklistField,
    PCBGeometryResult,
    PCBInfo,
    Provenance,
)

logger = logging.getLogger(__name__)

_PATTERNS = Path(
    os.environ.get(
        "PCBA_CHECKLIST_PATTERNS",
        Path(__file__).resolve().parent / "config" / "checklist_patterns.yaml",
    )
)

# The 34 rows of the checklist, in sheet order.
CHECKLIST_ROWS: Tuple[Tuple[str, str, str], ...] = (
    ("Build Info", "customer", "Customer"),
    ("Build Info", "product_name", "Product Name"),
    ("Build Info", "date", "Date"),
    ("Build Info", "triode_pn", "Triode PN"),
    ("Build Info", "rohs", "RoHS"),
    ("Build Info", "ipc_class", "IPC Class"),
    ("Build Info", "lead_time_weeks", "Lead Time (weeks)"),
    ("Build Info", "opp_number", "OPP number"),
    ("Build Info", "build_qty_1", "Build Qty 1"),
    ("Build Info", "build_qty_2", "Build Qty 2"),
    ("Build Info", "build_qty_3", "Build Qty 3"),
    ("Build Info", "build_qty_4", "Build Qty 4"),
    ("Build Info", "conformal_coat", "Conformal Coat"),
    ("Build Info", "cleaning", "Cleaning?"),
    ("Build Info", "wavable", "Wavable?"),
    ("Build Info", "odb_file", "ODB++/PCB File"),
    ("Build Info", "notes", "Notes"),
    ("Build Info", "holes_to_mask_for_wave", "# Holes to mask for wave"),
    ("Build Info", "spam_number", "SPAM#"),
    ("PCB Info", "x_dimension_mm", "X Dimension mm"),
    ("PCB Info", "y_dimension_mm", "Y Dimension mm"),
    ("PCB Info", "boards_per_panel", "Brds/Panel"),
    ("PCB Info", "peelable_mask", "Peelable Mask?"),
    ("PCB Info", "pcb_thickness_mm", "PCB Thickness"),
    ("PCB Info", "mask_colour", "Mask Colour"),
    ("PCB Info", "square_area_cm2", "Square Area cm2"),
    ("PCB Info", "has_smt", "Has SMT?"),
    ("PCB Info", "finish", "Finish"),
    ("PCB Info", "layers", "Layers"),
    ("PCB Info", "material", "Material"),
    ("PCB Info", "resin_filled_via", "Resin filled Via"),
    ("PCB Info", "copper_thickness_oz", "Copper Thickness"),
    ("PCB Info", "silk_colour", "Silk Screen Colour"),
    ("PCB Info", "double_sided", "Double Sided"),
)

# What the pricing engine assumes when a row comes back ABSENT. These mirror
# the PCBInfo defaults — the quote has to price *something* — but they are
# reported as assumptions, never as extracted values.
PRICING_FALLBACKS: Dict[str, Any] = {
    "boards_per_panel": 1,
    "peelable_mask": False,
    "pcb_thickness_mm": 1.6,
    "mask_colour": "Green",
    "has_smt": True,
    "finish": "ENIG",
    "material": "Standard FR4",
    "resin_filled_via": False,
    "copper_thickness_oz": 1.0,
    "silk_colour": "White",
    "ipc_class": "Class II",
    "rohs": True,
}


@functools.lru_cache(maxsize=2)
def load_patterns(path: Optional[str] = None) -> Dict[str, Any]:
    return yaml.safe_load(Path(path or _PATTERNS).read_text(encoding="utf-8")) or {}


# ── text helpers ────────────────────────────────────────────────────────────


def _labelled_window(text: str, labels: Sequence[str]) -> List[str]:
    """Return the text right after each `label:` occurrence.

    A labelled hit ("Surface Finish: ENIG") is worth more than a loose keyword,
    because "no gold plating anywhere" also contains the word gold.
    """
    out: List[str] = []
    for label in labels:
        for m in re.finditer(rf"{re.escape(label)}\s*[:=]\s*(.{{0,80}})", text, re.I):
            out.append(m.group(1))
    return out


def _first_enum(
    text: str, labelled: List[str], spec: Dict[str, Any]
) -> Optional[Tuple[str, float, str]]:
    """Match an enumerated value; labelled windows are searched first."""
    values: Dict[str, List[str]] = spec.get("values") or {}
    for scope, conf_key, how in (
        (labelled, "labelled_confidence", "labelled"),
        ([text], "confidence", "keyword"),
    ):
        for canonical, aliases in values.items():
            for alias in aliases:
                for chunk in scope:
                    if re.search(alias, chunk, re.I):
                        return canonical, float(spec.get(conf_key, 0.7)), how
    return None


def _first_number(text: str, patterns: Sequence[str]) -> Optional[float]:
    for pat in patterns or ():
        m = re.search(pat, text, re.I)
        if m:
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def _boolean(text: str, spec: Dict[str, Any]) -> Optional[bool]:
    """True on a positive hit, False on an explicit negation, None if silent.

    Negations win: "no-clean flux" must not be read as a cleaning requirement.
    """
    for pat in spec.get("negations") or ():
        if re.search(pat, text, re.I):
            return False
    for pat in spec.get("patterns") or ():
        if re.search(pat, text, re.I):
            return True
    return None


def _text_value(text: str, labels: Sequence[str]) -> Optional[str]:
    for label in labels:
        m = re.search(rf"^\s*{re.escape(label)}\s*[:=]\s*(.+?)\s*$", text, re.I | re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


# ── the extraction ──────────────────────────────────────────────────────────


def extract_checklist(
    geometry: Optional[PCBGeometryResult] = None,
    info: Optional[PCBInfo] = None,
    *,
    doc_texts: Optional[Sequence[str]] = None,
    doc_names: Optional[Sequence[str]] = None,
    bom: Optional[Sequence[BOMLine]] = None,
    pack_files: Optional[Sequence[str]] = None,
    operator_values: Optional[Dict[str, Any]] = None,
    patterns: Optional[Dict[str, Any]] = None,
) -> ChecklistExtraction:
    cfg = patterns or load_patterns()
    docs = [str(t or "") for t in (doc_texts or ()) if t]
    names = list(doc_names or ())
    blob = "\n".join(docs)
    operator = {k: v for k, v in (operator_values or {}).items() if v is not None}
    found: Dict[str, ChecklistField] = {}
    warnings: List[str] = []

    def put(
        name: str,
        value: Any,
        provenance: Provenance,
        confidence: float,
        source: str,
        note: str = "",
    ) -> None:
        found[name] = ChecklistField(
            field=name,
            value=value,
            present=True,
            provenance=provenance,
            confidence=round(min(1.0, max(0.0, confidence)), 3),
            source=source,
            note=note,
        )

    # ── measured off the artwork ────────────────────────────────────────────
    if geometry is not None and geometry.success:
        src = "Gerber ZIP / gerbonara"
        # An estimated outline is a weaker measurement, and says so.
        geo_conf = 0.70 if geometry.is_outline_estimated else 0.98
        est_note = (
            "No mechanical outline layer — dimensions estimated from copper/mask extents"
            if geometry.is_outline_estimated
            else ""
        )
        if geometry.width_mm > 0:
            put("x_dimension_mm", geometry.width_mm, Provenance.GERBER, geo_conf, src, est_note)
        if geometry.height_mm > 0:
            put("y_dimension_mm", geometry.height_mm, Provenance.GERBER, geo_conf, src, est_note)
        if geometry.area_cm2 > 0:
            put("square_area_cm2", geometry.area_cm2, Provenance.GERBER, geo_conf, src, est_note)
        if geometry.layer_count > 0:
            put("layers", geometry.layer_count, Provenance.GERBER, 0.98, src)

        # Double-sided is only claimable when both sides carry artwork. A
        # 2-layer board populated on one side is not double-sided.
        both_mask = geometry.has_top_soldermask and geometry.has_bottom_soldermask
        both_paste = geometry.has_top_paste and geometry.has_bottom_paste
        if both_paste:
            put("double_sided", True, Provenance.PASTE, 0.92, src,
                "paste on both sides — components on both sides")
        elif geometry.has_top_paste or geometry.has_bottom_paste:
            put("double_sided", False, Provenance.PASTE, 0.88, src,
                "paste on one side only")
        elif both_mask:
            put("double_sided", True, Provenance.GERBER, 0.60, src,
                "inferred from soldermask on both sides; no paste layer to confirm")

        # Has SMT: a stencil is cut only where paste is deposited.
        if geometry.has_top_paste or geometry.has_bottom_paste:
            put("has_smt", True, Provenance.PASTE, 0.95, src, "solder-paste layer present")
        elif geometry.detected_files:
            warnings.append(
                "No solder-paste layer in the pack — 'Has SMT' cannot be confirmed from "
                "the artwork; export the paste layer or confirm it on the wizard"
            )

    # ── parsed from the shipped documents ───────────────────────────────────
    if blob.strip():
        doc_src = ", ".join(names) or "fab notes"

        for name, spec in (cfg.get("enums") or {}).items():
            hit = _first_enum(blob, _labelled_window(blob, spec.get("labels") or []), spec)
            if hit:
                value, conf, how = hit
                put(name, value, Provenance.DOC_SCAN, conf, doc_src, f"{how} match in docs")

        for name, spec in (cfg.get("numerics") or {}).items():
            lo, hi = float(spec.get("min", -1e9)), float(spec.get("max", 1e9))
            conf = float(spec.get("confidence", 0.8))
            val = _first_number(blob, spec.get("patterns") or [])
            note = ""
            if val is None and spec.get("inch_patterns"):
                inches = _first_number(blob, spec["inch_patterns"])
                if inches is not None:
                    val = inches * float(spec.get("mm_per_inch", 25.4))
                    note = f"converted from {inches} in"
            if val is None and spec.get("micron_patterns"):
                um = _first_number(blob, spec["micron_patterns"])
                if um is not None:
                    val = um / float(spec.get("micron_per_oz", 35.0))
                    note = f"converted from {um} µm"
            if val is None:
                continue
            if not (lo <= val <= hi):
                warnings.append(
                    f"'{name}' scanned as {val:g} from the docs, outside the plausible "
                    f"{lo:g}–{hi:g} range — discarded rather than quoted"
                )
                continue
            # A count is an integer: "4.0 boards per panel" reads like a
            # measurement when it is really just a parsed digit.
            out = int(round(val)) if spec.get("integer") else round(val, 4)
            put(name, out, Provenance.DOC_SCAN, conf, doc_src, note)

        for name, spec in (cfg.get("booleans") or {}).items():
            val = _boolean(blob, spec)
            if val is not None:
                put(name, val, Provenance.DOC_SCAN, float(spec.get("confidence", 0.8)), doc_src)

        for name, spec in (cfg.get("texts") or {}).items():
            val = _text_value(blob, spec.get("labels") or [])
            if val:
                put(name, val, Provenance.DOC_SCAN, float(spec.get("confidence", 0.8)), doc_src)

        for name, spec in (cfg.get("dates") or {}).items():
            iso = _scan_date(blob, spec)
            if iso:
                put(name, iso, Provenance.DOC_SCAN, float(spec.get("confidence", 0.85)),
                    doc_src, "parsed from the document text")

        bq = cfg.get("build_quantities") or {}
        tiers = _build_quantities(blob, bq)
        for i, qty in enumerate(tiers[: int(bq.get("max_tiers", 4))], start=1):
            put(f"build_qty_{i}", qty, Provenance.DOC_SCAN,
                float(bq.get("confidence", 0.85)), doc_src)

    # ── properties of the pack itself ───────────────────────────────────────
    if pack_files is not None:
        exts = [e.lower() for e in (cfg.get("odb_extensions") or [])]
        dirs = [d.lower() for d in (cfg.get("odb_dir_names") or [])]
        lowered = [f.lower().replace("\\", "/") for f in pack_files]
        hit = next(
            (
                f
                for f in lowered
                if any(f.endswith(e) for e in exts)
                or any(f"/{d}/" in f"/{f}" for d in dirs)
            ),
            None,
        )
        put("odb_file", bool(hit), Provenance.PACK, 0.95,
            "data pack", f"matched '{hit}'" if hit else "no native CAD / ODB++ payload in the pack")

    # ── read off the BOM ────────────────────────────────────────────────────
    if bom:
        # SMT is confirmable from the BOM when no paste layer shipped: any
        # non-THT, non-DNP placed part is a surface-mount part.
        if "has_smt" not in found:
            smt = any(not ln.is_tht and not ln.dnp for ln in bom)
            put("has_smt", smt, Provenance.BOM, 0.85, "BOM",
                "inferred from package families; no paste layer to confirm")
        if "wavable" not in found:
            tht = any(ln.is_tht and not ln.dnp for ln in bom)
            put("wavable", tht, Provenance.BOM, 0.70, "BOM",
                "through-hole parts present" if tht else "no through-hole parts")

    # ── the operator's own entries win over everything ──────────────────────
    for name, value in operator.items():
        if any(name == row[1] for row in CHECKLIST_ROWS):
            put(name, value, Provenance.OPERATOR, 1.0, "wizard", "entered by the operator")

    # `date` is the RFQ date, which no Gerber carries. Only an operator entry
    # or a doc scan can supply it — today's date would be a fabrication.
    rows: List[ChecklistField] = []
    for category, name, label in CHECKLIST_ROWS:
        f = found.get(name)
        if f is None:
            f = ChecklistField(
                field=name,
                value=None,
                present=False,
                provenance=Provenance.ABSENT,
                confidence=0.0,
                note="not stated in the data pack",
                pricing_fallback=PRICING_FALLBACKS.get(name),
            )
        f.category = category
        f.label = label
        rows.append(f)

    present = [f for f in rows if f.present]
    assumed = [f for f in rows if f.is_assumed]
    if assumed:
        warnings.append(
            f"{len(assumed)} field(s) are not stated in the pack and will be priced on an "
            f"assumption: " + ", ".join(f.label for f in assumed)
        )
    return ChecklistExtraction(
        fields=rows,
        total=len(rows),
        extracted=len(present),
        absent=len(rows) - len(present),
        mean_confidence=round(sum(f.confidence for f in present) / len(present), 3)
        if present
        else 0.0,
        docs_scanned=list(names),
        warnings=warnings,
    )


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _scan_date(text: str, spec: Dict[str, Any]) -> Optional[str]:
    """Return an ISO date string, or None.

    Only unambiguous formats are accepted. 04/05/2024 is deliberately NOT
    matched: it is April 5th to half the world and May 4th to the other half,
    and a build sheet is the wrong place to guess.
    """
    windows = _labelled_window(text, spec.get("labels") or []) or [text]
    for pat in spec.get("patterns") or ():
        for chunk in windows:
            m = re.search(pat, chunk, re.I)
            if not m:
                continue
            raw = m.group(1).strip()
            iso = _to_iso(raw)
            if iso:
                return iso
    return None


def _to_iso(raw: str) -> Optional[str]:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        return raw
    m = re.fullmatch(r"([0-9]{1,2})\s+([a-z]+)\s+([0-9]{4})", raw, re.I)
    if m:
        mon = _MONTHS.get(m.group(2)[:3].lower())
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"([a-z]+)\s+([0-9]{1,2}),?\s+([0-9]{4})", raw, re.I)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    return None


def _build_quantities(text: str, spec: Dict[str, Any]) -> List[int]:
    """Pull the build-quantity tiers, de-duplicated and in ascending order."""
    out: List[int] = []
    for pat in spec.get("patterns") or ():
        for m in re.finditer(pat, text, re.I):
            for tok in re.split(r"[,/\s]+", m.group(1)):
                if tok.isdigit():
                    n = int(tok)
                    if n > 0 and n not in out:
                        out.append(n)
    return sorted(out)
