from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from grantbot.applications.package_builder import _load_facts as load_legacy_writer_facts
from grantbot.applications.production_packet import (
    _eligibility_results,
    build_production_application_packet,
    builtin_opportunity_path,
    load_opportunity_file,
)
from grantbot.knowledge.writer_facts import load_canonical_writer_facts


class ProductionApplicationPacketV301Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "GRANTBOT_DATABASE": str(self.root / "grantbot.db"),
                "GRANTBOT_DATA_DIR": str(self.root / "data"),
                "GRANTBOT_LOG_DIR": str(self.root / "logs"),
                "GRANTBOT_EXPORT_DIR": str(self.root / "exports"),
                "GRANTBOT_BACKUP_DIR": str(self.root / "backups"),
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def opportunity(self) -> dict:
        opportunity = load_opportunity_file(
            builtin_opportunity_path("publix-housing-2026")
        )
        # Keep the deterministic packet test stable after the real 2026 cycle.
        opportunity["deadline"] = "2099-08-31"
        return opportunity

    def test_packet_uses_official_sources_and_human_gates(self) -> None:
        packet = build_production_application_packet(
            self.opportunity(),
            output_root=self.root / "output",
            include_docx=False,
        )

        self.assertEqual(packet["status"], "NEEDS_USER")
        self.assertFalse(packet["safe_to_submit"])
        self.assertFalse(packet["submission_performed"])
        self.assertTrue(packet["human_review_required"])
        self.assertEqual(packet["deadline_review"]["status"], "OPEN")
        self.assertTrue(
            all(item["status"] == "PASS" for item in packet["eligibility"])
        )
        self.assertEqual(
            packet["opportunity"]["source_url"],
            "https://publixcharities.org/request-support/",
        )
        self.assertTrue(
            all(
                source["url"].startswith("https://")
                for source in packet["opportunity"]["official_sources"]
            )
        )

        fields = {item["key"]: item for item in packet["portal_fields"]}
        self.assertEqual(fields["legal_name"]["status"], "READY")
        self.assertEqual(fields["ein"]["status"], "MISSING")
        gates = "\n".join(packet["hard_gates"])
        self.assertIn("Exact EIN", gates)
        self.assertIn("request amount", gates.lower())
        self.assertIn("live portal", gates.lower())

        sections = {item["section_id"]: item for item in packet["sections"]}
        self.assertEqual(
            sections["community-need"]["status"],
            "READY_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(
            sections["community-need"]["quality"]["unsupported_numbers"],
            [],
        )
        self.assertIn("1,150", sections["community-need"]["draft"])
        self.assertEqual(
            sections["goals-objectives"]["status"],
            "READY_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(
            sections["partnerships"]["status"],
            "NEEDS_INFORMATION",
        )
        self.assertIn(
            "County and engineering approval",
            sections["program-design"]["draft"],
        )
        for artifact_key in ("json", "markdown", "checklist", "source_manifest"):
            self.assertTrue(Path(packet["artifacts"][artifact_key]).is_file())

        stored = json.loads(Path(packet["artifacts"]["json"]).read_text())
        self.assertEqual(stored["fact_snapshot_sha256"], packet["fact_snapshot_sha256"])

    def test_all_writer_paths_reject_legacy_sample_fact_store(self) -> None:
        for facts in (
            load_canonical_writer_facts(actor="test-production-packet"),
            load_legacy_writer_facts(),
        ):
            keys = {item["key"] for item in facts}
            self.assertNotIn("housing_units_planned", keys)
            self.assertNotIn("job_placement_target_rate", keys)
            self.assertTrue(
                all(item.get("source") != "legacy_fact_registry" for item in facts)
            )

    def test_semantic_eligibility_does_not_pass_wrong_geography(self) -> None:
        result = _eligibility_results(
            [
                {
                    "id": "geo",
                    "label": "Service area",
                    "requirement": "Serve Florida",
                    "source_url": "https://example.org/eligibility",
                    "evidence_fact_keys": ["service_area"],
                    "mode": "any",
                    "required_substrings_any": ["florida"],
                    "hard_fail_on_mismatch": True,
                    "action": "Hold for geography review.",
                }
            ],
            [
                {
                    "key": "service_area",
                    "value": "New York",
                    "verification_state": "VERIFIED",
                    "source": "official record",
                }
            ],
        )
        self.assertEqual(result[0].status, "FAIL")

    def test_docx_packet_is_valid_office_document(self) -> None:
        packet = build_production_application_packet(
            self.opportunity(),
            output_root=self.root / "docx-output",
            include_docx=True,
        )
        docx = Path(packet["artifacts"]["docx"])
        self.assertTrue(docx.is_file())
        self.assertTrue(zipfile.is_zipfile(docx))
        with zipfile.ZipFile(docx) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("Publix Super Markets Charities", document_xml)
        self.assertIn("Human-Required Gates", document_xml)


if __name__ == "__main__":
    unittest.main()
