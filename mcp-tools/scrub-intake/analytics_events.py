"""PostHog analytics safety foundation -- CAM backend.

This module is the ONLY place that decides what is allowed to reach an
analytics destination from any of the Python services (upload_server.py,
fastapi_router.py, hitl_router.py, scrub_mcp_server.py,
reporting_module/mcp_server.py, duck_db_api.py). It intentionally has zero
PostHog dependency and makes zero network calls -- it is pure
validation/bucketing logic that a future PostHog client wrapper sits behind
(see the note at the bottom of this file). Nothing outside EVENT_ALLOWLIST
can ever be sent:

  - An event name not in EVENT_ALLOWLIST is dropped entirely.
  - A property key not declared for that event is dropped.
  - A property value that doesn't match its declared type/enum is dropped.
  - Any dict, list, or other non-scalar passed as a property value is
    dropped -- only str/int/float/bool leaves are ever accepted.

build_safe_event_payload() can never raise. Every branch is defensive; the
outermost try/except guarantees a call site can never break request
handling because analytics code misbehaved.

This event catalog is the approved source of truth from the CAM PostHog
integration plan -- no event or property exists here that wasn't already
specified there. Do not add to this file without updating that plan. It
mirrors apps/web/src/client/lib/analytics-allowlist.ts (the frontend half)
in structure and intent, though the two carry different event sets (this
file owns the backend-only pipeline/upload-processing/report events).

Nothing in this repo imports this module yet (Phase 1 -- foundation only).
Wiring it into the 6 service files above is later, separately-approved work.

Run this module's tests with: python -m unittest test_analytics_events -v
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Shared bucket vocabularies
# ---------------------------------------------------------------------------

FILE_TYPE_CATEGORY = ("spreadsheet", "cad_drawing", "document", "image")
FILE_SIZE_BUCKET = ("empty", "tiny", "small", "medium", "large", "very_large")
ROW_COUNT_BUCKET = ("none", "few", "moderate", "large", "very_large")
SMALL_COUNT_BUCKET = ("none", "one", "couple", "several", "many")
DURATION_BUCKET = ("instant", "fast", "moderate", "slow", "very_slow")
ERROR_CATEGORY = (
    "missing_data",
    "transport_failure",
    "serialization_error",
    "report_generation_error",
    "metadata_lookup_error",
    "validation_error",
    "generic_error",
)
FILE_ROLE = ("BOM", "VOLUME", "QUOTEWIN", "COSTING_SHEET")

# The real MCP tool names confirmed directly against this project's own MCP
# Jungle tool listing this session -- not guessed. Extend this tuple (and
# only this tuple) if a new tool is confirmed later; do not widen tool_name
# to a free-text string.
MCP_TOOL_NAME = (
    "centum_intake__standardize_scrub_bom",
    "centum_intake__standardize_quote_win",
    "centum_intake__standardize_costing_sheet",
    "centum_intake__standardize_erp",
    "centum_reporting__cbom",
    "centum_reporting__enrich_erp",
    "centum_reporting__enrich_costing_sheet",
    "centum_reporting__resolve_final_selection",
    "centum_reporting__generate_reports",
    "centum_reporting__export_reports",
    "distributor__enrich_bom",
    "distributor__detect_alternates",
    "distributor__export_enriched_bom",
    "distributor__export_quote_summary",
)

HITL_GATE_NAME = ("resolve_final_selection", "detect_alternates")


# ---------------------------------------------------------------------------
# Allowlist schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PropertySpec:
    """Exactly one of these should be meaningfully set; enum takes priority
    when present. kind is informational/for tests, not load-bearing."""

    kind: str  # "enum" | "boolean" | "number" | "opaque-id"
    values: Optional[tuple] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None


def _enum(values) -> PropertySpec:
    return PropertySpec(kind="enum", values=tuple(values))


_BOOL = PropertySpec(kind="boolean")


def _number(min_value: Optional[float] = None, max_value: Optional[float] = None) -> PropertySpec:
    return PropertySpec(kind="number", min_value=min_value, max_value=max_value)


_OPAQUE_ID = PropertySpec(kind="opaque-id")


@dataclass(frozen=True)
class EventSpec:
    properties: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The allowlist -- every backend event CAM is approved to track, and
# nothing else. (Frontend-only events, e.g. theme_changed, live in
# apps/web/src/client/lib/analytics-allowlist.ts and are never emitted from
# Python.)
# ---------------------------------------------------------------------------

EVENT_ALLOWLIST: dict[str, EventSpec] = {
    # Pipeline
    "pipeline_stage_completed": EventSpec({
        "tool_name": _enum(MCP_TOOL_NAME),
        "skill_index": _number(min_value=0, max_value=50),
        "duration_bucket": _enum(DURATION_BUCKET),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "pipeline_stage_failed": EventSpec({
        "tool_name": _enum(MCP_TOOL_NAME),
        "error_category": _enum(ERROR_CATEGORY),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "pipeline_hitl_triggered": EventSpec({
        "tool_name": _enum(MCP_TOOL_NAME),
        "gate_name": _enum(HITL_GATE_NAME),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "pipeline_completed": EventSpec({
        "duration_bucket": _enum(DURATION_BUCKET),
        "pipeline_run_id": _OPAQUE_ID,
    }),

    # HITL resolution
    "hitl_conflicts_resolved": EventSpec({
        "resolved_count_bucket": _enum(SMALL_COUNT_BUCKET),
        "remaining_count_bucket": _enum(SMALL_COUNT_BUCKET),
        "fully_approved": _BOOL,
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "hitl_alternates_resolved": EventSpec({
        "resolved_count_bucket": _enum(SMALL_COUNT_BUCKET),
        "remaining_count_bucket": _enum(SMALL_COUNT_BUCKET),
        "fully_approved": _BOOL,
        "pipeline_run_id": _OPAQUE_ID,
    }),

    # Reports
    "report_generated": EventSpec({
        "report_count_bucket": _enum(SMALL_COUNT_BUCKET),
        "duration_bucket": _enum(DURATION_BUCKET),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "report_generation_failed": EventSpec({
        "error_category": _enum(ERROR_CATEGORY),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "report_export_generated": EventSpec({
        "worksheet_count_bucket": _enum(SMALL_COUNT_BUCKET),
        "duration_bucket": _enum(DURATION_BUCKET),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "report_export_failed": EventSpec({
        "error_category": _enum(ERROR_CATEGORY),
        "pipeline_run_id": _OPAQUE_ID,
    }),
    "report_downloaded": EventSpec({
        "report_type": _enum(("full_workbook", "cbom_only", "grid_excel_export")),
    }),

    # Uploads (backend half -- frontend half in analytics-allowlist.ts)
    "upload_received": EventSpec({
        "file_role": _enum(FILE_ROLE),
        "file_type_category": _enum(FILE_TYPE_CATEGORY),
        "file_size_bucket": _enum(FILE_SIZE_BUCKET),
        "is_new_version": _BOOL,
    }),
    "upload_validation_failed": EventSpec({
        "failure_category": _enum(("unsupported_file_type", "missing_rfq_id")),
    }),
    "upload_processing_started": EventSpec({
        "file_role": _enum(FILE_ROLE),
    }),
    "upload_processing_completed": EventSpec({
        "file_role": _enum(FILE_ROLE),
        "row_count_bucket": _enum(ROW_COUNT_BUCKET),
        "duration_bucket": _enum(DURATION_BUCKET),
        "already_processed": _BOOL,
    }),
    "upload_processing_skipped": EventSpec({
        "file_role": _enum(FILE_ROLE),
    }),
    "upload_processing_failed": EventSpec({
        "file_role": _enum(FILE_ROLE),
        "failure_category": _enum((
            "file_not_found",
            "sheet_not_found",
            "header_row_not_found",
            "missing_required_fields",
            "malformed_file",
            "already_exists_conflict",
            "database_error",
            "generic_error",
        )),
    }),
}


# ---------------------------------------------------------------------------
# Public validation entry point
# ---------------------------------------------------------------------------

AllowedPropertyValue = Union[str, int, float, bool]

_OPAQUE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _is_plain_scalar(value) -> bool:
    # bool is a subclass of int in Python -- checked separately by callers
    # that specifically need boolean vs numeric distinction.
    return isinstance(value, (str, int, float, bool))


def _is_value_allowed(spec: PropertySpec, value) -> bool:
    if not _is_plain_scalar(value):
        return False
    if spec.kind == "enum":
        return isinstance(value, str) and value in (spec.values or ())
    if spec.kind == "boolean":
        return isinstance(value, bool)
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if spec.min_value is not None and value < spec.min_value:
            return False
        if spec.max_value is not None and value > spec.max_value:
            return False
        return True
    if spec.kind == "opaque-id":
        return isinstance(value, str) and bool(_OPAQUE_ID_RE.match(value))
    return False


def build_safe_event_payload(event_name: str, raw_properties: Optional[dict] = None):
    """The single gate every analytics call must pass through.

    Returns None if the event itself isn't recognized (caller should send
    nothing). Otherwise returns {"event": event_name, "properties": {...}}
    with only the properties that passed validation -- unknown/invalid
    properties are silently dropped, never raised on. Never raises.
    """
    try:
        if not isinstance(event_name, str) or not event_name:
            return None
        spec = EVENT_ALLOWLIST.get(event_name)
        if spec is None:
            return None

        properties: dict = {}
        if isinstance(raw_properties, dict):
            for key, value in raw_properties.items():
                prop_spec = spec.properties.get(key)
                if prop_spec is None:
                    continue
                if _is_value_allowed(prop_spec, value):
                    properties[key] = value
        return {"event": event_name, "properties": properties}
    except Exception:
        return None


def is_known_event(event_name: str) -> bool:
    """True if an event name is recognized at all -- useful for call-site
    guards without needing to build a payload first."""
    try:
        return isinstance(event_name, str) and event_name in EVENT_ALLOWLIST
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Bucketing helpers -- every one is pure and defensive (bad input maps to
# the smallest/safest bucket rather than raising).
# ---------------------------------------------------------------------------

def bucket_file_size(num_bytes) -> str:
    try:
        num_bytes = float(num_bytes)
    except (TypeError, ValueError):
        return "empty"
    if num_bytes <= 0:
        return "empty"
    if num_bytes < 100 * 1024:
        return "tiny"
    if num_bytes < 1024 * 1024:
        return "small"
    if num_bytes < 10 * 1024 * 1024:
        return "medium"
    if num_bytes < 50 * 1024 * 1024:
        return "large"
    return "very_large"


def bucket_row_count(count) -> str:
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "none"
    if count <= 0:
        return "none"
    if count <= 50:
        return "few"
    if count <= 500:
        return "moderate"
    if count <= 5000:
        return "large"
    return "very_large"


def bucket_small_count(count) -> str:
    """For naturally-small counts (report/worksheet counts, HITL conflict
    counts) -- a coarser scale than bucket_row_count, appropriate for
    numbers that are rarely more than a couple dozen."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "none"
    if count <= 0:
        return "none"
    if count == 1:
        return "one"
    if count <= 3:
        return "couple"
    if count <= 10:
        return "several"
    return "many"


