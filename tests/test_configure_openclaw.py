from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "configure_openclaw.py"
SPEC = importlib.util.spec_from_file_location("configure_openclaw", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("无法加载 configure_openclaw.py")
CONFIGURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIGURE)


class ApiHandler(BaseHTTPRequestHandler):
    token = ""

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json({"status": "ok"})
            return
        if self.path.startswith("/api/v1/items/search?"):
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self.send_json({"error": {"code": "unauthorized"}}, status=401)
                return
            self.send_json({"status": "none", "count": 0, "candidates": []})
            return
        self.send_json({"error": {"code": "not_found"}}, status=404)

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class ConfigureOpenClawTestCase(unittest.TestCase):
    def test_resolve_agent_from_project_workspace(self) -> None:
        agents = [
            {"id": "main", "workspace": "/tmp/main-workspace"},
            {"id": "dongdong", "workspace": str(PROJECT_ROOT.parent)},
        ]
        resolved = CONFIGURE.resolve_agent_id(
            None,
            agents,
            PROJECT_ROOT,
            {},
        )
        self.assertEqual(resolved, "dongdong")

    def test_ambiguous_agent_requires_agent_context(self) -> None:
        agents = [
            {"id": "main", "workspace": "/tmp/main-workspace"},
            {"id": "dongdong", "workspace": "/tmp/dongdong-workspace"},
        ]
        with self.assertRaises(RuntimeError):
            CONFIGURE.resolve_agent_id(
                None,
                agents,
                PROJECT_ROOT,
                {},
            )

    def test_explicit_agent_resolves_outside_workspace(self) -> None:
        agents = [
            {"id": "main", "workspace": "/tmp/main-workspace"},
            {"id": "dongdong", "workspace": "/tmp/dongdong-workspace"},
        ]
        self.assertEqual(
            CONFIGURE.resolve_agent_id(
                "dongdong",
                agents,
                PROJECT_ROOT,
                {},
            ),
            "dongdong",
        )

    def test_allowlist_update_is_limited_to_target_agent(self) -> None:
        agents_config = {
            "defaults": {"skills": ["shared"]},
            "list": [
                {"id": "main", "skills": ["main-only"]},
                {"id": "dongdong"},
            ],
        }
        update = CONFIGURE.target_skill_update(agents_config, "dongdong")
        self.assertEqual(
            update,
            ("agents.list[1].skills", ["shared", "easystufffind"]),
        )
        self.assertEqual(agents_config["list"][0]["skills"], ["main-only"])

    def test_unrestricted_agent_does_not_gain_explicit_allowlist(self) -> None:
        self.assertIsNone(
            CONFIGURE.target_skill_update(
                {
                    "defaults": {},
                    "list": [{"id": "dongdong"}],
                },
                "dongdong",
            )
        )

    def test_restricted_defaults_are_not_changed_for_missing_agent_entry(self) -> None:
        with self.assertRaises(RuntimeError):
            CONFIGURE.target_skill_update(
                {
                    "defaults": {"skills": ["shared"]},
                    "list": [{"id": "other"}],
                },
                "dongdong",
            )

    def test_full_configuration_targets_current_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            token = "T" * 64
            token_file = root / "api-token"
            token_file.write_text(token, encoding="utf-8")
            token_file.chmod(0o600)
            log_file = root / "commands.jsonl"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_openclaw = bin_dir / "openclaw"
            fake_openclaw.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys

                    args = sys.argv[1:]
                    if args[:1] == ["--profile"]:
                        args = args[2:]
                    with open(os.environ["FAKE_OPENCLAW_LOG"], "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(args, ensure_ascii=False) + "\\n")
                    if args == ["agents", "list", "--json"]:
                        print(os.environ["FAKE_AGENTS_JSON"])
                    elif args == ["config", "get", "agents", "--json"]:
                        print(os.environ["FAKE_AGENTS_CONFIG_JSON"])
                    elif args[:2] == ["skills", "check"]:
                        print(json.dumps({
                            "eligible": ["easystufffind"],
                            "modelVisible": ["easystufffind"],
                            "commandVisible": ["easystufffind"],
                        }))
                    sys.exit(0)
                    """
                ),
                encoding="utf-8",
            )
            fake_openclaw.chmod(0o755)

            ApiHandler.token = token
            server = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                environment = os.environ.copy()
                environment.update(
                    {
                        "PATH": f"{bin_dir}{os.pathsep}{environment['PATH']}",
                        "FAKE_OPENCLAW_LOG": str(log_file),
                        "FAKE_AGENTS_JSON": json.dumps(
                            [
                                {
                                    "id": "dongdong",
                                    "workspace": str(PROJECT_ROOT.parent),
                                },
                                {
                                    "id": "main",
                                    "workspace": "/tmp/main-workspace",
                                },
                            ]
                        ),
                        "FAKE_AGENTS_CONFIG_JSON": json.dumps(
                            {
                                "defaults": {},
                                "list": [
                                    {"id": "dongdong", "skills": ["existing"]},
                                    {"id": "main", "skills": ["main-only"]},
                                ],
                            }
                        ),
                    }
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_PATH),
                        "--base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--token-file",
                        str(token_file),
                        "--profile",
                        "family",
                    ],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("agent=dongdong", result.stdout)
            self.assertNotIn(token, result.stdout)
            self.assertNotIn(token, result.stderr)

            commands = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            install = next(command for command in commands if command[:2] == ["skills", "install"])
            self.assertIn("--agent", install)
            self.assertEqual(install[install.index("--agent") + 1], "dongdong")
            self.assertIn("--force", install)
            self.assertFalse(
                any(command[:2] == ["gateway", "restart"] for command in commands)
            )

            allowlist_set = next(
                command
                for command in commands
                if command[:3]
                == ["config", "set", "agents.list[0].skills"]
            )
            self.assertEqual(
                json.loads(allowlist_set[3]),
                ["existing", "easystufffind"],
            )
            self.assertIn("--replace", allowlist_set)
            environment_set = next(
                command
                for command in commands
                if command[:3]
                == ["config", "set", "skills.entries.easystufffind.env"]
            )
            self.assertIn("--merge", environment_set)
            self.assertNotIn(token, log_file.read_text(encoding="utf-8"))

    def test_token_permissions_must_be_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            token_file = Path(temporary) / "api-token"
            token_file.write_text("T" * 64, encoding="utf-8")
            token_file.chmod(0o644)
            with self.assertRaises(RuntimeError):
                CONFIGURE.validate_token_file(token_file)


if __name__ == "__main__":
    unittest.main()
