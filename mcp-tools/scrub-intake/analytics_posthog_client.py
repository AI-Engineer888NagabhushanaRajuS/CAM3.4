"""PostHog SDK wrapper -- CAM backend. Phase 2: SDK wiring only.

This is the ONLY file in the backend that imports the `posthog` package.
`analytics_events.py` (the Phase 1 allowlist gate) deliberately has zero
PostHog dependency -- this module sits behind it, exactly as that module's
own docstring promises.

No backend service file imports this module yet -- nothing in the running
application calls capture() at this phase. That wiring (upload receipt,
pipeline stage advance, HITL resolution, report generation) is later,
separately-approved work.

Design:
  - Self-initializing, lazy singleton. There is no single shared backend
    "entry point" across the 7 independent services this project runs, so
    initialization happens on first use rather than requiring every service
    file to call an init function at startup.
  - Configured only from POSTHOG_API_KEY / POSTHOG_HOST environment
    variables (os.environ.get, matching config.py's/db.py's existing
    convention) -- never hardcoded, never read from any other source.
  - If POSTHOG_API_KEY is unset or blank, every capture() call is a no-op
    for the lifetime of the process. No client is constructed, no network
    connection is attempted.
  - capture() always runs the event through analytics_events's
    build_safe_event_payload() first. If that returns None (unknown event,
    or every property was stripped to nothing meaningful... actually even
    an empty-but-recognized event still gets sent -- only a fully unknown
    event name yields None), nothing is sent.
  - capture() can never raise and never blocks caller-visible control flow:
    every path is wrapped in try/except, and the underlying SDK already
    sends on a background thread by design.
"""

from __future__ import annotations

import os
from typing import Optional

import analytics_events

_DEFAULT_DISTINCT_ID = "cam-backend"

_client = None  # type: ignore[var-annotated]
_client_initialized = False


def _get_client():
    """Lazily constructs the PostHog client on first use. Returns None if
    POSTHOG_API_KEY isn't configured -- callers must treat None as "do
    nothing", never as an error."""
    global _client, _client_initialized
    if _client_initialized:
        return _client
    _client_initialized = True

    api_key = os.environ.get("POSTHOG_API_KEY", "").strip()
    if not api_key:
        _client = None
        return None

    try:
        import posthog

        host = os.environ.get("POSTHOG_HOST", "").strip() or None
        _client = posthog.Posthog(api_key, host=host) if host else posthog.Posthog(api_key)
    except Exception:
        # Any failure to construct the client (missing package, bad host
        # string, etc.) must degrade to "analytics is off", never to a
        # crash in whatever service imported this module.
        _client = None
    return _client


def is_enabled() -> bool:
    """True if a real PostHog client is configured and ready. Safe to call
    at any time; never raises."""
    try:
        return _get_client() is not None
    except Exception:
        return False


def capture(event_name: str, properties: Optional[dict] = None, distinct_id: str = _DEFAULT_DISTINCT_ID) -> None:
    """The single function every future backend call site should use to
    send an analytics event. Runs the Phase 1 allowlist gate first; only
    forwards to PostHog if both (a) the event/properties passed the gate
    and (b) a client is actually configured. Never raises, never blocks.

    distinct_id defaults to a constant, non-identifying service-level value
    (not an RFQ id, not a user id) -- backend pipeline events describe
    system behavior, not an individual person, and this default keeps that
    true even if a future call site forgets to pass one explicitly. Callers
    with a genuine, privacy-safe reason to group events differently (e.g.
    the random per-run pipeline_run_id from analytics_events.generate_run_id())
    may pass their own distinct_id.
    """
    try:
        payload = analytics_events.build_safe_event_payload(event_name, properties)
        if payload is None:
            return
        client = _get_client()
        if client is None:
            return
        client.capture(
            payload["event"],
            distinct_id=distinct_id,
            properties=payload["properties"],
        )
    except Exception:
        # Analytics must never affect application behavior -- swallow
        # everything. There is deliberately no logging of the exception
        # itself here, since a stack trace could echo back properties this
        # module is specifically trying to keep away from any sink.
        return


def shutdown() -> None:
    """Flushes and closes the client, if one was ever constructed. Safe to
    call even if analytics was never enabled. Not currently called from
    anywhere -- provided for future use during graceful service shutdown."""
    try:
        if _client is not None:
            _client.shutdown()
    except Exception:
        return
