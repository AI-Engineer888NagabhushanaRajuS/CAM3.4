import duckdb

from config import DB_PATH


def apply_alternatives(rfq_id):
    """
    Apply the user's preferred-alternate selections recorded in
    update_alternatives: for each CPN, keep only the MPN flagged
    preferred_flag=TRUE in processed_bom_items and remove every other
    alternate MPN for that CPN. Never calls DigiKey, Element14, or
    Mouser — pricing was already captured during enrichment.
    """

    rfq_id = str(rfq_id).strip()

    with duckdb.connect(DB_PATH) as conn:

        decisions_df = conn.execute(
            "SELECT cpn, mpn, preferred_flag FROM update_alternatives WHERE rfq_id = ?",
            [rfq_id]
        ).fetchdf()

        if decisions_df.empty:
            return {
                "status": "success",
                "message": "No alternate selections found."
            }

        cpns = decisions_df["cpn"].unique().tolist()

        # Validate every CPN has exactly one preferred selection before
        # making any change — fail the whole call rather than apply a
        # partial resolution.
        invalid = []
        preferred_by_cpn = {}

        for cpn in cpns:
            group = decisions_df[decisions_df["cpn"] == cpn]
            preferred_rows = group[group["preferred_flag"] == True]

            if len(preferred_rows) != 1:
                invalid.append({
                    "cpn": cpn,
                    "preferred_count": len(preferred_rows)
                })
            else:
                preferred_by_cpn[cpn] = preferred_rows.iloc[0]["mpn"]

        if invalid:
            return {
                "status": "failed",
                "error": "Each CPN must have exactly one preferred_flag=TRUE selection",
                "invalid_cpns": invalid
            }

        conn.execute("BEGIN TRANSACTION")
        try:
            mpns_removed = 0
            remaining_mpn_by_cpn = {}

            for cpn, preferred_mpn in preferred_by_cpn.items():

                deleted_count = conn.execute(
                    """
                    DELETE FROM processed_bom_items
                    WHERE rfq_id = ? AND cpn = ? AND mpn != ?
                    """,
                    [rfq_id, cpn, preferred_mpn]
                ).fetchone()[0]

                mpns_removed += deleted_count
                remaining_mpn_by_cpn[cpn] = preferred_mpn

            conn.execute("COMMIT")

        except Exception:
            conn.execute("ROLLBACK")
            raise

    return {
        "status": "success",
        "cpns_processed": len(preferred_by_cpn),
        "mpns_removed": mpns_removed,
        "remaining_mpn_by_cpn": remaining_mpn_by_cpn
    }
