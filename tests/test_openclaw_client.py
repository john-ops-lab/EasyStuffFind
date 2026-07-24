from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
CLIENT_PATH = PROJECT_ROOT / "skills" / "openclaw" / "scripts" / "client.py"


class PhotoApiHandler(BaseHTTPRequestHandler):
    token = "T" * 64
    has_photo = False
    uploaded_body = b""

    def do_GET(self) -> None:
        if self.path == "/api/v1/items/11":
            self.send_item()
            return
        self.send_json({"error": {"code": "not_found"}}, status=404)

    def do_PUT(self) -> None:
        if self.path != "/api/v1/items/11/photo":
            self.send_json({"error": {"code": "not_found"}}, status=404)
            return
        PhotoApiHandler.uploaded_body = self.rfile.read(
            int(self.headers.get("Content-Length", "0"))
        )
        PhotoApiHandler.has_photo = True
        self.send_item()

    def send_item(self) -> None:
        photo = (
            {"content_type": "image/jpeg", "updated_at": "2026-07-24T10:00:00Z"}
            if self.has_photo
            else None
        )
        self.send_json(
            {
                "item": {
                    "id": 11,
                    "name": "测试布袋",
                    "photo": photo,
                    "photo_url": (
                        "http://127.0.0.1/media/items/11/photo?"
                        "expires=1&signature=SECRET_SIGNATURE"
                        if self.has_photo
                        else None
                    ),
                }
            }
        )

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class OpenClawClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        PhotoApiHandler.has_photo = False
        PhotoApiHandler.uploaded_body = b""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PhotoApiHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.token_file = root / "api-token"
        self.token_file.write_text(PhotoApiHandler.token, encoding="utf-8")
        self.token_file.chmod(0o600)
        self.photo_file = root / "photo.jpg"
        self.photo_file.write_bytes(b"safe-test-photo")
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "EASYSTUFFFIND_BASE_URL": f"http://127.0.0.1:{self.server.server_port}",
                "EASYSTUFFFIND_TOKEN_FILE": str(self.token_file),
            }
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def run_client(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLIENT_PATH), *arguments],
            cwd=PROJECT_ROOT,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_verify_photo_fails_when_photo_is_absent(self) -> None:
        result = self.run_client("verify-photo", "11")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("照片尚未保存", result.stderr)

    def test_photo_upload_is_verified_without_printing_signed_url(self) -> None:
        result = self.run_client(
            "photo",
            "11",
            str(self.photo_file),
            "--content-type",
            "image/jpeg",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(PhotoApiHandler.uploaded_body, b"safe-test-photo")
        self.assertIn('"verified": true', result.stdout)
        self.assertIn('"item_id": 11', result.stdout)
        self.assertNotIn("signature", result.stdout)
        self.assertNotIn("SECRET_SIGNATURE", result.stdout)


if __name__ == "__main__":
    unittest.main()
