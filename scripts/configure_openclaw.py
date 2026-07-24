#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


SKILL_NAME = "easystufffind"


def openclaw_command(profile: str | None, *arguments: str) -> list[str]:
    command = ["openclaw"]
    if profile:
        command.extend(["--profile", profile])
    command.extend(arguments)
    return command


def run(command: list[str], label: str) -> None:
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{label}失败，退出码 {result.returncode}")
    print(f"PASS {label}")


def capture_json(command: list[str], label: str) -> Any:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label}失败，退出码 {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label}没有返回有效 JSON") from exc


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_agent_id(
    explicit_agent: str | None,
    agents: list[dict[str, Any]],
    project_root: Path,
    environment: dict[str, str],
) -> str:
    agent_ids = {
        str(agent.get("id", "")).strip()
        for agent in agents
        if str(agent.get("id", "")).strip()
    }
    if explicit_agent:
        if explicit_agent not in agent_ids:
            raise RuntimeError(f"OpenClaw agent 不存在：{explicit_agent}")
        return explicit_agent

    candidate_ids: set[str] = set()
    location_hints: list[tuple[str, Path]] = [("workspace", project_root)]
    workspace_override = environment.get("OPENCLAW_WORKSPACE_DIR", "").strip()
    if workspace_override:
        location_hints.append(
            ("workspace", Path(workspace_override).expanduser().resolve())
        )
    agent_dir_override = environment.get("OPENCLAW_AGENT_DIR", "").strip()
    if agent_dir_override:
        location_hints.append(
            ("agentDir", Path(agent_dir_override).expanduser().resolve())
        )

    for agent in agents:
        agent_id = str(agent.get("id", "")).strip()
        if not agent_id:
            continue
        for field, hint in location_hints:
            raw_location = str(agent.get(field, "")).strip()
            if not raw_location:
                continue
            configured_location = Path(raw_location).expanduser().resolve()
            if field == "workspace":
                if path_is_within(hint, configured_location):
                    candidate_ids.add(agent_id)
            elif hint == configured_location:
                candidate_ids.add(agent_id)

    if len(candidate_ids) == 1:
        return candidate_ids.pop()
    if len(agents) == 1 and agent_ids:
        return next(iter(agent_ids))

    available = "、".join(sorted(agent_ids)) or "无"
    raise RuntimeError(
        "无法从当前 OpenClaw workspace 唯一确定正在对话的 agent；"
        f"可用 agent：{available}。请由当前 OpenClaw agent 使用自身 ID 重跑 "
        "`--agent <id>`，不要让用户选择，也不要批量授权其他 agent"
    )


def validate_token_file(token_file: Path) -> str:
    if not token_file.is_file():
        raise RuntimeError(f"token 文件不存在：{token_file}")
    file_stat = token_file.stat()
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode != 0o600:
        raise RuntimeError(
            f"token 文件权限必须是 0600，当前是 {mode:04o}：{token_file}"
        )
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise RuntimeError(f"token 文件不属于当前用户：{token_file}")
    if not os.access(token_file, os.R_OK):
        raise RuntimeError(f"token 文件不可读：{token_file}")
    token = token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError(f"token 文件无效：{token_file}")
    return token


