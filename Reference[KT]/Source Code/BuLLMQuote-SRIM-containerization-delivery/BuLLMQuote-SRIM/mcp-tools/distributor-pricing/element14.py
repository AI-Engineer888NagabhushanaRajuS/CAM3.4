"""
Element14 / Farnell / Newark Part Information Lookup Tool.

Fetches part details (pricing, MOQ, SPQ, EOL status, stock, etc.)
from the element14 Product Search API.
"""

import os
import sys
import time
import json
import requests
from dotenv import load_dotenv
from openpyxl import load_workbook
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

load_dotenv()

API_BASE_URL = "https://api.element14.com/catalog/products"

# releaseStatusCode meanings from element14 API docs
RELEASE_STATUS = {
    1: "New Product",
    2: "Active",
    4: "Not Recommended for New Designs",
    6: "End of Life (EOL)",
    7: "Obsolete",
}

# inventoryCode meanings
INVENTORY_STATUS = {
    2: "Stocked",
    5: "Non-Stocked",
    6: "Available (Last Time Buy)",
    9: "Marketplace",
}

# stock.status meanings
STOCK_STATUS = {
    1: "In Stock",
    0: "Temporarily Out of Stock",
    -1: "Awaiting Delivery",
    -2: "No Longer Manufactured",
    -3: "Not Normally Stocked",
    -4: "Status Unknown",
}


def get_api_key():
    key = os.getenv("ELEMENT14_API_KEY", "")
    if not key or key == "your_api_key_here":
        print("ERROR: Set your API key in the .env file (ELEMENT14_API_KEY).")
        sys.exit(1)
    return key


def get_store():
    return os.getenv("ELEMENT14_STORE", "www.newark.com")


