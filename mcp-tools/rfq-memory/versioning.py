"""Version/race safety (plan §0.A) and dataset lifecycle for the Cognee-backed
RFQ memory. This module is the ONLY place that decides whether an ingestion
job's write is allowed to land, and the only place that prunes a dataset --
every other module calls into these two functions rather than touching
Cognee's dataset-delete API directly, so this invariant has one
implementation, not several copies that could drift out of sync.
"""

import logging

# config MUST be imported before cognee -- see ingest.py's identical comment.
import config
import cognee

logger = logging.getLogger("rfq_memory.versioning")


class StaleVersionError(Exception):
    """Raised when an ingestion job's carried version no longer matches the
    RFQ's current active version. Callers must treat this as a silent
    no-op (log-only), never propagate it as a request failure -- an old
    in-flight job losing a race is expected, not exceptional."""


def assert_current_version(rfq_id: str, claimed_version: int) -> None:
    """Re-validates `claimed_version` against file_metadata_db_2's
    rfq_process_tracking, freshly read right now -- NOT the version that was
    active when the ingestion job was first triggered. This is what makes
    the race in plan §0.A safe: an old-version job that was queued before a
    re-upload, and only gets around to writing after the re-upload's prune
    has already happened, is caught here and rejected rather than silently
    reintroducing stale content into the current dataset.

    Uses db.get_active_version (fastmcp-router/db.py) unmodified -- the same
    function every other part of the platform already trusts for "what
    version is active right now."
    """
    current_version = config.get_active_version(rfq_id)
    if current_version != claimed_version:
        raise StaleVersionError(
            f"rfq_id={rfq_id}: ingestion job carried version={claimed_version}, "
            f"but the current active version is {current_version}. Write rejected."
        )


async def _resolve_dataset_id(dataset_name: str, user=None):
    """Cognee's dataset-management API (cognee.datasets.empty_dataset) takes
    a dataset_id (UUID), not a bare name -- add()/search() accept a name
    directly and create/resolve the dataset implicitly, but pruning needs
    the id. Resolves by listing datasets and matching on name. Returns None
    if the dataset doesn't exist yet (nothing to prune -- not an error, a
    brand-new RFQ has no dataset until its first successful ingest)."""
    existing = await cognee.datasets.list_datasets(user=user)
    for ds in existing or []:
        name = getattr(ds, "name", None) or (ds.get("name") if isinstance(ds, dict) else None)
        if name == dataset_name:
            return getattr(ds, "id", None) or (ds.get("id") if isinstance(ds, dict) else None)
    return None


async def prune_rfq_dataset(rfq_id: str) -> None:
    """Full prune of one RFQ's Cognee dataset -- called before a new file
    version's content starts repopulating it (plan §9), and exposed via
    POST /internal/memory/reset for whatever future RFQ-deletion mechanism
    needs it (plan §9's disclosed gap: nothing calls that automatically
    today). Safe to call on a dataset that doesn't exist yet -- a no-op,
    not an error, since a brand-new RFQ's first ingest hasn't run yet."""
    dataset_name = config.dataset_name_for(rfq_id)
    dataset_id = await _resolve_dataset_id(dataset_name)
    if dataset_id is None:
        logger.info("[MEMORY PRUNE] rfq_id=%s: no existing dataset, nothing to prune", rfq_id)
        return
    await cognee.datasets.empty_dataset(dataset_id)
    logger.info("[MEMORY PRUNE] rfq_id=%s: dataset %s emptied", rfq_id, dataset_name)