def bucket_duration_seconds(seconds) -> str:
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "instant"
    if seconds < 0:
        return "instant"
    if seconds < 1:
        return "instant"
    if seconds < 10:
        return "fast"
    if seconds < 60:
        return "moderate"
    if seconds < 300:
        return "slow"
    return "very_slow"


_CAD_DRAWING_EXTENSIONS = {"stp", "step", "dwg", "dxf", "274x", "274-d", "x2", "x3"}
_DOCUMENT_EXTENSIONS = {"pdf", "eml", "zip"}
_IMAGE_EXTENSIONS = {"jpeg", "jpg", "png", "bmp", "tiff"}
_SPREADSHEET_EXTENSIONS = {"csv", "xls", "xlsx"}


def _extname(name_or_ext: str) -> str:
    trimmed = (name_or_ext or "").strip().lower()
    if "." in trimmed:
        return trimmed.rsplit(".", 1)[-1]
    return trimmed


def categorize_file_type(name_or_ext: str) -> str:
    """Categorizes an RFQ document upload by the real 19-extension allowlist
    used in upload_server.py:30-34 -- never returns or logs the name itself."""
    ext = _extname(name_or_ext)
    if ext in _SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if ext in _CAD_DRAWING_EXTENSIONS:
        return "cad_drawing"
    if ext in _DOCUMENT_EXTENSIONS:
        return "document"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    return "other"


