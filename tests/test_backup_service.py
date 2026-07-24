from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from easystufffind.backup_service import BackupService
from easystufffind.database import Database
from easystufffind.repository import Repository
from easystufffind.security import TokenManager, WebAuthManager


class BackupServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name) / "data"
        self.data_dir.mkdir()
        self.photo_dir = self.data_dir / "photos"
        self.photo_dir.mkdir()
        self.database = Database(self.data_dir / "easystufffind.sqlite3")
        self.database.initialize()
        self.token_manager = TokenManager(self.data_dir / "api-token")
        self.token_manager.ensure()
        self.web_auth = WebAuthManager(self.database, self.token_manager)
        self.web_auth.ensure_default_account()
        self.repository = Repository(self.database)
        self.service = BackupService(
            self.data_dir,
            self.data_dir / "backups",
            self.data_dir / "backup-config.json",
        )
        self.service.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_restore_preserves_runtime_identity_and_cloud_config(self) -> None:
        item = self.repository.create_item(
            name="布袋",
            aliases=[],
            location_id=None,
            location_path="储物间-柜子",
            note="原始备注",
        )
        photo = self.photo_dir / "bag.png"
        photo.write_bytes(b"original-photo")
        self.repository.replace_photo_metadata(
            item["id"],
            filename=photo.name,
            content_type="image/png",
        )
        original_token = (self.data_dir / "api-token").read_text(encoding="utf-8")
        self.service.save_config(
            {
                "cloud_enabled": True,
                "endpoint_url": "https://example.invalid",
                "region": "test",
                "bucket": "private",
                "access_key_id": "EXAMPLE_ACCESS_KEY",
                "secret_access_key": "EXAMPLE_SECRET",
            }
        )
        backup = self.service.create_backup()

        changed = self.web_auth.change_password("admin", "admin", "new-password")
        self.assertIsNotNone(changed)
        filename = self.repository.delete_item(item["id"])
        (self.photo_dir / filename).unlink()

        ticket, _ = self.service.issue_restore_ticket(backup["id"], "admin")
        restored = self.service.restore_with_ticket(ticket, "admin", "RESTORE")

        self.assertTrue(restored["restored"])
        self.assertEqual(
            self.repository.search_items("布袋")["status"],
            "unique",
        )
        self.assertEqual((self.photo_dir / "bag.png").read_bytes(), b"original-photo")
        self.assertEqual(
            (self.data_dir / "api-token").read_text(encoding="utf-8"),
            original_token,
        )
        self.assertIsNotNone(
            self.web_auth.authenticate("admin", "new-password")
        )
        self.assertEqual(
            self.service.load_config()["secret_access_key"],
            "EXAMPLE_SECRET",
        )
        self.assertNotEqual(restored["emergency_backup"], backup["id"])

    def test_invalid_archive_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "备份格式无效"):
            self.service.import_archive(b"not-a-zip")

    def test_schedule_slots_are_idempotent(self) -> None:
        self.service.save_config(
            {"frequency": "weekly", "time": "03:00", "weekday": 1}
        )
        monday = datetime.fromisoformat("2026-07-27T03:15:00+08:00")
        tuesday = datetime.fromisoformat("2026-07-28T03:15:00+08:00")
        self.assertEqual(self.service.scheduled_slot(monday), "weekly:2026-W31")
        self.assertIsNone(self.service.scheduled_slot(tuesday))

    def test_cloud_upload_sends_explicit_content_length_without_multipart(self) -> None:
        archive = self.service.backup_dir / "large.zip"
        archive.write_bytes(b"x" * (9 * 1024 * 1024))

        class FakeS3Client:
            def __init__(self) -> None:
                self.request = None

            def put_object(self, **kwargs):
                self.request = kwargs
                self.request["Body"].read()
                return {"ETag": "example"}

        client = FakeS3Client()
        self.service._cloud_client = lambda: (
            {"bucket": "private-bucket", "prefix": "easystufffind"},
            client,
        )
        self.service.upload_to_cloud(archive)

        self.assertEqual(client.request["ContentLength"], archive.stat().st_size)
        self.assertEqual(client.request["ServerSideEncryption"], "AES256")
        self.assertEqual(client.request["ContentType"], "application/zip")
        self.assertEqual(
            client.request["Key"],
            "easystufffind/large.zip",
        )


if __name__ == "__main__":
    unittest.main()
