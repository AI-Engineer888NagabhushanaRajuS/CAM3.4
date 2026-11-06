import json

import duckdb
from config import DB_PATH


def _ensure_tables(conn):
    """Idempotent, additive -- same convention as
    mcp-tools/intake/bom_to_database.py's _ensure_structure_table(). One row
    per rfq_id in gerber_geometry (the flat PCBGeometryResult); many rows per
    rfq_id in gerber_checklist (one per checklist field, same shape as the
    Gerber MCP server's own checklist_records table, just keyed by rfq_id
    instead of a PCBA-FE-local run_id)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gerber_geometry (
            rfq_id VARCHAR NOT NULL,
            width_mm DOUBLE,
            height_mm DOUBLE,
            area_cm2 DOUBLE,
            layer_count INTEGER,
            inner_layer_count INTEGER,
            has_top_soldermask BOOLEAN,
            has_bottom_soldermask BOOLEAN,
            has_top_silkscreen BOOLEAN,
            has_bottom_silkscreen BOOLEAN,
            has_top_paste BOOLEAN,
            has_bottom_paste BOOLEAN,
            is_outline_estimated BOOLEAN,
            confidence DOUBLE,
            board_name VARCHAR,
            generator VARCHAR,
            total_holes INTEGER,
            min_hole_size_mm DOUBLE,
            max_hole_size_mm DOUBLE,
            unique_tool_count INTEGER,
            has_plated_through_holes BOOLEAN,
            has_non_plated_holes BOOLEAN,
            detected_files VARCHAR,
            warnings VARCHAR,
            error_message VARCHAR,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gerber_checklist (
            rfq_id VARCHAR NOT NULL,
            field VARCHAR NOT NULL,
            category VARCHAR,
            label VARCHAR,
            value_text VARCHAR,
            value_num DOUBLE,
            value_bool BOOLEAN,
            value_type VARCHAR,
            present BOOLEAN,
            provenance VARCHAR,
            confidence DOUBLE,
            source VARCHAR,
            note VARCHAR,
            pricing_fallback VARCHAR,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _split_value(value):
    """Same tri-typed split the Gerber MCP server's own checklist_records
    table uses (run_store.py's _split_value) -- lets a caller query
    value_num/value_bool without casting, while value_text always carries a
    human-readable form regardless of type."""
    if value is None:
        return {"value_text": None, "value_num": None, "value_bool": None, "value_type": "null"}
    if isinstance(value, bool):
        return {"value_text": str(value), "value_num": None, "value_bool": value, "value_type": "bool"}
    if isinstance(value, (int, float)):
        return {"value_text": str(value), "value_num": float(value), "value_bool": None, "value_type": "number"}
    return {"value_text": str(value), "value_num": None, "value_bool": None, "value_type": "text"}


def save_gerber_geometry(rfq_id, geometry: dict):
    """Upsert (delete-then-insert, DuckDB has no native UPSERT-by-default
    here) the single geometry row for this rfq_id."""
    drills = geometry.get("drills") or {}
    with duckdb.connect(DB_PATH) as conn:
        _ensure_tables(conn)
        conn.execute("DELETE FROM gerber_geometry WHERE rfq_id = ?", [rfq_id])
        conn.execute(
            """
            INSERT INTO gerber_geometry (
                rfq_id, width_mm, height_mm, area_cm2, layer_count, inner_layer_count,
                has_top_soldermask, has_bottom_soldermask, has_top_silkscreen, has_bottom_silkscreen,
                has_top_paste, has_bottom_paste, is_outline_estimated, confidence,
                board_name, generator, total_holes, min_hole_size_mm, max_hole_size_mm,
                unique_tool_count, has_plated_through_holes, has_non_plated_holes,
                detected_files, warnings, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                rfq_id,
                geometry.get("width_mm"), geometry.get("height_mm"), geometry.get("area_cm2"),
                geometry.get("layer_count"), geometry.get("inner_layer_count"),
                geometry.get("has_top_soldermask"), geometry.get("has_bottom_soldermask"),
                geometry.get("has_top_silkscreen"), geometry.get("has_bottom_silkscreen"),
                geometry.get("has_top_paste"), geometry.get("has_bottom_paste"),
                geometry.get("is_outline_estimated"), geometry.get("confidence"),
                geometry.get("board_name"), geometry.get("generator"),
                drills.get("total_holes"), drills.get("min_hole_size_mm"), drills.get("max_hole_size_mm"),
                drills.get("unique_tool_count"), drills.get("has_plated_through_holes"),
                drills.get("has_non_plated_holes"),
                json.dumps(geometry.get("detected_files") or []),
                json.dumps(geometry.get("warnings") or []),
                geometry.get("error_message"),
            ],
        )


def save_gerber_checklist(rfq_id, fields: list):
    """Replace every checklist row for this rfq_id with the freshly extracted
    set -- same all-or-nothing replace semantics as save_gerber_geometry,
    EXCEPT for fields a human has already manually corrected
    (provenance='operator') -- extract_features can in principle run again
    for the same rfq_id (e.g. a fresh Gerber re-upload), and a plain
    delete+insert would silently blow away that correction. Captured before
    the delete, re-applied after the fresh insert, so a re-extraction
    refreshes everything EXCEPT what a human already touched."""
    with duckdb.connect(DB_PATH) as conn:
        _ensure_tables(conn)

        preserved = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT field, value_text, value_num, value_bool, value_type,
                       present, confidence, source, note, pricing_fallback
                FROM gerber_checklist
                WHERE rfq_id = ? AND provenance = 'operator'
                """,
                [rfq_id],
            ).fetchall()
        }

        conn.execute("DELETE FROM gerber_checklist WHERE rfq_id = ?", [rfq_id])
        for f in fields:
            split = _split_value(f.get("value"))
            conn.execute(
                """
                INSERT INTO gerber_checklist (
                    rfq_id, field, category, label,
                    value_text, value_num, value_bool, value_type,
                    present, provenance, confidence, source, note, pricing_fallback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    rfq_id, f.get("field"), f.get("category"), f.get("label"),
                    split["value_text"], split["value_num"], split["value_bool"], split["value_type"],
                    f.get("present"), f.get("provenance"), f.get("confidence"),
                    f.get("source"), f.get("note"),
                    None if f.get("pricing_fallback") is None else str(f.get("pricing_fallback")),
                ],
            )

        for field, (value_text, value_num, value_bool, value_type, present, confidence, source, note, pricing_fallback) in preserved.items():
            conn.execute(
                """
                UPDATE gerber_checklist
                SET value_text = ?, value_num = ?, value_bool = ?, value_type = ?,
                    present = ?, provenance = 'operator', confidence = ?, source = ?,
                    note = ?, pricing_fallback = ?
                WHERE rfq_id = ? AND field = ?
                """,
                [value_text, value_num, value_bool, value_type, present, confidence, source, note, pricing_fallback, rfq_id, field],
            )
