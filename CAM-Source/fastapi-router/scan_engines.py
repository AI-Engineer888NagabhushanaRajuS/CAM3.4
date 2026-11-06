"""Two-engine security perimeter for files attached in the RFQ assistant (twin verdict, fail-closed).

  BuLL*Sav (ClamAV)    static signatures: runs `clamscan` (CLAMSCAN_PATH), exit 0 clean / 1 infected / 2 error,
                       the same semantics as mcp-tools/intake/mcp_server.py scan_local_file.
  Repel Evasion Shield behavioural heuristics in pure Python: disguised executables and polyglots, OOXML macros /
                       external links / embedded objects / DDE and formula injection / zip bombs / path traversal,
                       legacy OLE macros, active PDF content, and prompt injection or hidden Unicode in the text the
                       assistant will read (the same text attachment_text.chunks() hands it).

A file is released only when BOTH engines say clean. A missing, failing or timed-out engine is an error, and an error
is never a release. No shell, no model calls; every external step has a hard timeout.
"""
import concurrent.futures
import functools
import hashlib
import os
import re
import subprocess
import sys
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

import attachment_text

CLAMAV_LABEL = "BuLL*Sav (ClamAV)"
REPEL_LABEL = "Repel Shield"
REPEL_VERSION = "1.0"
CLAMAV_TIMEOUT = int(os.environ.get("CLAMAV_TIMEOUT_SECONDS", "240"))   # one run loads ~110 MB of signatures
REPEL_TIMEOUT = int(os.environ.get("REPEL_TIMEOUT_SECONDS", "60"))

# ---- names ---------------------------------------------------------------------------------------------------------

_HIDDEN = re.compile("[​-‏‪-‮⁠-⁯﻿]")
_TAGS = re.compile("[\U000e0000-\U000e007f]")


def safe_name(name):
    """The last path component only, with a conservative character set: `..\\..\\evil.xlsx` -> `evil.xlsx`."""
    base = re.split(r"[\\/]", unicodedata.normalize("NFKC", name or ""))[-1]
    base = _TAGS.sub("", _HIDDEN.sub("", base))
    base = re.sub(r"[^A-Za-z0-9._\-() ]+", "_", base).strip(" .")
    stem, ext = os.path.splitext(base)
    stem, ext = stem[:120].strip(" ."), ext[:12]
    return (stem or "attachment") + ext


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---- engine 1: ClamAV ----------------------------------------------------------------------------------------------

def _clamscan():
    return os.environ.get("CLAMSCAN_PATH", "clamscan")


def _run(args, timeout):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)


@functools.lru_cache(maxsize=4)
def _clamav_status(binary):
    """`clamscan --version` prints `ClamAV 1.4.3/28173/Tue Nov  3 06:27:52 2026` when a signature DB is loaded,
    and only `ClamAV 1.5.4` when there is none: no DB means it cannot detect anything, so it is unavailable."""
    try:
        out = _run([binary, "--version"], 30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "unavailable", "version": None, "detail": f"cannot run {binary}: {e}"}
    parts = out.split("/")
    if len(parts) < 3 or not parts[1].strip().isdigit():
        return {"status": "unavailable", "version": out or None, "detail": "clamscan has no signature database"}
    return {"status": "ok", "version": f"{parts[0].strip()}, signatures {parts[1].strip()} ({parts[2].strip()})",
            "detail": ""}


def clamav_status():
    return {"id": "clamav", "label": CLAMAV_LABEL, **_clamav_status(_clamscan())}


