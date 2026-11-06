import os
import duckdb
from concurrent.futures import ThreadPoolExecutor, as_completed


from config import DB_PATH
from currency import convert_to_inr
from digikey_client import DigikeyClient
from element14 import (
            search_by_part_number,
            parse_part_info,
            get_price_for_qty,
        )
from models import select_price_for_qty
from mouser_client import MouserClient


# ==========================================================
# NUMERIC PLACEHOLDER SANITIZER
# ==========================================================

INVALID_NUMERIC_PLACEHOLDERS = {"N/A", "NA", "", "-"}


def clean_number(value):

    if value is None:
        return None

    if isinstance(value, str) and value.strip().upper() in INVALID_NUMERIC_PLACEHOLDERS:
        return None

    return value


def effective_moq(raw_moq, required_qty):
    """A distributor's own MOQ can be smaller than what this BOM actually
    needs (e.g. MOQ=100 on a part where required_qty=8000) -- ordering
    exactly the fetched MOQ in that case would under-order. Confirmed
    business rule: the effective MOQ is whichever is LARGER, the fetched MOQ
    or required_qty -- never smaller than what's actually needed, but never
    invented when the distributor didn't return an MOQ at all (raw_moq is
    None stays None, not silently replaced by required_qty).
    """
    if raw_moq is None:
        return None
    try:
        raw_moq = float(raw_moq)
    except (TypeError, ValueError):
        return raw_moq
    try:
        required_qty = float(required_qty)
    except (TypeError, ValueError):
        return raw_moq
    return max(raw_moq, required_qty)


# ==========================================================
# ENSURE ALL DISTRIBUTOR COLUMNS EXIST
# ==========================================================

