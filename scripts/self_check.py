#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SelfCheckError(RuntimeError):
    pass


def request_json(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        with exc:
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
                message = error_body.get("error", {}).get("message", f"HTTP {exc.code}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                message = f"HTTP {exc.code}"
        raise SelfCheckError(f"{method} {path} 失败：{message}") from exc
    except URLError as exc:
        raise SelfCheckError(f"无法连接服务：{exc.reason}") from exc


def run_check(base_url: str, token_file: Path, timeout: float) -> None:
    if not token_file.is_file():
        raise SelfCheckError(f"token 文件不存在：{token_file}")
    token = token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SelfCheckError(f"token 文件无效：{token_file}")

    marker = uuid.uuid4().hex[:12]
    item_name = f"EasyStuffFind自检物品-{marker}"
    alias = f"esf-check-{marker}"
    location_path = f"EasyStuffFind自检区{marker}-临时层级-临时容器"
    item_id: int | None = None
    location_ids: list[int] = []

    try:
        created = request_json(
            base_url,
            token,
            "POST",
            "/api/v1/items/upsert",
            {
                "name": item_name,
                "aliases": [alias],
                "location_path": location_path,
                "note": "自动自检数据，可安全删除",
            },
            timeout,
        )
        if created.get("action") != "created":
            raise SelfCheckError("记录步骤未创建测试物品")
        item = created["item"]
        item_id = int(item["id"])
        if item["location"]["path"] != location_path:
            raise SelfCheckError("记录步骤返回的位置路径不一致")

        location = request_json(
            base_url,
            token,
            "GET",
            f"/api/v1/locations/{item['location']['id']}",
            timeout=timeout,
        )["location"]
        while location:
            location_ids.append(int(location["id"]))
            parent_id = location.get("parent_id")
            if parent_id is None:
                break
            location = request_json(
                base_url,
                token,
                "GET",
                f"/api/v1/locations/{parent_id}",
                timeout=timeout,
            )["location"]

        queried = request_json(
            base_url,
            token,
            "GET",
            f"/api/v1/items/search?q={alias}",
            timeout=timeout,
        )
        if queried.get("status") != "unique" or queried.get("item", {}).get("id") != item_id:
            raise SelfCheckError("查询步骤未唯一命中测试物品")

        request_json(
            base_url,
            token,
            "DELETE",
            f"/api/v1/items/{item_id}",
            timeout=timeout,
        )
        item_id = None
        for location_id in location_ids:
            request_json(
                base_url,
                token,
                "DELETE",
                f"/api/v1/locations/{location_id}",
                timeout=timeout,
            )
        location_ids.clear()
        print("PASS EasyStuffFind 自检：记录 → 别名查询 → 删除闭环通过")
        print(f"服务地址：{base_url.rstrip('/')}")
        print(f"token 位置：{token_file}")
    finally:
        if item_id is not None:
            try:
                request_json(
                    base_url,
                    token,
                    "DELETE",
                    f"/api/v1/items/{item_id}",
                    timeout=timeout,
                )
            except SelfCheckError:
                pass
        for location_id in location_ids:
            try:
                request_json(
                    base_url,
                    token,
                    "DELETE",
                    f"/api/v1/locations/{location_id}",
                    timeout=timeout,
                )
            except SelfCheckError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyStuffFind API 闭环自检")
    parser.add_argument("--base-url", default="http://127.0.0.1:8733")
    parser.add_argument("--token-file", type=Path, default=Path("data/api-token"))
    parser.add_argument("--timeout", type=float, default=10)
    arguments = parser.parse_args()
    try:
        run_check(arguments.base_url, arguments.token_file, arguments.timeout)
    except SelfCheckError as exc:
        print(f"FAIL EasyStuffFind 自检：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
