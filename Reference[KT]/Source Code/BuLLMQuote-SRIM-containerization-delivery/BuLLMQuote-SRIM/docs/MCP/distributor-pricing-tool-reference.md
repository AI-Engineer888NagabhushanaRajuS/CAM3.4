# Distributor Pricing MCP Server — Reference

Source directory: `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\`

This is a standalone FastMCP server (`mcp_server.py`) implementing supplier-pricing
enrichment for BOM/RFQ costing. It queries DigiKey, Element14 (Farnell/Newark), and
Mouser distributor APIs, writes pricing/availability data back into the shared
`processed_bom_items` DuckDB table, and provides alternate-manufacturer-part detection
and resolution workflows plus an Excel export.

**Status: DORMANT.** This server is fully implemented and independently startable
(intended for port 8003 / `mcp.run(transport="http", host="192.168.1.27", port=8003)`
in `mcp_server.py`), but it is **not** registered in the `SERVICES` list of
`C:\Users\ADMIN\Documents\SRIM\Tools\I n D\centum intake\manage_backend.py`. That file's
`SERVICES` list currently manages `upload_server`, `fastapi_router`, `hitl_router`,
`scrub_mcp_server`, `reporting_mcp_server`, `bom_qa_lookup_server`, `python_bridge`, and
`web_frontend` (plus a `superset` / `daemon` entry and external TCP/HTTP health checks
for Postgres, Ollama, and an MCP gateway) — no entry for this tool or port 8003 exists,
so it does not start automatically with the rest of the backend.

## Database path — confirmed

This folder has **no local copy** of `duckdb_schema.py` and no local DuckDB file. Every
module that touches the database (`enrichment.py`, `detect_alternates.py`,
`apply_alternatives.py`, `export_bom.py`) imports `DB_PATH` from `config.py`, which in
turn does:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.db_config import DB_PATH
```

`shared/db_config.py` (at `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\shared\db_config.py`,
a sibling of `distributor_pricing/` and `intake/`) defines:

```python
DB_PATH = Path(r"C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb")
```

Its own comment states this is deliberate: *"The single shared constant both intake/
and distributor_pricing/ need identically — both FastMCP servers are separate
processes pointed at the same physical DuckDB file."* Both `C:\SRIM-DB-SETUP\Databases\Bom_storage.duckdb`
and `duckdb_schema.py` in that same folder exist on disk (Windows paths are
case-insensitive, so the differing capitalization noted in the task brief refers to the
same file). This tool therefore reads/writes the **original external database at
`C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb`**, not the copy that was made earlier
this session into `C:\Users\ADMIN\Documents\BuLLMQuote-SRIM\database\Bom_storage.duckdb`.
Any documentation, testing, or migration work referencing "the" database for this tool
should be aware these are two distinct files on disk unless deliberately kept in sync.

## Tool execution order

The four `@mcp.tool()` functions in `mcp_server.py` have a real sequencing dependency.
They are not independently callable in arbitrary order if the intent is a full
enrichment-to-export cycle:

```
enrich_bom  →  detect_alternates  →  apply_alternatives  →  export_enriched_bom
```

1. **`enrich_bom(rfq_id)`** must run first — it is the only tool that calls the
   DigiKey/Element14/Mouser APIs and populates the distributor columns on
   `processed_bom_items`.
2. **`detect_alternates(rfq_id)`** requires `processed_bom_items` to already be
   enriched (it reads `cpn`/`mpn`/`mfr`, not distributor pricing directly, but its own
   docstring states it "must run after distributor_pricing's enrich_bom"). It populates
   `update_alternatives` for human review and refuses to run twice for the same
   `rfq_id` (returns `status: failed` if rows already exist).
3. **`apply_alternatives(rfq_id)`** requires a human to have set exactly one
   `preferred_flag=TRUE` row per `cpn` in `update_alternatives` (presumably via a
   separate UI/HITL step outside this codebase) before it is called. It then deletes
   the non-preferred alternate MPN rows from `processed_bom_items`.
4. **`export_enriched_bom(rfq_id)`** can be run at any point after enrichment to
   produce the Excel deliverable, but is normally run last so the export reflects the
   post-alternate-resolution state of `processed_bom_items`.

`export_enriched_bom` does not strictly require steps 2–3 to have run (it just dumps
whatever is currently in `processed_bom_items` for the `rfq_id` into the template), but
running it before alternates are resolved will include duplicate CPN rows with
unresolved alternate MPNs in the output.

## Table of Contents

