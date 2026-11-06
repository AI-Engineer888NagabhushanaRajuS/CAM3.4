"""Store each formula's calculated value next to it in an exported workbook.

openpyxl writes formulas without results. Excel recalculates on open (the workbook asks for it), but Protected
View (files from email or the web), Outlook/Windows previews, phones and scripts do not recalculate, so every
formula cell shows blank. LibreOffice, run headless on a copy, recalculates every formula; its results are copied
verbatim into the original file's cells, so layout and styles stay exactly as the exporter wrote them. Excel still
recalculates on open (fullCalcOnLoad), so Excel's own values win wherever it is allowed to calculate.

Never fatal: if LibreOffice is missing or fails, or the patched file does not open, the exported file is left as
it was and the result says why.

  LIBREOFFICE_BIN    path or command of soffice (default: found on PATH / the usual Windows locations)
  CAM_LO_TIMEOUT     seconds LibreOffice may take (default 180)
  CAM_CACHE_VALUES   "0" turns this step off
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape, unescape

logger = logging.getLogger(__name__)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_VALUE_TYPES = {"n", "str", "b", "e"}  # number, text, boolean, error: the only result types a formula cell has

# LibreOffice keeps cached values on load by default; this makes it recalculate every formula.
_RECALC_ALWAYS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""

# An openpyxl formula cell with no result: <c r="B2" s="40"><f>...</f><v /></c>. The empty <v> is written as
# <v />, <v></v> or left out depending on whether lxml is installed. A cell that already has a value is left alone.
_FORMULA_CELL = re.compile(
    r'<c r="([A-Z]+[0-9]+)"((?: [A-Za-z:]+="[^"]*")*)>(<f(?:\s[^>]*)?>.*?</f>|<f(?:\s[^>]*)?/>)(?:<v\s*/>|<v>\s*</v>)?(</c>)',
    re.S)


def find_libreoffice():
    candidates = [
        os.environ.get("LIBREOFFICE_BIN", ""), "soffice", "libreoffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).is_file():
            return candidate
    return None


def _recalculate(src: Path, workdir: Path, lo: str, timeout: int) -> Path:
    profile = workdir / "lo_profile"
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text(_RECALC_ALWAYS, encoding="utf-8")
    out = workdir / "recalc"
    out.mkdir()
    subprocess.run(
        [lo, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
         "--convert-to", "xlsx", "--outdir", str(out), str(src)],
        check=True, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    result = out / src.name
    if not result.exists():
        raise RuntimeError(f"LibreOffice produced no file for {src.name}")
    return result


def _sheet_parts(z: zipfile.ZipFile) -> dict:
    """{sheet name: worksheet part path}. Names are XML-escaped in workbook.xml ("Sum &amp; Count")."""
    workbook = z.read("xl/workbook.xml").decode("utf-8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets = {re.search(r'Id="([^"]+)"', tag).group(1): re.search(r'Target="([^"]+)"', tag).group(1)
               for tag in re.findall(r"<Relationship\b[^>]*>", rels)}
    parts = {}
    for tag in re.findall(r"<sheet\b[^>]*>", workbook):
        name = unescape(re.search(r'name="([^"]*)"', tag).group(1), {"&quot;": '"', "&apos;": "'"})
        target = targets[re.search(r'r:id="([^"]+)"', tag).group(1)]
        parts[name] = target.lstrip("/") if target.startswith("/") else "xl/" + target  # openpyxl: absolute, LO: relative
    return parts


def _results(z: zipfile.ZipFile, part: str) -> dict:
    """{"B2": (type, text)} for every formula cell of one worksheet, as LibreOffice calculated it."""
    found = {}
    with z.open(part) as fh:
        for _, el in ElementTree.iterparse(fh, events=("end",)):
            if el.tag == _NS + "c":
                if el.find(_NS + "f") is not None:
                    v = el.find(_NS + "v")
                    found[el.get("r")] = (el.get("t", "n"), "" if v is None or v.text is None else v.text)
                el.clear()
    return found


def _patch(xml: str, results: dict):
    cached = 0

    def store(m):
        nonlocal cached
        got = results.get(m.group(1))
        if got is None or got[0] not in _VALUE_TYPES:
            return m.group(0)
        kind, text = got
        attrs = re.sub(r' t="[^"]*"', "", m.group(2)) + ("" if kind == "n" else f' t="{kind}"')
        cached += 1
        return f'<c r="{m.group(1)}"{attrs}>{m.group(3)}<v>{escape(text)}</v>{m.group(4)}'

    return _FORMULA_CELL.sub(store, xml), cached


def _inject(original: Path, recalculated: Path, out: Path) -> dict:
    formulas = cached = 0
    with zipfile.ZipFile(original) as zo, zipfile.ZipFile(recalculated) as zr, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zw:
        ours, theirs = _sheet_parts(zo), _sheet_parts(zr)
        sheet_of = {part: name for name, part in ours.items()}
        for info in zo.infolist():
            data = zo.read(info.filename)
            name = sheet_of.get(info.filename)
            if name is not None and name in theirs:
                xml = data.decode("utf-8")
                formulas += len(re.findall(r"<f[\s>/]", xml))
                xml, n = _patch(xml, _results(zr, theirs[name]))
                cached += n
                data = xml.encode("utf-8")
            zw.writestr(info, data)
    return {"formulas": formulas, "cached": cached}


def add_cached_values(path, timeout=None) -> dict:
    """Give every formula cell of the workbook at `path` its calculated value. Returns a status dict."""
    started = time.time()
    path = Path(path)
    if os.environ.get("CAM_CACHE_VALUES", "1") == "0":
        return {"status": "skipped", "reason": "disabled (CAM_CACHE_VALUES=0)"}
    lo = find_libreoffice()
    if lo is None:
        logger.warning("cached values skipped for %s: LibreOffice not found (set LIBREOFFICE_BIN)", path.name)
        return {"status": "skipped", "reason": "LibreOffice not found (set LIBREOFFICE_BIN)"}
    work = Path(tempfile.mkdtemp(prefix="cam_cached_values_"))
    # Hidden and not *.xlsx: the exports folder is globbed for CBOM_Report_*_*.xlsx, which must never
    # see a half-written file. os.replace then swaps it in atomically.
    staged = path.with_name("." + path.name + ".part")
    try:
        recalculated = _recalculate(path, work, lo, timeout or int(os.environ.get("CAM_LO_TIMEOUT", "180")))
        patched = work / "patched.xlsx"
        stats = _inject(path, recalculated, patched)
        import openpyxl  # the patched file must still open, formulas and values both
        openpyxl.load_workbook(patched).close()
        openpyxl.load_workbook(patched, data_only=True).close()
        shutil.copyfile(patched, staged)
        os.replace(staged, path)
        stats.update(status="ok", seconds=round(time.time() - started, 1))
        logger.info("cached values stored for %s: %s", path.name, stats)
        return stats
    except Exception as e:  # never fail an export over this
        logger.warning("cached values failed for %s: %s", path.name, e)
        return {"status": "failed", "reason": f"{type(e).__name__}: {e}"[:300]}
    finally:
        shutil.rmtree(work, ignore_errors=True)
        staged.unlink(missing_ok=True)
