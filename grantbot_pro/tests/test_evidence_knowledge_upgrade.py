from __future__ import annotations

import unittest

from grantbot.evidence.document_intelligence import (
    authoritative_requirements,
    extract_requirements,
)


class EvidenceKnowledgeTests(unittest.TestCase):
    def test_primary_nofo_outranks_webinar(self) -> None:
        primary = extract_requirements(
            opportunity_id="OPP-1",
            pages=["Applicants must submit an SF-424 and budget narrative."],
            title="Notice of Funding Opportunity",
            authority_type="PRIMARY_NOFO",
        )
        webinar = extract_requirements(
            opportunity_id="OPP-1",
            pages=["During office hours, applicants should consider a letter of support."],
            title="Webinar Transcript",
            authority_type="WEBINAR_TRANSCRIPT",
        )
        combined = authoritative_requirements(primary + webinar)
        self.assertTrue(combined)
        self.assertTrue(all(item["authority_rank"] <= 6 for item in combined))
        self.assertEqual(combined[0]["authority_type"], "PRIMARY_NOFO")

    def test_requirement_has_page_provenance(self) -> None:
        results = extract_requirements(
            opportunity_id="OPP-1",
            pages=[
                "General introduction.",
                "Applicants shall provide evidence of SAM.gov registration.",
            ],
            source_url="https://example.gov/nofo.pdf",
            title="NOFO",
            authority_type="PRIMARY_NOFO",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["page_number"], 2)
        self.assertEqual(results[0]["requirement_level"], "MANDATORY")
        self.assertEqual(results[0]["category"], "SUBMISSION")


if __name__ == "__main__":
    unittest.main()
