from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class LiveApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temporary.name)
        cls.port = free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        environment = os.environ.copy()
        environment.update(
            {
                "EASYSTUFFFIND_DATA_DIR": str(cls.data_dir),
                "EASYSTUFFFIND_HOST": "127.0.0.1",
                "EASYSTUFFFIND_PORT": str(cls.port),
                "EASYSTUFFFIND_LOG_LEVEL": "INFO",
            }
        )
        cls.process = subprocess.Popen(
            [os.environ.get("PYTHON", os.sys.executable), "-m", "easystufffind"],
            cwd=Path(__file__).parents[1],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if cls.process.poll() is not None:
                output = cls.process.stdout.read() if cls.process.stdout else ""
                raise RuntimeError(f"测试服务提前退出：{output}")
            try:
                with urlopen(f"{cls.base_url}/health", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            cls.process.terminate()
            raise RuntimeError("测试服务启动超时")
        cls.token = (cls.data_dir / "api-token").read_text(encoding="utf-8").strip()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.terminate()
        try:
            output, _ = cls.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            output, _ = cls.process.communicate(timeout=5)
        if cls.token and cls.token in output:
            raise AssertionError("服务日志泄露了 API token")
        cls.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | bytes | None = None,
        content_type: str = "application/json",
        authenticated: bool = True,
    ) -> tuple[int, dict[str, Any] | bytes]:
        if isinstance(payload, dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            body = payload
        headers = {"Content-Type": content_type}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=5) as response:
                response_body = response.read()
                if "application/json" in response.headers.get("content-type", ""):
                    return response.status, json.loads(response_body.decode("utf-8"))
                return response.status, response_body
        except HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_complete_api_flow(self) -> None:
        with urlopen(f"{self.base_url}/openapi.json", timeout=5) as response:
            openapi = json.loads(response.read().decode("utf-8"))
        validation_descriptions = {
            operation["responses"]["422"]["description"]
            for path in openapi["paths"].values()
            for operation in path.values()
            if "422" in operation.get("responses", {})
        }
        self.assertEqual(validation_descriptions, {"Unprocessable Content"})

        status, unauthorized = self.request("GET", "/api/v1/items", authenticated=False)
        self.assertEqual(status, 401)
        self.assertEqual(unauthorized["error"]["code"], "unauthorized")

        status, created = self.request(
            "POST",
            "/api/v1/items/upsert",
            {
                "name": "护照",
                "aliases": ["passport"],
                "location_path": "书房-书桌-第二个抽屉",
                "note": "红色护照",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(created["action"], "created")
        item_id = created["item"]["id"]

        status, queried = self.request("GET", "/api/v1/items/search?q=passport")
        self.assertEqual(status, 200)
        self.assertEqual(queried["status"], "unique")
        self.assertEqual(queried["item"]["id"], item_id)

        status, uploaded = self.request(
            "PUT",
            f"/api/v1/items/{item_id}/photo",
            PNG_1X1,
            content_type="image/png",
        )
        self.assertEqual(status, 200)
        photo_url = uploaded["item"]["photo_url"]
        self.assertNotIn(self.token, photo_url)
        with urlopen(photo_url, timeout=5) as response:
            self.assertEqual(response.read(), PNG_1X1)
            self.assertEqual(response.headers.get_content_type(), "image/png")

        status, moved = self.request(
            "POST",
            f"/api/v1/items/{item_id}/move",
            {"location_path": "卧室-保险柜"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(moved["item"]["location"]["path"], "卧室-保险柜")
        status, history = self.request("GET", f"/api/v1/items/{item_id}/history")
        self.assertEqual(status, 200)
        self.assertEqual(history["history"][0]["old_location_path"], "书房-书桌-第二个抽屉")

        status, conflict = self.request(
            "DELETE",
            f"/api/v1/locations/{moved['item']['location']['id']}",
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"]["code"], "location_not_empty")

        status, deleted = self.request("DELETE", f"/api/v1/items/{item_id}")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(list((self.data_dir / "photos").iterdir()), [])

    def test_three_query_states_and_ambiguous_upsert(self) -> None:
        item_ids = []
        for location in ["书房-线材盒", "卧室-线材盒"]:
            status, body = self.request(
                "POST",
                "/api/v1/items",
                {
                    "name": "数据线",
                    "aliases": [],
                    "location_path": location,
                    "note": None,
                },
            )
            self.assertEqual(status, 201)
            item_ids.append(body["item"]["id"])

        status, result = self.request(
            "GET",
            f"/api/v1/items/search?q={quote('数据线')}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "multiple")
        self.assertEqual(len(result["candidates"]), 2)
        self.assertTrue(all(candidate["location"]["path"] for candidate in result["candidates"]))

        status, none = self.request(
            "GET",
            f"/api/v1/items/search?q={quote('完全不存在')}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(none["status"], "none")
        self.assertEqual(none["count"], 0)

        status, ambiguous = self.request(
            "POST",
            "/api/v1/items/upsert",
            {
                "name": "数据线",
                "aliases": [],
                "location_path": "客厅-收纳盒",
                "note": None,
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(ambiguous["error"]["code"], "item_upsert_ambiguous")
        self.assertEqual(len(ambiguous["error"]["details"]["candidates"]), 2)

        for item_id in item_ids:
            self.request("DELETE", f"/api/v1/items/{item_id}")


if __name__ == "__main__":
    unittest.main()
