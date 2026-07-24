#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(data_dir: Path, output_root: Path) -> Path:
    database_path = data_dir / "easystufffind.sqlite3"
    token_path = data_dir / "api-token"
    photo_dir = data_dir / "photos"
    if not database_path.is_file():
        raise RuntimeError(f"数据库不存在：{database_path}")
    if not token_path.is_file():
        raise RuntimeError(f"token 文件不存在：{token_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = output_root / f"easystufffind-backup-{timestamp}"
    bundle.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(bundle, 0o700)

    destination_database = bundle / "easystufffind.sqlite3"
    with sqlite3.connect(database_path) as source, sqlite3.connect(
        destination_database
    ) as destination:
        source.backup(destination)
    with sqlite3.connect(destination_database) as verification:
        integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
        schema_version = int(verification.execute("PRAGMA user_version").fetchone()[0])
    if integrity != "ok":
        raise RuntimeError("备份数据库完整性检查失败")

    destination_photos = bundle / "photos"
    if photo_dir.is_dir():
        shutil.copytree(photo_dir, destination_photos)
    else:
        destination_photos.mkdir(mode=0o700)
    shutil.copy2(token_path, bundle / "api-token")
    os.chmod(bundle / "api-token", 0o600)

    photos = sorted(path for path in destination_photos.iterdir() if path.is_file())
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": schema_version,
        "database": {
            "path": destination_database.name,
            "sha256": sha256_file(destination_database),
            "bytes": destination_database.stat().st_size,
        },
        "token": {
            "path": "api-token",
            "sha256": sha256_file(bundle / "api-token"),
        },
        "photos": [
            {
                "path": f"photos/{path.name}",
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in photos
        ],
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="一致性备份 EasyStuffFind 数据")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    arguments = parser.parse_args()
    try:
        arguments.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        bundle = backup(arguments.data_dir.resolve(), arguments.output_dir.resolve())
    except Exception as exc:
        print(f"FAIL 备份失败：{exc}", file=sys.stderr)
        return 1
    print(f"PASS 备份完成：{bundle}")
    print("已使用 SQLite backup API，并验证数据库完整性和文件校验值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
