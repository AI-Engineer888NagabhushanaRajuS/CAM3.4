"""Name a saved workbook's cell comments the way Excel does, so the browser's workbook editor (ExcelJS) can open it.

openpyxl writes the comment part as xl/comments/comment1.xml and its VML drawing as xl/drawings/commentsDrawing1.vml. Excel
reads those, but ExcelJS only recognises xl/comments<N>.xml and xl/drawings/vmlDrawing<N>.vml, so it never registers the
comments and throws "Cannot read properties of undefined (reading 'comments')". This renames the two parts, and updates the
sheet relationships and the content types that point at them. Nothing else in the workbook changes.
"""
import os
import re
import shutil
import tempfile
import zipfile

_COMMENT_PART = re.compile(r"^xl/comments/comment(\d+)\.xml$")
_VML_PART = re.compile(r"^xl/drawings/commentsDrawing(\d+)\.vml$")
_SHEET_RELS = re.compile(r"^xl/worksheets/_rels/[^/]+\.rels$")


def _renames(names):
    """Old part name -> Excel's name for it, for every openpyxl comment and VML part in the archive."""
    out = {}
    for n in names:
        m = _COMMENT_PART.match(n)
        if m:
            out[n] = f"xl/comments{m.group(1)}.xml"
        m = _VML_PART.match(n)
        if m:
            out[n] = f"xl/drawings/vmlDrawing{m.group(1)}.vml"
    return out


def normalise_comment_parts(path):
    """Rename openpyxl's comment parts to Excel's names; returns how many parts were renamed (0 when there are none)."""
    with zipfile.ZipFile(path) as src:
        names = src.namelist()
        renames = _renames(names)
        if not renames:
            return 0
        if len(set(renames.values()) & set(names)):
            raise RuntimeError("comment part names already in use; not renaming")

        def rel_target(old):
            # Targets in xl/worksheets/_rels are relative to xl/worksheets/, like Excel writes them.
            return "../" + renames[old][len("xl/"):]

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(os.path.abspath(path)))
        os.close(tmp_fd)
        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if _SHEET_RELS.match(info.filename):
                        text = data.decode("utf-8")
                        for old in renames:
                            text = text.replace(f'Target="/{old}"', f'Target="{rel_target(old)}"')
                        data = text.encode("utf-8")
                    elif info.filename == "[Content_Types].xml":
                        text = data.decode("utf-8")
                        for old, new in renames.items():
                            text = text.replace(f'PartName="/{old}"', f'PartName="/{new}"')
                        data = text.encode("utf-8")
                    dst.writestr(renames.get(info.filename, info.filename), data)
            shutil.move(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    return len(renames)