def clamav_scan(paths):
    """One clamscan run for the whole batch (the signature load is the expensive part). Per path:
    `<path>: OK` -> clean, `<path>: <sig> FOUND` -> threat, anything else (no line, ERROR) -> error."""
    status = clamav_status()
    if status["status"] != "ok":
        return {p: {"verdict": "error", "detail": f"{CLAMAV_LABEL} unavailable: {status['detail']}"} for p in paths}
    try:
        proc = _run([_clamscan(), "--no-summary", *paths], CLAMAV_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {p: {"verdict": "error", "detail": f"{CLAMAV_LABEL} timed out after {CLAMAV_TIMEOUT}s"} for p in paths}
    except (OSError, subprocess.SubprocessError) as e:
        return {p: {"verdict": "error", "detail": f"{CLAMAV_LABEL} unavailable: {e}"} for p in paths}
    out = {}
    for p in paths:
        line = next((l for l in proc.stdout.splitlines() if l.startswith(p + ": ")), "")
        said = line[len(p) + 2:].strip()
        if said == "OK":
            out[p] = {"verdict": "clean", "detail": "No signature matched"}
        elif said.endswith(" FOUND"):
            out[p] = {"verdict": "threat", "detail": said}
        else:
            err = said or proc.stderr.strip()[:300] or f"exit code {proc.returncode}"
            out[p] = {"verdict": "error", "detail": f"{CLAMAV_LABEL} error: {err}"}
    return out


# ---- engine 2: Repel Evasion Shield --------------------------------------------------------------------------------

_MAGIC = [  # offset-0 signatures -> kind
    (b"MZ", "pe"), (b"\x7fELF", "elf"), (b"\xfe\xed\xfa\xce", "macho"), (b"\xfe\xed\xfa\xcf", "macho"),
    (b"\xce\xfa\xed\xfe", "macho"), (b"\xcf\xfa\xed\xfe", "macho"), (b"\xca\xfe\xba\xbe", "macho"), (b"#!", "script"),
    (b"%PDF", "pdf"), (b"PK\x03\x04", "zip"), (b"PK\x05\x06", "zip"), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),
]
_EXECUTABLE = {"pe", "elf", "macho", "script"}
# .xls -> zip too: SAP and other tools commonly save real xlsx under .xls; it then gets every OOXML check.
_EXPECTED = {".xlsx": {"zip"}, ".xlsm": {"zip"}, ".docx": {"zip"}, ".docm": {"zip"}, ".pptx": {"zip"},
             ".zip": {"zip"}, ".pdf": {"pdf"}, ".xls": {"ole", "zip"}, ".doc": {"ole"}, ".ppt": {"ole"},
             ".csv": {"text"}, ".tsv": {"text"}, ".txt": {"text"}, ".md": {"text"}, ".json": {"text"}}
_RISKY_MEMBER = re.compile(r"\.(exe|dll|scr|com|bat|cmd|ps1|vbs|vbe|js|jse|wsf|hta|lnk|msi|jar|sh)$", re.I)
_NESTED = re.compile(r"\.(zip|rar|7z|gz|tgz|bz2|xz|cab|iso|tar)$", re.I)

MAX_ENTRIES = 10000
MAX_UNCOMPRESSED = 500 * 1024 * 1024
MAX_MEMBER_RATIO = 200          # real sheet XML compresses ~10-30x
MAX_XML_SCAN = 100 * 1024 * 1024

_DANGEROUS_CMD = r"\b(cmd|powershell|pwsh|mshta|wscript|cscript|rundll32|regsvr32|certutil|bitsadmin|msiexec)\b"
_DDE = re.compile(r"[A-Za-z0-9_.]+\s*\|\s*'[^']*'\s*!|\bDDE(AUTO)?\s*\(", re.I)
_FORMULA_CMD = re.compile(_DANGEROUS_CMD, re.I)
_FORMULA_FUNCS = re.compile(r"\b(WEBSERVICE|CALL|REGISTER(\.ID)?|EXEC)\s*\(", re.I)
_HYPERLINK = re.compile(r'HYPERLINK\s*\(\s*"([^"]*)"', re.I)
_CELL_INJECTION = re.compile(r"^\s*[=+\-@].*(" + _DANGEROUS_CMD + r"|\|\s*'|HYPERLINK\s*\()", re.I | re.S)

_INJECTION = [re.compile(p, re.I) for p in (
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules|messages)",
    r"disregard\s+(all\s+)?(the\s+)?(above|previous|prior)",
    r"\byou\s+are\s+now\b",
    r"\bsystem\s+prompt\b",
    r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions)",
    r"BEGIN\s+SYSTEM",
)]
_EXFIL = re.compile(r"\b(send|post|upload|forward|exfiltrate|email)\b[^.\n]{0,120}?\bto\s+https?://", re.I)

