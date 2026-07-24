#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="等待 EasyStuffFind 健康")
    parser.add_argument("--url", default="http://127.0.0.1:8733/health")
    parser.add_argument("--timeout", type=float, default=60)
    arguments = parser.parse_args()
    deadline = time.monotonic() + arguments.timeout
    last_error = "尚未响应"
    while time.monotonic() < deadline:
        try:
            with urlopen(arguments.url, timeout=3) as response:
                body = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and body.get("status") == "ok":
                    print(
                        f"PASS 服务健康：{arguments.url} "
                        f"(version={body.get('version')}, schema={body.get('schema_version')})"
                    )
                    return 0
                last_error = f"HTTP {response.status}: {body.get('status')}"
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    print(f"FAIL 健康检查超时：{last_error}", file=sys.stderr)
    print("排查：运行 docker compose logs --tail=100 easystufffind", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
