from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from grantbot.compliance.requirements import (
    requirement_summary,
    set_requirement_status,
    sync_requirements,
)
from grantbot.core.database import connection, utc_now
from grantbot.master.database import initialize_master_schema
from grantbot.review.staging_v17 import (
    initialize_schema as initialize_staging_schema,
)


class RequirementComplianceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "grantbot.db"
        self.old_database = os.environ.get("GRANTBOT_DATABASE")
        self.old_staging = os.environ.get("GRANTBOT_DB_PATH")
        os.environ["GRANTBOT_DATABASE"] = str(self.db)
        os.environ["GRANTBOT_DB_PATH"] = str(self.db)
        initialize_master_schema()
        initialize_staging_schema()
        now = utc_now()
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO application_staging_v17(
                    workspace_id, opportunity_id, title, funder, stage,
                    readiness_score, competitive_score, human_approved,
                    approved_by, approved_at, analysis_json,
                    created_at, updated_at
                ) VALUES (
                    'ws1','opp1','Opportunity','Funder','APPROVED',
                    90,90,1,'reviewer','', '{}', ?, ?
                )
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO master_documents(
                    document_id, opportunity_id, title, source_url,
                    authority_type, authority_rank, pages_json,
                    sha256, created_at
                ) VALUES (
                    'doc1','opp1','Primary NOFO',
                    'https://example.gov/nofo.pdf',
                    'PRIMARY_NOFO',1,'[]','abc',?
                )
                """,
                (now,),
            )
            for requirement in (
                (
                    "req_m",
                    "ELIGIBILITY",
                    "MANDATORY",
                    "Applicant must maintain active SAM.gov registration.",
                    4,
                ),
                (
                    "req_c",
                    "MATCH",
                    "CONDITIONAL",
                    "If matching funds are required, document the non-federal share.",
                    8,
                ),
                (
                    "req_o",
                    "GENERAL",
                    "OPTIONAL",
                    "Applicants may provide supplemental context.",
                    10,
                ),
            ):
                conn.execute(
                    """
                    INSERT INTO master_requirements(
                        requirement_id, document_id, opportunity_id,
                        category, requirement_level, text, page_number,
                        section, authority_type, authority_rank, source_url,
                        confidence, created_at
                    ) VALUES (
                        ?, 'doc1', 'opp1', ?, ?, ?, ?, 'Section',
                        'PRIMARY_NOFO', 1,
                        'https://example.gov/nofo.pdf', 0.95, ?
                    )
                    """,
                    (*requirement, now),
                )

    def tearDown(self) -> None:
        if self.old_database is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_database
        if self.old_staging is None:
            os.environ.pop("GRANTBOT_DB_PATH", None)
        else:
            os.environ["GRANTBOT_DB_PATH"] = self.old_staging
        self.tmp.cleanup()

    def test_mandatory_and_conditional_requirements_block_until_reviewed(self) -> None:
        summary = sync_requirements("ws1")
        self.assertEqual(summary["blocking_count"], 2)
        set_requirement_status(
            "ws1",
            "req_m",
            status="SATISFIED",
            actor="reviewer",
            evidence_note="SAM registration verified.",
            evidence_source="SAM.gov entity record",
        )
        summary = requirement_summary("ws1")
        self.assertEqual(summary["blocking_count"], 1)
        set_requirement_status(
            "ws1",
            "req_c",
            status="NOT_APPLICABLE",
            actor="reviewer",
            evidence_note=(
                "NOFO states no non-federal share for this applicant pathway."
            ),
            evidence_source="Primary NOFO page 8",
            allow_not_applicable=True,
        )
        summary = requirement_summary("ws1")
        self.assertTrue(summary["ready"])
        with connection() as conn:
            statuses = {
                row["item_text"]: row["status"]
                for row in conn.execute(
                    "SELECT item_text,status FROM application_checklist_v17 "
                    "WHERE workspace_id='ws1' "
                    "AND item_type LIKE 'AUTHORITATIVE_%'"
                ).fetchall()
            }
        self.assertEqual(len(statuses), 2)
        self.assertIn("VERIFIED", statuses.values())
        self.assertIn("NOT_APPLICABLE", statuses.values())

    def test_mandatory_requirement_cannot_be_not_applicable(self) -> None:
        sync_requirements("ws1")
        with self.assertRaisesRegex(ValueError, "Mandatory requirements"):
            set_requirement_status(
                "ws1",
                "req_m",
                status="NOT_APPLICABLE",
                actor="reviewer",
                evidence_note="Attempted exception.",
                evidence_source="Reviewer note",
                allow_not_applicable=True,
            )

    def test_not_applicable_requires_authorized_reviewer_and_evidence(self) -> None:
        sync_requirements("ws1")
        with self.assertRaisesRegex(
            PermissionError,
            "authorized requirement reviewer",
        ):
            set_requirement_status(
                "ws1",
                "req_c",
                status="NOT_APPLICABLE",
                actor="writer",
                evidence_note="Condition does not apply.",
                evidence_source="NOFO page 8",
                allow_not_applicable=False,
            )
        with self.assertRaisesRegex(
            ValueError,
            "evidence_note and evidence_source",
        ):
            set_requirement_status(
                "ws1",
                "req_c",
                status="SATISFIED",
                actor="reviewer",
                evidence_note="",
                evidence_source="",
            )

    def test_optional_pending_does_not_block_or_create_checklist_item(self) -> None:
        summary = sync_requirements("ws1")
        self.assertEqual(summary["counts"]["OPTIONAL"]["pending"], 1)
        with connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM application_checklist_v17 "
                "WHERE workspace_id='ws1' "
                "AND item_text LIKE '%supplemental context%'"
            ).fetchone()[0]
        self.assertEqual(int(count), 0)


if __name__ == "__main__":
    unittest.main()