def ensure_columns(conn):

    columns = [

        # ---------------- DigiKey ----------------

        ("digikey_part_number", "VARCHAR"),
        ("digikey_stock", "DOUBLE"),
        ("digikey_lifecycle_status", "VARCHAR"),
        ("digikey_datasheet_url", "VARCHAR"),
        ("digikey_moq", "DOUBLE"),
        ("digikey_spq", "DOUBLE"),
        ("digikey_lead_time", "VARCHAR"),
        ("digikey_unit_price", "DOUBLE"),
        ("digikey_currency", "VARCHAR"),

        # ---------------- Element14 ----------------

        ("element14_part_number", "VARCHAR"),
        ("element14_stock", "DOUBLE"),
        ("element14_inventory_status", "VARCHAR"),
        ("element14_datasheet_url", "VARCHAR"),
        ("element14_rohs", "VARCHAR"),
        ("element14_moq", "DOUBLE"),
        ("element14_spq", "DOUBLE"),
        ("element14_lead_time", "VARCHAR"),
        ("element14_unit_price", "DOUBLE"),
        ("element14_currency", "VARCHAR"),

        # ---------------- Mouser ----------------

        ("mouser_part_number", "VARCHAR"),
        ("mouser_stock", "DOUBLE"),
        ("mouser_lifecycle_status", "VARCHAR"),
        ("mouser_datasheet_url", "VARCHAR"),
        ("mouser_product_url", "VARCHAR"),
        ("mouser_moq", "DOUBLE"),
        ("mouser_spq", "DOUBLE"),
        ("mouser_lead_time", "VARCHAR"),
        ("mouser_unit_price", "DOUBLE"),
        ("mouser_currency", "VARCHAR"),

        # ---------------- Selected (authoritative single-source price) ----------------
        # The one price every downstream consumer (Quote summary, exports) must read
        # instead of comparing digikey_unit_price/element14_unit_price/mouser_unit_price
        # independently in more than one place -- computed once here, right after all
        # three distributor lookups for a row are in, from the already-INR-converted
        # prices enrich_digikey/enrich_element14/enrich_mouser produce.

        ("selected_unit_price", "DOUBLE"),
        ("selected_currency", "VARCHAR"),
        ("selected_supplier", "VARCHAR"),
        # MOQ from the SAME winning distributor as selected_unit_price/
        # selected_supplier (see select_best_distributor_price()) -- never a
        # separately-chosen MOQ. Feeds MOQ Charges for Batch (quote_summary.py).
        ("selected_moq", "DOUBLE")
    ]

    existing = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name='processed_bom_items'
        """
    ).fetchall()

    existing = {row[0].lower() for row in existing}

    for column_name, column_type in columns:

        if column_name.lower() not in existing:

            print(f"Adding column : {column_name}")

            conn.execute(
                f"""
                ALTER TABLE processed_bom_items
                ADD COLUMN {column_name}
                {column_type}
                """
            )


# ==========================================================
# DIGIKEY ENRICHMENT
# ==========================================================

def enrich_digikey(client, mpn, required_qty):

    try:

        result = client.lookup(mpn)

        if result.error:
            return {}

        # Price-break tier for the ACTUAL quantity needed, not price_breaks[0]
        # (the qty=1 base tier client.lookup() defaults unit_price to) --
        # then converted to INR so every stored price is in one currency
        # regardless of which currency the distributor quoted it in.
        tier_price, tier_currency = select_price_for_qty(result.price_breaks, required_qty)
        if tier_price is None:
            tier_price, tier_currency = result.unit_price, result.currency
        inr_price = convert_to_inr(tier_price, tier_currency)

        return {

            "digikey_part_number":
                result.distributor_pn,

            "digikey_stock":
                result.stock_quantity,

            "digikey_lifecycle_status":
                result.lifecycle_status,

            "digikey_datasheet_url":
                result.datasheet_url,

            "digikey_moq":
                effective_moq(result.moq, required_qty),

            "digikey_spq":
                result.spq,

            "digikey_lead_time":
                result.lead_time,

            "digikey_unit_price":
                inr_price,

            "digikey_currency":
                "INR" if inr_price is not None else tier_currency
        }

    except Exception as e:

        print(f"DigiKey Error ({mpn}) : {e}")

        return {}
# ==========================================================
# ELEMENT14 ENRICHMENT
# ==========================================================

def enrich_element14(mpn, required_qty):

    # element14.py's get_api_key() calls sys.exit(1) when the API key is
    # missing (SystemExit is not caught by "except Exception" below) —
    # check for it first so a missing credential degrades gracefully like
    # every other lookup failure, instead of killing the whole process.
    if not os.getenv("ELEMENT14_API_KEY"):
        return {}

    try:

        data = search_by_part_number(
            mpn,
            "manuPartNum"
        )

        results = data.get(
            "manufacturerPartNumberSearchReturn",
            data.get(
                "keywordSearchReturn",
                {}
            )
        )

        products = results.get(
            "products",
            []
        )

        if not products:
            return {}

        info = parse_part_info(products[0])

        # Price-break tier for required_qty, not info["Unit Price"] (which
        # parse_part_info always sets to the qty=1 base tier) -- same
        # under-priced-at-volume bug as DigiKey/Mouser. element14.py's own
        # get_price_for_qty() already implements the right "highest
        # breakpoint <= qty" selection; this module just never called it.
        tier_price = get_price_for_qty(required_qty, info.get("Price Breaks", []))
        if tier_price is None:
            tier_price = clean_number(info.get("Unit Price", None))
        inr_price = convert_to_inr(tier_price, "USD")

        return {

            "element14_part_number":
                info.get(
                    "Manufacturer Part Number",
                    ""
                ),

            "element14_stock":
                info.get(
                    "Stock Level",
                    None
                ),

            "element14_inventory_status":
                info.get(
                    "Inventory Status",
                    ""
                ),

            "element14_datasheet_url":
                info.get(
                    "Datasheet URL",
                    ""
                ),

            "element14_rohs":
                info.get(
                    "RoHS",
                    ""
                ),

            "element14_moq":
                effective_moq(clean_number(info.get(
                    "MOQ",
                    None
                )), required_qty),

            "element14_spq":
                clean_number(info.get(
                    "SPQ",
                    None
                )),

            "element14_lead_time":
                str(
                    info.get(
                        "Lead Time (days)",
                        ""
                    )
                ),

            "element14_unit_price":
                inr_price,

            "element14_currency":
                "INR" if inr_price is not None else "USD"
        }

    except Exception as e:

        print(f"Element14 Error ({mpn}) : {e}")

        return {}

# ==========================================================
# MOUSER ENRICHMENT
# ==========================================================

def enrich_mouser(client, mpn, required_qty):

    try:

        result = client.lookup(mpn)

        if result.error:
            return {}

        tier_price, tier_currency = select_price_for_qty(result.price_breaks, required_qty)
        if tier_price is None:
            tier_price, tier_currency = result.unit_price, result.currency
        inr_price = convert_to_inr(tier_price, tier_currency)

        return {

            "mouser_part_number":
                result.distributor_pn,

            "mouser_stock":
                result.stock_quantity,

            "mouser_lifecycle_status":
                result.lifecycle_status,

            "mouser_datasheet_url":
                result.datasheet_url,

            "mouser_product_url":
                result.product_url,

            "mouser_moq":
                effective_moq(result.moq, required_qty),

            "mouser_spq":
                result.spq,

            "mouser_lead_time":
                result.lead_time,

            "mouser_unit_price":
                inr_price,

            "mouser_currency":
                "INR" if inr_price is not None else tier_currency
        }

    except Exception as e:

        print(f"Mouser Error ({mpn}) : {e}")

        return {}

# ==========================================================
# SINGLE-SOURCE PRICE SELECTION
#
# Lowest valid (non-null, > 0) price across the three distributors, all
# already INR-converted by enrich_digikey/enrich_element14/enrich_mouser --
# this is the ONE value every downstream consumer (Quote summary, exports)
# must read. Never re-derive/re-compare digikey_unit_price/element14_unit_price/
# mouser_unit_price independently elsewhere -- extend this function instead.
# ==========================================================

def select_best_distributor_price(dg, e14, mouser):
    """Picks the winning distributor by price, then reads its price, currency,
    AND moq together as one unit -- MOQ is never separately/independently
    selected from a different distributor than the one whose price won. This
    is the one place price-source selection happens; MOQ Charges for Batch
    (quote_summary.py) and everything else must read selected_moq/
    selected_unit_price from here, never re-derive their own pick.

    selected_moq is read as-is from digikey_moq/element14_moq/mouser_moq,
    which are already max(raw fetched MOQ, required_qty) per distributor
    (see effective_moq() above) -- so MOQ Charges for Batch's own
    max(selected_moq - required_qty, 0) is mathematically identical to
    computing it against the raw MOQ with the same guard: when the raw MOQ
    already covered required_qty, selected_moq is untouched and the
    subtraction is already >= 0; when the raw MOQ was smaller, selected_moq
    became required_qty, so the subtraction is exactly 0 -- the correct
    "no MOQ premium" answer either way.
    """
    candidates = [
        ("DigiKey", dg.get("digikey_unit_price"), dg.get("digikey_currency"), dg.get("digikey_moq")),
        ("Element14", e14.get("element14_unit_price"), e14.get("element14_currency"), e14.get("element14_moq")),
        ("Mouser", mouser.get("mouser_unit_price"), mouser.get("mouser_currency"), mouser.get("mouser_moq")),
    ]

    valid = [
        (supplier, price, currency, moq)
        for supplier, price, currency, moq in candidates
        if price is not None and price > 0
    ]

    if not valid:
        return None, None, None, None

    supplier, price, currency, moq = min(valid, key=lambda c: c[1])
    return price, currency, supplier, moq


# ==========================================================
# ENRICH ALL DISTRIBUTORS
# ==========================================================

def enrich_distributors(rfq_id):

    rfq_id = str(rfq_id).strip()

    conn = duckdb.connect(DB_PATH)

    ensure_columns(conn)

    digikey_client = DigikeyClient(
        os.getenv("DIGIKEY_CLIENT_ID"),
        os.getenv("DIGIKEY_CLIENT_SECRET")
    )

    mouser_client = MouserClient(
        os.getenv("MOUSER_API_KEY")
    )

    rows = conn.execute(
        """
        SELECT
            bom_item_id,
            mpn,
            required_qty
        FROM processed_bom_items
        WHERE CAST(rfq_id AS VARCHAR)=?
        AND mpn IS NOT NULL
        ORDER BY mpn
        """,
        [rfq_id]
    ).fetchall()

    total = len(rows)

    digikey_found = 0
    element14_found = 0
    mouser_found = 0

    updated = 0

    print("\n========================================")
    print(" DISTRIBUTOR ENRICHMENT")
    print("========================================")
    print(f"Total Parts : {total}\n")

    # Each row previously did 3 sequential HTTP round-trips (DigiKey,
    # Element14, Mouser) one row at a time -- 57 parts meant ~171 sequential
    # network calls. These are independent, I/O-bound lookups with no shared
    # state (each client call is stateless per-mpn), so they parallelize
    # safely across rows via a thread pool -- Python threads release the GIL
    # during I/O wait, so this is a real speedup, not just apparent
    # concurrency. DuckDB itself stays single-threaded: only the main thread
    # ever touches `conn`, per its single-writer design (see CLAUDE.md).
    MAX_WORKERS = 8

    def _enrich_one(bom_item_id, mpn, required_qty):
        # No stated required_qty (e.g. a row from before volume expansion) --
        # fall back to 1, the same qty the old price_breaks[0]-always logic
        # implicitly assumed for every row.
        qty = required_qty if required_qty is not None else 1
        dg = enrich_digikey(digikey_client, mpn, qty)
        e14 = enrich_element14(mpn, qty)
        mouser = enrich_mouser(mouser_client, mpn, qty)
        return bom_item_id, mpn, dg, e14, mouser

    fetched = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(_enrich_one, bom_item_id, mpn, required_qty)
            for bom_item_id, mpn, required_qty in rows
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            bom_item_id, mpn, dg, e14, mouser = future.result()
            print(f"[{index}/{total}] {mpn}")
            fetched.append((bom_item_id, dg, e14, mouser))

    for bom_item_id, dg, e14, mouser in fetched:

        if dg:
            digikey_found += 1

        if e14:
            element14_found += 1

        if mouser:
            mouser_found += 1

        selected_price, selected_currency, selected_supplier, selected_moq = select_best_distributor_price(
            dg, e14, mouser
        )

        conn.execute(
            """
            UPDATE processed_bom_items
            SET

            digikey_part_number=?,
            digikey_stock=?,
            digikey_lifecycle_status=?,
            digikey_datasheet_url=?,
            digikey_moq=?,
            digikey_spq=?,
            digikey_lead_time=?,
            digikey_unit_price=?,
            digikey_currency=?,

            element14_part_number=?,
            element14_stock=?,
            element14_inventory_status=?,
            element14_datasheet_url=?,
            element14_rohs=?,
            element14_moq=?,
            element14_spq=?,
            element14_lead_time=?,
            element14_unit_price=?,
            element14_currency=?,

            mouser_part_number=?,
            mouser_stock=?,
            mouser_lifecycle_status=?,
            mouser_datasheet_url=?,
            mouser_product_url=?,
            mouser_moq=?,
            mouser_spq=?,
            mouser_lead_time=?,
            mouser_unit_price=?,
            mouser_currency=?,

            selected_unit_price=?,
            selected_currency=?,
            selected_supplier=?,
            selected_moq=?

            WHERE bom_item_id=?
            """,
            [

                dg.get("digikey_part_number"),
                dg.get("digikey_stock"),
                dg.get("digikey_lifecycle_status"),
                dg.get("digikey_datasheet_url"),
                dg.get("digikey_moq"),
                dg.get("digikey_spq"),
                dg.get("digikey_lead_time"),
                dg.get("digikey_unit_price"),
                dg.get("digikey_currency"),

                e14.get("element14_part_number"),
                e14.get("element14_stock"),
                e14.get("element14_inventory_status"),
                e14.get("element14_datasheet_url"),
                e14.get("element14_rohs"),
                e14.get("element14_moq"),
                e14.get("element14_spq"),
                e14.get("element14_lead_time"),
                e14.get("element14_unit_price"),
                e14.get("element14_currency"),

                mouser.get("mouser_part_number"),
                mouser.get("mouser_stock"),
                mouser.get("mouser_lifecycle_status"),
                mouser.get("mouser_datasheet_url"),
                mouser.get("mouser_product_url"),
                mouser.get("mouser_moq"),
                mouser.get("mouser_spq"),
                mouser.get("mouser_lead_time"),
                mouser.get("mouser_unit_price"),
                mouser.get("mouser_currency"),

                selected_price,
                selected_currency,
                selected_supplier,
                selected_moq,

                bom_item_id

            ]
        )

        updated += 1

    conn.commit()
    conn.close()

    mouser_missing = total - mouser_found

    print("\n========================================")
    print(" ENRICHMENT COMPLETE")
    print("========================================")
    print(f"Updated Parts     : {updated}")
    print(f"DigiKey Found     : {digikey_found}")
    print(f"Element14 Found   : {element14_found}")
    print(f"Mouser Found      : {mouser_found}")
    print(f"Mouser Missing    : {mouser_missing}")
    print("========================================")

    return {
        "status": "success",
        "hitl":0,
        "updated": updated,
        "digikey": digikey_found,
        "element14": element14_found,
        "mouser": mouser_found,
        "mouser_missing": mouser_missing
    }

# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    try:

        from dotenv import load_dotenv

        load_dotenv()

    except ImportError:

        pass

    print("\n========================================")
    print(" DISTRIBUTOR ENRICHMENT")
    print("========================================")

    rfq_id = input(
        "\nEnter RFQ ID : "
    ).strip()

    result = enrich_distributors(
        rfq_id
    )

    print("\n========================================")
    print(" FINAL RESULT")
    print("========================================")

    print(f"Status            : {result['status']}")
    print(f"Updated Parts     : {result['updated']}")
    print(f"DigiKey Found     : {result['digikey']}")
    print(f"Element14 Found   : {result['element14']}")
    print(f"Mouser Found      : {result['mouser']}")
    print(f"Mouser Missing    : {result['mouser_missing']}")

    print("\nDone.")
