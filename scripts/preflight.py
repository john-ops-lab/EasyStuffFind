#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def run(command: list[str], label: str) -> None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label}失败：{exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{label}失败：{detail}")
    print(f"PASS {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyStuffFind 安装前检查")
    parser.add_argument("--port", type=int, default=8733)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    arguments = parser.parse_args()
    try:
        if shutil.which("docker") is None:
            raise RuntimeError(
                "未找到 Docker。请安装 Docker Desktop，启动后重新运行本命令"
            )
        run(["docker", "info"], "Docker daemon")
        run(["docker", "compose", "version"], "Docker Compose")

        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("0.0.0.0", arguments.port))
            except OSError as exc:
                raise RuntimeError(
                    f"端口 {arguments.port} 已被占用；停止占用进程后重试"
                ) from exc
        print(f"PASS 端口 {arguments.port} 可用")

        arguments.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        test_file = arguments.data_dir / ".write-test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print(f"PASS 数据目录可写：{arguments.data_dir.resolve()}")

        env_path = Path(".env")
        existing_lines = (
            env_path.read_text(encoding="utf-8").splitlines()
            if env_path.is_file()
            else []
        )
        managed_prefixes = ("EASYSTUFFFIND_UID=", "EASYSTUFFFIND_GID=")
        preserved_lines = [
            line for line in existing_lines if not line.startswith(managed_prefixes)
        ]
        preserved_lines.extend(
            [
                f"EASYSTUFFFIND_UID={os.getuid()}",
                f"EASYSTUFFFIND_GID={os.getgid()}",
            ]
        )
        env_path.write_text("\n".join(preserved_lines) + "\n", encoding="utf-8")
        print("PASS 容器用户映射已写入本地 .env（不含 Secret）")
    except RuntimeError as exc:
        print(f"FAIL 安装前检查：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
