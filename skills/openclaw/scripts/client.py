#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def connection() -> tuple[str, str]:
    base_url = os.getenv("EASYSTUFFFIND_BASE_URL", "").rstrip("/")
    token_path_text = os.getenv("EASYSTUFFFIND_TOKEN_FILE", "")
    if not base_url:
        raise RuntimeError("缺少 EASYSTUFFFIND_BASE_URL")
    if not token_path_text:
        raise RuntimeError("缺少 EASYSTUFFFIND_TOKEN_FILE")
    token_path = Path(token_path_text).expanduser()
    if not token_path.is_file():
        raise RuntimeError(f"token 文件不存在：{token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError(f"token 文件无效：{token_path}")
    return base_url, token


def send(
    method: str,
    path: str,
    body: bytes | None = None,
    content_type: str = "application/json",
    *,
    print_body: bool = True,
) -> int:
    base_url, token = connection()
    if not path.startswith("/api/v1/"):
        raise RuntimeError("业务请求路径必须以 /api/v1/ 开头")
    request = Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read()
            if payload and print_body:
                print(payload.decode("utf-8"))
            return 0
    except HTTPError as exc:
        with exc:
            payload = exc.read()
            if payload:
                print(payload.decode("utf-8"), file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"无法连接 EasyStuffFind：{exc.reason}", file=sys.stderr)
        return 1


def verify_photo(item_id: int) -> int:
    base_url, token = connection()
    request = Request(
        f"{base_url}/api/v1/items/{item_id}",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        with exc:
            body = exc.read()
            if body:
                print(body.decode("utf-8"), file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"无法连接 EasyStuffFind：{exc.reason}", file=sys.stderr)
        return 1

    item = payload.get("item") if isinstance(payload, dict) else None
    if not isinstance(item, dict) or not item.get("photo") or not item.get("photo_url"):
        print(f"照片尚未保存：item_id={item_id}", file=sys.stderr)
        return 1
    photo = item["photo"]
    print(
        json.dumps(
            {
                "verified": True,
                "item_id": item_id,
                "photo_saved": True,
                "photo_updated_at": (
                    photo.get("updated_at") if isinstance(photo, dict) else None
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


def health() -> int:
    base_url, _ = connection()
    try:
        with urlopen(f"{base_url}/health", timeout=10) as response:
            payload = response.read().decode("utf-8")
            print(payload)
            return 0 if response.status == 200 else 1
    except URLError as exc:
        print(f"无法连接 EasyStuffFind：{exc.reason}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyStuffFind OpenClaw HTTP 客户端")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health")

    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("method", choices=["GET", "POST", "PATCH", "DELETE"])
    request_parser.add_argument("path")
    request_parser.add_argument("--json")

    photo_parser = subparsers.add_parser("photo")
    photo_parser.add_argument("item_id", type=int)
    photo_parser.add_argument("file", type=Path)
    photo_parser.add_argument(
        "--content-type",
        required=True,
        choices=["image/jpeg", "image/png", "image/webp", "image/gif"],
    )
    verify_photo_parser = subparsers.add_parser("verify-photo")
    verify_photo_parser.add_argument("item_id", type=int)
    arguments = parser.parse_args()

    try:
        if arguments.command == "health":
            return health()
        if arguments.command == "request":
            body = arguments.json.encode("utf-8") if arguments.json else None
            return send(arguments.method, arguments.path, body)
        if arguments.command == "verify-photo":
            return verify_photo(arguments.item_id)
        if not arguments.file.is_file():
            raise RuntimeError(f"图片不存在：{arguments.file}")
        uploaded = send(
            "PUT",
            f"/api/v1/items/{arguments.item_id}/photo",
            arguments.file.read_bytes(),
            arguments.content_type,
            print_body=False,
        )
        return uploaded or verify_photo(arguments.item_id)
    except (RuntimeError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"EasyStuffFind 客户端失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
