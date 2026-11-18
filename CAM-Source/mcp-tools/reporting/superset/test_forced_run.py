"""The forced-run comments: an error cell or a blank gap in a flagged part's row gets a hover comment; nothing else does."""
import json
import os
import tempfile
import unittest

import openpyxl

import config
from reports import forced_run


class ForcedRunComments(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = config.PROJECT_DATABASE_DIR
        config.PROJECT_DATABASE_DIR = self._tmp.name
        os.makedirs(os.path.join(self._tmp.name, "forced_runs"))

    def tearDown(self):
        config.PROJECT_DATABASE_DIR = self._saved
        self._tmp.cleanup()

    def _workbook(self, rows):
        path = os.path.join(self._tmp.name, "out.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "CBOM"
        for row in rows:
            ws.append(row)
        wb.save(path)
        return path

    def _record(self, rfq_id, issues):
        with open(os.path.join(self._tmp.name, "forced_runs", f"{rfq_id}.json"), "w", encoding="utf-8") as f:
            json.dump({"rfq_id": rfq_id, "version": 1, "unresolved_cells": len(issues), "issues": issues}, f)

    def test_a_run_that_was_not_forced_is_left_alone(self):
        path = self._workbook([["Part", "Qty"], ["P1", "#VALUE!"]])
        self.assertEqual(forced_run.annotate_error_cells(path, "NOT-FORCED")["status"], "skipped")
        self.assertIsNone(openpyxl.load_workbook(path)["CBOM"]["B2"].comment)

    def test_error_cell_and_blank_gap_in_a_flagged_row_get_comments(self):
        rows = [
            ["Part", "Qty", "Price"],
            ["P1", 1, 5],
            ["P1", 2, None],      # blank gap in the flagged part's row: Price is normally filled
            ["P2", 3, "#VALUE!"],  # error cell, no flagged part in its row: general note
            ["P3", 4, 5],
            ["P3", 5, 6],
        ]
        self._record("RUN-1", [{"severity": "error", "sheet": "SCRUB BOM", "row": 2, "column": "Qty", "message": "Qty is text.", "part": "P1"}])
        result = forced_run.annotate_error_cells(self._workbook(rows), "RUN-1")
        self.assertEqual(result["error_cells_commented"], 1)
        self.assertEqual(result["blank_cells_commented"], 1)

        ws = openpyxl.load_workbook(os.path.join(self._tmp.name, "out.xlsx"))["CBOM"]
        self.assertIn("Input problem for part P1", ws["C3"].comment.text)   # the blank gap
        self.assertIn("in error because its input is incomplete", ws["C4"].comment.text)  # the error cell
        self.assertIsNone(ws["C2"].comment)  # a filled cell in a flagged row is not commented
        self.assertIsNone(ws["C5"].comment)  # an unflagged row is not commented

    def test_a_merged_cell_is_skipped_without_error(self):
        path = self._workbook([["Part", "Qty", "Price"], ["P1", 1, 5], ["P1", 2, None], ["P2", 3, 6]])
        ws = openpyxl.load_workbook(path)["CBOM"]
        ws.merge_cells("C2:C3")
        ws.parent.save(path)
        self._record("RUN-2", [{"severity": "error", "sheet": "SCRUB BOM", "row": 2, "column": "Qty", "message": "x", "part": "P1"}])
        result = forced_run.annotate_error_cells(path, "RUN-2")
        self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main()