_PDF_PATTERNS = [
    ("pdf_javascript", re.compile(rb"/(JavaScript|JS)(?![A-Za-z0-9])")),
    ("pdf_open_action", re.compile(rb"/OpenAction\s*(<<|\d+\s+\d+\s+R)")),   # a [page /Fit] destination is benign
    ("pdf_launch", re.compile(rb"/Launch(?![A-Za-z0-9])")),
    ("pdf_embedded_file", re.compile(rb"/EmbeddedFiles?(?![A-Za-z0-9])")),
    ("pdf_additional_actions", re.compile(rb"/AA(?![A-Za-z0-9])")),
]

_WEIGHT = {"executable_content": 90, "embedded_executable": 90, "polyglot": 80, "macro_vba": 80, "dde_formula": 80,
           "formula_injection": 70, "path_traversal": 80, "zip_bomb": 80, "pdf_launch": 80, "pdf_javascript": 70,
           "extension_mismatch": 60, "external_link": 50, "external_reference": 60, "embedded_object": 60,
           "nested_archive": 40, "suspicious_hyperlink": 40, "pdf_open_action": 40, "pdf_embedded_file": 50,
           "pdf_additional_actions": 40, "macro_xlm": 80, "prompt_injection": 70, "exfiltration_phrase": 60, "hidden_unicode": 50,
           "unicode_tags": 70, "hidden_unicode_filename": 60}


def _kind(head):
    for sig, kind in _MAGIC:
        if head.startswith(sig) and not (kind == "pe" and b"\x00" not in head[2:64]):   # a CSV row "MZ5..." is text
            return kind
    if head[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" not in head[:8192]:
        return "text"
    return "binary"


class _Flags:
    def __init__(self):
        self.found = {}

    def add(self, flag, detail):
        self.found.setdefault(flag, detail)


def _check_bytes(path, ext, flags):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(65536)
        f.seek(max(0, size - 65558))
        tail = f.read()
    kind = _kind(head)
    if kind in _EXECUTABLE:
        flags.add("executable_content", f"content is an executable ({kind}) behind a {ext or 'no'} extension")
    elif ext in _EXPECTED and kind not in _EXPECTED[ext]:
        flags.add("extension_mismatch", f"{ext} file whose content is {kind}")
    if kind != "pdf" and b"%PDF-" in head[1:1024]:
        flags.add("polyglot", "a PDF header is hidden behind another file type's header")
    eocd = tail.rfind(b"PK\x05\x06")   # an archive that ENDS the file: legacy .xls embeds a theme zip mid-file
    if kind != "zip" and eocd >= 0 and eocd + 22 + int.from_bytes(tail[eocd + 20:eocd + 22], "little") == len(tail):
        flags.add("polyglot", f"a ZIP archive is appended to a {kind} file")
    with open(path, "rb") as f:   # a plain DOS stub anywhere means an uncompressed PE is carried inside
        if kind != "pe" and b"This program cannot be run in DOS mode" in f.read():
            flags.add("embedded_executable", "an uncompressed Windows executable is embedded in the file")
    return kind


def _scan_formula(text, flags, where):
    if _DDE.search(text):
        flags.add("dde_formula", f"DDE formula at {where}")
    if _FORMULA_CMD.search(text) or _FORMULA_FUNCS.search(text):
        flags.add("formula_injection", f"formula that runs commands or calls out at {where}")
    for target in _HYPERLINK.findall(text):
        if not target.lower().startswith("https://"):
            flags.add("suspicious_hyperlink", f"HYPERLINK to a non-https target at {where}")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _check_zip(path, flags):
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"unreadable archive: {e}")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            flags.add("zip_bomb", f"{len(infos)} archive entries")
        total = sum(i.file_size for i in infos)
        if total > MAX_UNCOMPRESSED:
            flags.add("zip_bomb", f"expands to {total // (1 << 20)} MB")
        for i in infos:
            name = i.filename
            lower = name.lower()
            parts = re.split(r"[\\/]", name)
            if ".." in parts or name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
                flags.add("path_traversal", f"archive entry escapes its folder: {name[:80]}")
            if i.file_size > 20 * 1024 * 1024 and i.file_size > MAX_MEMBER_RATIO * max(i.compress_size, 1):
                flags.add("zip_bomb", f"{name[:80]} expands {i.file_size // max(i.compress_size, 1)}x")
            if lower.endswith("vbaproject.bin") or lower.endswith("vbaprojectsignature.bin"):
                flags.add("macro_vba", f"VBA macro project {name}")
            if lower.startswith(("xl/macrosheets/", "xl/dialogsheets/")):
                flags.add("macro_xlm", f"Excel 4.0 (XLM) macro sheet {name}")
            if "/externallinks/" in "/" + lower:
                flags.add("external_link", f"workbook links to external workbooks ({name})")
            if "/embeddings/" in "/" + lower or "/activex/" in "/" + lower or "oleobject" in lower:
                flags.add("embedded_object", f"embedded OLE/ActiveX object {name}")
            if _RISKY_MEMBER.search(lower):
                flags.add("embedded_executable", f"archive carries {name[:80]}")
            if _NESTED.search(lower):
                flags.add("nested_archive", f"archive inside the archive: {name[:80]}")
        if flags.found.keys() & {"zip_bomb", "path_traversal"}:
            return  # do not inflate it any further
        for i in infos:
            lower = i.filename.lower()
            if not lower.endswith((".xml", ".rels")) or i.file_size > MAX_XML_SCAN:
                continue
            if lower.endswith(".rels"):
                _check_rels(zf, i, flags)
            elif lower.startswith(("xl/worksheets/", "xl/macrosheets/")) or lower == "xl/sharedstrings.xml":
                _check_sheet_xml(zf, i, flags)
            elif lower.startswith("word/"):
                raw = zf.read(i)
                if re.search(rb"instr(Text)?[^>]*>\s*DDE|w:instr=\"\s*DDE", raw):
                    flags.add("dde_formula", f"DDE field in {i.filename}")


