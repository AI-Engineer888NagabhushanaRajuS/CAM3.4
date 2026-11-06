"""Runs exactly the slice of the original PCBA-FE quoting pipeline that
Gerber geometry + checklist extraction actually needs, replacing what used
to be two separate MCP calls (`gerber__extract_pcb_specs`,
`gerber__extract_checklist`) to a second, externally-managed server.

The original pipeline (`pcba_pipeline.run_async`, in the external PCBA-FE
project) runs geometry -> rendering -> BOM -> LIVE SUPPLIER PRICING ->
material/fab cost -> assembly plan/cost -> checklist -> quote consolidation,
of which the checklist is only one late stage. Only unpack -> geometry ->
BOM parse/enrich -> doc-text extraction actually feed into
`extract_checklist()` (confirmed by reading that function's real call site) --
rendering, live pricing, and every cost engine do not, so none of that runs
here. This keeps the extraction fully local/offline: no network calls, no
external process, no MCP hop.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

# gerbonara warns (SyntaxWarning) on every spec-noncompliant line it tolerates
# in real-world vendor Gerber exports (e.g. zero-size-aperture D01 codes) --
# harmless to the extraction itself (confirmed: geometry/checklist results
# are correct regardless), but floods this service's log with thousands of
# lines per real file. Suppressed at the source rather than left to bury
# genuine errors in the same log.
warnings.filterwarnings("ignore", category=SyntaxWarning, module="gerbonara.*")

# component_intel/packages.py resolves its package_map.yaml path at IMPORT
# TIME, defaulting to the original PCBA-FE project's own directory layout
# (a sibling `assembly_cost_engine/config/` folder we deliberately didn't
# copy, since assembly_cost_engine itself is cost-pipeline-only and unused
# here). Must be set before that import below, pointing at this repo's own
# copy instead.
os.environ.setdefault(
    "PCBA_PACKAGE_MAP",
    str(Path(__file__).resolve().parent / "config" / "package_map.yaml"),
)

from bom_parser import parse_bom_files  # noqa: E402
from checklist_extractor import extract_checklist  # noqa: E402
from component_intel import enrich_lines  # noqa: E402
from pcb_geometry_service import GerberGeometryExtractor  # noqa: E402
from pcba_schemas import pcb_info_from_result  # noqa: E402

logger = logging.getLogger(__name__)

_extractor = GerberGeometryExtractor()


def _doc_texts(docs: List[Path]) -> List[str]:
    """Best-effort text out of the pack's readme / fab-note files -- verbatim
    logic from the original pipeline's own `_doc_texts` helper."""
    out: List[str] = []
    for p in docs:
        try:
            if p.suffix.lower() == ".pdf":
                import pymupdf  # noqa: PLC0415 - optional dependency

                with pymupdf.open(p) as pdf:
                    out.append("\n".join(page.get_text() for page in pdf))
            else:
                out.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not read doc %s: %s", p, exc)
    return out


def _pack_file_names(pack: Any) -> List[str]:
    """Every file in the pack, for the checklist's own ODB++/native-CAD
    detection. `unknown` here matches `DataPack`'s own attribute name
    (pcb_geometry_service.py) -- the original pipeline's equivalent pack
    object called this bucket `other`, but it's the same role."""
    names: List[str] = []
    for attr in ("gerber", "drill", "bom", "pick_place", "docs", "unknown"):
        for p in getattr(pack, attr, None) or ():
            try:
                names.append(str(p))
            except Exception:  # noqa: BLE001
                pass
    return names


def run_geometry_and_checklist(archive_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Unpacks *archive_path* once, extracts Gerber geometry, parses+enriches
    any BOM in the pack, reads any doc text, then runs the 34-row checklist
    extraction against all of it. Returns `(geometry_dict, checklist_dict)`
    in the exact shape `mcp_server.py`'s `extract_features` already expects
    from the two former MCP tool calls this replaces -- no changes needed
    there beyond how these two dicts are obtained.

    Never raises -- geometry extraction itself already never raises
    (`GerberGeometryExtractor.extract`'s own contract), and every stage past
    it degrades independently exactly as the original pipeline did (a BOM
    that fails to parse still allows geometry+checklist to complete; a
    checklist failure is reported via its own `success` field).
    """
    staging = Path(tempfile.mkdtemp(prefix="gerber_pack_"))
    try:
        try:
            pack = _extractor.unpack(archive_path, staging)
        except Exception as exc:  # noqa: BLE001 - unpack/ingest failure
            geometry_dict = {"success": False, "error_message": f"{type(exc).__name__}: {exc}"}
            checklist_dict = {"success": False, "error_message": "pipeline stopped before the checklist stage"}
            return geometry_dict, checklist_dict

        geometry = _extractor._analyze(pack)
        geometry_dict = geometry.model_dump(mode="json")

        if not geometry.success:
            checklist_dict = {
                "success": False,
                "error_message": geometry.error_message or "geometry extraction failed",
            }
            return geometry_dict, checklist_dict

        info = pcb_info_from_result(geometry)

        bom_lines = []
        if pack.bom:
            parsed = parse_bom_files(pack.bom)
            if parsed.success:
                bom_lines = enrich_lines(parsed.lines)

        try:
            checklist = extract_checklist(
                geometry,
                info,
                doc_texts=_doc_texts(pack.docs),
                doc_names=[d.name for d in pack.docs],
                bom=bom_lines,
                pack_files=_pack_file_names(pack),
                operator_values={},  # no operator-override UI exists in this flow
            )
            checklist_dict = {"success": True, **checklist.model_dump(mode="json", by_alias=True)}
        except Exception as exc:  # noqa: BLE001 - a checklist miss must not kill the extraction
            logger.warning("checklist extraction failed: %s", exc)
            checklist_dict = {"success": False, "error_message": f"{type(exc).__name__}: {exc}"}

        return geometry_dict, checklist_dict
    finally:
        shutil.rmtree(staging, ignore_errors=True)
