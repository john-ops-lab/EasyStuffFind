from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from easystufffind.database import SCHEMA_V1, Database
from easystufffind.security import TokenManager, WebAuthManager


class SecurityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = Database(self.data_dir / "test.sqlite3")
        self.database.initialize()
        self.token_manager = TokenManager(self.data_dir / "api-token")
        self.token_manager.ensure()
        self.web_auth = WebAuthManager(self.database, self.token_manager)
        self.web_auth.ensure_default_account()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_login_session_and_password_change(self) -> None:
        account = self.web_auth.authenticate("admin", "admin")
        self.assertIsNotNone(account)
        self.assertFalse(account["password_changed"])
        self.assertIsNone(self.web_auth.authenticate("admin", "wrong"))

        old_session = self.web_auth.create_session(account)
        self.assertEqual(
            self.web_auth.account_from_session(old_session)["username"],
            "admin",
        )
        self.assertIsNone(
            self.web_auth.account_from_session(old_session + "tampered")
        )

        updated = self.web_auth.change_password(
            "admin",
            "admin",
            "a-new-password",
        )
        self.assertIsNotNone(updated)
        self.assertTrue(updated["password_changed"])
        self.assertIsNone(self.web_auth.authenticate("admin", "admin"))
        self.assertIsNotNone(
            self.web_auth.authenticate("admin", "a-new-password")
        )
        self.assertIsNone(self.web_auth.account_from_session(old_session))
        self.assertIsNotNone(
            self.web_auth.account_from_session(
                self.web_auth.create_session(updated)
            )
        )

    def test_schema_v1_is_migrated_without_losing_data(self) -> None:
        legacy_path = self.data_dir / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(SCHEMA_V1)
            connection.execute(
                """
                INSERT INTO locations (
                    parent_id, name, normalized_name, created_at, updated_at
                ) VALUES (NULL, '书房', '书房', '2026-01-01', '2026-01-01')
                """
            )
        legacy = Database(legacy_path)
        legacy.initialize()
        with legacy.read() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            location = connection.execute(
                "SELECT name FROM locations"
            ).fetchone()[0]
            account_table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'web_accounts'
                """
            ).fetchone()
        self.assertEqual(version, 2)
        self.assertEqual(location, "书房")
        self.assertIsNotNone(account_table)


if __name__ == "__main__":
    unittest.main()
