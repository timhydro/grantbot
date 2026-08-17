from __future__ import annotations

import unittest

from grantbot.nofo.acquisition_v13 import (
    AcquiredDocument,
    _authoritative_documents,
    _requirement_texts,
    _resolve_authority,
)


class V13AuthorityIntegrationTests(unittest.TestCase):
    def test_transcript_is_excluded_when_primary_nofo_exists(self) -> None:
        documents = [
            AcquiredDocument(
                url="https://agency.gov/nofo.pdf",
                content_type="application/pdf",
                title="NOFO",
                authority_type="PRIMARY_NOFO",
                authority_rank=1,
                pages=["Applicants must submit a budget."],
            ),
            AcquiredDocument(
                url="https://agency.gov/webinar.txt",
                content_type="text/plain",
                title="Webinar Transcript",
                authority_type="WEBINAR_TRANSCRIPT",
                authority_rank=7,
                pages=["A speaker suggested another attachment."],
            ),
        ]
        selected = _authoritative_documents(documents)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].authority_type, "PRIMARY_NOFO")

    def test_requirement_categories_are_selected_deterministically(self) -> None:
        requirements = [
            {"category": "BUDGET", "text": "Budget narrative is required."},
            {"category": "MATCH", "text": "A 20 percent match is required."},
            {"category": "SUBMISSION", "text": "Submit through Grants.gov."},
        ]
        self.assertEqual(
            _requirement_texts(requirements, "MATCH"),
            ["A 20 percent match is required."],
        )

    def test_pdf_filename_can_identify_primary_nofo(self) -> None:
        authority = _resolve_authority(
            url="https://agency.gov/files/fy26-nofo.pdf",
            title="fy26-nofo.pdf",
            content_type="application/pdf",
        )
        self.assertEqual(authority, "PRIMARY_NOFO")


if __name__ == "__main__":
    unittest.main()
