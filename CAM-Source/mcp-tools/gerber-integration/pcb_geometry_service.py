"""SUB_01 → SUB_03 — the Gerber data-pack extractor (WORK_REPORT §A6 / §B1.1).

Hardened wrapper around ``gerbonara.LayerStack`` that turns a PCBA data-pack ZIP
into a `PCBGeometryResult`. Never raises on user input: every failure comes back
as ``success=False`` with an ``error_message``, so the pipeline degrades instead
of exploding.

FastMCP bindings: ``fastmcp_ingest_pcba_pack``, ``fastmcp_standardize_files``,
``fastmcp_extract_pcb_specs``.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, IO, List, Optional, Union

from pcba_schemas import DrillMetrics, PCBGeometryResult

logger = logging.getLogger(__name__)

try:  # guarded so tests that monkeypatch gerbonara still import
    from gerbonara.utils import MM
except Exception:  # pragma: no cover - gerbonara always ships utils.MM
    MM = "mm"  # type: ignore[assignment]

# §A15 SS-INGEST-DATAPACK dynamic_attributes
GERBER_EXTS = {
    ".gbr", ".ger", ".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs",
    ".gtp", ".gbp", ".gko", ".gm1", ".gm2", ".gm3", ".gpt", ".gpb",
    ".g1", ".g2", ".g3", ".g4", ".top", ".bot", ".smt", ".smb",
    ".sst", ".ssb", ".outline", ".pho",
}
DRILL_EXTS = {".drl", ".xln", ".txt", ".exc", ".tap", ".nc"}
BOM_EXTS = {".xlsx", ".xls", ".csv", ".tsv"}
PNP_EXTS = {".pos", ".xy", ".pnp", ".csv"}
DOC_EXTS = {".pdf", ".md", ".doc", ".docx", ".rtf", ".txt", ".log", ".ini", ".rpt"}

MAX_MEMBERS = 4096
MAX_UNCOMPRESSED_MB = 512


class UnsafeArchiveError(RuntimeError):
    """ZipSlip, zip-bomb, or an otherwise unprocessable archive."""


@dataclass
class DataPack:
    """SUB_02 output — every archive member bucketed by role."""

    root: Path
    gerber_root: Path
    gerber: List[Path] = field(default_factory=list)
    drill: List[Path] = field(default_factory=list)
    bom: List[Path] = field(default_factory=list)
    pick_place: List[Path] = field(default_factory=list)
    docs: List[Path] = field(default_factory=list)
    unknown: List[Path] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, List[str]]:
        return {
            bucket: [str(p) for p in getattr(self, bucket)]
            for bucket in ("gerber", "drill", "bom", "pick_place", "docs", "unknown")
        }


class GerberGeometryExtractor:
    """Extracts board geometry from a PCBA data-pack ZIP."""

    def __init__(
        self,
        *,
        max_members: int = MAX_MEMBERS,
        max_uncompressed_mb: int = MAX_UNCOMPRESSED_MB,
    ) -> None:
        self.max_members = max_members
        self.max_uncompressed_bytes = max_uncompressed_mb * 1024 * 1024

    # ── public API ──────────────────────────────────────────────────────────

    def extract(self, archive: Union[str, Path, bytes, IO[bytes]]) -> PCBGeometryResult:
        """Parse *archive* and return a `PCBGeometryResult`. Never raises."""
        staging: Optional[Path] = None
        try:
            staging = Path(tempfile.mkdtemp(prefix="pcba_pack_"))
            pack = self.unpack(archive, staging)
            return self._analyze(pack)
        except UnsafeArchiveError as exc:
            return PCBGeometryResult(success=False, error_message=str(exc))
        except zipfile.BadZipFile:
            return PCBGeometryResult(
                success=False, error_message="Not a readable ZIP archive (corrupt or truncated)"
            )
        except FileNotFoundError as exc:
            return PCBGeometryResult(success=False, error_message=f"File not found: {exc}")
        except Exception as exc:  # noqa: BLE001 - the whole point is to never raise
            logger.exception("gerber extraction failed")
            return PCBGeometryResult(success=False, error_message=f"{type(exc).__name__}: {exc}")
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    def unpack(self, archive: Union[str, Path, bytes, IO[bytes]], staging: Path) -> DataPack:
        """SUB_01 + SUB_02 — safe extraction then role bucketing."""
        src: Union[str, Path, IO[bytes]]
        if isinstance(archive, bytes):
            import io

            src = io.BytesIO(archive)
        elif isinstance(archive, (str, Path)):
            p = Path(archive)
            if p.is_dir():
                raise UnsafeArchiveError(f"Expected a ZIP archive, got a directory: {p}")
            if not p.exists():
                raise FileNotFoundError(str(p))
            src = p
        else:
            src = archive

        with zipfile.ZipFile(src) as zf:  # type: ignore[arg-type]
            self._guard(zf, staging)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest = self._safe_dest(staging, info.filename)
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with zf.open(info) as fh, dest.open("wb") as out:
                        shutil.copyfileobj(fh, out)
                except RuntimeError as exc:  # encrypted member
                    raise UnsafeArchiveError(
                        f"Password-protected archive member: {info.filename}"
                    ) from exc

        return self._bucket(staging)

    # ── SUB_01 guards ───────────────────────────────────────────────────────

    def _guard(self, zf: zipfile.ZipFile, staging: Path) -> None:
        infos = zf.infolist()
        if len(infos) > self.max_members:
            raise UnsafeArchiveError(
                f"Archive has {len(infos)} members, limit is {self.max_members}"
            )
        total = sum(i.file_size for i in infos)
        if total > self.max_uncompressed_bytes:
            raise UnsafeArchiveError(
                f"Archive expands to {total / 1048576:.1f} MiB, limit is "
                f"{self.max_uncompressed_bytes / 1048576:.0f} MiB"
            )
        for info in infos:
            self._safe_dest(staging, info.filename)

    @staticmethod
    def _safe_dest(staging: Path, name: str) -> Path:
        """ZipSlip check — resolve the destination and confirm it stays inside."""
        norm = name.replace("\\", "/")
        parts = Path(norm).parts
        # PureWindowsPath("/etc/x").is_absolute() is False, so a POSIX-absolute
        # member would slip past to the weaker resolve check. The archive author's
        # intent is absolute either way - reject on the leading separator too.
        if norm.startswith("/") or Path(norm).is_absolute() or (len(norm) > 1 and norm[1] == ":"):
            raise UnsafeArchiveError(f"Absolute path in archive member: {name}")
        if ".." in parts:
            raise UnsafeArchiveError(f"Parent-directory traversal in archive member: {name}")
        dest = (staging / norm).resolve()
        if not str(dest).startswith(str(staging.resolve())):
            raise UnsafeArchiveError(f"Archive member escapes the staging directory: {name}")
        return dest

    # ── SUB_02 bucketing ────────────────────────────────────────────────────

    def _bucket(self, staging: Path) -> DataPack:
        files = [p for p in staging.rglob("*") if p.is_file()]
        if not files:
            raise UnsafeArchiveError("Archive is empty")

        gerber_root, warnings = self._find_gerber_root(staging, files)
        pack = DataPack(root=staging, gerber_root=gerber_root, warnings=warnings)

        for p in files:
            ext = p.suffix.lower()
            name = p.name.lower()
            if ext in GERBER_EXTS:
                pack.gerber.append(p)
            elif ext in DRILL_EXTS and self._looks_like_drill(p):
                pack.drill.append(p)
            elif ext in BOM_EXTS and ("bom" in name or "bill" in name):
                pack.bom.append(p)
            elif ext in PNP_EXTS and any(
                k in name for k in ("pos", "pnp", "cpl", "centroid", "pick", "place", "-all", "xy")
            ):
                pack.pick_place.append(p)
            elif ext in BOM_EXTS:
                pack.bom.append(p)
            elif ext in DOC_EXTS:
                pack.docs.append(p)
            else:
                pack.unknown.append(p)

        if not pack.gerber:
            raise UnsafeArchiveError(
                "No Gerber layers found in the archive — expected .gbr/.gtl/.gbl or similar"
            )
        return pack

    @staticmethod
    def _looks_like_drill(path: Path) -> bool:
        """`.txt` is shared between drill files and readmes — probe the content."""
        if path.suffix.lower() != ".txt":
            return True
        try:
            head = path.read_text(errors="ignore")[:2048].upper()
        except OSError:
            return False
        return "M48" in head or "T01" in head or "DRILL" in head

    def _find_gerber_root(self, staging: Path, files: List[Path]) -> tuple[Path, List[str]]:
        """Nested-folder tolerance — pick the dir with the most gerber-like files."""
        counts: Dict[Path, int] = {}
        for p in files:
            if p.suffix.lower() in GERBER_EXTS:
                counts[p.parent] = counts.get(p.parent, 0) + 1
        if not counts:
            return staging, []
        best = max(counts, key=lambda d: counts[d])
        if best != staging:
            rel = best.relative_to(staging)
            return best, [f"Gerber files found in nested folder '{rel}'"]
        return best, []

    # ── SUB_03 analysis ─────────────────────────────────────────────────────

    def _analyze(self, pack: DataPack) -> PCBGeometryResult:
        from gerbonara import LayerStack

        warnings = list(pack.warnings)
        # lazy=True so one unparsable member (a vendor-quirk Excellon, an Allegro
        # drill file missing its nc_param.txt) degrades that layer only — every
        # accessor below resolves its own file inside a try.
        stack = LayerStack.open_dir(pack.gerber_root, lazy=True, autoguess=True)

        width, height, estimated, dim_warnings = self._dimensions(stack)
        warnings.extend(dim_warnings)

        layer_count = len(list(stack.copper_layers))
        inner = len(list(stack.inner_layers))

        drills, drill_warnings = self._drills(stack)
        warnings.extend(drill_warnings)

        confidence = 1.0
        if estimated:
            confidence -= 0.3
        if layer_count == 0:
            confidence -= 0.4
            warnings.append("No copper layers detected")
        if width <= 0 or height <= 0:
            confidence -= 0.3
            warnings.append("One or more dimensions resolved to zero")

        detected = sorted(p.name for p in pack.gerber + pack.drill)

        return PCBGeometryResult(
            success=True,
            width_mm=round(width, 3),
            height_mm=round(height, 3),
            area_cm2=round(width * height / 100.0, 3),
            layer_count=layer_count,
            inner_layer_count=inner,
            has_top_soldermask=self._has(stack, "top", "mask"),
            has_bottom_soldermask=self._has(stack, "bottom", "mask"),
            has_top_silkscreen=self._has(stack, "top", "silk"),
            has_bottom_silkscreen=self._has(stack, "bottom", "silk"),
            has_top_paste=self._has(stack, "top", "paste"),
            has_bottom_paste=self._has(stack, "bottom", "paste"),
            is_outline_estimated=estimated,
            confidence=round(max(0.0, min(1.0, confidence)), 3),
            drills=drills,
            board_name=getattr(stack, "board_name", None),
            generator=getattr(stack, "generator", None),
            detected_files=detected,
            warnings=warnings,
        )

    @staticmethod
    def _resolve(layer):
        """Force a `LazyCamFile` to parse. Returns None if the file is unparsable."""
        if layer is None:
            return None
        if not getattr(layer, "is_lazy", False):
            return layer
        try:
            return layer.instance
        except Exception as exc:  # noqa: BLE001 - one bad layer must not kill the run
            logger.warning("layer failed to parse: %s", exc)
            return None

    @classmethod
    def _has(cls, stack, side: str, kind: str) -> bool:
        try:
            layer = cls._resolve(stack[side, kind])
        except (KeyError, IndexError, TypeError):
            return False
        return layer is not None and not getattr(layer, "is_empty", False)

    def _dimensions(self, stack) -> tuple[float, float, bool, List[str]]:
        """Primary: mechanical outline bbox. Fallback: copper+mask. Last: full stack."""
        warnings: List[str] = []

        bbox = self._bbox(self._resolve(stack.outline))
        if bbox:
            (x0, y0), (x1, y1) = bbox
            return abs(x1 - x0), abs(y1 - y0), False, warnings

        boxes = [
            b
            for b in (
                self._bbox(self._layer(stack, "top", "copper")),
                self._bbox(self._layer(stack, "bottom", "copper")),
                self._bbox(self._layer(stack, "top", "mask")),
                self._bbox(self._layer(stack, "bottom", "mask")),
            )
            if b
        ]
        if boxes:
            x0 = min(b[0][0] for b in boxes)
            y0 = min(b[0][1] for b in boxes)
            x1 = max(b[1][0] for b in boxes)
            y1 = max(b[1][1] for b in boxes)
            warnings.append(
                "No mechanical outline layer — dimensions estimated from copper/mask extents"
            )
            return abs(x1 - x0), abs(y1 - y0), True, warnings

        try:
            (x0, y0), (x1, y1) = self._stack_bbox(stack)
            warnings.append("Dimensions estimated from the full layer-stack bounding box")
            return abs(x1 - x0), abs(y1 - y0), True, warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Could not compute a bounding box: {exc}")
            return 0.0, 0.0, True, warnings

    @classmethod
    def _layer(cls, stack, side: str, kind: str):
        try:
            return cls._resolve(stack[side, kind])
        except (KeyError, IndexError, TypeError):
            return None

    @staticmethod
    def _bbox(layer):
        if layer is None:
            return None
        try:
            if getattr(layer, "is_empty", False):
                return None
            return layer.bounding_box(MM)
        except Exception:  # noqa: BLE001
            return None

    @classmethod
    def _stack_bbox(cls, stack):
        """Composite bbox over every layer that parses. Raises if none do."""
        boxes = []
        for layer in stack.graphic_layers.values():
            b = cls._bbox(cls._resolve(layer))
            if b:
                boxes.append(b)
        if not boxes:
            raise ValueError("no layer in the stack produced a bounding box")
        return (
            (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
            (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
        )

    def _drills(self, stack) -> tuple[DrillMetrics, List[str]]:
        warnings: List[str] = []
        layers = []
        for raw in stack.drill_layers:
            resolved = self._resolve(raw)
            if resolved is None:
                warnings.append(
                    f"Drill file could not be parsed and was skipped: "
                    f"{getattr(raw, 'original_path', '<unknown>')}"
                )
                continue
            layers.append(resolved)
        if not layers:
            warnings.append("No drill (Excellon) file found in the data pack")
            return DrillMetrics(), warnings

        total = 0
        sizes: List[float] = []
        plated = nonplated = False
        for drill in layers:
            try:
                total += sum(1 for _ in drill.drills())
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Could not count holes in a drill layer: {exc}")
            try:
                # unit= here is called as a callable by gerbonara — pass MM, never "mm"
                sizes.extend(float(s) for s in drill.drill_sizes(unit=MM))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Could not read drill tool sizes: {exc}")
            plated = plated or bool(getattr(drill, "is_plated", False))
            nonplated = nonplated or bool(getattr(drill, "is_nonplated", False))

        if not plated and not nonplated:
            plated = True  # the common case when the export omits plating tags

        sizes = [s for s in sizes if s > 0]
        return (
            DrillMetrics(
                total_holes=total,
                min_hole_size_mm=round(min(sizes), 4) if sizes else None,
                max_hole_size_mm=round(max(sizes), 4) if sizes else None,
                unique_tool_count=len(set(round(s, 4) for s in sizes)),
                has_plated_through_holes=plated,
                has_non_plated_holes=nonplated,
            ),
            warnings,
        )


# ── FastMCP handler bindings (§A5) ──────────────────────────────────────────

_extractor = GerberGeometryExtractor()


def fastmcp_ingest_pcba_pack(archive_path: str, staging_dir: Optional[str] = None) -> dict:
    """SUB_01 — safe-extract the data pack, return the bucketed manifest."""
    staging = Path(staging_dir) if staging_dir else Path(tempfile.mkdtemp(prefix="pcba_pack_"))
    try:
        pack = _extractor.unpack(archive_path, staging)
        return {"success": True, "root": str(staging), **pack.as_dict(), "warnings": pack.warnings}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error_message": str(exc)}


def fastmcp_standardize_files(root: str) -> dict:
    """SUB_02 — re-bucket an already-staged directory."""
    try:
        pack = _extractor._bucket(Path(root))
        return {"success": True, "gerber_root": str(pack.gerber_root), **pack.as_dict()}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error_message": str(exc)}


def fastmcp_extract_pcb_specs(archive_path: str) -> dict:
    """SUB_03 — full extraction from a pack path; returns `PCBGeometryResult`."""
    return _extractor.extract(archive_path).model_dump(mode="json")


def extract_geometry(archive: Union[str, Path, bytes, IO[bytes]]) -> PCBGeometryResult:
    """Convenience wrapper used by the REST layer and the pipeline."""
    return _extractor.extract(archive)