def _check_rels(zf, info, flags):
    try:
        root = ET.fromstring(zf.read(info))
    except ET.ParseError:
        return
    for rel in root:
        if rel.get("TargetMode") != "External":
            continue
        rtype, target = rel.get("Type", "").rsplit("/", 1)[-1], rel.get("Target", "")
        if rtype == "hyperlink":
            if re.match(r"(?i)(file:|\\\\|javascript:|vbscript:|data:|ms-|search-ms:)", target):
                flags.add("suspicious_hyperlink", f"hyperlink to {target[:60]}")
        elif rtype != "attachedTemplate" or re.match(r"(?i)(https?:|\\\\|//|file://[^/])", target):
            flags.add("external_reference", f"{rtype} loaded from {target[:80]}")   # a local Word template is normal


def _check_sheet_xml(zf, info, flags):
    where = info.filename
    with zf.open(info) as f:
        try:
            for _, el in ET.iterparse(f):
                tag = _local(el.tag)
                if tag == "f" and el.text:
                    _scan_formula(el.text, flags, where)
                elif tag == "t" and el.text and _CELL_INJECTION.search(el.text):
                    flags.add("formula_injection", f"cell text that becomes a command formula in {where}")
                el.clear()
        except ET.ParseError:
            pass   # openpyxl will refuse it below and the scan errors


def _check_ole(path, flags):
    with open(path, "rb") as f:
        data = f.read()
    for marker in ("_VBA_PROJECT", "Macros\0"):   # directory names are NUL-terminated UTF-16LE, body text is not
        if marker.encode("utf-16-le") in data or (marker == "_VBA_PROJECT" and marker.encode() in data):
            flags.add("macro_vba", f"legacy Office file carries a {marker} storage")


def _check_pdf(path, flags):
    """Searches the object dictionaries (pymupdf also unpacks compressed object streams), never the binary page
    streams, where a 3-byte name like /AA would match by chance. Without pymupdf: a raw byte search."""
    try:
        import pymupdf
        with pymupdf.open(path, filetype="pdf") as doc:
            blob = "\n".join(doc.xref_object(x, compressed=False) for x in range(1, doc.xref_length()))
        blob = blob.encode("latin-1", "replace")
    except ImportError:
        with open(path, "rb") as f:
            blob = f.read()
    blob = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), blob)   # /J#61vaScript
    for flag, pattern in _PDF_PATTERNS:
        if pattern.search(blob):
            flags.add(flag, f"PDF has {flag.replace('pdf_', '').replace('_', ' ')}")