def search_by_part_number(part_number, search_type="manuPartNum"):
    """
    Search element14 by part number.

    search_type options:
      - 'manuPartNum'  : search by manufacturer part number (default)
      - 'id'           : search by element14/Farnell/Newark SKU
    """
    api_key = get_api_key()
    store = get_store()

    params = {
        "term": f"{search_type}:{part_number}",
        "storeInfo.id": store,
        "resultsSettings.offset": 0,
        "resultsSettings.numberOfResults": 10,
        "resultsSettings.responseGroup": "large",
        "callInfo.apiKey": api_key,
        "callInfo.responseDataFormat": "JSON",
    }

    resp = requests.get(API_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def search_alternatives(keyword):

    api_key = get_api_key()
    store = get_store()

    params = {
        "term": f"any:{keyword}",
        "storeInfo.id": store,
        "resultsSettings.offset": 0,
        "resultsSettings.numberOfResults": 20,
        "resultsSettings.responseGroup": "large",
        "callInfo.apiKey": api_key,
        "callInfo.responseDataFormat": "JSON",
    }

    try:

        resp = requests.get(
            API_BASE_URL,
            params=params,
            timeout=30
        )

        resp.raise_for_status()

        data = resp.json()

        results = data.get(
            "keywordSearchReturn",
            {}
        )

        return results.get(
            "products",
            []
        )

    except Exception as e:

        print(f"Element14 search failed: {e}")

        return []

def get_price_for_qty(qty, price_breaks):

    selected_price = None

    for pb in price_breaks:

        try:
            if qty >= int(pb["from"]):
                selected_price = float(pb["unit_price"])
        except:
            pass

    return selected_price

def parse_part_info(product):
    """Extract key fields from an element14 product record."""
    info = {
        "SKU": product.get("sku", "N/A"),
        "Manufacturer Part Number": product.get("translatedManufacturerPartNumber", "N/A"),
        "Manufacturer": product.get("brandName", product.get("vendorName", "N/A")),
        "Description": product.get("displayName", "N/A"),
    }

    # --- Pricing ---
    prices = product.get("prices", [])
    price_breaks = []
    for p in prices:
        price_breaks.append({
            "from": p.get("from", ""),
            "to": p.get("to", ""),
            "unit_price": p.get("cost", "N/A"),
        })
    info["Price Breaks"] = price_breaks

    # Unit price = first tier price (qty 1)
    if price_breaks:
        info["Unit Price"] = price_breaks[0]["unit_price"]
    else:
        info["Unit Price"] = "N/A"

    # --- MOQ ---
    info["MOQ"] = product.get("translatedMinimumOrderQuality", "N/A")

    # --- SPQ (Sales Pack Quantity / Pack Size) ---
    info["SPQ"] = product.get("packSize", product.get("unitOfMeasure", "N/A"))

    # --- EOL / Release Status ---
    release_code = product.get("releaseStatusCode", None)
    info["Release Status Code"] = release_code
    info["Release Status"] = RELEASE_STATUS.get(release_code, "Unknown")

    # --- Inventory Code ---
    inv_code = product.get("inventoryCode", None)
    info["Inventory Code"] = inv_code
    info["Inventory Status"] = INVENTORY_STATUS.get(inv_code, "Unknown")

    # --- Stock ---
    stock = product.get("stock", {})
    info["Stock Level"] = stock.get("level", "N/A")
    status_code = stock.get("status", None)
    info["Stock Status"] = STOCK_STATUS.get(status_code, "Unknown")
    info["Lead Time (days)"] = stock.get("leastLeadTime", "N/A")

    # --- Product Status ---
    info["Product Status"] = product.get("productStatus", "N/A")

    # --- Datasheet ---
    datasheets = product.get("datasheets", [])
    if datasheets:
        info["Datasheet URL"] = datasheets[0].get("url", "N/A")
    else:
        info["Datasheet URL"] = "N/A"

    # --- RoHS ---
    info["RoHS"] = product.get("rohsStatusCode", "N/A")

    return info


def display_part_info(info, qty=1):
    """Print part information in a readable format."""
    print("\n" + "=" * 60)
    print(f"  SKU:                  {info['SKU']}")
    print(f"  Mfr Part Number:      {info['Manufacturer Part Number']}")
    print(f"  Manufacturer:         {info['Manufacturer']}")
    print(f"  Description:          {info['Description']}")
    print("-" * 60)
    print(f"  Unit Price:           {info['Unit Price']}")

    # Extended price
    try:
        ext_price = float(info["Unit Price"]) * qty
        print(f"  Ext. Price (x{qty}):    {ext_price:.4f}")
    except (ValueError, TypeError):
        print(f"  Ext. Price (x{qty}):    N/A")

    print(f"  MOQ:                  {info['MOQ']}")
    print(f"  SPQ:                  {info['SPQ']}")
    print("-" * 60)
    print(f"  Release Status:       {info['Release Status']} (code: {info['Release Status Code']})")
    print(f"  Inventory Status:     {info['Inventory Status']} (code: {info['Inventory Code']})")
    print(f"  Product Status:       {info['Product Status']}")
    print("-" * 60)
    print(f"  Stock Level:          {info['Stock Level']}")
    print(f"  Stock Status:         {info['Stock Status']}")
    print(f"  Lead Time (days):     {info['Lead Time (days)']}")
    print(f"  RoHS:                 {info['RoHS']}")
    print(f"  Datasheet:            {info['Datasheet URL']}")

    if info["Price Breaks"]:
        print("-" * 60)
        print("  Price Breaks:")
        print(f"    {'Qty From':<12} {'Qty To':<12} {'Unit Price':<12}")
        for pb in info["Price Breaks"]:
            print(f"    {str(pb['from']):<12} {str(pb['to']):<12} {str(pb['unit_price']):<12}")

    print("=" * 60)


def lookup_part(part_number, search_type="manuPartNum", qty=1):
    """Look up a part and display its info."""
    print(f"\nSearching for '{part_number}' (type: {search_type}, store: {get_store()})...")

    try:
        data = search_by_part_number(part_number, search_type)
    except requests.exceptions.HTTPError as e:
        print(f"API Error: {e}")
        return
    except requests.exceptions.ConnectionError:
        print("Connection error. Check your internet connection.")
        return

    # Navigate the response structure
    results = data.get("manufacturerPartNumberSearchReturn", data.get("keywordSearchReturn", {}))
    products = results.get("products", [])

    if not products:
        print(f"No results found for '{part_number}'.")
        return

    print(f"Found {len(products)} result(s):")

    for product in products:
        info = parse_part_info(product)
        display_part_info(info, qty)


def read_part_numbers_from_excel(filepath):
    """Read part numbers from an Excel file. Looks for a 'Part Number' column header."""
    wb = load_workbook(filepath, read_only=True)
    ws = wb.active

    # Find the 'Part Number' column
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=False))
    pn_col = None
    qty_col = None
    for cell in header_row:
        val = str(cell.value or "").strip().lower()
        if val in ("part number", "part_number", "partnumber", "mpn", "mfr part number"):
            pn_col = cell.column
        if val in ("qty", "quantity"):
            qty_col = cell.column

    if pn_col is None:
        print("ERROR: Could not find a 'Part Number' column header in the Excel file.")
        print("       Make sure your file has a header row with 'Part Number' as a column name.")
        wb.close()
        sys.exit(1)

    parts = []
    for row in ws.iter_rows(min_row=2, values_only=False):
        pn_value = row[pn_col - 1].value
        if pn_value is not None and str(pn_value).strip():
            qty = 1
            if qty_col is not None:
                q = row[qty_col - 1].value
                if q is not None:
                    try:
                        qty = int(q)
                    except (ValueError, TypeError):
                        qty = 1
            parts.append((str(pn_value).strip(), qty))

    wb.close()
    return parts


