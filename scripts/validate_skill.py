#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def validate(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return ["SKILL.md 不存在"]
    content = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not match:
        return ["YAML frontmatter 缺失或格式错误"]
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            errors.append(f"frontmatter 行无效：{line}")
            continue
        fields[key.strip()] = value.strip()
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not re.fullmatch(r"[a-z0-9-]{1,63}", name):
        errors.append("name 必须是 1–63 位小写字母、数字或连字符")
    if not description or description.startswith("[TODO"):
        errors.append("description 缺失")
    if "[TODO" in content:
        errors.append("仍包含 TODO 占位")
    if len(content.splitlines()) > 500:
        errors.append("SKILL.md 超过 500 行")
    client = skill_dir / "scripts" / "client.py"
    if not client.is_file():
        errors.append("scripts/client.py 缺失")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验仓库内 Agent Skill")
    parser.add_argument("skill_dir", type=Path)
    arguments = parser.parse_args()
    errors = validate(arguments.skill_dir)
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"PASS Skill 有效：{arguments.skill_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
