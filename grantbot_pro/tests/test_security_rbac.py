from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from grantbot.security.auth import (
    ADMIN,
    GRANT_WRITER,
    Principal,
    authenticate_api_key,
    create_api_key,
    ensure_admin_key,
    list_api_keys,
    revoke_api_key,
    security_status,
)


class SecurityRBACTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_database = os.environ.get("GRANTBOT_DATABASE")
        self.previous_key_file = os.environ.get("GRANTBOT_MASTER_API_KEY_FILE")
        self.database = Path(self.temporary.name) / "grantbot.db"
        self.key_file = Path(self.temporary.name) / "admin.key"
        os.environ["GRANTBOT_DATABASE"] = str(self.database)
        os.environ["GRANTBOT_MASTER_API_KEY_FILE"] = str(self.key_file)

    def tearDown(self) -> None:
        if self.previous_database is None:
            os.environ.pop("GRANTBOT_DATABASE", None)
        else:
            os.environ["GRANTBOT_DATABASE"] = self.previous_database
        if self.previous_key_file is None:
            os.environ.pop("GRANTBOT_MASTER_API_KEY_FILE", None)
        else:
            os.environ["GRANTBOT_MASTER_API_KEY_FILE"] = self.previous_key_file
        self.temporary.cleanup()

    def test_admin_bootstrap_generates_authenticating_0600_key(self) -> None:
        result = ensure_admin_key()
        self.assertTrue(result["created"])
        self.assertTrue(self.key_file.is_file())
        mode = stat.S_IMODE(self.key_file.stat().st_mode)
        self.assertEqual(mode, 0o600)
        raw = self.key_file.read_text(encoding="utf-8").strip()
        principal = authenticate_api_key(raw, touch=False)
        self.assertEqual(principal.role, ADMIN)
        self.assertEqual(principal.label, "local-admin")

    def test_role_key_authenticates_and_wrong_secret_fails(self) -> None:
        ensure_admin_key()
        issued = create_api_key(label="writer-one", role=GRANT_WRITER)
        principal = authenticate_api_key(issued["api_key"], touch=False)
        self.assertEqual(principal.role, GRANT_WRITER)
        self.assertEqual(principal.label, "writer-one")
        key_id = issued["key_id"]
        with self.assertRaises(PermissionError):
            authenticate_api_key(f"gbk_{key_id}_this-secret-is-intentionally-wrong-12345", touch=False)

    def test_revocation_disables_key(self) -> None:
        ensure_admin_key()
        admin_raw = self.key_file.read_text(encoding="utf-8").strip()
        admin = authenticate_api_key(admin_raw, touch=False)
        issued = create_api_key(label="writer-two", role=GRANT_WRITER)
        result = revoke_api_key(issued["key_id"], actor=admin)
        self.assertFalse(result["active"])
        with self.assertRaises(PermissionError):
            authenticate_api_key(issued["api_key"], touch=False)

    def test_last_admin_cannot_be_revoked(self) -> None:
        ensure_admin_key()
        raw = self.key_file.read_text(encoding="utf-8").strip()
        admin = authenticate_api_key(raw, touch=False)
        with self.assertRaises(ValueError):
            revoke_api_key(admin.key_id, actor=admin)

    def test_second_admin_allows_rotation(self) -> None:
        ensure_admin_key()
        first_raw = self.key_file.read_text(encoding="utf-8").strip()
        first = authenticate_api_key(first_raw, touch=False)
        second = create_api_key(label="backup-admin", role=ADMIN)
        result = revoke_api_key(first.key_id, actor=first)
        self.assertFalse(result["active"])
        second_principal = authenticate_api_key(second["api_key"], touch=False)
        self.assertEqual(second_principal.role, ADMIN)

    def test_non_admin_cannot_revoke(self) -> None:
        ensure_admin_key()
        writer = create_api_key(label="writer-three", role=GRANT_WRITER)
        principal = authenticate_api_key(writer["api_key"], touch=False)
        self.assertIsInstance(principal, Principal)
        with self.assertRaises(PermissionError):
            revoke_api_key(writer["key_id"], actor=principal)

    def test_key_listing_never_exposes_secret_hashes(self) -> None:
        ensure_admin_key()
        keys = list_api_keys()
        self.assertEqual(len(keys), 1)
        serialized = repr(keys[0]).lower()
        self.assertNotIn("salt", serialized)
        self.assertNotIn("hash", serialized)
        self.assertNotIn("api_key", serialized)
        status = security_status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["active_roles"][ADMIN], 1)


if __name__ == "__main__":
    unittest.main()
