#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bundle(bundle: Path) -> dict:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("备份清单不存在")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [manifest["database"], manifest["token"], *manifest["photos"]]
    for entry in entries:
        path = bundle / entry["path"]
        if not path.is_file():
            raise RuntimeError(f"备份文件缺失：{entry['path']}")
        if sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"备份校验失败：{entry['path']}")
    with sqlite3.connect(bundle / manifest["database"]["path"]) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("备份数据库完整性检查失败")
    return manifest


def restore(bundle: Path, target: Path) -> None:
    manifest = validate_bundle(bundle)
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("目标目录不是空目录；请先停服并把现有数据目录移到安全位置")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    shutil.copy2(bundle / manifest["database"]["path"], target / "easystufffind.sqlite3")
    shutil.copy2(bundle / manifest["token"]["path"], target / "api-token")
    os.chmod(target / "api-token", 0o600)
    (target / "photos").mkdir(mode=0o700)
    for entry in manifest["photos"]:
        shutil.copy2(bundle / entry["path"], target / "photos" / Path(entry["path"]).name)


def main() -> int:
    parser = argparse.ArgumentParser(description="恢复 EasyStuffFind 备份到空目录")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        restore(arguments.backup.resolve(), arguments.target.resolve())
    except Exception as exc:
        print(f"FAIL 恢复失败：{exc}", file=sys.stderr)
        return 1
    print(f"PASS 恢复完成：{arguments.target.resolve()}")
    print("启动服务并运行 self_check.py 后再替换真实数据目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
