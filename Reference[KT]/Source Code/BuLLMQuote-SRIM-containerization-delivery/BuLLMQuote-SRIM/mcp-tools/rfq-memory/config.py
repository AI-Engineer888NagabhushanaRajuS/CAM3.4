"""Config for the Cognee-backed RFQ chat memory service.

Reuses fastmcp-router's own db.py (Postgres connections, get_active_version,
versioned_key) and auth.py (JWT scheme) directly rather than duplicating
either -- see plan §0/§8: this service must never re-implement the JWT
scheme or invent a second Postgres-connection convention. fastmcp-router is
a sibling directory of this one under the repo root, so it's added to
sys.path the same way mcp-tools/gerber-integration/config.py already
reaches mcp-tools/shared/db_config.py.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

# Loads mcp-tools/rfq-memory/.env (gitignored -- see .gitignore's existing
# .env/.env.* patterns) if present, same convention already used by
# mcp-tools/distributor-pricing/mcp_server.py for its own API keys. Silently
# does nothing if the file doesn't exist -- never required, only a
# convenience for secrets that shouldn't live in shell profiles/manage_backend.py.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent / ".env")

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent  # BuLLMQuote-SRIM
_FASTMCP_ROUTER_DIR = _REPO_ROOT / "fastmcp-router"

sys.path.insert(0, str(_FASTMCP_ROUTER_DIR))

import db  # noqa: E402  (fastmcp-router/db.py -- Postgres + version helpers)
import auth  # noqa: E402  (fastmcp-router/auth.py -- JWT scheme, reused unmodified)

# Re-exported so callers in this service import everything from one place.
FILE_METADATA_DB_URL = db.FILE_METADATA_DB_URL
get_active_version = db.get_active_version
verify_token = auth.verify_token

# ---------------------------------------------------------------------------
# Network topology (plan §0.B -- two separate listeners, not one shared port)
# ---------------------------------------------------------------------------
# Chat routes (JWT-required): bound to this machine's stable NetBird mesh
# IP (not a physical LAN IP, which changes -- see manage_backend.py's own
# SERVICES entries, all switched to this same convention for the same
# reason: binding to one specific LAN IP means the process refuses
# connections when that IP no longer exists on the host).
CHAT_HOST = os.environ.get("RFQ_MEMORY_CHAT_HOST", "100.121.36.255")
CHAT_PORT = int(os.environ.get("RFQ_MEMORY_CHAT_PORT", "8108"))

# Ingest/reset routes: loopback-only, genuinely unreachable off this host --
# not "unauthenticated by convention" but actually unroutable from the LAN.
# Only same-host processes (fastapi_router.py, upload_server.py,
# hitl_router.py) can ever reach this listener.
INTERNAL_HOST = os.environ.get("RFQ_MEMORY_INTERNAL_HOST", "127.0.0.1")
INTERNAL_PORT = int(os.environ.get("RFQ_MEMORY_INTERNAL_PORT", "8109"))

# ---------------------------------------------------------------------------
# Ollama / Cognee LLM+embedding config -- reuses the platform's existing
# Ollama dependency (already health-checked by manage_backend.py's
# EXTERNAL_DEPENDENCIES at http://localhost:11434/api/tags). No second LLM
# provider, no new API key. Same env-var-with-dev-fallback convention as
# JWT_SECRET/MCP_JUNGLE_URL -- override every one of these before deploying
# anywhere off this dev machine.
# ---------------------------------------------------------------------------
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")

# ---------------------------------------------------------------------------
# LLM provider: OpenRouter (cloud) by default when OPENROUTER_API_KEY is
# set, else falls back to local Ollama automatically -- 2026-09-10 decision:
# local Ollama repeatedly hung mid-ingestion on this dev machine (see
# docs/RfqChat/cognee-isolation-investigation.md's ingestion-hang follow-up),
# most plausibly because this one machine also runs 12 other services
# competing for the same resources, whereas a cloud LLM has no such
# contention. OpenRouter is OpenAI-API-compatible -- there is no dedicated
# "openrouter" entry in cognee's own LLMProvider enum (confirmed by reading
# cognee/infrastructure/llm/.../get_llm_client.py directly), so this uses
# LLM_PROVIDER="openai" pointed at OpenRouter's base URL, which its OpenAI
# adapter (a thin litellm/instructor wrapper) accepts transparently.
#
# Switching back to local Ollama is a manual env var change (the explicit,
# simpler option chosen over building real automatic runtime failover --
# cognee's own `fallback_*` config fields do NOT cover network/timeout
# failures, only content-policy rejections, so they would not have actually
# solved the hang either): unset OPENROUTER_API_KEY (or set
# RFQ_MEMORY_LLM_PROVIDER=ollama explicitly) and restart rfq_memory_server.
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
_USE_OPENROUTER = bool(OPENROUTER_API_KEY) and os.environ.get("RFQ_MEMORY_LLM_PROVIDER", "").lower() != "ollama"

if _USE_OPENROUTER:
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
    # Confirmed empirically (not guessed -- a real single-completion test
    # call against this exact config, after the earlier ollama/ollama_chat
    # prefix mixup taught us not to trust an unverified model-string format
    # again): cognee's OpenAIAdapter passes `model` straight through to
    # litellm.acompletion() with no prefixing of its own. litellm then tries
    # to infer the provider from the string BEFORE api_base/api_key are
    # consulted -- passing the bare OpenRouter id ("qwen/qwen-2.5-7b-instruct")
    # makes litellm read "qwen" as the provider name, which doesn't exist in
    # its provider list, and the call fails every retry with a
    # "Provider List: https://docs.litellm.ai/docs/providers" error. Explicitly
    # prefixing with "openai/" forces litellm down its openai-compatible path
    # (honoring the api_base override to openrouter.ai) while still passing
    # "qwen/qwen-2.5-7b-instruct" through as the actual OpenRouter model id.
    LLM_MODEL = os.environ.get("LLM_MODEL", "openai/qwen/qwen-2.5-7b-instruct")
    LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "https://openrouter.ai/api/v1")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", OPENROUTER_API_KEY)
else:
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")
    # Model + endpoint format confirmed against the installed cognee package's
    # actual Ollama adapter (cognee/infrastructure/llm/structured_output_
    # framework/litellm_instructor/llm/ollama/adapter.py): it wraps an
    # AsyncOpenAI client pointed at `endpoint`, so this MUST be Ollama's
    # OpenAI-compatible base path (.../v1), not the bare host -- a bare
    # `http://localhost:11434` 404s. Model prefix is `ollama/`, not
    # `ollama_chat/` (that prefix is litellm's own native-provider convention,
    # a different code path than this adapter). qwen3:8b is the
    # confirmed-working local default -- override via LLM_MODEL for any
    # other deployment's actual pulled model set.
    LLM_MODEL = os.environ.get("LLM_MODEL", "ollama/qwen3:8b")
    LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", f"{OLLAMA_ENDPOINT}/v1")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")  # Ollama ignores this; Cognee's config still wants a non-empty string

EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "ollama")
# NOTE: this model must be `ollama pull`ed on this host before first use --
# a deployment step, not a code change (plan §15/§19). Confirmed via
# OllamaEmbeddingEngine's own default: endpoint is Ollama's native
# /api/embed path, NOT an OpenAI-compatible /v1/embeddings path (unlike the
# LLM_ENDPOINT above -- these two intentionally differ).
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_ENDPOINT = os.environ.get("EMBEDDING_ENDPOINT", f"{OLLAMA_ENDPOINT}/api/embed")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))

# ---------------------------------------------------------------------------
# Cognee's own file-based storage location -- kept inside this repo's own
# database/ convention (see database/README.md) rather than an OS-default
# per-user directory, so it's easy to find/back up/wipe in dev. Still used
# for whatever Cognee leaves file-based (vector store default: LanceDB) even
# though the graph+relational store below is Postgres-backed.
# ---------------------------------------------------------------------------
COGNEE_DATA_ROOT = os.environ.get(
    "COGNEE_DATA_ROOT", str(_REPO_ROOT / "database" / "cognee_data")
)

# ---------------------------------------------------------------------------
# Graph/relational storage -- Postgres-backed (plan revision: Cognee's
# default embedded graph store, Kuzu via a wrapper called "ladybug", fails
# to load on this Windows/Python 3.10 machine -- a native shared library
# (ladybug's C API) is missing and Cognee's own documented fix is a bash
# download script, not something to chase down on Windows. Confirmed
# unfixable without OS-level work; switched to Cognee's Postgres-backed
# graph provider instead (cognee 1.5.4's "postgres_demo" adapter -- Cognee's
# own docs label this a demo/non-production feature, but it needs no native
# library and this platform already runs a healthy Postgres instance).
#
# Uses a DEDICATED, separate database (cognee_memory_db) -- created once via
# a one-off provisioning script, NOT logic_db_2/file_metadata_db_2 -- so
# Cognee's own tables never mix with this platform's application tables.
# Same Postgres server/credentials this dev machine's other 2 databases
# already use (derived from db.LOGIC_DB_URL, never re-typed literally here),
# with COGNEE_DB_* env vars to override any field independently for a real
# deployment.
#
# Provider name confirmed against the actually-installed cognee==1.4.2
# package (requirements.txt pins this exact version -- see its own comment
# for why): valid values are "neo4j", "ladybug", "ladybug-remote", "kuzu",
# "kuzu-remote", "postgres", "neptune", "neptune_analytics", "turso". NOT
# "postgres_demo" -- that key only exists in cognee>=1.5's directory-name-
# based provider dispatch (a version this platform can't use here, since
# it's where the Kuzu/ladybug blocker lives -- see requirements.txt).
# ---------------------------------------------------------------------------
_admin_parts = urlsplit(db.LOGIC_DB_URL)

GRAPH_DATABASE_PROVIDER = os.environ.get("COGNEE_GRAPH_DATABASE_PROVIDER", "postgres")

COGNEE_RELATIONAL_DB_CONFIG = {
    "db_provider": os.environ.get("COGNEE_DB_PROVIDER", "postgres"),
    "db_host": os.environ.get("COGNEE_DB_HOST", _admin_parts.hostname or "localhost"),
    "db_port": os.environ.get("COGNEE_DB_PORT", str(_admin_parts.port or 5432)),
    "db_username": os.environ.get("COGNEE_DB_USERNAME", _admin_parts.username or "postgres"),
    "db_password": os.environ.get("COGNEE_DB_PASSWORD", _admin_parts.password or ""),
    "db_name": os.environ.get("COGNEE_DB_NAME", "cognee_memory_db"),
}

# Explicit graph-store credentials -- REQUIRED, not optional. Confirmed via
# direct testing (docs/RfqChat/cognee-isolation-investigation.md) that
# leaving these unset makes cognee fall back to a more permissive path;
# every isolation test that actually passed (node_name-based, see below)
# set these explicitly. Same server/credentials as the relational config
# above (same dedicated cognee_memory_db) -- separate dict only because
# cognee's own config API takes graph vs. relational settings separately.
COGNEE_GRAPH_DB_CONFIG = {
    "graph_database_provider": os.environ.get("COGNEE_GRAPH_DATABASE_PROVIDER", "postgres"),
    "graph_database_host": os.environ.get("COGNEE_GRAPH_DB_HOST", _admin_parts.hostname or "localhost"),
    "graph_database_port": int(os.environ.get("COGNEE_GRAPH_DB_PORT", str(_admin_parts.port or 5432))),
    "graph_database_username": os.environ.get("COGNEE_GRAPH_DB_USERNAME", _admin_parts.username or "postgres"),
    "graph_database_password": os.environ.get("COGNEE_GRAPH_DB_PASSWORD", _admin_parts.password or ""),
    "graph_database_name": os.environ.get("COGNEE_GRAPH_DB_NAME", "cognee_memory_db"),
}

# Cognee 1.5.4 defaults to its OWN multi-user access-control/auth layer
# ("authentication=required, multi_tenant=enabled" per its own startup log).
# This service deliberately does NOT use that system for isolation (plan
# §8/§11, confirmed by explicit user decision): this service is the SOLE
# Cognee caller, and is never exposed directly to frontend/external
# clients (plan §0.B -- ingest/reset are loopback-bound; chat routes are
# JWT-gated at THIS service's own boundary, not at Cognee's). Isolation is
# enforced entirely by which dataset this service's code chooses to query,
# always computed server-side via dataset_name_for() from a verified
# rfq_id -- never a client-supplied dataset name, and Cognee's own ACL is
# not relied on at all. Explicitly disabled here rather than left on with
# a fixed service-account user, per that same decision (a second, unused
# identity layer would add friction without adding real isolation, since
# dataset-scoping is what's actually enforced).
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
os.environ.setdefault("REQUIRE_AUTHENTICATION", "false")

# Master feature flag for the ingestion side -- independent of the
# daemon's own ACCOMPLISH_ENABLE_RFQ_CHAT flag (plan §18), which only gates
# the query/retrieval path.
#
# RESOLVED 2026-09-10: the dataset-isolation leak documented in
# docs/RfqChat/cognee-isolation-investigation.md was traced to cognee's
# `datasets=[...]` search parameter not reliably constraining graph
# traversal. Fix (see node_set_tag_for's own docstring): isolation is now
# enforced via `search(node_type=NodeSet, node_name=[rfq_tag])`, a
# single-element tag filter -- verified via repeated, independent tests
# (2-way, 3-way, process-restart persistence, and a full integration test
# against this service's own real ingest.py/query.py/citation_store.py) to
# give real, leak-free isolation. Re-enabled by default now that this is
# confirmed in the actual production code path, not just a standalone test.
RFQ_MEMORY_ENABLED = os.environ.get("RFQ_MEMORY_ENABLED", "1") == "1"


def dataset_name_for(rfq_id: str) -> str:
    """Per-RFQ dataset -- kept as a secondary/operational scoping boundary
    (lifecycle: pruning a whole RFQ's memory via datasets.empty_dataset()
    stays simple) but is NO LONGER the sole enforced security boundary --
    see node_set_tag_for()'s own docstring for why."""
    return f"rfq_{rfq_id}"