def verify_service(base_url: str, token: str) -> None:
    try:
        with urlopen(f"{base_url}/health", timeout=10) as response:
            health = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or health.get("status") != "ok":
            raise RuntimeError("健康检查没有返回 status=ok")

        marker = quote(f"EasyStuffFind对接验证-{uuid.uuid4().hex}")
        request = Request(
            f"{base_url}/api/v1/items/search?q={marker}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=10) as response:
            query = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or query.get("status") != "none":
            raise RuntimeError("认证查询没有返回预期的空结果")
    except HTTPError as exc:
        raise RuntimeError(f"EasyStuffFind API 验证失败：HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"无法连接 EasyStuffFind：{reason}") from exc
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RuntimeError("EasyStuffFind 返回了无效 JSON") from exc
    print("PASS EasyStuffFind 健康检查与认证查询")


def target_skill_update(
    agents_config: dict[str, Any],
    target_agent: str,
) -> tuple[str, list[str]] | None:
    defaults = agents_config.get("defaults")
    defaults = defaults if isinstance(defaults, dict) else {}
    default_skills = defaults.get("skills")
    default_skills = default_skills if isinstance(default_skills, list) else None

    entries = agents_config.get("list")
    entries = entries if isinstance(entries, list) else []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get("id") != target_agent:
            continue
        if "skills" in entry:
            skills = entry.get("skills")
            if not isinstance(skills, list):
                raise RuntimeError(f"agent {target_agent} 的 skills 配置不是数组")
            if SKILL_NAME in skills:
                return None
            return f"agents.list[{index}].skills", [*skills, SKILL_NAME]
        if default_skills is None or SKILL_NAME in default_skills:
            return None
        return f"agents.list[{index}].skills", [*default_skills, SKILL_NAME]

    if default_skills is None or SKILL_NAME in default_skills:
        return None
    raise RuntimeError(
        f"agent {target_agent} 没有独立配置项，无法在不影响其他 agent 的前提下"
        "扩展默认 Skill allowlist"
    )


def verify_agent_visibility(
    profile: str | None,
    target_agent: str,
) -> None:
    result = capture_json(
        openclaw_command(
            profile,
            "skills",
            "check",
            "--agent",
            target_agent,
            "--json",
        ),
        "检查目标 agent 的 Skill 可见性",
    )
    eligible = result.get("eligible", [])
    model_visible = result.get("modelVisible", [])
    if SKILL_NAME not in eligible or SKILL_NAME not in model_visible:
        raise RuntimeError(
            f"Skill 已安装但对 agent {target_agent} 不可见；"
            "请检查该 agent 的 skills allowlist 和 Skill requirements"
        )
    print(f"PASS 目标 agent 可见 EasyStuffFind Skill：{target_agent}")


def main() -> int:
    parser = argparse.ArgumentParser(description="安装并配置 EasyStuffFind OpenClaw Skill")
    parser.add_argument("--base-url", default="http://127.0.0.1:8733")
    parser.add_argument("--token-file", type=Path, default=Path("data/api-token"))
    parser.add_argument(
        "--agent",
        help="目标 OpenClaw agent；省略时从当前 workspace 自动识别",
    )
    parser.add_argument(
        "--profile",
        help="目标 OpenClaw profile；省略时沿用 OPENCLAW_PROFILE 或默认 profile",
    )
    arguments = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    skill_dir = project_root / "skills" / "openclaw"
    token_file = (
        arguments.token_file
        if arguments.token_file.is_absolute()
        else project_root / arguments.token_file
    ).resolve()
    base_url = arguments.base_url.rstrip("/")

    try:
        if shutil.which("openclaw") is None:
            raise RuntimeError("未找到 openclaw CLI；请先完成 OpenClaw 安装")
        token = validate_token_file(token_file)
        verify_service(base_url, token)

        agents = capture_json(
            openclaw_command(arguments.profile, "agents", "list", "--json"),
            "读取 OpenClaw agent 列表",
        )
        if not isinstance(agents, list):
            raise RuntimeError("OpenClaw agent 列表格式无效")
        target_agent = resolve_agent_id(
            arguments.agent,
            agents,
            project_root,
            dict(os.environ),
        )
        print(f"PASS 已确定当前 OpenClaw agent：{target_agent}")

        agents_config = capture_json(
            openclaw_command(
                arguments.profile,
                "config",
                "get",
                "agents",
                "--json",
            ),
            "读取 agent 技能过滤配置",
        )
        if not isinstance(agents_config, dict):
            raise RuntimeError("OpenClaw agents 配置格式无效")

        run(
            openclaw_command(
                arguments.profile,
                "skills",
                "install",
                str(skill_dir),
                "--as",
                SKILL_NAME,
                "--agent",
                target_agent,
                "--force",
            ),
            f"安装 EasyStuffFind Skill 到 agent {target_agent}",
        )

        update = target_skill_update(agents_config, target_agent)
        if update:
            config_path, skills = update
            run(
                openclaw_command(
                    arguments.profile,
                    "config",
                    "set",
                    config_path,
                    json.dumps(skills, ensure_ascii=False, separators=(",", ":")),
                    "--strict-json",
                    "--replace",
                ),
                f"授权 agent {target_agent} 使用 EasyStuffFind",
            )
        else:
            print(f"PASS agent {target_agent} 无需修改 Skill allowlist")

        environment = json.dumps(
            {
                "EASYSTUFFFIND_BASE_URL": base_url,
                "EASYSTUFFFIND_TOKEN_FILE": str(token_file),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        run(
            openclaw_command(
                arguments.profile,
                "config",
                "set",
                f"skills.entries.{SKILL_NAME}.env",
                environment,
                "--strict-json",
                "--merge",
            ),
            "写入 Skill 环境引用",
        )
        run(
            openclaw_command(arguments.profile, "config", "validate"),
            "校验 OpenClaw 配置",
        )
        verify_agent_visibility(arguments.profile, target_agent)
    except (OSError, RuntimeError) as exc:
        print(f"FAIL OpenClaw 对接：{exc}", file=sys.stderr)
        return 1

    print(
        "PASS OpenClaw 对接完成；"
        f"agent={target_agent}；下一轮对话起可直接使用；"
        "token 仅由文件路径引用，未写入配置明文。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
