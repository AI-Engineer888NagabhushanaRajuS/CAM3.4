"""SUB_05 — BOM ingestion (WORK_REPORT §A6)."""
from bom_parser.parser import (
    BOMParseResult,
    expand_refdes,
    fastmcp_extract_bom_components,
    parse_bom,
    parse_bom_files,
    parse_cpl,
)

__all__ = [
    "BOMParseResult",
    "expand_refdes",
    "fastmcp_extract_bom_components",
    "parse_bom",
    "parse_bom_files",
    "parse_cpl",
]
