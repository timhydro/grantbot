from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grantbot.vault import packet, readiness, repository


class DocumentVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("GRANTBOT_DATABASE")
        self.old_vault = os.environ.get("GRANTBOT_VAULT_ROOT")
        root = Path(self.tmp.name)
        os.environ["GRANTBOT_DATABASE"] = str(root / "grantbot.db")
        os.environ["GRANTBOT_VAULT_ROOT"] = str(root / "vault")

    def tearDown(self) -> None:
        if self.old_db is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.old_db
        if self.old_vault is None:
            os.environ.pop("GRANTBOT_VAULT_ROOT", None)
        else:
            os.environ["GRANTBOT_VAULT_ROOT"] = self.old_vault
        self.tmp.cleanup()

    def _store(
        self,
        *,
        content: bytes = b"Broken Growth governing document\n",
        expires_at: str = "",
        review_due_date: str = "",
    ) -> dict:
        return repository.store_document(
            document_key="governance.bylaws",
            title="Bylaws",
            category="BYLAWS",
            filename="bylaws.txt",
            content=content,
            source_reference="board-record:bylaws",
            actor="writer@test",
            effective_date="2026-02-23",
            expires_at=expires_at,
            review_due_date=review_due_date,
            description="Controlled bylaws copy",
            tags=["governance", "core"],
        )

    def test_content_type_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match extension"):
            repository.store_document(
                document_key="irs.letter",
                title="IRS Letter",
                category="IRS_DETERMINATION",
                filename="letter.pdf",
                content=b"This is plain text, not a PDF.",
                source_reference="irs-source",
                actor="writer@test",
            )

    def test_new_candidate_does_not_replace_approved_current_until_approved(self) -> None:
        first = self._store(content=b"Version one\n")
        first = repository.approve_document(
            first["document_id"],
            actor="reviewer@test",
            review_note="Board-approved governing copy",
        )
        self.assertTrue(first["is_current"])
        self.assertEqual(first["lifecycle_state"], "ACTIVE")

        second = self._store(content=b"Version two\n")
        self.assertEqual(second["version"], 2)
        self.assertFalse(second["is_current"])
        self.assertEqual(second["lifecycle_state"], "CANDIDATE")
        still_current = repository.list_documents(
            document_key="governance.bylaws",
            current_only=True,
        )
        self.assertEqual(still_current[0]["document_id"], first["document_id"])

        promoted = repository.approve_document(
            second["document_id"],
            actor="reviewer@test",
            review_note="Revised bylaws approved",
        )
        self.assertTrue(promoted["is_current"])
        old = repository.get_document(first["document_id"])
        self.assertFalse(old["is_current"])
        self.assertEqual(old["lifecycle_state"], "SUPERSEDED")

    def test_identical_content_is_idempotent_for_same_document_key(self) -> None:
        first = self._store(content=b"Identical controlled content\n")
        second = self._store(content=b"Identical controlled content\n")
        self.assertEqual(first["document_id"], second["document_id"])
        self.assertEqual(first["version"], 1)
        self.assertEqual(len(repository.list_documents()), 1)

    def test_freshness_enforces_expiry_and_review_dates(self) -> None:
        document = self._store(
            content=b"Insurance certificate\n",
            review_due_date="2026-08-16",
        )
        document = repository.approve_document(
            document["document_id"],
            actor="reviewer@test",
            review_note="Verified current copy",
            review_due_date="2026-08-16",
        )
        freshness = repository.document_freshness(
            document,
            as_of="2026-08-17",
        )
        self.assertEqual(freshness["state"], "REVIEW_DUE")
        self.assertFalse(freshness["usable_for_packet"])

        expiring = repository.store_document(
            document_key="insurance.general",
            title="Insurance",
            category="INSURANCE",
            filename="insurance.txt",
            content=b"Insurance copy\n",
            source_reference="carrier-certificate",
            actor="writer@test",
            effective_date="2026-01-01",
            expires_at="2026-08-16",
        )
        expiring = repository.approve_document(
            expiring["document_id"],
            actor="reviewer@test",
            review_note="Verified certificate",
        )
        expired = repository.document_freshness(
            expiring,
            as_of="2026-08-17",
        )
        self.assertEqual(expired["state"], "EXPIRED")

    def test_readiness_uses_only_explicit_source_backed_controls(self) -> None:
        requirement = repository.add_requirement(
            requirement_key="federal.bylaws",
            title="Current approved bylaws",
            category="BYLAWS",
            scope="FEDERAL",
            source_reference="internal-control:federal-application-readiness",
            actor="reviewer@test",
            document_key="governance.bylaws",
            required=True,
            must_be_approved=True,
            max_age_days=3650,
        )
        self.assertTrue(requirement["required"])
        missing = readiness.readiness_dashboard(
            scope="FEDERAL",
            as_of="2026-08-17",
        )
        self.assertFalse(missing["ready"])
        self.assertEqual(missing["blocking_count"], 1)

        document = self._store(content=b"Approved bylaws\n")
        repository.approve_document(
            document["document_id"],
            actor="reviewer@test",
            review_note="Approved for reusable application support",
        )
        ready = readiness.readiness_dashboard(
            scope="FEDERAL",
            as_of="2026-08-17",
        )
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["blocking_count"], 0)
        self.assertIn("explicitly configured", ready["policy_note"])

    def test_vault_path_is_content_addressed_and_hash_verified(self) -> None:
        document = self._store(content=b"Content address test\n")
        path = repository.resolve_document_path(document["document_id"])
        self.assertTrue(path.is_file())
        self.assertNotEqual(path.name, "bylaws.txt")
        self.assertEqual(len(path.name), 64)
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash verification failed"):
            repository.resolve_document_path(document["document_id"])

    def test_packet_binding_requires_approved_fresh_document_and_records_link(self) -> None:
        document = self._store(content=b"Approved attachment\n")
        with self.assertRaisesRegex(ValueError, "not eligible"):
            packet.attach_document_to_packet(
                document_id=document["document_id"],
                packet_id="packet-1",
                logical_name="bylaws.txt",
                required=True,
                actor="writer@test",
                as_of="2026-08-17",
            )
        approved = repository.approve_document(
            document["document_id"],
            actor="reviewer@test",
            review_note="Approved attachment source",
        )
        registered = {
            "attachments": [
                {
                    "attachment_id": "attachment-1",
                    "logical_name": "bylaws.txt",
                }
            ]
        }
        verified = {
            "packet_id": "packet-1",
            "attachments": [
                {
                    "attachment_id": "attachment-1",
                    "logical_name": "bylaws.txt",
                    "verified": True,
                }
            ],
        }
        with patch(
            "grantbot.packaging.packet_guard_v19.register_attachment",
            return_value=registered,
        ), patch(
            "grantbot.packaging.packet_guard_v19.verify_attachment",
            return_value=verified,
        ):
            result = packet.attach_document_to_packet(
                document_id=approved["document_id"],
                packet_id="packet-1",
                logical_name="bylaws.txt",
                required=True,
                actor="writer@test",
                as_of="2026-08-17",
            )
        self.assertEqual(result["attachment_id"], "attachment-1")
        self.assertTrue(result["packet"]["attachments"][0]["verified"])
        links = repository.list_links(approved["document_id"])
        self.assertEqual(links[0]["entity_type"], "APPLICATION_PACKET")


if __name__ == "__main__":
    unittest.main()