def classify_error(exc: Optional[BaseException] = None, message: Optional[str] = None) -> str:
    """Maps a raw exception/message to a small closed error_category bucket.
    The raw text is only ever inspected here, inside this function -- it is
    never itself returned, stored on the result, or otherwise propagated to
    a caller that might attach it to an event payload."""
    try:
        text = ""
        if message:
            text = str(message)
        elif exc is not None:
            text = str(exc)
        text_lower = text.lower()

        if "no cbom rows found" in text_lower or "call the cbom tool first" in text_lower:
            return "missing_data"
        if "bridge extraction failure" in text_lower or "non-json content" in text_lower:
            return "serialization_error"
        if "tool call failed" in text_lower or "timeout" in text_lower:
            return "transport_failure"
        if "report(s) failed" in text_lower:
            return "report_generation_error"
        if "could not retrieve file path" in text_lower:
            return "metadata_lookup_error"
        if "is not one of its available_sources" in text_lower:
            return "validation_error"
        return "generic_error"
    except Exception:
        return "generic_error"


def classify_upload_processing_error(exc: Optional[BaseException] = None, message: Optional[str] = None) -> str:
    """Maps a raw upload-processing exception/message to one of the
    upload_processing_failed.failure_category buckets. Separate from
    classify_error() above because it targets a different, upload-specific
    enum (sheet_not_found, header_row_not_found, etc.) rather than the
    general-purpose pipeline/report ERROR_CATEGORY -- reusing classify_error()
    here would silently map every one of these real, confirmed message
    patterns (from scrub_bom_processing.py, quote_win_processing.py,
    costing_sheet_processing.py, scrub_bom_to_database.py,
    quote_win_to_database.py, costing_sheet_to_database.py) to its
    "generic_error" catch-all instead. The raw text is only ever inspected
    here -- never returned, stored, or otherwise propagated to a caller that
    might attach it to an event payload."""
    try:
        text = ""
        if message:
            text = str(message)
        elif exc is not None:
            text = str(exc)
        text_lower = text.lower()

        if "could not retrieve file path" in text_lower:
            return "file_not_found"
        if "no bom file uploaded" in text_lower or "no quotewin file uploaded" in text_lower:
            return "file_not_found"
        if "could not find a sheet named" in text_lower:
            return "sheet_not_found"
        if "could not locate the quotewin data header row" in text_lower:
            return "header_row_not_found"
        if "missing critical mappings" in text_lower or "could not find an 'fg' column" in text_lower:
            return "missing_required_fields"
        if "already exists in" in text_lower:
            return "already_exists_conflict"
        if "not a zip file" in text_lower or "corrupt" in text_lower or "unsupported format" in text_lower:
            return "malformed_file"
        if "psycopg2" in text_lower or "duckdb" in text_lower or "database" in text_lower or "connection" in text_lower:
            return "database_error"
        return "generic_error"
    except Exception:
        return "generic_error"


