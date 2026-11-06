import duckdb

from config import DB_PATH


def _ensure_alternatives_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS update_alternatives (
            id UUID DEFAULT gen_random_uuid(),
            rfq_id VARCHAR(100),
            bom_item_id UUID,
            cpn VARCHAR,
            mpn VARCHAR,
            mfr VARCHAR,
            preferred_flag BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def detect_alternates(rfq_id):
    """
    Detect alternate manufacturer parts in an already-enriched
    processed_bom_items (same cpn / UBR Number, different mpn) and
    populate update_alternatives with one row per alternate MPN for user
    review. Performs no supplier lookups — pricing is already present on
    processed_bom_items from distributor_pricing's enrich_bom.
    """

    rfq_id = str(rfq_id).strip()

    with duckdb.connect(DB_PATH) as conn:

        _ensure_alternatives_table(conn)

        existing_count = conn.execute(
            "SELECT COUNT(*) FROM update_alternatives WHERE rfq_id = ?",
            [rfq_id]
        ).fetchone()[0]

        if existing_count > 0:
            return {
                "status": "failed",
                "error": f"Alternates already detected for RFQ {rfq_id}",
                "existing_rows": existing_count
            }

        df = conn.execute(
            """
            SELECT bom_item_id, cpn, mpn, mfr
            FROM processed_bom_items
            WHERE rfq_id = ? AND cpn IS NOT NULL AND cpn != ''
            """,
            [rfq_id]
        ).fetchdf()

        if df.empty:
            return {"status": "success", "cpns_flagged": 0, "alternates_found": 0}

        mpn_counts = df.groupby("cpn")["mpn"].nunique()
        duplicate_cpns = mpn_counts[mpn_counts > 1].index.tolist()

        if not duplicate_cpns:
            return {"status": "success", "cpns_flagged": 0, "alternates_found": 0}

        conn.execute("BEGIN TRANSACTION")
        try:
            inserted = 0

            for cpn in duplicate_cpns:

                group = df[df["cpn"] == cpn]

                for _, row in group.iterrows():
                    conn.execute(
                        """
                        INSERT INTO update_alternatives
                            (id, rfq_id, bom_item_id, cpn, mpn, mfr,
                             preferred_flag, created_at, updated_at)
                        VALUES (gen_random_uuid(), ?, ?, ?, ?, ?, FALSE,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [rfq_id, row["bom_item_id"], cpn, row["mpn"], row["mfr"]]
                    )
                    inserted += 1

            conn.execute("COMMIT")

        except Exception:
            conn.execute("ROLLBACK")
            raise

    return {
        "status": "success",
        "cpns_flagged": len(duplicate_cpns),
        "alternates_found": inserted,
    }