def node_set_tag_for(rfq_id: str) -> str:
    """THE actual enforced isolation mechanism (plan revision, 2026-09-10):
    confirmed via direct, repeated testing
    (docs/RfqChat/cognee-isolation-investigation.md) that cognee 1.4.2's
    Postgres graph backend does NOT reliably constrain search() to a
    dataset -- a search scoped via `datasets=[...]` alone leaked another
    RFQ's content. A `search(node_type=NodeSet, node_name=[tag])` filter,
    scoped to a SINGLE tag (not combined with a second tag in the same
    list -- node_name_filter_operator defaults to "OR", which would widen
    rather than narrow), was verified to give real isolation across 2 and
    3 simultaneous RFQs, including after a process restart.

    Every cognee.add() call must tag its content with THIS value (alongside
    any content-type tag, e.g. node_set=[node_set_tag_for(rfq_id), "cbom"]
    -- multiple tags on a node at ADD time is fine, the risk is only in
    SEARCH time's OR-combination). Every cognee.search() call MUST pass
    node_name=[node_set_tag_for(rfq_id)] as a single-element list -- never
    omitted, never combined with a second tag in the same list.
    """
    return f"rfq_{rfq_id}"


def configure_cognee(cognee_module) -> None:
    """Applies every cognee.config.* setting this service needs, in one
    place, so memory_service.py and any standalone verification/test
    script call exactly the same setup rather than duplicating these
    calls. Takes the already-imported `cognee` module as a parameter
    (not imported by this file itself) so this module keeps its own
    "config sets env vars before cognee is ever imported" ordering
    invariant intact for every caller.
    """
    import os as _os

    _os.makedirs(COGNEE_DATA_ROOT, exist_ok=True)
    cognee_module.config.system_root_directory(COGNEE_DATA_ROOT)
    cognee_module.config.data_root_directory(COGNEE_DATA_ROOT)

    cognee_module.config.set_llm_provider(LLM_PROVIDER)
    cognee_module.config.set_llm_model(LLM_MODEL)
    cognee_module.config.set_llm_endpoint(LLM_ENDPOINT)
    cognee_module.config.set_llm_api_key(LLM_API_KEY)
    cognee_module.config.set_embedding_provider(EMBEDDING_PROVIDER)
    cognee_module.config.set_embedding_model(EMBEDDING_MODEL)
    cognee_module.config.set_embedding_endpoint(EMBEDDING_ENDPOINT)
    cognee_module.config.set_embedding_dimensions(EMBEDDING_DIMENSIONS)

    # Postgres-backed graph+relational store -- see the module-level
    # comment above COGNEE_RELATIONAL_DB_CONFIG for why (Kuzu/ladybug is
    # broken on this Windows/3.10 machine). Explicit graph credentials are
    # required, not optional -- see COGNEE_GRAPH_DB_CONFIG's own comment.
    cognee_module.config.set_relational_db_config(COGNEE_RELATIONAL_DB_CONFIG)
    cognee_module.config.set_graph_db_config(COGNEE_GRAPH_DB_CONFIG)
    cognee_module.config.set_graph_database_provider(GRAPH_DATABASE_PROVIDER)
