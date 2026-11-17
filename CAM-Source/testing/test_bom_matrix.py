"""The BOM MATRIX tab: each part's quantity per assembly, read in the tab's own layout (rfq_analytics._bom_matrix)."""
import openpyxl

import rfq_analytics


def _book(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    m = wb.create_sheet("BOM MATRIX")
    m.append([None, None, None, None, "VL-1"])
    m.append(["Part Number", "HCV_BMS_MB", "HCV_BMS_SB", "Grand Total", "EAU VL-1", "Description", "Commodity"])
    m.append(["AC-1", 91, 25, 116, 174000, "Resistor", "PASSIVE"])
    m.append(["AC-2", "-", 16, 16, 24000, "Resistor 2", "PASSIVE"])
    m.append(["AC-3", None, None, 0, 0, "Packing", "Packing"])
    path = str(tmp_path / "book.xlsx")
    wb.save(path)
    return path


def test_each_part_has_its_quantity_per_assembly_and_its_total(tmp_path):
    wb = openpyxl.load_workbook(_book(tmp_path), data_only=True, read_only=True)
    got = rfq_analytics._bom_matrix(wb)
    assert got["assemblies"] == ["HCV_BMS_MB", "HCV_BMS_SB"]
    first = got["parts"][0]
    assert first == {"part": "AC-1", "quantities": {"HCV_BMS_MB": 91.0, "HCV_BMS_SB": 25.0}, "grand_total": 116.0, "commodity": "PASSIVE"}
    assert got["parts"][1]["quantities"] == {"HCV_BMS_MB": 0.0, "HCV_BMS_SB": 16.0}


def test_a_workbook_without_the_tab_gives_none(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    path = str(tmp_path / "x.xlsx")
    wb.save(path)
    assert rfq_analytics._bom_matrix(openpyxl.load_workbook(path, read_only=True)) is None
