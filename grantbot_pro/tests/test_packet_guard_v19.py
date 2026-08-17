from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from grantbot.packaging import packet_guard_v19 as guard
from grantbot.packaging import packet_v19


class PacketGuardV19Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        os.environ["GRANTBOT_DATABASE"] = str(self.root / "grantbot.db")
        self.workspace = {
            "workspace_id": "workspace1",
            "opportunity_id": "opp1",
            "title": "Opportunity",
            "funder": "Funder",
            "stage": "APPROVED",
            "human_approved": True,
        }
        self.revisions = [
            {
                "revision_id": "rev1",
                "workspace_id": "workspace1",
                "task_id": "task1",
                "version": 1,
                "content": "Verified narrative.",
                "status": "READY_FOR_REVIEW",
                "facts": [{"fact_id": "f1"}],
                "claims": {"safe": True},
                "quality": {"passed": True},
                "provider": "ollama",
                "model": "llama3.2:3b",
            }
        ]
        self.patches = [
            patch.object(packet_v19, "_root", return_value=self.root),
            patch.object(
                guard,
                "get_workspace",
                side_effect=lambda _: deepcopy(self.workspace),
            ),
            patch.object(
                guard,
                "list_revisions",
                side_effect=lambda _: deepcopy(self.revisions),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        self.tmp.cleanup()

    def _packet_with_verified_pdf(self) -> tuple[dict, str]:
        packet = guard.build_packet("workspace1")
        source = guard.controlled_upload_path("workspace1", "budget.pdf")
        source.write_bytes(b"%PDF-1.4\n% test\n")
        packet = guard.register_attachment(
            packet["packet_id"],
            source_path=str(source),
            logical_name="budget.pdf",
            media_type="application/pdf",
        )
        attachment_id = packet["attachments"][0]["attachment_id"]
        packet = guard.verify_attachment(
            packet["packet_id"],
            attachment_id,
            actor="reviewer@test",
        )
        return packet, attachment_id

    def test_approval_freezes_packet_and_seal_is_verifiable(self) -> None:
        packet, attachment_id = self._packet_with_verified_pdf()
        packet = guard.approve_packet(
            packet["packet_id"],
            actor="authorized@test",
            note="Approved.",
        )
        self.assertEqual(packet["status"], "APPROVED")
        with self.assertRaisesRegex(ValueError, "immutable"):
            guard.verify_attachment(
                packet["packet_id"],
                attachment_id,
                actor="reviewer@test",
            )
        self.workspace["stage"] = "READY_FOR_SUBMISSION"
        sealed = guard.finalize_packet(
            packet["packet_id"],
            actor="authorized@test",
        )
        self.assertEqual(sealed["status"], "SEALED")
        integrity = guard.verify_packet_integrity(packet["packet_id"])
        self.assertTrue(integrity["safe"], integrity["issues"])
        archive = Path(sealed["archive_path"])
        archive.write_bytes(archive.read_bytes() + b"tamper")
        integrity = guard.verify_packet_integrity(packet["packet_id"])
        self.assertFalse(integrity["safe"])
        self.assertIn("Sealed archive hash mismatch", integrity["issues"])

    def test_unverified_attachment_blocks_approval(self) -> None:
        packet = guard.build_packet("workspace1")
        source = guard.controlled_upload_path("workspace1", "budget.pdf")
        source.write_bytes(b"%PDF-1.4\n% test\n")
        packet = guard.register_attachment(
            packet["packet_id"],
            source_path=str(source),
            logical_name="budget.pdf",
            media_type="application/pdf",
        )
        with self.assertRaisesRegex(
            ValueError,
            "Every included packet attachment",
        ):
            guard.approve_packet(
                packet["packet_id"],
                actor="authorized@test",
                note="No.",
            )

    def test_duplicate_names_and_content_mismatch_are_rejected(self) -> None:
        packet, _ = self._packet_with_verified_pdf()
        source = guard.controlled_upload_path("workspace1", "other.pdf")
        source.write_bytes(b"%PDF-1.4\n% second\n")
        with self.assertRaisesRegex(ValueError, "Duplicate attachment"):
            guard.register_attachment(
                packet["packet_id"],
                source_path=str(source),
                logical_name="budget.pdf",
                media_type="application/pdf",
            )
        packet2 = guard.build_packet("workspace1")
        fake = guard.controlled_upload_path("workspace1", "fake.pdf")
        fake.write_text("not a pdf", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match extension"):
            guard.register_attachment(
                packet2["packet_id"],
                source_path=str(fake),
                logical_name="fake.pdf",
                media_type="application/pdf",
            )

    def test_new_writer_revision_blocks_sealing(self) -> None:
        packet, _ = self._packet_with_verified_pdf()
        packet = guard.approve_packet(
            packet["packet_id"],
            actor="authorized@test",
            note="Approved.",
        )
        newer = deepcopy(self.revisions[0])
        newer["revision_id"] = "rev2"
        newer["version"] = 2
        newer["content"] = "Newer narrative."
        self.revisions.append(newer)
        self.workspace["stage"] = "READY_FOR_SUBMISSION"
        with self.assertRaisesRegex(ValueError, "newer writer revision"):
            guard.finalize_packet(
                packet["packet_id"],
                actor="authorized@test",
            )


if __name__ == "__main__":
    unittest.main()
