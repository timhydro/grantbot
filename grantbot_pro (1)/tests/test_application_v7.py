from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from grantbot.applications.package_builder import (
    build_application_package,
    load_application_package,
)
from grantbot.automation.opportunity_pipeline import Opportunity


class ApplicationV7Tests(unittest.TestCase):
    def test_build_without_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            opportunity = Opportunity(
                id="test-package",
                title="Florida Reentry Workforce",
                description=(
                    "reentry homelessness housing employment "
                    "workforce supportive services Florida"
                ),
                eligibility="nonprofit organizations",
                deadline="2099-12-01",
                nofo_text=(
                    "Nonprofit organizations may apply. "
                    "This program supports reentry housing employment. "
                    "1. Describe your organization mission?"
                ),
            )

            package = build_application_package(
                opportunity,
                generate_drafts=False,
                output_root=Path(td),
            )

            self.assertEqual(
                package.package_id,
                "test-package",
            )

            self.assertTrue(
                Path(package.output_path).exists()
            )

            loaded = load_application_package(
                "test-package",
                output_root=Path(td),
            )

            self.assertEqual(
                loaded["package_id"],
                "test-package",
            )

    def test_safe_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            opportunity = Opportunity(
                id="../../bad id",
                title="Test",
                description="housing employment reentry",
                eligibility="nonprofit",
                deadline="2099-12-01",
            )

            package = build_application_package(
                opportunity,
                generate_drafts=False,
                output_root=Path(td),
            )

            self.assertNotIn(
                "..",
                package.package_id,
            )

            self.assertNotIn(
                "/",
                package.package_id,
            )


if __name__ == "__main__":
    unittest.main()