1. [mcp_server.py](#mcp_serverpy)
2. [config.py](#configpy)
3. [enrichment.py](#enrichmentpy)
4. [digikey_client.py](#digikey_clientpy)
5. [element14.py](#element14py)
6. [mouser_client.py](#mouser_clientpy)
7. [models.py](#modelspy)
8. [detect_alternates.py](#detect_alternatespy)
9. [apply_alternatives.py](#apply_alternativespy)
10. [export_bom.py](#export_bompy)
11. [requirements.txt](#requirementstxt)
12. [.env](#env)
13. [__init__.py](#__init__py)
14. [.claude/settings.local.json](#claudesettingslocaljson)
15. [Generated Excel outputs (excluded from per-file docs)](#generated-excel-outputs)

---

## `mcp_server.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\mcp_server.py`

**Purpose:** Entry point for the FastMCP server. Wires the four public tools to their
underlying implementation modules, wraps every tool in a uniform try/except JSON
response envelope, and starts the HTTP transport.

**Responsibilities:**
- Load `.env` via `python-dotenv` before anything else executes.
- Instantiate the `FastMCP("DistributorPricing")` app object.
- Validate `rfq_id`-like inputs against a safe character set before they reach any
  SQL interpolation performed in downstream modules.
- Expose 4 tools (`enrich_bom`, `export_enriched_bom`, `detect_alternates`,
  `apply_alternatives`), each delegating to the corresponding module and returning a
  JSON string (`json.dumps(...)`), catching all exceptions and returning
  `{"status": "failed", "error": ..., "traceback": ...}` instead of raising.
- Run the server over HTTP transport on `192.168.1.27:8003` when executed directly.

**Dependencies:** `json`, `re`, `traceback` (stdlib); `python-dotenv` (`load_dotenv`);
`fastmcp` (`FastMCP`); local modules `enrichment.py` (`enrich_distributors`),
`export_bom.py` (`export_bom`), `detect_alternates.py` (aliased `_detect_alternates`),
`apply_alternatives.py` (aliased `_apply_alternatives`).

**Public interfaces:**

- `_validate_id(value: str) -> str` — regex-validates an ID string against
  `^[A-Za-z0-9_\-]+$`; raises `ValueError` on any other character. Used to reject
  SQL-unsafe characters before interpolation. **Note:** only `detect_alternates` and
  `apply_alternatives` call this; `enrich_bom` and `export_enriched_bom` do not (see
  below).

- `@mcp.tool() enrich_bom(rfq_id: str)` — **Tool 1.**
  - **Parameters:** `rfq_id` (str) — the RFQ to enrich.
  - **Behavior:** Calls `enrich_distributors(rfq_id)` from `enrichment.py` directly
    (no `_validate_id` call, no `.strip()` on input here — stripping happens inside
    `enrich_distributors` itself). Wraps the call in try/except.
  - **Returns:** JSON string of the result dict from `enrich_distributors`, e.g.
    `{"status": "success", "hitl": 0, "updated": N, "digikey": N, "element14": N,
    "mouser": N, "mouser_missing": N}` on success, or the standard
    `{"status": "failed", "error", "traceback"}` envelope on exception.
  - **Docstring intent:** "Enrich every row of processed_bom_items for this RFQ using
    DigiKey, Element14, and Mouser. Supplier pricing is fetched exactly once per part
    and written back into processed_bom_items. This tool does not perform alternate
    detection or user interaction."

- `@mcp.tool() export_enriched_bom(rfq_id: str)` — **Tool 2.**
  - **Parameters:** `rfq_id` (str).
  - **Behavior:** `rfq_id.strip()`, then calls `export_bom(rfq_id)` from
    `export_bom.py`. No `_validate_id` call (relies on `export_bom`'s parameterized
    query for safety).
  - **Returns:** JSON string of `export_bom`'s result dict (status, rows_written,
    columns_matched, columns_skipped, skipped_columns, output_file) or the failure
    envelope.
  - **Docstring:** "Export Final Enriched BOM."

- `@mcp.tool() detect_alternates(rfq_id) -> str` — **Tool 3.**
  - **Parameters:** `rfq_id` (untyped in signature, coerced to `str` internally).
  - **Behavior:** `rfq_id_str = _validate_id(str(rfq_id).strip())`, then calls
    `_detect_alternates(rfq_id_str)` (the aliased import of `detect_alternates.py`'s
    `detect_alternates` function).
  - **Returns:** JSON string of the result (status, cpns_flagged, alternates_found, or
    a failure/duplicate-run error) or the failure envelope.
  - **Docstring:** "Detect alternate manufacturer parts (same CPN, different MPN) in
    an already-enriched processed_bom_items and populate update_alternatives for user
    review. Must run after distributor_pricing's enrich_bom, and performs no supplier
    lookups itself."

- `@mcp.tool() apply_alternatives(rfq_id) -> str` — **Tool 4.**
  - **Parameters:** `rfq_id` (untyped, coerced to `str` internally).
  - **Behavior:** `rfq_id_str = _validate_id(str(rfq_id).strip())`, then calls
    `_apply_alternatives(rfq_id_str)` (the aliased import of `apply_alternatives.py`'s
    `apply_alternatives` function).
  - **Returns:** JSON string of the result (status, cpns_processed, mpns_removed,
    remaining_mpn_by_cpn, or a validation failure listing `invalid_cpns`) or the
    failure envelope.
  - **Docstring:** "Apply the user's preferred-alternate selections recorded in
    update_alternatives: for each CPN, keep only the MPN flagged preferred_flag=TRUE
    and remove every other alternate MPN from processed_bom_items. Never calls
    DigiKey, Element14, or Mouser."

**Internal execution flow:** `mcp_server.py` itself contains no API-integration logic —
it is purely a thin dispatch/validation/error-envelope layer. See `enrichment.py`,
`digikey_client.py`, `element14.py`, and `mouser_client.py` below for the actual
supplier-integration flow.

**Configuration usage:** Calls `load_dotenv()` at import time so all downstream modules
(`enrichment.py`, `element14.py`) can read `os.getenv(...)` for API credentials without
each needing their own `load_dotenv()` call (though `element14.py` and the
`__main__` block of `enrichment.py` also call `load_dotenv()` defensively). Hardcodes
the bind host `192.168.1.27` and port `8003` in the `if __name__ == "__main__":` block.

**Related files:** `enrichment.py`, `export_bom.py`, `detect_alternates.py`,
`apply_alternatives.py`, `.env`.

**Inference:** `enrich_bom` and `export_enriched_bom` do not call `_validate_id`, unlike
`detect_alternates` and `apply_alternatives`. This is an inconsistency in the codebase —
it is not clear whether this is intentional (e.g. because `enrich_distributors` and
`export_bom` use parameterized queries throughout and were judged already safe) or an
oversight. Both downstream functions do use parameterized DuckDB queries for `rfq_id`,
so there is no obvious SQL-injection path even without `_validate_id`, but the
inconsistent hardening pattern is worth flagging for a future cleanup pass.

---

## `config.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\config.py`

**Purpose:** Single source of truth for the DuckDB file path used by every DB-touching
module in this package, by re-exporting a constant from the sibling `shared/` package.

**Responsibilities:**
- Insert the parent-of-parent directory (i.e.
  `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\`) onto `sys.path` so the sibling `shared`
  package can be imported regardless of the current working directory the server is
  launched from.
- Re-export `DB_PATH` from `shared.db_config`.

**Dependencies:** `sys`, `pathlib.Path` (stdlib); `shared.db_config` (external sibling
package, not inside this folder).

**Public interfaces:**
- Module-level constant `DB_PATH` — a `pathlib.Path` pointing at
  `C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb` (see the "Database path — confirmed"
  section above for full detail on how this resolves).

**Internal execution flow:** N/A (no functions; pure import-time path setup).

**Configuration usage:** This is itself the configuration indirection point — every
other module in this package (`enrichment.py`, `detect_alternates.py`,
`apply_alternatives.py`, `export_bom.py`) does `from config import DB_PATH` rather than
hardcoding or reading an environment variable for the DB location.

**Related files:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\shared\db_config.py`
(external, one directory up and over — not part of the ~17 files in this folder, but is
a hard dependency of this entire package).

---

## `enrichment.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\enrichment.py`

**Purpose:** Core orchestration for Tool 1 (`enrich_bom`). Iterates every BOM line for
an RFQ, queries all three distributor clients once each, and writes results back into
`processed_bom_items`.

**Responsibilities:**
- Ensure all 28 distributor-specific columns (9 DigiKey + 10 Element14 + 9 Mouser)
  exist on `processed_bom_items`, adding any missing ones via `ALTER TABLE`.
- Sanitize distributor-returned numeric placeholder strings (`"N/A"`, `"NA"`, `""`,
  `"-"`) to `None` before they're written to `DOUBLE` columns.
- For every row with a non-null `mpn` in the given `rfq_id`, call DigiKey, Element14,
  and Mouser lookups exactly once each, then `UPDATE` that row's 28 columns in a single
  statement.
- Track and report per-distributor hit counts and a final summary.
- Provide a standalone CLI entry point (`python enrichment.py`) that prompts for an
  RFQ ID interactively — useful for manual/offline runs outside the MCP tool.

**Dependencies:** `os`, `duckdb` (third-party); local imports `config.DB_PATH`,
`digikey_client.DigikeyClient`, `element14.search_by_part_number` /
`element14.parse_part_info`, `mouser_client.MouserClient`. The `__main__` block also
imports `dotenv.load_dotenv` defensively (wrapped in `try/except ImportError`).

**Public interfaces:**

- `clean_number(value)` — returns `None` if `value` is `None` or (after
  `.strip().upper()`) one of `{"N/A", "NA", "", "-"}`; otherwise returns `value`
  unchanged. Used only on Element14 MOQ/SPQ/unit-price fields, which come back as raw
  strings from the API.

- `ensure_columns(conn)` — queries `information_schema.columns` for
  `processed_bom_items`, compares (case-insensitively) against the 28-column list
  (DigiKey/Element14/Mouser part number, stock, lifecycle/status, datasheet URL,
  MOQ, SPQ, lead time, unit price, currency — plus Element14-only `rohs` and
  Mouser-only `product_url`), and `ALTER TABLE ... ADD COLUMN`s any that are missing.
  Idempotent — safe to call on every `enrich_bom` invocation.

- `enrich_digikey(client, mpn)` — calls `client.lookup(mpn)` on a `DigikeyClient`
  instance; returns `{}` if `result.error` is truthy or on any exception (logged to
  stdout as `"DigiKey Error (<mpn>) : <e>"`); otherwise returns a dict of the 9
  `digikey_*` fields pulled off the returned `PartDetails`.

- `enrich_element14(mpn)` — **not** parameterized with a client instance (element14.py
  exposes module-level functions, not a class). First checks
  `os.getenv("ELEMENT14_API_KEY")`; if unset, returns `{}` immediately. This guard
  exists specifically because `element14.get_api_key()` (inside `element14.py`) calls
  `sys.exit(1)` when the key is missing/placeholder, and `SystemExit` does **not**
  inherit from `Exception`, so a bare `except Exception` would not catch it — without
  this pre-check a missing Element14 key would kill the entire enrichment process
  instead of degrading gracefully like a normal per-distributor lookup failure. If the
  key is present, calls `search_by_part_number(mpn, "manuPartNum")`, extracts
  `manufacturerPartNumberSearchReturn` (falling back to `keywordSearchReturn`), takes
  the first product, calls `parse_part_info`, and maps its fields (with `clean_number`
  applied to MOQ/SPQ/unit price) into the 10 `element14_*` fields. Returns `{}` on any
  other exception or if no products are found.

- `enrich_mouser(client, mpn)` — calls `client.lookup(mpn)` on a `MouserClient`
  instance; same `{}`-on-error/exception pattern as `enrich_digikey`, mapping to the 9
  `mouser_*` fields.

- `enrich_distributors(rfq_id)` — **the main orchestration function**, called directly
  by `mcp_server.enrich_bom`.
  - Strips `rfq_id` to a string.
  - Opens a DuckDB connection to `config.DB_PATH`, calls `ensure_columns`.
  - Instantiates one `DigikeyClient` (credentials from `DIGIKEY_CLIENT_ID` /
    `DIGIKEY_CLIENT_SECRET` env vars) and one `MouserClient` (`MOUSER_API_KEY` env var)
    — reused across all rows so DigiKey's OAuth token is cached/reused rather than
    re-authenticated per part.
  - Queries all `(bom_item_id, mpn)` pairs from `processed_bom_items` for the given
    `rfq_id` where `mpn IS NOT NULL`, ordered by `mpn`.
  - For each row (sequentially, not concurrently): calls `enrich_digikey`,
    `enrich_element14`, `enrich_mouser` in that fixed order, increments per-distributor
    found-counters, then issues one `UPDATE ... WHERE bom_item_id=?` writing all 28
    columns (using `.get()` on each per-distributor dict so missing keys become `NULL`
    parameters rather than raising `KeyError`).
  - Commits and closes the connection after the full loop (not per-row).
  - Prints progress (`[i/total] <mpn>`) and a final summary block to stdout.
  - Returns `{"status": "success", "hitl": 0, "updated": N, "digikey": N,
    "element14": N, "mouser": N, "mouser_missing": N}`.

- `if __name__ == "__main__":` block — interactive CLI: loads `.env`, prompts for an
  RFQ ID via `input()`, calls `enrich_distributors`, prints the result summary.

**Internal execution flow (core logic):** For each BOM row, three independent
API calls are made unconditionally and sequentially (DigiKey → Element14 → Mouser),
each wrapped so a failure in one distributor never blocks the others or aborts the
row's DB write. This satisfies the stated design goal that "supplier pricing is
fetched exactly once per part" — there is no retry loop and no caching across rows
(every row does 3 fresh HTTP round-trips, except DigiKey's OAuth token which is cached
on the shared `DigikeyClient` instance for its ~1-hour lifetime).

**Configuration usage:** Reads `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET`,
`MOUSER_API_KEY`, `ELEMENT14_API_KEY` from environment (populated via `.env` +
`load_dotenv()`, called upstream in `mcp_server.py` or defensively in this file's own
`__main__` block). Uses `config.DB_PATH` for the DuckDB connection.

**Related files:** `config.py`, `digikey_client.py`, `element14.py`,
`mouser_client.py`, `mcp_server.py` (caller), `.env` (credential source).

---

## `digikey_client.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\digikey_client.py`

**Purpose:** Self-contained HTTP client for the DigiKey Product Information API v4,
handling OAuth2 client-credentials auth, product lookup by exact part number with
keyword-search fallback, and response normalization into the shared `PartDetails`
model.

**Responsibilities:**
- Manage a client-credentials OAuth2 token lifecycle (fetch, cache, expire, re-fetch
  on 401).
- Look up a part first via the exact-match Product Details endpoint; if that fails,
  fall back to keyword search and pick the best match.
- Normalize DigiKey's nested JSON (`Product` / `ProductVariations` / `StandardPricing`)
  into a flat `PartDetails` dataclass, preferring a "Cut Tape" packaging variation when
  available.
- Expose a `search_alternatives` helper for keyword-based alternate-part search
  (defined here but not currently called by `detect_alternates.py`, which does its own
  DB-only same-CPN grouping instead).

**Dependencies:** `time`, `requests` (third-party). Imports `PartDetails`, `PriceBreak`
from `models.py`, with a fallback `from distributor_pricing.models import ...` for when
this module is imported as part of a `distributor_pricing` package rather than run
from within the folder directly.

**Public interfaces:**

- `class DigikeyClient`
  - `__init__(self, client_id: str, client_secret: str)` — stores credentials, sets up
    a `requests.Session`, initializes token cache state (`_token=None`,
    `_token_expiry=0`).
  - `_authenticate(self)` — POSTs to `TOKEN_URL` with `client_credentials` grant; on
    success stores `access_token` and computes `_token_expiry` as
    `now + expires_in - 60` (60-second safety margin). Raises via `raise_for_status()`
    on failure.
  - `_get_token(self)` — returns cached token, re-authenticating first if `None` or
    expired.
  - `_headers(self)` — builds the `Authorization: Bearer`, `X-DIGIKEY-Client-Id`,
    `Accept` header dict.
  - `_make_request(self, method, url, **kwargs)` — issues the HTTP request; on a 401
    response, clears the cached token and retries once with a freshly fetched token.
  - `lookup(self, part_number)` — **primary public entry point.** Tries
    `_lookup_product_details` first; if that returns a `PartDetails` with `.error` set,
    falls back to `_lookup_keyword_search`.
  - `_lookup_product_details(self, part_number)` — GETs
    `PRODUCT_DETAILS_URL` (exact-match endpoint, part number URL-quoted). Maps
    404/400 → `error="Part not found"`, 429 → `error="Rate limit exceeded"`, any
    `requests.RequestException` → `error=str(e)`. On success, delegates to
    `_parse_response`.
  - `_lookup_keyword_search(self, part_number)` — POSTs `KEYWORD_SEARCH_URL` with
    `{Keywords, RecordCount=10, RecordStartPosition=0, ExcludeMarketPlaceProducts=True}`.
    Picks the first product whose `ManufacturerPartNumber` matches `part_number`
    case-insensitively, else falls back to the first result overall. Same error-mapping
    pattern as above (no explicit 404 case here — relies on `products` being empty →
    `"Part not found"`).
  - `search_alternatives(self, keyword, limit=20)` — POSTs the same keyword-search
    endpoint with a configurable `limit`, returns the raw `Products` list (or `[]` on
    any exception, logged to stdout). **Not currently invoked elsewhere in this
    codebase** — alternate detection is done purely via DB grouping in
    `detect_alternates.py`.
  - `_parse_response(self, part_number, data)` — the response normalizer. Unwraps
    `data["Product"]` (or uses `data` directly for the keyword-search shape). Picks the
    `ProductVariations` entry whose `PackageType.Name` contains `"Cut Tape"`, else the
    first variation, else `None`. Builds a `PriceBreak` list from that variation's
    `StandardPricing`. Derives `unit_price` from the product level, falling back to the
    first price break's price if absent. Handles `Description` as either a dict
    (`ProductDescription`/`DetailedDescription`) or a plain string. Handles
    `ProductStatus` as either a dict (`.Status`) or plain string. Pulls `moq`/`spq` off
    the chosen variation (`MinimumOrderQuantity`/`StandardPackage`), `distributor_pn`
    off `DigiKeyProductNumber`, and formats `lead_time` as `"<N> weeks"` from
    `ManufacturerLeadWeeks`. Returns a fully populated `PartDetails`.

**Internal execution flow:** `lookup()` → exact-match GET first (cheaper, single
result) → on any error condition, POST keyword search and best-match selection. Token
refresh is transparent to callers via `_get_token`/`_make_request`'s 401-retry. No
rate-limit backoff/retry beyond surfacing `"Rate limit exceeded"` as an `error` string
on the returned `PartDetails` (the caller in `enrichment.py` treats this the same as
any other lookup failure — logs and moves on).

**Configuration usage:** Takes `client_id`/`client_secret` as constructor arguments
(sourced from `DIGIKEY_CLIENT_ID`/`DIGIKEY_CLIENT_SECRET` env vars by the caller in
`enrichment.py`, populated via `.env`). No other configuration.

**Related files:** `models.py` (`PartDetails`, `PriceBreak`), `enrichment.py` (sole
caller via `enrich_digikey`), `.env` (credential source).

---

## `element14.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\element14.py`

**Purpose:** Dual-role module — (1) a library of module-level functions used by
`enrichment.py` for programmatic Element14/Farnell/Newark part lookups, and (2) a
fully independent standalone CLI tool (`python element14.py <part_number>` or
`--file <excel>`) for interactive or bulk-Excel part verification, complete with its
own styled-output Excel writer. This is the largest file in the package (605 lines) and
the only one with a real `__main__` CLI beyond a simple `input()` prompt.

**Responsibilities:**
- Read `ELEMENT14_API_KEY` / `ELEMENT14_STORE` from environment and validate the key is
  present and not the placeholder value.
- Query the element14 Catalog Products API by manufacturer part number or by
  element14/Farnell/Newark SKU.
- Parse the API's product JSON into a flat `info` dict (pricing tiers, MOQ, SPQ,
  release/inventory/stock status codes translated to human labels, datasheet URL,
  RoHS).
- Provide CLI conveniences: single-part lookup with formatted console display,
  bulk lookup from an input Excel file (with a "Present or not" column plus 16 detail
  columns appended, color-coded Yes/No/EOL/Not-Recommended highlighting), saved to a
  new `<name>_results.xlsx` file.

**Dependencies:** `os`, `sys`, `time` (unused — imported but not called), `json`
(unused — imported but not called), `requests`; `dotenv.load_dotenv`; `openpyxl`
(`load_workbook`, `Workbook` (unused — imported but not instantiated), `Font`,
`PatternFill`, `Alignment`, `Border`, `Side`).

**Public interfaces:**

- Module-level constants: `API_BASE_URL`, `RELEASE_STATUS` (dict: releaseStatusCode →
  label, e.g. `2: "Active"`, `6: "End of Life (EOL)"`, `7: "Obsolete"`),
  `INVENTORY_STATUS` (inventoryCode → label), `STOCK_STATUS` (stock.status code →
  label).

- `get_api_key()` — reads `ELEMENT14_API_KEY`; if empty or equal to the literal
  placeholder `"your_api_key_here"`, prints an error and calls `sys.exit(1)`. **This is
  the function `enrichment.enrich_element14` explicitly pre-checks around**, since
  `SystemExit` bypasses `except Exception`.

- `get_store()` — reads `ELEMENT14_STORE`, defaulting to `"www.newark.com"`.

- `search_by_part_number(part_number, search_type="manuPartNum")` — GETs
  `API_BASE_URL` with `term=<search_type>:<part_number>`, store info, and
  `responseGroup=large`; returns parsed JSON. `search_type` can be `"manuPartNum"`
  (default) or `"id"` (SKU search). No try/except here — `resp.raise_for_status()` can
  raise, caught by callers.

- `search_alternatives(keyword)` — GETs with `term=any:<keyword>`, 20 results; returns
  the `products` list from `keywordSearchReturn`, or `[]` on any exception (logged to
  stdout). **Not called anywhere else in this codebase** (alternate detection is DB-only
  in `detect_alternates.py`, same situation as DigiKey's unused
  `search_alternatives`).

- `get_price_for_qty(qty, price_breaks)` — walks a list of `{from, unit_price}` dicts,
  returning the unit price of the highest `from` tier that is `<= qty`, or `None` if
  none qualify or all entries are malformed (silently swallowed via bare `except`).
  Used only by the CLI bulk-lookup path for extended-price calculation, not by
  `enrichment.py`.

- `parse_part_info(product)` — **the function `enrichment.enrich_element14` calls
  directly.** Extracts SKU, translated MPN, manufacturer, description; builds a
  `price_breaks` list from `product["prices"]` and sets `Unit Price` to the first
  tier's cost (or `"N/A"`); MOQ from `translatedMinimumOrderQuality`; SPQ from
  `packSize` (falling back to `unitOfMeasure`); release status via
  `RELEASE_STATUS` lookup; inventory status via `INVENTORY_STATUS` lookup; stock level
  and status via the `stock` sub-object and `STOCK_STATUS` lookup; lead time from
  `stock.leastLeadTime`; raw `productStatus`; first datasheet URL if present; RoHS
  status code. Returns the flat `info` dict consumed by `enrichment.enrich_element14`.

- `display_part_info(info, qty=1)` — pretty-prints a single part's `info` dict to
  stdout for the interactive CLI, including an extended-price calculation.

- `lookup_part(part_number, search_type="manuPartNum", qty=1)` — CLI single-lookup
  orchestrator: calls `search_by_part_number`, unwraps the result shape, prints
  `display_part_info` for each product found (catches `HTTPError` and
  `ConnectionError` explicitly for friendly CLI messages).

- `read_part_numbers_from_excel(filepath)` — CLI helper: opens a workbook read-only,
  locates a "Part Number"-ish header column (accepts `"part number"`, `"part_number"`,
  `"partnumber"`, `"mpn"`, `"mfr part number"`) and an optional `"qty"`/`"quantity"`
  column, returns a list of `(part_number, qty)` tuples. Exits via `sys.exit(1)` if no
  part-number column is found.

- `bulk_lookup_to_excel(input_filepath)` — CLI bulk-mode orchestrator: loads the
  workbook editable, finds/creates a "Present or not" column, appends 16 styled detail
  columns (SKU through Datasheet URL), loops every data row doing a live
  `search_by_part_number` call per row, writes Yes/No/Error status with color coding
  (green/red/yellow fills for found/not-found/not-recommended, red fill override for
  EOL/Obsolete), computes extended price via `get_price_for_qty`, auto-fits new column
  widths, and saves to `<original_name>_results.xlsx` alongside the input file. Returns
  the output path.

- `main()` — CLI argument parser/dispatcher: no-args prints usage; `--file <path>`
  routes to `bulk_lookup_to_excel`; otherwise treats `sys.argv[1]` as a part number with
  optional `--sku` (search by SKU instead of MPN) and `--qty N` flags, routing to
  `lookup_part`.

- `if __name__ == "__main__": main()`.

**Internal execution flow (as used by the MCP server):** Only `search_by_part_number`
and `parse_part_info` are actually exercised by the live enrichment path
(`enrichment.enrich_element14`) — everything else in this file (CLI, bulk Excel,
alternates search, price-for-qty) is dead code from the MCP server's perspective, but
remains fully functional as a standalone script for manual/offline part verification
(this is almost certainly the origin of `Distributor_Verification_Output.xlsx` /
`_filled.xlsx` in this same folder — see below).

**Configuration usage:** `ELEMENT14_API_KEY` (required, validated, `sys.exit(1)` if
missing/placeholder), `ELEMENT14_STORE` (optional, defaults to `www.newark.com`) — both
read via `os.getenv` after this module's own `load_dotenv()` call at import time (so
this module can also be run completely standalone without relying on
`mcp_server.py` having loaded the environment first).

**Related files:** `enrichment.py` (caller of `search_by_part_number` /
`parse_part_info`), `.env` (credential/store source), the two `.xlsx` files in this
folder are plausible artifacts of this file's standalone bulk-lookup CLI mode
(**Inference:** their exact provenance/generation command wasn't confirmed from code
alone, but the column-header conventions in `Distributor_Verification_Output_filled.xlsx`
and the `bulk_lookup_to_excel` output shape are consistent with each other; the
"template" role of `Distributor_Verification_Output.xlsx` in `export_bom.py`, however,
points to `C:\Users\ADMIN\Documents\SRIM\Tools\distributor_pricing\` — note: **no** `I n D`
segment — a different, older path than this file's own folder, so the exact
relationship between these two on-disk `.xlsx` files and `export_bom.py`'s template is
not fully certain).

---

## `mouser_client.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\mouser_client.py`

**Purpose:** Self-contained HTTP client for the Mouser Search API (part-number search
variant), normalizing responses into the shared `PartDetails` model.

**Responsibilities:**
- POST a part-number search request to Mouser's v2 API using an API key passed as a
  query parameter.
- Handle Mouser's error-array response shape (`data.Errors`) as a failure case distinct
  from HTTP-level errors.
- Parse price breaks (stripping currency symbols/formatting from price strings via
  regex), stock (parsed out of a free-text `Availability` string), MOQ/SPQ, and other
  fields into `PartDetails`.

**Dependencies:** `re`, `requests` (third-party). Imports `PartDetails`, `PriceBreak`
from `models.py` with the same `try/except ImportError` fallback pattern as
`digikey_client.py`.

**Public interfaces:**

- `class MouserClient`
  - `__init__(self, api_key: str)` — stores the API key, creates a `requests.Session`.
  - `lookup(self, part_number: str) -> PartDetails` — **primary public entry point.**
    POSTs to `SEARCH_URL?apiKey=<key>` with body
    `{"SearchByPartRequest": {"mouserPartNumber": part_number, "partSearchOptions": ""}}`.
    Maps HTTP 429 → `error="Rate limit exceeded"`. Checks `data["Errors"]`; if
    non-empty, joins all `Message` fields (or `str(e)` fallback) into one `error`
    string. If `SearchResults.Parts` is empty, returns `error="Part not found"`.
    Otherwise parses the first part via `_parse_part`. Catches
    `requests.RequestException` generically, mapping to `error=str(e)`.
  - `_parse_part(self, part_number, part: dict) -> PartDetails` — builds `PriceBreak`
    list from `part["PriceBreaks"]`, stripping non-numeric characters from each
    `Price` string via `re.sub(r"[^\d.]", "", price_str)` before `float()` conversion.
    Sets top-level `unit_price`/`currency` from the first price break if present.
    Parses stock via `_parse_stock`. Maps `MouserPartNumber` → `distributor_pn`,
    `Min`/`Mult` → `moq`/`spq` (via `_safe_int`), `LeadTime`, `LifecycleStatus`,
    `DataSheetUrl`, `ProductDetailUrl` → `product_url`.
  - `_parse_stock(availability: str) -> int | None` (static) — regex-searches for
    `"<digits> In Stock"` (comma-tolerant, case-insensitive) and returns the parsed
    int; if no digit match but the string contains `"in stock"` (case-insensitive),
    returns `0`; otherwise returns `None`.
  - `_safe_int(value) -> int | None` (static) — `int(value)`, returning `None` on
    `ValueError`/`TypeError` or if `value is None`.

**Internal execution flow:** Single-request lookup, no retry/backoff logic (unlike
DigiKey's 401-retry), no OAuth (a static API key passed as a URL query parameter on
every call). Errors — HTTP-level, Mouser's own `Errors` array, empty results, and
network exceptions — all collapse into `PartDetails.error` strings that
`enrichment.enrich_mouser` treats uniformly as "no data available, skip this
distributor for this part."

**Configuration usage:** Takes `api_key` as a constructor argument (sourced from
`MOUSER_API_KEY` env var by the caller in `enrichment.py`).

**Related files:** `models.py` (`PartDetails`, `PriceBreak`), `enrichment.py` (sole
caller via `enrich_mouser`), `.env` (credential source).

---

## `models.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\models.py`

**Purpose:** Shared, distributor-agnostic data model used by all three distributor
clients (`digikey_client.py`, `element14.py` indirectly via its own `info` dict shape,
and `mouser_client.py`) to represent a single part's pricing/availability lookup
result.

**Responsibilities:**
- Define `PriceBreak` and `PartDetails` as plain `@dataclass`es so client code has a
  consistent, typed shape to populate regardless of which distributor's API is being
  called.
- Provide a `to_dict()` convenience method for flattening a `PartDetails` (including
  its price breaks) into a spreadsheet/report-friendly flat dict — used for ad hoc
  reporting rather than by the DB-write path in `enrichment.py` (which reads individual
  attributes off `PartDetails` directly instead).

**Dependencies:** `dataclasses` (`dataclass`, `field`), `typing.Optional` (stdlib
only — no third-party dependencies).

**Public interfaces:**

- `@dataclass class PriceBreak` — fields: `quantity: int`, `unit_price: float`,
  `currency: str = "USD"`.

- `@dataclass class PartDetails` — fields: `part_number: str` (required), plus
  optional/defaulted: `manufacturer`, `description`, `distributor`, `distributor_pn`
  (all `str`, default `""`), `unit_price: Optional[float] = None`,
  `currency: str = "USD"`, `moq: Optional[int]`, `spq: Optional[int]`,
  `stock_quantity: Optional[int]`, `lead_time: str`, `lifecycle_status: str`,
  `datasheet_url: str`, `product_url: str`, `price_breaks: list[PriceBreak]`
  (via `field(default_factory=list)`), `error: str = ""` (empty string means success —
  every client checks `if result.error:` as its failure branch).
  - `to_dict(self) -> dict` — returns a dict with human-readable keys ("Part Number",
    "Manufacturer", "Description", "Distributor", "Distributor PN", "Unit Price",
    "Currency", "MOQ", "SPQ", "Stock", "Lead Time", "Lifecycle Status",
    "Datasheet URL", "Product URL", "Price Breaks" (joined as
    `"<qty>+: <currency> <price>; ..."`), "Error"). **Not called anywhere else in this
    package** — `enrichment.py` reads `PartDetails` attributes directly rather than via
    `to_dict()`.

**Internal execution flow:** N/A — pure data container, no control flow of its own.

**Configuration usage:** None.

**Related files:** `digikey_client.py`, `mouser_client.py` (both construct
`PartDetails`/`PriceBreak` instances directly), `enrichment.py` (consumes the
attributes).

---

## `detect_alternates.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\detect_alternates.py`

**Purpose:** Implements Tool 3. Finds CPNs (customer/company part numbers) in an
already-enriched `processed_bom_items` that map to more than one distinct MPN
(manufacturer part number) — i.e. candidate alternate-manufacturer situations — and
records every (cpn, mpn) pair for such CPNs into `update_alternatives` for a human to
later flag one as `preferred_flag=TRUE`.

**Responsibilities:**
- Lazily create the `update_alternatives` table if it doesn't exist yet
  (`CREATE TABLE IF NOT EXISTS`), defining its full schema in-code (this is the only
  place in this folder that defines that table's DDL — there is no local
  `duckdb_schema.py` copy).
- Guard against being run twice for the same `rfq_id` by checking for existing rows
  first and returning a `status: "failed"` response rather than inserting duplicates.
- Group `processed_bom_items` rows by `cpn` (via pandas `groupby(...).nunique()`),
  identify CPNs with more than one distinct `mpn`, and insert one row per (cpn, mpn)
  pair for every such CPN into `update_alternatives`, all `preferred_flag=FALSE`
  initially, inside an explicit transaction (`BEGIN`/`COMMIT`/`ROLLBACK` on exception).

**Dependencies:** `duckdb` (third-party); local `config.DB_PATH`. Uses DuckDB's
`fetchdf()` to get a pandas DataFrame (implicit `pandas` dependency, consistent with
`requirements.txt`).

**Public interfaces:**

- `_ensure_alternatives_table(conn)` — issues the `CREATE TABLE IF NOT EXISTS
  update_alternatives (id UUID DEFAULT gen_random_uuid(), rfq_id VARCHAR(100),
  bom_item_id UUID, cpn VARCHAR, mpn VARCHAR, mfr VARCHAR, preferred_flag BOOLEAN
  DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
  DEFAULT CURRENT_TIMESTAMP)` DDL.

- `detect_alternates(rfq_id)` — **the function `mcp_server.detect_alternates` calls
  (aliased as `_detect_alternates`).**
  - Strips `rfq_id` to string.
  - Opens a `with duckdb.connect(DB_PATH) as conn:` context.
  - Calls `_ensure_alternatives_table`.
  - Checks `SELECT COUNT(*) FROM update_alternatives WHERE rfq_id = ?`; if `> 0`,
    returns `{"status": "failed", "error": f"Alternates already detected for RFQ
    {rfq_id}", "existing_rows": existing_count}` — **this makes the tool
    non-idempotent by design**: it must be re-run only after the existing rows for
    that RFQ are cleared (no code path in this package clears them automatically).
  - Queries `bom_item_id, cpn, mpn, mfr` from `processed_bom_items` for the RFQ where
    `cpn IS NOT NULL AND cpn != ''`, as a DataFrame.
  - If the DataFrame is empty, returns `{"status": "success", "cpns_flagged": 0,
    "alternates_found": 0}` immediately (no table insert).
  - Computes `mpn_counts = df.groupby("cpn")["mpn"].nunique()`; `duplicate_cpns` = CPNs
    where this count is `> 1`.
  - If none, returns the same zero-count success shape.
  - Otherwise, in a transaction, for every duplicate CPN and every row in that CPN's
    group, inserts one `update_alternatives` row (with a fresh `gen_random_uuid()` for
    `id`), incrementing an `inserted` counter.
  - Returns `{"status": "success", "cpns_flagged": len(duplicate_cpns),
    "alternates_found": inserted}`.

**Internal execution flow:** Pure DB/pandas logic — no distributor API calls at all
(confirmed by the docstring: "Performs no supplier lookups — pricing is already
present on processed_bom_items from distributor_pricing's enrich_bom"). The
alternate-detection logic itself is a simple same-CPN/different-MPN group-by, not a
fuzzy or cross-reference lookup against any distributor's "alternates" API (contrast
with the unused `search_alternatives` functions in `digikey_client.py` and
`element14.py`, which would do keyword-based external alternate search but are not
wired up here).

**Configuration usage:** `config.DB_PATH` only.

**Related files:** `config.py`, `apply_alternatives.py` (downstream consumer of the
`update_alternatives` rows this file creates), `mcp_server.py` (caller).

**Inference:** The "must run after enrich_bom" ordering constraint is stated in both
the module docstring and the `mcp_server.py` wrapper's docstring, but is not
technically enforced by this function itself — it only requires `cpn`/`mpn`/`mfr` to be
populated, which could in principle happen before enrichment too (those columns look
like they originate from earlier BOM-processing steps, not from `enrich_bom`'s own
column set). The stated ordering is therefore a workflow/process convention rather than
a hard runtime dependency enforced by this code.

---

## `apply_alternatives.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\apply_alternatives.py`

**Purpose:** Implements Tool 4. Consumes human review decisions recorded in
`update_alternatives` (specifically, the `preferred_flag` column) and prunes
`processed_bom_items` down to just the preferred MPN per CPN.

**Responsibilities:**
- Load all `update_alternatives` rows for the given `rfq_id`.
- Validate that every CPN present has **exactly one** row flagged
  `preferred_flag=TRUE` — if any CPN has zero or more than one, abort the entire
  operation with no DB changes and report every offending CPN.
- If validation passes, delete every `processed_bom_items` row for that CPN whose
  `mpn` is not the preferred one, inside a single transaction across all CPNs.

**Dependencies:** `duckdb` (third-party); local `config.DB_PATH`. Uses `fetchdf()`
(pandas).

**Public interfaces:**

- `apply_alternatives(rfq_id)` — **the function `mcp_server.apply_alternatives` calls
  (aliased as `_apply_alternatives`).**
  - Strips `rfq_id` to string.
  - Opens `with duckdb.connect(DB_PATH) as conn:`.
  - Loads `cpn, mpn, preferred_flag` from `update_alternatives` for the RFQ as a
    DataFrame (`decisions_df`).
  - If empty, returns `{"status": "success", "message": "No alternate selections
    found."}` (a no-op success, not a failure — distinguishing "nothing to do" from
    "validation failed").
  - For each unique `cpn`, filters to `preferred_flag == True` rows; if the count is
    not exactly 1, records `{"cpn": cpn, "preferred_count": len(...)}` into an
    `invalid` list; otherwise records the single preferred `mpn` into
    `preferred_by_cpn[cpn]`.
  - If `invalid` is non-empty, returns `{"status": "failed", "error": "Each CPN must
    have exactly one preferred_flag=TRUE selection", "invalid_cpns": invalid}` —
    **no deletions occur in this path; the whole call fails atomically before any
    transaction is opened.**
  - Otherwise, opens a transaction; for each `(cpn, preferred_mpn)` pair, executes
    `DELETE FROM processed_bom_items WHERE rfq_id = ? AND cpn = ? AND mpn != ?`,
    accumulating the DuckDB-reported deleted-row count into `mpns_removed`, and
    records `remaining_mpn_by_cpn[cpn] = preferred_mpn`. Commits (or rolls back and
    re-raises on any exception).
  - Returns `{"status": "success", "cpns_processed": len(preferred_by_cpn),
    "mpns_removed": mpns_removed, "remaining_mpn_by_cpn": remaining_mpn_by_cpn}`.

**Internal execution flow:** Validate-then-act, all-or-nothing across CPNs — the
function explicitly favors failing the entire call over applying a partial resolution
(see its own inline comment: "Validate every CPN has exactly one preferred selection
before making any change — fail the whole call rather than apply a partial
resolution"). No distributor API calls (`docstring`: "Never calls DigiKey, Element14,
or Mouser — pricing was already captured during enrichment").

**Configuration usage:** `config.DB_PATH` only.

**Related files:** `config.py`, `detect_alternates.py` (upstream producer of the
`update_alternatives` rows this file consumes), `mcp_server.py` (caller).

**Inference:** `DELETE ... RETURNING` semantics — DuckDB's `DELETE` here is captured
via `.fetchone()[0]` immediately after `execute()`, implying this DuckDB version
returns the deleted row count directly from `execute()` without an explicit
`RETURNING` clause in the SQL text shown. This matches DuckDB's documented behavior of
returning a changed-row count for DML statements; flagged only because it's a slightly
unusual pattern to rely on implicitly rather than via an explicit `RETURNING` clause.

---

## `export_bom.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\export_bom.py`

**Purpose:** Implements Tool 2. Exports the current state of `processed_bom_items` for
an RFQ into a copy of a pre-existing, pre-styled Excel template, matching DB columns to
template header cells by normalized name rather than positional order.

**Responsibilities:**
- Load the full `processed_bom_items` row set for the RFQ into a pandas DataFrame.
- Load a fixed Excel template file with `openpyxl` (preserving all existing styles,
  formatting, and any other sheets).
- Build a mapping from template header-row column index to a normalized DB column
  name, using a small alias table for a few labels whose normalized form doesn't match
  their DB column name (`digikey_price` → `digikey_unit_price`, etc.).
- Clear all data rows (row 2 onward) while leaving the header row and all cell
  formatting/styles untouched.
- Write fresh values into only the columns that matched a DB column; report which DB
  columns had no matching template header (`skipped_columns`).
- Save to a new file (`<template_stem>_filled.xlsx`) — **the original template file is
  never overwritten**, so repeated exports are idempotent with respect to the template.

**Dependencies:** `datetime`, `re`, `uuid`, `pathlib.Path` (stdlib); `duckdb`, `numpy`,
`openpyxl`, `pandas` (third-party); local `config.DB_PATH`.

**Public interfaces:**

- Module constant `TEMPLATE_PATH` — **hardcoded** to
  `C:\Users\ADMIN\Documents\SRIM\Tools\distributor_pricing\Distributor_Verification_Output.xlsx`.
  Note this path does **not** include the `I n D` segment that the actual running
  folder (`Tools\I n D\distributor_pricing\`) has. This constant is not derived from
  `__file__` or any relative path — it is a hardcoded absolute string literal.
  **Confirmed broken:** the path without `I n D` does **not** exist on this machine
  (verified directly while writing this document) — the real template file lives at
  `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\Distributor_Verification_Output.xlsx`
  instead, i.e. right next to `export_bom.py` itself. As currently written, calling
  `export_enriched_bom` will hit this function's own `FileNotFoundError` check and
  fail every time on this machine, unless `TEMPLATE_PATH` is corrected (e.g. to
  `Path(__file__).parent / "Distributor_Verification_Output.xlsx"`) before this tool
  is activated. This is a confirmed, currently-broken bug, not a hypothetical.

- Module constant `HEADER_ALIASES` — dict of 3 entries mapping a few
  human-friendly-but-non-standard normalized header labels to their real DB column
  names (`digikey_price`/`element14_price`/`mouser_price` → `*_unit_price`).

- `_to_excel_value(value)` — type-coercion helper so openpyxl never receives a type it
  can't serialize: `None` passes through; `uuid.UUID` → `str`; `pd.Timestamp` → Python
  `datetime` (or `None` if `pd.isna`); any `numpy` generic scalar → native Python via
  `.item()`; float NaN (self-inequality trick `value != value`) → `None`; native
  `date`/`datetime`/`str`/`int`/`float`/`bool` pass through unchanged; anything else
  falls back to `str(value)`.

- `_normalize(label)` — lowercases, strips, and collapses any run of non-alphanumeric
  characters to a single underscore (regex `[^a-z0-9]+` → `_`), then strips leading/
  trailing underscores. E.g. `"DigiKey Unit Price"` → `"digikey_unit_price"`.

- `_build_header_map(header_row)` — iterates the template's first row's cells; for
  each non-empty header cell, normalizes its text and looks it up in
  `HEADER_ALIASES` (falling back to the normalized text itself if not aliased);
  returns `(header_map, matched_headers)` where `header_map` is
  `{1-indexed column index: db_column_name}` and `matched_headers` is a parallel list
  of `(original_header_text, resolved_db_column)` pairs (this second return value is
  computed but **not used** by `export_bom` beyond being discarded — dead/unused
  return data at the call site, though still potentially useful for debugging).

- `export_bom(rfq_id)` — **the function `mcp_server.export_enriched_bom` calls
  directly.**
  - Strips `rfq_id`.
  - Queries `SELECT * FROM processed_bom_items WHERE CAST(rfq_id AS VARCHAR)=?` into a
    DataFrame.
  - Raises `FileNotFoundError` if `TEMPLATE_PATH` doesn't exist.
  - Loads the template workbook, gets its active sheet, builds the header map from row
    1.
  - Computes `matched_db_columns` (intersection of header-map values and actual
    DataFrame columns) and `skipped_db_columns` (DB columns with no matching header).
  - Clears every cell value (not formatting) in rows 2 through the template's existing
    `max_row`.
  - Converts the DataFrame to `records` (list of dicts) and writes each record's
    matched fields into the corresponding template columns starting at row 2, applying
    `_to_excel_value` to every written value.
  - Saves to `<TEMPLATE_PATH.stem>_filled.xlsx` in the same directory as the template
    (i.e. `Distributor_Verification_Output_filled.xlsx`).
  - Prints a summary (rows written, columns matched/skipped, listing skipped column
    names, output path).
  - Returns `{"status": "success", "rows_written": N, "columns_matched": N,
    "columns_skipped": N, "skipped_columns": [...], "output_file": "<path str>"}`.

- `if __name__ == "__main__":` block — interactive CLI: prompts for RFQ ID, calls
  `export_bom`, prints the raw result dict.

**Internal execution flow:** This is a "fill-in-place" export, not a from-scratch
workbook generator — it depends entirely on a pre-existing, pre-formatted template
file living at a fixed path, and only ever adds a `_filled` suffix copy. If the
template's row count is smaller than the number of RFQ records, rows beyond
`max_row` from the original template will still be written by the write loop
(`row_offset + 2` can exceed the original `max_row` used for clearing) — openpyxl
will happily extend the sheet, but those new rows will lack whatever
formatting/styling the original template rows had, since only rows 2..max_row were
ever "prepared" (cleared) from the template; rows beyond that are entirely new,
unstyled cells. **Inference:** this edge case (RFQ with more line items than the
template has template rows) was not tested — flagged as a potential formatting gap
for large RFQs.

**Configuration usage:** `config.DB_PATH` for the query; `TEMPLATE_PATH` hardcoded
constant (see caveat above) for the output template — not sourced from `.env` or any
environment variable.

**Related files:** `config.py`, `mcp_server.py` (caller),
`Distributor_Verification_Output.xlsx` (required input template — generated output,
excluded from this doc's per-file treatment per the task's exclusion rule, but
referenced here because it's a hard runtime dependency),
`Distributor_Verification_Output_filled.xlsx` (this function's own prior output,
likewise excluded).

---

## `requirements.txt`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\requirements.txt`

**Purpose:** Pinned (by name only, no version pins) dependency manifest for this
package.

**Responsibilities:** Declares the 7 third-party packages this server needs:

```
fastmcp
duckdb
pandas
numpy
requests
openpyxl
python-dotenv
```

This matches exactly what the task brief expected and what was observed in every
module's `import` statements across this package (`fastmcp` in `mcp_server.py`;
`duckdb` everywhere DB access happens; `pandas`/`numpy` in `export_bom.py` and
implicitly via `fetchdf()` in `detect_alternates.py`/`apply_alternatives.py`;
`requests` in `digikey_client.py`/`element14.py`/`mouser_client.py`; `openpyxl` in
`element14.py`/`export_bom.py`; `python-dotenv` in `mcp_server.py`/`element14.py`/
`enrichment.py`'s `__main__`).

**Dependencies:** N/A (this file declares dependencies; it has none itself).

**Public interfaces:** N/A (not a Python module).

**Internal execution flow:** N/A.

**Configuration usage:** None — no version pins, no extras, no `-r` includes.

**Related files:** Every `.py` file in this package indirectly depends on this
manifest being installed into whatever Python environment runs `mcp_server.py`.

**Inference:** No version pins means reproducibility across environments/machines is
not guaranteed by this file alone — if this server is ever activated for production
use, pinning versions (or generating a lockfile) would reduce the risk of a
distributor-client-breaking dependency upgrade (e.g. a `requests` or `openpyxl` major
version bump) going unnoticed.

---

## `.env`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\.env`

**Purpose:** Local environment-variable file supplying API credentials and one
configuration value, loaded via `python-dotenv`'s `load_dotenv()` (called in
`mcp_server.py` at import time, and defensively again in `element14.py` and in
`enrichment.py`'s `__main__` block).

**Responsibilities:** Supplies the following environment variables (values
intentionally **not** reproduced here — credentials are configured via this `.env`
file and should not be copied into documentation or logs):

- `DIGIKEY_CLIENT_ID` — consumed by `enrichment.enrich_distributors` when
  constructing the `DigikeyClient`.
- `DIGIKEY_CLIENT_SECRET` — same.
- `MOUSER_API_KEY` — consumed by `enrichment.enrich_distributors` when constructing
  the `MouserClient`.
- `ELEMENT14_API_KEY` — consumed by `element14.get_api_key()` (and pre-checked by
  `enrichment.enrich_element14` before it's used).
- `ELEMENT14_STORE` — consumed by `element14.get_store()`; controls which
  Farnell/Newark/element14 storefront is queried (this `.env` sets it to the Newark
  storefront).
- `MYSQL_PASSWORD` — present in this file but **not referenced by any `.py` file in
  this package** (no `mysql`, `pymysql`, `sqlalchemy`, or similar import anywhere in
  this folder's source). **Inference:** this is likely a leftover/shared credential
  from another tool in the broader `SRIM\Tools\I n D` codebase that happens to share
  this `.env` file, or a vestige from before this package standardized on DuckDB —
  it appears to be dead configuration from this package's own point of view.

**Dependencies:** N/A (not a Python module; consumed via `python-dotenv`).

**Public interfaces:** N/A.

**Internal execution flow:** N/A.

**Configuration usage:** This *is* the configuration source for all three distributor
clients plus the Element14 store selector. Credentials are configured via `.env` in
this folder; no secret values are reproduced in this document.

**Related files:** `mcp_server.py`, `enrichment.py`, `element14.py` (all call
`load_dotenv()` and/or read these variables via `os.getenv`).

---

## `__init__.py`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\__init__.py`

**Purpose:** Empty marker file (0 bytes) making `distributor_pricing` importable as a
Python package (e.g. `from distributor_pricing.models import PartDetails`), which is
exactly the fallback import path used in both `digikey_client.py` and
`mouser_client.py`'s `try/except ImportError` blocks.

**Responsibilities:** None beyond package-marker semantics — the file is completely
empty.

**Dependencies:** None.

**Public interfaces:** None.

**Internal execution flow:** N/A.

**Configuration usage:** None.

**Related files:** Enables the `from distributor_pricing.models import ...` /
`from distributor_pricing.models import ...` fallback imports in `digikey_client.py`
and `mouser_client.py`, which activate when this folder is imported as a subpackage
of some larger project rather than run with itself as the working directory.

---

## `.claude/settings.local.json`

**File path:** `C:\Users\ADMIN\Documents\SRIM\Tools\I n D\distributor_pricing\.claude\settings.local.json`

**Purpose:** Local Claude Code permission allowlist scoped to this folder, recording
previously-approved Bash command patterns so future sessions working in this directory
don't re-prompt for the same low-risk commands.

**Responsibilities:** Declares an `permissions.allow` array whitelisting 6 specific
Bash command patterns observed from prior work in this folder:
- `cd /c`
- `find . -type d -name "dify"`
- `python -m py_compile bom_processing.py server.py`
- a `python "<scratchpad path>\test_consolidation.py"` invocation referencing a
  session-specific temp path under a differently-named scratchpad directory
  (`C--Users-ADMIN-Documents-SRIM-Tools-distributor-pricing`, again missing the
  `I n D` segment — consistent with the same older-path pattern seen in
  `export_bom.py`'s `TEMPLATE_PATH`)
- `python -c ' *` (wildcard-prefixed inline Python execution)
- `python -m py_compile export_bom.py`
- `python -m py_compile export_bom.py server.py`

**Dependencies:** None (consumed by the Claude Code CLI harness, not by this
package's own Python code).

**Public interfaces:** N/A (JSON configuration, not code).

**Internal execution flow:** N/A.

**Configuration usage:** Read by the Claude Code tool harness only — has no effect on
`mcp_server.py`'s runtime behavior.

**Related files:** None within this package's own execution path; purely
tooling/session metadata. The repeated references to `server.py` (rather than
`mcp_server.py`) and `bom_processing.py` (a filename that doesn't exist in this
folder's current file list) in the allowlisted commands suggest this file predates a
rename or reorganization — **Inference:** `server.py`/`bom_processing.py` were
possibly earlier names for what is now `mcp_server.py`/some enrichment-related module,
but this wasn't independently confirmed since those files don't exist in the current
folder to inspect.

---

## Generated Excel outputs

The following files exist in this folder but are excluded from full per-file
documentation per the task's scope (generated `.xlsx` outputs, not source):

- `Distributor_Verification_Output.xlsx` — the input template that `export_bom.py`'s
  hardcoded `TEMPLATE_PATH` is meant to point at (though see the path-mismatch caveat
  in the `export_bom.py` section above regarding the missing `I n D` segment in that
  constant).
- `Distributor_Verification_Output_filled.xlsx` — plausible prior output of
  `export_bom.export_bom()` (`<template_stem>_filled.xlsx` naming matches exactly).
- `Enriched_BOM_456.xlsx` — plausible manual/ad hoc export or renamed copy of a
  `_filled.xlsx` output for a specific RFQ (`456`); no code in this package writes a
  file with this exact naming pattern, so its exact origin is not confirmed from
  source alone.

`__pycache__/` and `.git/` are likewise excluded (compiled bytecode cache and VCS
metadata respectively; this folder is not itself a git repository root based on the
directory listing obtained for this document, though `.git` was excluded from scope
regardless per the task instructions).
