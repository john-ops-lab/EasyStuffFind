from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from botocore.config import Config

from .database import SCHEMA_VERSION

BACKUP_PREFIX = "easystufffind-backup-"
MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_CONFIG: dict[str, Any] = {
    "cloud_enabled": False,
    "provider": "aliyun",
    "endpoint_url": "",
    "region": "",
    "bucket": "",
    "prefix": "easystufffind",
    "access_key_id": "",
    "secret_access_key": "",
    "frequency": "off",
    "time": "03:00",
    "weekday": 1,
    "monthday": 1,
    "retention_days": 30,
    "last_scheduled_slot": "",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupService:
    def __init__(self, data_dir: Path, backup_dir: Path, config_path: Path) -> None:
        self.data_dir = data_dir
        self.database_path = data_dir / "easystufffind.sqlite3"
        self.photo_dir = data_dir / "photos"
        self.token_path = data_dir / "api-token"
        self.backup_dir = backup_dir
        self.config_path = config_path
        self.lock = threading.RLock()
        self._tickets: dict[str, dict[str, Any]] = {}

    def initialize(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.backup_dir, 0o700)
        if not self.config_path.exists():
            self.save_config({})
        else:
            os.chmod(self.config_path, 0o600)

    def load_config(self) -> dict[str, Any]:
        config = dict(DEFAULT_CONFIG)
        if self.config_path.is_file():
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                config.update(raw)
        return config

    def save_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        config = self.load_config() if self.config_path.exists() else dict(DEFAULT_CONFIG)
        secret = updates.pop("secret_access_key", None)
        config.update(updates)
        if secret is not None:
            config["secret_access_key"] = secret
        self.config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.config_path.parent, prefix=".backup-config-"
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(config, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.config_path)
            os.chmod(self.config_path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
        return config

    @staticmethod
    def public_config(config: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in config.items() if key != "secret_access_key"}
        access_key = str(result.get("access_key_id", ""))
        result["access_key_id_masked"] = (
            f"{access_key[:3]}***{access_key[-3:]}" if len(access_key) >= 8 else ("已配置" if access_key else "")
        )
        result["access_key_id"] = ""
        result["secret_configured"] = bool(config.get("secret_access_key"))
        result.pop("last_scheduled_slot", None)
        return result

    def create_backup(self, *, upload_cloud: bool = False, reason: str = "manual") -> dict[str, Any]:
        with self.lock:
            if not self.database_path.is_file() or not self.token_path.is_file():
                raise RuntimeError("数据库或 API token 不存在")
            now = utc_now()
            nonce = secrets.token_hex(3)
            backup_id = f"{BACKUP_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}-{nonce}"
            archive = self.backup_dir / f"{backup_id}.zip"
            with tempfile.TemporaryDirectory(prefix="easystufffind-backup-") as work:
                bundle = Path(work) / backup_id
                bundle.mkdir(mode=0o700)
                database_copy = bundle / "easystufffind.sqlite3"
                with closing(sqlite3.connect(self.database_path)) as source, closing(sqlite3.connect(
                    database_copy
                )) as destination:
                    source.backup(destination)
                with closing(sqlite3.connect(database_copy)) as verification:
                    integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
                    schema_version = int(verification.execute("PRAGMA user_version").fetchone()[0])
                if integrity != "ok":
                    raise RuntimeError("备份数据库完整性检查失败")
                shutil.copy2(self.token_path, bundle / "api-token")
                photos_target = bundle / "photos"
                photos_target.mkdir(mode=0o700)
                if self.photo_dir.is_dir():
                    for photo in self.photo_dir.iterdir():
                        if photo.is_file():
                            shutil.copy2(photo, photos_target / photo.name)
                entries = [database_copy, bundle / "api-token", *sorted(photos_target.iterdir())]
                manifest = {
                    "format_version": 1,
                    "id": backup_id,
                    "created_at": now.isoformat().replace("+00:00", "Z"),
                    "reason": reason,
                    "schema_version": schema_version,
                    "files": [
                        {
                            "path": str(path.relative_to(bundle)),
                            "sha256": sha256_file(path),
                            "bytes": path.stat().st_size,
                        }
                        for path in entries
                    ],
                }
                (bundle / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                descriptor, temporary_name = tempfile.mkstemp(
                    dir=self.backup_dir, prefix=".backup-", suffix=".zip"
                )
                os.close(descriptor)
                temporary = Path(temporary_name)
                try:
                    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
                        for path in bundle.rglob("*"):
                            if path.is_file():
                                output.write(path, path.relative_to(bundle))
                    os.chmod(temporary, 0o600)
                    os.replace(temporary, archive)
                finally:
                    temporary.unlink(missing_ok=True)
            cloud_uploaded = False
            if upload_cloud:
                self.upload_to_cloud(archive)
                cloud_uploaded = True
            self.prune_local()
            return self.describe_archive(archive) | {"cloud_uploaded": cloud_uploaded}

    def describe_archive(self, archive: Path, source: str = "local") -> dict[str, Any]:
        with zipfile.ZipFile(archive) as content:
            manifest = json.loads(content.read("manifest.json"))
        return {
            "id": manifest["id"],
            "created_at": manifest["created_at"],
            "reason": manifest.get("reason", "manual"),
            "schema_version": manifest["schema_version"],
            "bytes": archive.stat().st_size,
            "source": source,
            "filename": archive.name,
        }

    def list_local(self) -> list[dict[str, Any]]:
        records = []
        for archive in self.backup_dir.glob(f"{BACKUP_PREFIX}*.zip"):
            try:
                records.append(self.describe_archive(archive))
            except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                continue
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def archive_path(self, backup_id: str) -> Path:
        if not backup_id.startswith(BACKUP_PREFIX) or "/" in backup_id or "\\" in backup_id:
            raise FileNotFoundError("备份不存在")
        path = self.backup_dir / f"{backup_id}.zip"
        if not path.is_file():
            raise FileNotFoundError("备份不存在")
        return path

    def ensure_archive(self, backup_id: str) -> Path:
        try:
            return self.archive_path(backup_id)
        except FileNotFoundError:
            return self.download_from_cloud(backup_id)

    def import_archive(self, body: bytes) -> dict[str, Any]:
        if not body or len(body) > MAX_BACKUP_BYTES:
            raise ValueError("备份文件为空或超过 2 GiB")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.backup_dir, prefix=".backup-upload-", suffix=".zip"
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(body)
            return self.import_archive_file(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def import_archive_file(self, temporary: Path) -> dict[str, Any]:
        manifest = self.validate_archive(temporary)
        target = self.backup_dir / f"{manifest['id']}.zip"
        if target.exists():
            raise ValueError("同一份备份已经存在")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        return self.describe_archive(target)

    def validate_archive(self, archive: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(archive) as content:
                names = content.namelist()
                if len(names) > 20000:
                    raise ValueError("备份文件数量异常")
                file_infos = [info for info in content.infolist() if not info.is_dir()]
                if sum(info.file_size for info in file_infos) > MAX_BACKUP_BYTES:
                    raise ValueError("备份解压后超过 2 GiB")
                for name in names:
                    pure = PurePosixPath(name)
                    if pure.is_absolute() or ".." in pure.parts:
                        raise ValueError("备份包含不安全路径")
                manifest = json.loads(content.read("manifest.json"))
                if manifest.get("format_version") != 1:
                    raise ValueError("不支持的备份格式")
                backup_id = manifest.get("id")
                if (
                    not isinstance(backup_id, str)
                    or not backup_id.startswith(BACKUP_PREFIX)
                    or "/" in backup_id
                    or "\\" in backup_id
                ):
                    raise ValueError("备份 ID 无效")
                if manifest.get("schema_version") != SCHEMA_VERSION:
                    raise ValueError(
                        f"备份 Schema 版本不兼容：需要 {SCHEMA_VERSION}"
                    )
                expected = {"easystufffind.sqlite3", "api-token"}
                listed = {entry["path"] for entry in manifest["files"]}
                if not expected.issubset(listed):
                    raise ValueError("备份缺少数据库或 token")
                if set(info.filename for info in file_infos) != listed | {"manifest.json"}:
                    raise ValueError("备份清单与压缩包文件不一致")
                total_bytes = sum(int(entry["bytes"]) for entry in manifest["files"])
                if total_bytes > MAX_BACKUP_BYTES:
                    raise ValueError("备份解压后超过 2 GiB")
                for entry in manifest["files"]:
                    data = content.read(entry["path"])
                    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                        raise ValueError(f"备份校验失败：{entry['path']}")
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise ValueError("备份格式无效") from exc
        return manifest

    def issue_restore_ticket(self, backup_id: str, username: str) -> tuple[str, dict[str, Any]]:
        archive = self.ensure_archive(backup_id)
        manifest = self.validate_archive(archive)
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = {
            "backup_id": backup_id,
            "username": username,
            "expires_at": time.time() + 300,
        }
        return ticket, {
            "id": manifest["id"],
            "created_at": manifest["created_at"],
            "schema_version": manifest["schema_version"],
            "files": len(manifest["files"]),
        }

    def restore_with_ticket(self, ticket: str, username: str, confirmation: str) -> dict[str, Any]:
        details = self._tickets.pop(ticket, None)
        if (
            details is None
            or details["username"] != username
            or details["expires_at"] < time.time()
            or confirmation != "RESTORE"
        ):
            raise PermissionError("恢复确认已失效或不正确")
        return self.restore_business_data(details["backup_id"])

    def restore_business_data(self, backup_id: str) -> dict[str, Any]:
        with self.lock:
            archive = self.archive_path(backup_id)
            self.validate_archive(archive)
            emergency = self.create_backup(reason="pre_restore")
            with tempfile.TemporaryDirectory(prefix="easystufffind-restore-") as work:
                staging = Path(work)
                with zipfile.ZipFile(archive) as content:
                    content.extractall(staging)
                restored_db = staging / "easystufffind.sqlite3"
                with closing(sqlite3.connect(self.database_path)) as current:
                    account = current.execute("SELECT * FROM web_accounts WHERE id = 1").fetchone()
                    columns = [row[1] for row in current.execute("PRAGMA table_info(web_accounts)")]
                with closing(sqlite3.connect(restored_db)) as restored:
                    if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("恢复数据库完整性检查失败")
                    if account is not None:
                        restored.execute("DELETE FROM web_accounts")
                        placeholders = ",".join("?" for _ in columns)
                        restored.execute(
                            f"INSERT INTO web_accounts ({','.join(columns)}) VALUES ({placeholders})",
                            tuple(account),
                        )
                        restored.commit()
                        restored.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                rollback_db = staging / "rollback.sqlite3"
                shutil.copy2(self.database_path, rollback_db)
                rollback_photos = staging / "rollback-photos"
                if self.photo_dir.is_dir():
                    shutil.copytree(self.photo_dir, rollback_photos)
                incoming_photos = staging / "photos"
                incoming_photos.mkdir(exist_ok=True)
                replacement_photos = self.data_dir / ".photos-restore"
                old_photos = self.data_dir / ".photos-before-restore"
                replacement_db = self.data_dir / ".database-restore"
                shutil.copy2(restored_db, replacement_db)
                shutil.rmtree(replacement_photos, ignore_errors=True)
                shutil.copytree(incoming_photos, replacement_photos)
                try:
                    with closing(sqlite3.connect(self.database_path)) as current:
                        current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    for suffix in ("-wal", "-shm"):
                        Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
                    shutil.rmtree(old_photos, ignore_errors=True)
                    if self.photo_dir.exists():
                        os.replace(self.photo_dir, old_photos)
                    os.replace(replacement_photos, self.photo_dir)
                    os.replace(replacement_db, self.database_path)
                    with closing(sqlite3.connect(self.database_path)) as check:
                        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise RuntimeError("恢复后数据库检查失败")
                except Exception:
                    shutil.copy2(rollback_db, self.database_path)
                    shutil.rmtree(self.photo_dir, ignore_errors=True)
                    if rollback_photos.exists():
                        shutil.copytree(rollback_photos, self.photo_dir)
                    raise
                finally:
                    shutil.rmtree(old_photos, ignore_errors=True)
                    shutil.rmtree(replacement_photos, ignore_errors=True)
                    replacement_db.unlink(missing_ok=True)
            return {"restored": True, "backup_id": backup_id, "emergency_backup": emergency["id"]}

    def _cloud_client(self):
        config = self.load_config()
        required = ("endpoint_url", "region", "bucket", "access_key_id", "secret_access_key")
        if not config.get("cloud_enabled") or any(not config.get(key) for key in required):
            raise ValueError("云对象存储配置不完整")
        if not str(config["endpoint_url"]).startswith("https://"):
            raise ValueError("对象存储地址必须使用 HTTPS")
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=config["endpoint_url"],
            region_name=config["region"],
            aws_access_key_id=config["access_key_id"],
            aws_secret_access_key=config["secret_access_key"],
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                connect_timeout=10,
                read_timeout=60,
                retries={"max_attempts": 3, "mode": "standard"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        return config, client

    def test_cloud(self) -> None:
        config, client = self._cloud_client()
        client.head_bucket(Bucket=config["bucket"])

    def upload_to_cloud(self, archive: Path) -> None:
        config, client = self._cloud_client()
        prefix = str(config["prefix"]).strip("/")
        key = f"{prefix}/{archive.name}" if prefix else archive.name
        with archive.open("rb") as content:
            client.put_object(
                Bucket=config["bucket"],
                Key=key,
                Body=content,
                ContentLength=archive.stat().st_size,
                ServerSideEncryption="AES256",
                ContentType="application/zip",
            )

    def list_cloud(self) -> list[dict[str, Any]]:
        config, client = self._cloud_client()
        prefix = str(config["prefix"]).strip("/")
        response = client.list_objects_v2(
            Bucket=config["bucket"],
            Prefix=f"{prefix}/{BACKUP_PREFIX}" if prefix else BACKUP_PREFIX,
        )
        records = []
        for entry in response.get("Contents", []):
            filename = PurePosixPath(entry["Key"]).name
            if not filename.startswith(BACKUP_PREFIX) or not filename.endswith(".zip"):
                continue
            records.append(
                {
                    "id": filename[:-4],
                    "created_at": entry["LastModified"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "reason": "cloud",
                    "schema_version": None,
                    "bytes": int(entry["Size"]),
                    "source": "cloud",
                    "filename": filename,
                }
            )
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def download_from_cloud(self, backup_id: str) -> Path:
        if not backup_id.startswith(BACKUP_PREFIX) or "/" in backup_id or "\\" in backup_id:
            raise FileNotFoundError("备份不存在")
        config, client = self._cloud_client()
        prefix = str(config["prefix"]).strip("/")
        filename = f"{backup_id}.zip"
        key = f"{prefix}/{filename}" if prefix else filename
        target = self.backup_dir / filename
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.backup_dir, prefix=".cloud-download-", suffix=".zip"
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            client.download_file(config["bucket"], key, str(temporary))
            self.validate_archive(temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except Exception as exc:
            raise FileNotFoundError("云端备份不存在或下载失败") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def prune_local(self) -> None:
        retention = int(self.load_config().get("retention_days", 30))
        if retention == 0:
            return
        cutoff = time.time() - retention * 86400
        for archive in self.backup_dir.glob(f"{BACKUP_PREFIX}*.zip"):
            if archive.stat().st_mtime < cutoff:
                archive.unlink(missing_ok=True)

    def scheduled_slot(self, now: datetime | None = None) -> str | None:
        now = now or datetime.now().astimezone()
        config = self.load_config()
        frequency = config.get("frequency", "off")
        if frequency == "off":
            return None
        hour, minute = (int(value) for value in str(config.get("time", "03:00")).split(":"))
        if (now.hour, now.minute) < (hour, minute):
            return None
        if frequency == "weekly" and now.isoweekday() != int(config.get("weekday", 1)):
            return None
        if frequency == "monthly" and now.day != int(config.get("monthday", 1)):
            return None
        if frequency == "daily":
            return now.strftime("daily:%Y-%m-%d")
        if frequency == "weekly":
            return now.strftime("weekly:%G-W%V")
        return now.strftime("monthly:%Y-%m")

    def run_scheduled_if_due(self) -> bool:
        slot = self.scheduled_slot()
        if not slot:
            return False
        config = self.load_config()
        if config.get("last_scheduled_slot") == slot:
            return False
        self.create_backup(upload_cloud=bool(config.get("cloud_enabled")), reason="scheduled")
        self.save_config({"last_scheduled_slot": slot})
        return True
