"""Native-Excel check of a delivered report: every formula cell's stored value (what the app delivered) against Excel's own full recalculation.

Step 1 (PowerShell, Excel installed): open the delivered workbook, run CalculateFullRebuild(), SaveAs xlsx (FileFormat 51) to a second file.
Step 2: python excel_oracle.py <delivered.xlsx> <excel_recalculated.xlsx>
Prints, per tab, how many formula cells agree with Excel and lists the first that do not. Used on 11 Nov (SPEC-025 section 7): it found the
Price Control formulas giving #VALUE! in Excel while LibreOffice and the Formula Engine accepted them.
"""
import math
import sys

import openpyxl

delivered, excel = sys.argv[1], sys.argv[2]
stored = openpyxl.load_workbook(delivered, data_only=True)
forms = openpyxl.load_workbook(delivered, data_only=False)
xl = openpyxl.load_workbook(excel, data_only=True)


def same(a, b):
    if a in (None, "") and b in (None, ""):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


total = agree = 0
bad = []
for ws in forms.worksheets:
    n = a = 0
    for row in ws.iter_rows():
        for cell in row:
            if cell.data_type != "f":
                continue
            n += 1
            ok = same(stored[ws.title][cell.coordinate].value, xl[ws.title][cell.coordinate].value)
            a += ok
            if not ok and len(bad) < 10:
                bad.append((ws.title, cell.coordinate, stored[ws.title][cell.coordinate].value, xl[ws.title][cell.coordinate].value))
    total += n
    agree += a
    if a != n:
        print(f"{ws.title:24} {a} of {n} agree with Excel")
print(f"TOTAL {agree} of {total} formula cells agree with native Excel")
for b in bad:
    print("differs:", b)
