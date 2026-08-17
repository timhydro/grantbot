from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from grantbot.core.database import connection, initialize_database
from grantbot.evidence.repository import ingest_document, list_requirements
from grantbot.knowledge.canonical import current_facts, migrate_legacy_facts, set_fact
from grantbot.knowledge.repository import save_fact
from grantbot.retrieval.hybrid import rank_facts


class CanonicalEvidenceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_database = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(Path(self.temporary.name) / "grantbot.db")
        initialize_database()

    def tearDown(self) -> None:
        if self.previous_database is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.previous_database
        self.temporary.cleanup()

    def test_legacy_migration_is_idempotent(self) -> None:
        save_fact(
            category="legal",
            fact_key="formation_date",
            value="2026-02-23",
            status="VERIFIED",
            source="Sunbiz",
            confidence=1.0,
        )
        first = migrate_legacy_facts()
        second = migrate_legacy_facts()
        self.assertEqual(first["migrated"], 1)
        self.assertEqual(second["migrated"], 0)
        self.assertEqual(second["skipped"], 1)
        current = current_facts(category="legal")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["fact_type"], "VERIFIED_FACT")
        self.assertEqual(current[0]["verification_state"], "VERIFIED")

    def test_fact_versioning_leaves_one_current_value(self) -> None:
        first = set_fact(
            category="program",
            fact_key="sobriety_requirement_days",
            value=180,
            fact_type="USER_PROVIDED_FACT",
            verification_state="APPROVED",
            source="founder",
        )
        second = set_fact(
            category="program",
            fact_key="sobriety_requirement_days",
            value=30,
            fact_type="USER_PROVIDED_FACT",
            verification_state="APPROVED",
            source="founder-update",
        )
        current = current_facts(category="program")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["value"], 30)
        self.assertEqual(current[0]["supersedes_fact_id"], first["fact_id"])
        with connection() as conn:
            old = conn.execute(
                "SELECT verification_state, valid_to FROM canonical_facts WHERE fact_id=?",
                (first["fact_id"],),
            ).fetchone()
        self.assertEqual(old["verification_state"], "SUPERSEDED")
        self.assertTrue(old["valid_to"])
        self.assertNotEqual(first["fact_id"], second["fact_id"])

    def test_document_ingest_is_idempotent_and_opportunity_scoped(self) -> None:
        page = "Applicants must submit an SF-424 through Grants.gov by the stated deadline."
        first = ingest_document(
            opportunity_id="OPP-A",
            title="Notice of Funding Opportunity",
            pages=[page],
            source_url="https://agency.gov/nofo-a.pdf",
            authority_type="PRIMARY_NOFO",
        )
        duplicate = ingest_document(
            opportunity_id="OPP-A",
            title="Notice of Funding Opportunity",
            pages=[page],
            source_url="https://agency.gov/nofo-a.pdf",
            authority_type="PRIMARY_NOFO",
        )
        second_opportunity = ingest_document(
            opportunity_id="OPP-B",
            title="Notice of Funding Opportunity",
            pages=[page],
            source_url="https://agency.gov/nofo-b.pdf",
            authority_type="PRIMARY_NOFO",
        )
        self.assertEqual(first["document_id"], duplicate["document_id"])
        self.assertNotEqual(first["document_id"], second_opportunity["document_id"])
        a = list_requirements(opportunity_id="OPP-A")
        b = list_requirements(opportunity_id="OPP-B")
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertEqual(a[0]["opportunity_id"], "OPP-A")
        self.assertEqual(b[0]["opportunity_id"], "OPP-B")

    def test_hybrid_retrieval_prefers_relevant_verified_fact(self) -> None:
        set_fact(
            category="housing",
            fact_key="tiny_home_plan",
            value="The planned first phase includes 10 to 15 tiny homes.",
            fact_type="REASONABLE_PROJECTION",
            verification_state="UNVERIFIED",
            source="planning record",
        )
        set_fact(
            category="legal",
            fact_key="formation_date",
            value="February 23, 2026",
            fact_type="VERIFIED_FACT",
            verification_state="VERIFIED",
            source="Sunbiz",
        )
        ranked = rank_facts("tiny homes housing plan", include_unverified=True)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["fact_key"], "tiny_home_plan")


if __name__ == "__main__":
    unittest.main()
