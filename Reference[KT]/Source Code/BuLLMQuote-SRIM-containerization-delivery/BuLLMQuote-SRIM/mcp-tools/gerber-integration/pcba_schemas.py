"""Pydantic v2 contracts for Gerber geometry + PCBA checklist extraction.

Trimmed subset of the original PCBA-FE project's `engine/pcba_schemas.py` --
this repo only ever needs the geometry/checklist/BOM-line models (used by
`pcb_geometry_service.py`, `checklist_extractor/extractor.py`,
`bom_parser/parser.py`, `component_intel/packages.py`), never the
costing/quote/pricing models (SupplierPrice, MaterialCost, FabCost,
AssemblyPlan/Cost, MachineCost, LabourCost, LogisticsCost, TaxLine,
PCBAQuote, HITLRequest) -- those belonged to the full quoting pipeline this
platform deliberately does not run (see `extraction_pipeline.py`'s own
module docstring for why). Every model kept below is copied verbatim from
the original, not rewritten.

Every model is ``extra="forbid"`` so a typo in a handler payload fails loudly
at the subskill boundary instead of silently vanishing into the manifest.
"""
from __future__ import annotations

from datetime import date as _date
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── Gerber geometry ──────────────────────────────────────────────────────────


class DrillMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_holes: int = Field(0, ge=0)
    min_hole_size_mm: Optional[float] = Field(None, gt=0)
    max_hole_size_mm: Optional[float] = Field(None, gt=0)
    unique_tool_count: int = Field(0, ge=0)
    has_plated_through_holes: bool = False
    has_non_plated_holes: bool = False


class PCBGeometryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool = False
    width_mm: float = 0.0
    height_mm: float = 0.0
    area_cm2: float = 0.0
    layer_count: int = 0
    inner_layer_count: int = 0
    has_top_soldermask: bool = False
    has_bottom_soldermask: bool = False
    has_top_silkscreen: bool = False
    has_bottom_silkscreen: bool = False
    # Solder-paste layers are the physical evidence for "Has SMT": a stencil is
    # only cut where paste is deposited, so no paste layer means no reflow SMT.
    has_top_paste: bool = False
    has_bottom_paste: bool = False
    is_outline_estimated: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    drills: DrillMetrics = Field(default_factory=DrillMetrics)
    board_name: Optional[str] = None
    generator: Optional[str] = None
    detected_files: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def area_dm2(self) -> float:
        """Board area in dm² -- kept for parity with the original schema even
        though no cost engine consumes it here."""
        return round(self.area_cm2 / 100.0, 6)


class PCBInfo(BaseModel):
    """The industry "PCB Info" build sheet. Non-Gerber-derivable fields carry
    the same industry defaults the original schema used."""

    model_config = ConfigDict(extra="forbid")

    product_name: str = "Unnamed board"
    date: _date = Field(default_factory=_date.today)
    x_dimension_mm: float = 0.0
    y_dimension_mm: float = 0.0
    square_area_cm2: float = 0.0
    layers: int = 0
    boards_per_panel: int = 1
    finish: str = "ENIG"
    material: str = "Standard FR4"
    pcb_thickness_mm: float = 1.6
    copper_thickness_oz: float = 1.0
    mask_colour: str = "Green"
    silk_colour: str = "White"
    peelable_mask: bool = False
    resin_filled_via: bool = False
    has_smt: bool = True
    double_sided: bool = False

    @property
    def area_dm2(self) -> float:
        return round(self.square_area_cm2 / 100.0, 6)


def pcb_info_from_result(
    result: PCBGeometryResult,
    *,
    product_name: Optional[str] = None,
    date: Optional[_date] = None,
    **overrides: Any,
) -> PCBInfo:
    """Compose a `PCBInfo` from a geometry result plus operator overrides."""
    layers = result.layer_count
    fields: Dict[str, Any] = {
        "product_name": product_name or result.board_name or "Unnamed board",
        "date": date or _date.today(),
        "x_dimension_mm": result.width_mm,
        "y_dimension_mm": result.height_mm,
        "square_area_cm2": result.area_cm2,
        "layers": layers,
        "double_sided": (result.has_top_soldermask and result.has_bottom_soldermask)
        or layers >= 2,
    }
    fields.update({k: v for k, v in overrides.items() if v is not None})
    return PCBInfo(**fields)


# ── PCBA checklist extraction ────────────────────────────────────────────────


class Provenance(str, Enum):
    """Where a checklist value actually came from.

    `ABSENT` is a first-class outcome, not a failure: a pack that does not
    state its copper weight must record "not stated", never 1 oz. A default
    written into the record is indistinguishable from a measurement later, and
    that is how a board gets built on an assumption nobody agreed to.
    """

    GERBER = "gerber"          # measured off the Gerber geometry
    DRILL = "drill"            # measured off the Excellon drill file
    PASTE = "paste"            # inferred from solder-paste layer presence
    DOC_SCAN = "doc_scan"      # parsed out of fab notes / README / fab drawing
    BOM = "bom"                # read from the BOM file
    CPL = "cpl"                # read from the pick-and-place file
    PACK = "pack"              # a property of the pack itself (file presence)
    OPERATOR = "operator"      # entered on the wizard
    ABSENT = "absent"          # not in the pack and not supplied


class ChecklistField(BaseModel):
    """One checklist row, with its evidence attached."""

    model_config = ConfigDict(extra="forbid")

    category: str = ""
    field: str = ""
    label: str = ""
    value: Optional[Any] = None
    present: bool = False
    provenance: Provenance = Provenance.ABSENT
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    source: str = ""
    note: str = ""
    # What the pricing engine would assume when `present` is False. Carried
    # separately from `value` so an assumption can never be read as a fact.
    pricing_fallback: Optional[Any] = None

    @property
    def is_assumed(self) -> bool:
        return not self.present and self.pricing_fallback is not None


class ChecklistExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    fields_: List[ChecklistField] = Field(default_factory=list, alias="fields")
    total: int = 0
    extracted: int = 0
    absent: int = 0
    mean_confidence: float = 0.0
    docs_scanned: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    def get(self, name: str) -> Optional[ChecklistField]:
        return next((f for f in self.fields_ if f.field == name), None)


# ── BOM ───────────────────────────────────────────────────────────────────────


class BOMLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refdes: List[str] = Field(default_factory=list)
    qty_per_board: int = Field(1, ge=0)
    package: str = ""
    mpn: str = ""
    alt_mpns: List[str] = Field(default_factory=list)
    manufacturer: str = ""
    description: str = ""
    dnp: bool = False
    substitutes_allowed: bool = True
    # filled by component_intel
    placement_class: str = "PLACE-SMD-STANDARD"
    package_family: str = "UNKNOWN"
    is_tht: bool = False
    pin_count: int = Field(0, ge=0)
    lifecycle_status: str = "unknown"
