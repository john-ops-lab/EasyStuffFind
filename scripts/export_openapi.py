#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from easystufffind.api import app


def rendered_contract() -> str:
    return json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 EasyStuffFind OpenAPI 契约")
    parser.add_argument("--check", action="store_true", help="只检查契约是否最新")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("contracts/openapi.json"),
    )
    arguments = parser.parse_args()
    expected = rendered_contract()
    if arguments.check:
        if not arguments.output.is_file():
            print(f"FAIL 契约文件不存在：{arguments.output}", file=sys.stderr)
            return 1
        if arguments.output.read_text(encoding="utf-8") != expected:
            print(f"FAIL 契约已漂移：{arguments.output}", file=sys.stderr)
            return 1
        print(f"PASS 契约一致：{arguments.output}")
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(expected, encoding="utf-8")
    print(f"OpenAPI 已写入：{arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
