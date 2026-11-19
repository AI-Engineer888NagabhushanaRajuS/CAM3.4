"""openpyxl's comment parts get Excel's names (what ExcelJS reads); the comment itself is kept."""
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment

sys.path.insert(0, str(Path(__file__).parent))
from reports.xlsx_rels import normalise_comment_parts


def _read(path):
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".rels", ".xml"))}
        return list(z.namelist()), parts


def test_comment_parts_get_excel_names_and_keep_the_comment():
    wb = openpyxl.Workbook()
    wb.active["A1"] = 5
    wb.active["A1"].comment = Comment("input problem: bad quantity", "CAM")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "report.xlsx"
        wb.save(path)
        names, _ = _read(path)
        assert "xl/comments/comment1.xml" in names and "xl/drawings/commentsDrawing1.vml" in names

        assert normalise_comment_parts(path) == 2
        names, parts = _read(path)
        assert "xl/comments1.xml" in names and "xl/drawings/vmlDrawing1.vml" in names
        assert "xl/comments/comment1.xml" not in names
        sheet_rels = [v for k, v in parts.items() if re.match(r"xl/worksheets/_rels/.+\.rels$", k) and "comments" in v]
        assert sheet_rels and '"../comments1.xml"' in sheet_rels[0] and '"../drawings/vmlDrawing1.vml"' in sheet_rels[0], sheet_rels
        assert "/xl/comments1.xml" in parts["[Content_Types].xml"]

        assert "bad quantity" in openpyxl.load_workbook(path).active["A1"].comment.text

        assert normalise_comment_parts(path) == 0  # nothing left to rename


if __name__ == "__main__":
    test_comment_parts_get_excel_names_and_keep_the_comment()
    print("ok")