def bulk_lookup_to_excel(input_filepath):
    """
    Read an Excel file with 'Part Number' and 'Present or not' columns.
    Fill 'Present or not' with Yes/No and append detail columns for found parts.
    Saves results to a new file.
    """
    # Load the input workbook (editable copy)
    wb = load_workbook(input_filepath)
    ws = wb.active

    # --- Find key columns in the header row ---
    header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=False))[0]
    pn_col = None
    present_col = None
    qty_col = None
    max_col = 0

    for cell in header_row:
        val = str(cell.value or "").strip().lower()
        if val in ("part number", "part_number", "partnumber", "mpn", "mfr part number"):
            pn_col = cell.column
        if val in ("present or not", "present", "available"):
            present_col = cell.column
        if val in ("qty", "quantity"):
            qty_col = cell.column
        if cell.column > max_col:
            max_col = cell.column

    if pn_col is None:
        print("ERROR: Could not find a 'Part Number' column header in the Excel file.")
        sys.exit(1)

    # If 'Present or not' column doesn't exist, create it after the last column
    if present_col is None:
        present_col = max_col + 1
        ws.cell(row=1, column=present_col, value="Present or not")
        max_col = present_col

    # --- Define detail columns to append after existing columns ---
    detail_columns = [
        "SKU",
        "Manufacturer Part Number",
        "Manufacturer",
        "Description",
        "Unit Price",
        "Ext. Price",
        "MOQ",
        "SPQ",
        "Release Status",
        "Inventory Status",
        "Product Status",
        "Stock Level",
        "Stock Status",
        "Lead Time (days)",
        "RoHS",
        "Datasheet URL",
    ]

    detail_start_col = max_col + 1

    # Style for new headers
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    green_font = Font(bold=True, color="006100")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    red_font = Font(bold=True, color="9C0006")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    # Style the 'Present or not' header
    present_header = ws.cell(row=1, column=present_col)
    present_header.font = header_font
    present_header.fill = header_fill
    present_header.alignment = Alignment(horizontal="center")
    present_header.border = thin_border

    # Write detail column headers
    for i, col_name in enumerate(detail_columns):
        cell = ws.cell(row=1, column=detail_start_col + i, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = thin_border

    # --- Process each row ---
    total_rows = ws.max_row - 1  # exclude header
    found_count = 0
    not_found_count = 0

    for row_num in range(2, ws.max_row + 1):
        pn_value = ws.cell(row=row_num, column=pn_col).value
        if pn_value is None or not str(pn_value).strip():
            continue

        part_number = str(pn_value).strip()

        # Get quantity if column exists
        qty = 1
        if qty_col is not None:
            q = ws.cell(row=row_num, column=qty_col).value
            if q is not None:
                try:
                    qty = int(q)
                except (ValueError, TypeError):
                    qty = 1

        print(f"[{row_num - 1}/{total_rows}] Looking up: {part_number}...", end=" ")

        try:
            data = search_by_part_number(part_number, "manuPartNum")
        except requests.exceptions.HTTPError as e:
            print(f"API Error: {e}")
            cell = ws.cell(row=row_num, column=present_col, value="Error")
            cell.border = thin_border
            continue
        except requests.exceptions.ConnectionError:
            print("Connection error.")
            cell = ws.cell(row=row_num, column=present_col, value="Error")
            cell.border = thin_border
            continue

        results = data.get("manufacturerPartNumberSearchReturn", data.get("keywordSearchReturn", {}))
        products = results.get("products", [])

        if not products:
            # --- NOT FOUND ---
            cell = ws.cell(row=row_num, column=present_col, value="No")
            cell.font = red_font
            cell.fill = red_fill
            cell.alignment = Alignment(horizontal="center")
            cell.border = thin_border
            not_found_count += 1
            print("NOT FOUND")
        else:
            # --- FOUND ---
            cell = ws.cell(row=row_num, column=present_col, value="Yes")
            cell.font = green_font
            cell.fill = green_fill
            cell.alignment = Alignment(horizontal="center")
            cell.border = thin_border
            found_count += 1

            # Parse and write detail columns
            product = products[0]
            info = parse_part_info(product)
             
            selected_price = get_price_for_qty(
                qty,
                info["Price Breaks"]
            )

            if selected_price is not None:
                info["Unit Price"] = selected_price

            try:
                ext_price = float(info["Unit Price"]) * qty
            except (ValueError, TypeError):
                ext_price = "N/A"

            detail_values = [
                info["SKU"],
                info["Manufacturer Part Number"],
                info["Manufacturer"],
                info["Description"],
                info["Unit Price"],
                ext_price,
                info["MOQ"],
                info["SPQ"],
                info["Release Status"],
                info["Inventory Status"],
                info["Product Status"],
                info["Stock Level"],
                info["Stock Status"],
                info["Lead Time (days)"],
                info["RoHS"],
                info["Datasheet URL"],
            ]

            for i, value in enumerate(detail_values):
                dcell = ws.cell(row=row_num, column=detail_start_col + i, value=value)
                dcell.border = thin_border

            # Highlight EOL/Obsolete rows
            release = str(info.get("Release Status", ""))
            if "EOL" in release or "Obsolete" in release:
                eol_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
                for c in range(detail_start_col, detail_start_col + len(detail_columns)):
                    ws.cell(row=row_num, column=c).fill = eol_fill

            # Highlight "Not Recommended" rows
            if "Not Recommended" in release:
                for c in range(detail_start_col, detail_start_col + len(detail_columns)):
                    ws.cell(row=row_num, column=c).fill = yellow_fill

            print(f"YES - {info['Manufacturer Part Number']} ({info['Release Status']})")


    # --- Auto-fit new columns ---
    total_cols = detail_start_col + len(detail_columns) - 1
    for col_idx in range(present_col, total_cols + 1):
        max_len = len(str(ws.cell(row=1, column=col_idx).value or ""))
        for row in range(2, ws.max_row + 1):
            val = ws.cell(row=row, column=col_idx).value
            if val:
                max_len = max(max_len, min(len(str(val)), 50))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max_len + 3

    # --- Save output ---
    base = os.path.splitext(os.path.basename(input_filepath))[0]
    output_dir = os.path.dirname(os.path.abspath(input_filepath))
    output_path = os.path.join(output_dir, f"{base}_results.xlsx")

    wb.save(output_path)
    print(f"\n{'=' * 50}")
    print(f"Results saved to: {output_path}")
    print(f"Total: {found_count + not_found_count} | Found: {found_count} | Not Found: {not_found_count}")
    print(f"{'=' * 50}")
    return output_path


def main():
    if len(sys.argv) < 2:
        print("Element14 Part Lookup Tool")
        print("-" * 40)
        print("Usage:")
        print(f"  python {sys.argv[0]} <part_number> [options]")
        print(f"  python {sys.argv[0]} --file <excel_file>")
        print()
        print("Options:")
        print("  --file FILE    Bulk lookup from Excel file (requires 'Part Number' column)")
        print("  --sku          Search by element14/Newark SKU instead of MPN")
        print("  --qty N        Quantity for extended price calculation (default: 1)")
        print()
        print("Examples:")
        print(f"  python {sys.argv[0]} LM339ADT")
        print(f"  python {sys.argv[0]} 1278613 --sku")
        print(f"  python {sys.argv[0]} LM339ADT --qty 100")
        print(f"  python {sys.argv[0]} --file parts_list.xlsx")
        print()
        print("Excel file format:")
        print("  Must have a header row with 'Part Number' column.")
        print("  Optional 'Qty' column for extended price calculation.")
        print("  Output is saved as <filename>_results.xlsx")
        print()
        print(f"Store: {get_store()} (change in .env: ELEMENT14_STORE)")
        return

    # Check for --file mode
    if "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 >= len(sys.argv):
            print("ERROR: --file requires a file path.")
            return
        filepath = sys.argv[idx + 1]
        if not os.path.isfile(filepath):
            print(f"ERROR: File not found: {filepath}")
            return
        bulk_lookup_to_excel(filepath)
        return

    part_number = sys.argv[1]
    search_type = "manuPartNum"
    qty = 1

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--sku":
            search_type = "id"
        elif sys.argv[i] == "--qty" and i + 1 < len(sys.argv):
            i += 1
            try:
                qty = int(sys.argv[i])
            except ValueError:
                print(f"Invalid quantity: {sys.argv[i]}")
                return
        i += 1

    lookup_part(part_number, search_type, qty)


if __name__ == "__main__":
    main()
