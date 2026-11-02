import json
import os
import re
import traceback

from dotenv import load_dotenv
load_dotenv()

from fastmcp import FastMCP



from enrichment import enrich_distributors
from export_bom import export_bom
from quote_summary import build_quote_summary

from detect_alternates import detect_alternates as _detect_alternates
from apply_alternatives import apply_alternatives as _apply_alternatives

# Initialize the FastMCP server instance
mcp = FastMCP("DistributorPricing")


def _validate_id(value: str) -> str:
    """Reject IDs that contain SQL-unsafe characters before interpolation."""
    if not re.fullmatch(r'[A-Za-z0-9_\-]+', value):
        raise ValueError(f"Invalid ID format: {value!r}")
    return value


# ==========================================================
# TOOL 1
# DIGIKEY + ELEMENT14 + MOUSER ENRICHMENT
# ==========================================================

@mcp.tool()
def enrich_bom(
    rfq_id: str
):
    """
    Enrich every row of processed_bom_items for this RFQ using:

    - DigiKey
    - Element14
    - Mouser

    Supplier pricing is fetched exactly once per part and written back
    into processed_bom_items. This tool does not perform alternate
    detection or user interaction.
    """

    try:

        result = enrich_distributors(
            rfq_id
        )


        return json.dumps(result) #was: return result -13-07-26
        # return {
        #     "status": "success",
        #     "hitl":0,
        # }

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })


# ==========================================================
# TOOL 2
# EXPORT FINAL BOM
# ==========================================================

@mcp.tool()
def export_enriched_bom(
    rfq_id: str
):
    """
    Export Final Enriched BOM
    """

    try:

        rfq_id = rfq_id.strip()

        result = export_bom(
            rfq_id
        )

        return json.dumps(result)

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@mcp.tool()
def export_quote_summary(
    rfq_id: str
):
    """
    Build a standalone "Quote" summary workbook for this RFQ, modeled on the
    reference Quote sheet structure: BOM cost is populated from
    processed_bom_items.required_qty x selected_unit_price (the single
    authoritative distributor price enrich_bom already selected); every other
    cost row (MOQ Charges for batch, Material Yield %, Frt & Duty chgs, Total
    BoM Cost, Assy Charges, Testing, Over head and Profits, Final Selling
    Price) is written with its label but left blank -- those business rules
    haven't been defined yet. Must run after enrich_bom. Does not modify
    export_enriched_bom's own template-fill output.
    """

    try:

        rfq_id = rfq_id.strip()

        result = build_quote_summary(
            rfq_id
        )

        return json.dumps(result)

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@mcp.tool()
def detect_alternates(rfq_id) -> str:
    """
    Detect alternate manufacturer parts (same CPN, different MPN) in an
    already-enriched processed_bom_items and populate update_alternatives
    for user review. Must run after distributor_pricing's enrich_bom, and
    performs no supplier lookups itself.
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())

    try:
        result = _detect_alternates(rfq_id_str)
        return json.dumps(result)

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@mcp.tool()
def apply_alternatives(rfq_id) -> str:
    """
    Apply the user's preferred-alternate selections recorded in
    update_alternatives: for each CPN, keep only the MPN flagged
    preferred_flag=TRUE and remove every other alternate MPN from
    processed_bom_items. Never calls DigiKey, Element14, or Mouser.
    """
    rfq_id_str = _validate_id(str(rfq_id).strip())

    try:
        result = _apply_alternatives(rfq_id_str)
        return json.dumps(result)

    except Exception as e:

        return json.dumps({
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        })




if __name__ == "__main__":
    mcp.run(transport="http", host=os.environ.get("CAM_BIND_HOST", "0.0.0.0"), port=8003)
