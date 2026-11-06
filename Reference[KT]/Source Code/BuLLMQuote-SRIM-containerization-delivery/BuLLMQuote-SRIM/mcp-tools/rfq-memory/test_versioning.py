"""Unit tests for versioning.py's version-race safety (plan §0.A -- the
first of the four mandatory, non-negotiable requirements) and for ingest.py's
version-aware-ingestion-payload contract (plan §0.C).

Uses the standard library's unittest, matching this repo's one existing
test file's own convention (mcp-tools/reporting/superset/test_currency.py)
-- no pytest dependency needed.

Run with: python -m unittest test_versioning -v
"""

import asyncio
import unittest
from unittest.mock import patch

import config
import versioning
import ingest


class VersionRaceSafetyTests(unittest.TestCase):
    """plan §0.A: a stale ingestion job (carrying a version that is no
    longer the RFQ's active one by the time it actually tries to write)
    must be rejected -- never silently written."""

    def test_current_version_passes(self):
        with patch.object(config, "get_active_version", return_value=2):
            # Must not raise.
            versioning.assert_current_version("RFQ-TEST-001", 2)

    def test_stale_version_is_rejected(self):
        with patch.object(config, "get_active_version", return_value=2):
            with self.assertRaises(versioning.StaleVersionError):
                # This job was queued when version 1 was active, but by the
                # time it runs, version 2 (a re-upload) is now active --
                # the exact race described in plan §0.A.
                versioning.assert_current_version("RFQ-TEST-001", 1)

    def test_race_ordering_old_job_completes_after_new_version_prune(self):
        """Simulates the exact ordering plan §0.A calls out: an old-version
        (v1) ingestion job is in flight when a re-upload bumps the active
        version to v2 (which prunes the dataset), and only THEN does the
        old job's write attempt run. The stale job's write must be
        rejected, not silently reintroduce v1 content into v2's dataset.
        """
        active_version_at_time_of_check = {"value": 1}

        def fake_get_active_version(rfq_id):
            return active_version_at_time_of_check["value"]

        with patch.object(config, "get_active_version", side_effect=fake_get_active_version):
            # Old job (carrying version=1) was triggered while v1 was active.
            claimed_version = 1
            versioning.assert_current_version("RFQ-TEST-001", claimed_version)  # OK so far

            # A re-upload happens WHILE the old job is still "in flight" --
            # the active version flips to 2.
            active_version_at_time_of_check["value"] = 2

            # The old job now finally gets around to its write-time check
            # (plan §0.A: re-validated immediately before writing, not just
            # at trigger time) -- this MUST reject.
            with self.assertRaises(versioning.StaleVersionError):
                versioning.assert_current_version("RFQ-TEST-001", claimed_version)


class VersionAwareIngestionPayloadTests(unittest.TestCase):
    """plan §0.C: every ingestion call must carry an explicit, non-inferred
    version -- ingest_stage's write-time re-validation must reject a stale
    claimed version before ever calling cognee.add(), and must not even
    attempt the DB read for an unregistered source."""

    def test_ingest_stage_rejects_stale_version_before_any_cognee_call(self):
        with patch.object(config, "get_active_version", return_value=5):
            with patch("ingest.cognee") as mock_cognee:
                result = asyncio.run(
                    ingest.ingest_stage(rfq_id="RFQ-TEST-002", version=3, source="centum_reporting__cbom")
                )
                self.assertEqual(result["status"], "stale_version_rejected")
                mock_cognee.add.assert_not_called()
                mock_cognee.cognify.assert_not_called()

    def test_ingest_stage_skips_unregistered_source_without_db_access(self):
        # No get_active_version patch needed -- an unregistered source must
        # short-circuit before even checking the version, so this would
        # raise (unpatched Postgres connection) if that guarantee broke.
        result = asyncio.run(
            ingest.ingest_stage(rfq_id="RFQ-TEST-003", version=1, source="not_a_real_source")
        )
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