def generate_run_id() -> str:
    """Generates a random, per-run correlation token -- a foundation for
    future cross-event correlation (e.g. tying together the several backend
    events that belong to one pipeline run). Deliberately NOT a function of
    any RFQ id, customer id, or other business identifier: it is pure
    randomness (uuid4), so it can never be reversed or brute-forced back to
    an internal identifier by anyone who only has analytics access.
    Persisting/threading this value across a single run's events is future
    wiring, not part of this foundation.
    """
    try:
        return uuid.uuid4().hex[:12]
    except Exception:
        # uuid4() failing at all would be extraordinary, but this function
        # must never raise -- fall back to a still-random, still-unlinkable
        # value rather than propagate an exception into a request handler.
        import os

        return os.urandom(6).hex()


# ---------------------------------------------------------------------------
# Future wiring note (NOT part of this phase -- no SDK is initialized here):
#
#   1. This module will gain a thin PostHog Python client wrapper.
#   2. The 6 backend service files will call build_safe_event_payload() at
#      their respective points (upload receipt/validation/processing,
#      pipeline stage advance/fail/hitl, report generation/export/download)
#      and forward the result to that client only if it's non-None.
#   3. Only allowlisted names/properties can ever reach PostHog when that
#      happens -- this file's behavior does not change.
# ---------------------------------------------------------------------------