def scan_text(text, flags, where):
    if _TAGS.search(text):
        flags.add("unicode_tags", f"invisible Unicode tag characters in {where}")
    if _HIDDEN.search(text):
        flags.add("hidden_unicode", f"zero-width / bidi control characters in {where}")
    plain = _TAGS.sub("", _HIDDEN.sub("", text))
    for p in _INJECTION:
        m = p.search(plain)
        if m:
            flags.add("prompt_injection", f"instruction-like text {m.group(0)!r} in {where}")
    m = _EXFIL.search(plain)
    if m:
        flags.add("exfiltration_phrase", f"exfiltration-like text {m.group(0)[:60]!r} in {where}")


def _repel(path, original_name):
    flags = _Flags()
    if _HIDDEN.search(original_name or "") or _TAGS.search(original_name or ""):
        flags.add("hidden_unicode_filename", "the file name hides bidi / zero-width characters")
    ext = os.path.splitext(safe_name(original_name))[1].lower()
    kind = _check_bytes(path, ext, flags)
    if kind == "zip":
        _check_zip(path, flags)
    elif kind == "ole":
        _check_ole(path, flags)
    elif kind == "pdf":
        _check_pdf(path, flags)
    if not flags.found.keys() & {"zip_bomb", "path_traversal", "executable_content", "extension_mismatch"}:
        for chunk in attachment_text.chunks(path, safe_name(original_name)):   # exactly what the assistant reads
            scan_text(chunk["text"], flags, chunk["label"])
    found = flags.found
    if not found:
        return {"verdict": "clean", "score": 0, "flags": [], "detail": "No heuristic indicators"}
    return {"verdict": "threat", "score": min(100, sum(_WEIGHT.get(f, 50) for f in found)), "flags": list(found),
            "detail": "; ".join(found.values())}


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="repel")


def repel_scan(path, original_name):
    # ponytail: a thread cannot be killed, so a runaway scan keeps its worker after the timeout; inputs are capped
    # (25 MB upload, entry/size/ratio limits) so this is a backstop, move to a process pool if it ever fires.
    future = _pool.submit(_repel, path, original_name)
    try:
        return future.result(timeout=REPEL_TIMEOUT)
    except concurrent.futures.TimeoutError:
        return {"verdict": "error", "score": 0, "flags": [], "detail": f"{REPEL_LABEL} timed out after {REPEL_TIMEOUT}s"}
    except Exception as e:
        return {"verdict": "error", "score": 0, "flags": [], "detail": f"{REPEL_LABEL} could not read the file: {e}"}


def repel_status():
    return {"id": "repel", "label": REPEL_LABEL, "status": "ok", "version": REPEL_VERSION}


# ---- twin verdict --------------------------------------------------------------------------------------------------

def _decide(clam, repel):
    if clam["verdict"] == "threat":
        return "quarantined", f"{CLAMAV_LABEL}: {clam['detail']}"
    if repel["verdict"] == "threat":
        return "quarantined", f"{REPEL_LABEL}: {', '.join(repel['flags'])}"
    if clam["verdict"] != "clean":
        return "error", f"{clam['detail']}: files are held, not released"
    if repel["verdict"] != "clean":
        return "error", f"{repel['detail']}: files are held, not released"
    return "released", "Clean on both engines"


def scan_files(items):
    """items: [(path, original_name)] -> one result per item, in order (one clamscan run for the batch)."""
    started = time.monotonic()
    clam = clamav_scan([p for p, _ in items])
    clam_ms = (time.monotonic() - started) * 1000
    results = []
    for path, name in items:
        t = time.monotonic()
        repel = repel_scan(path, name)
        decision, reason = _decide(clam[path], repel)
        results.append({"name": safe_name(name), "size": os.path.getsize(path), "sha256": sha256_of(path),
                        "ext": os.path.splitext(safe_name(name))[1].lower(), "clamav": clam[path], "repel": repel,
                        "decision": decision, "reason": reason,
                        "ms": round(clam_ms / max(len(items), 1) + (time.monotonic() - t) * 1000)})
    return results


def scan_file(path, original_name):
    return scan_files([(path, original_name)])[0]
