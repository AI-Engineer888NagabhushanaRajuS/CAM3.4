"""
SPEC-017 bug (final_selection.py): resolve_final_selection is re-runnable, but the conflict
query never looks at final_*, so a re-run re-inserted conflicts a human had already resolved.
The pending-conflict builder must skip cbom rows that already have a resolved conflict.

build_pending_conflicts is lifted out of the source with ast (final_selection.py imports
psycopg2 and sibling modules that are not importable here).
"""
import ast
import os

FS = os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset", "final_selection.py")


def _builder():
    with open(FS, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    wanted = {"SOURCE_FIELDS", "build_pending_conflicts"}
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) in wanted for t in n.targets):
            nodes.append(n)
        if isinstance(n, ast.FunctionDef) and n.name in wanted:
            nodes.append(n)
    namespace = {"json": __import__("json"), "uuid": __import__("uuid")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), FS, "exec"), namespace)
    return namespace["build_pending_conflicts"]


def _row(cbom_item_id, cpn):
    columns = ["cbom_item_id", "bom_item_id", "volume_no", "cpn",
               "price_conv_costing", "price_original_costing", "currency_original_costing",
               "mfg_name_costing", "supp_name_costing", "pkg_qty_costing", "moq_costing",
               "lead_time_costing", "unit_of_measure_costing",
               "price_conv_erp", "price_original_erp", "currency_original_erp",
               "mfg_name_erp", "supp_name_erp", "pkg_qty_erp", "moq_erp",
               "lead_time_erp", "unit_of_measure_erp",
               "price_conv_qw", "price_original_qw", "currency_original_qw",
               "mfg_name_qw", "supp_name_qw", "pkg_qty_qw", "moq_qw",
               "lead_time_qw", "unit_of_measure_qw"]
    values = [cbom_item_id, "bom-1", "1", cpn] + [None] * 8 + [1.5, None, "USD", "Acme", None, None, None, None, None, "EA"] + [None] * 9
    return columns, tuple(values)


def test_already_resolved_conflict_is_not_reopened():
    build = _builder()
    cols, row_a = _row("item-A", "CPN-A")
    _, row_b = _row("item-B", "CPN-B")
    out = build("RFQ-1", [row_a, row_b], cols, resolved_item_ids={"item-A"})
    assert len(out) == 1, out
    assert out[0][2] == "item-B"


def test_unresolved_conflicts_are_all_kept():
    build = _builder()
    cols, row_a = _row("item-A", "CPN-A")
    _, row_b = _row("item-B", "CPN-B")
    out = build("RFQ-1", [row_a, row_b], cols, resolved_item_ids=set())
    assert [t[2] for t in out] == ["item-A", "item-B"]
