"""The engine check must read the finished workbook: it runs after the last write (comment parts), not in the middle of the export."""
from pathlib import Path

SOURCE = (Path(__file__).parent / "mcp_server.py").read_text(encoding="utf-8")


def test_engine_check_runs_after_the_last_write():
    engine = SOURCE.index('result["engine_check"] = _engine_check(')
    last_write = SOURCE.index('result["comment_parts_renamed"] = xlsx_rels.normalise_comment_parts(')
    assert last_write < engine, "the engine check reads a file that is still being written"


if __name__ == "__main__":
    test_engine_check_runs_after_the_last_write()
    print("ok")
