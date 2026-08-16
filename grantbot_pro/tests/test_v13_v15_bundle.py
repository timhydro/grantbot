from __future__ import annotations

import unittest

from grantbot.nofo.acquisition_v13 import (
    _dedupe,
    _lines,
    _safe_url,
)
from grantbot.matching.competitive_v14 import _priority
from grantbot.compliance.readiness_v15 import _status


class V13V15BundleTests(unittest.TestCase):
    def test_safe_government_urls(self) -> None:
        self.assertTrue(
            _safe_url("https://www.grants.gov/test.pdf")
        )
        self.assertTrue(
            _safe_url("https://www.ojp.gov/test.pdf")
        )
        self.assertFalse(
            _safe_url("http://www.grants.gov/test.pdf")
        )
        self.assertFalse(
            _safe_url("https://example.com/test.pdf")
        )

    def test_dedupe(self) -> None:
        self.assertEqual(
            _dedupe(["A", "A", "B"]),
            ["A", "B"],
        )

    def test_line_normalization(self) -> None:
        lines = _lines(
            "Describe the proposed program and implementation strategy.\n"
            "Short\n"
            "Provide a complete budget narrative."
        )
        self.assertEqual(len(lines), 2)

    def test_priority(self) -> None:
        self.assertEqual(
            _priority(90, False),
            "CRITICAL",
        )
        self.assertEqual(
            _priority(90, True),
            "REJECT",
        )

    def test_status(self) -> None:
        self.assertEqual(
            _status(95, []),
            "SUBMISSION_READY",
        )
        self.assertEqual(
            _status(40, []),
            "NOT_READY",
        )
        self.assertEqual(
            _status(
                95,
                ["REJECT: failed gate"],
            ),
            "REJECTED",
        )


if __name__ == "__main__":
    unittest.main()
