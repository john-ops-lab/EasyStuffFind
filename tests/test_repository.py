from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from easystufffind.database import Database
from easystufffind.errors import DomainError
from easystufffind.repository import Repository


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = Database(self.data_dir / "test.sqlite3")
        self.database.initialize()
        self.repository = Repository(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_record_alias_query_move_and_history(self) -> None:
        item = self.repository.create_item(
            name="护照",
            aliases=["passport"],
            location_id=None,
            location_path="书房-书桌-第二个抽屉",
            note="红色护照",
        )
        self.assertEqual(item["location"]["path"], "书房-书桌-第二个抽屉")
        query = self.repository.search_items("passport")
        self.assertEqual(query["status"], "unique")
        self.assertEqual(query["item"]["id"], item["id"])

        moved = self.repository.move_item(
            item["id"],
            location_id=None,
            location_path="卧室-保险柜",
        )
        self.assertEqual(moved["location"]["path"], "卧室-保险柜")
        history = self.repository.item_history(item["id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_location_path"], "书房-书桌-第二个抽屉")
        self.assertEqual(history[0]["new_location_path"], "卧室-保险柜")

    def test_duplicate_name_returns_multiple_and_upsert_conflict(self) -> None:
        first = self.repository.create_item(
            name="数据线",
            aliases=[],
            location_id=None,
            location_path="书房-抽屉",
            note=None,
        )
        second = self.repository.create_item(
            name="数据线",
            aliases=[],
            location_id=None,
            location_path="卧室-床头柜",
            note=None,
        )
        result = self.repository.search_items("数据线")
        self.assertEqual(result["status"], "multiple")
        self.assertEqual({item["id"] for item in result["candidates"]}, {first["id"], second["id"]})
        self.assertEqual(
            {item["location"]["path"] for item in result["candidates"]},
            {"书房-抽屉", "卧室-床头柜"},
        )
        with self.assertRaises(DomainError) as context:
            self.repository.upsert_item(
                item_id=None,
                name="数据线",
                aliases=[],
                location_id=None,
                location_path="客厅-柜子",
                note=None,
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.code, "item_upsert_ambiguous")

    def test_upsert_unique_match_updates_and_records_history(self) -> None:
        original = self.repository.create_item(
            name="护照",
            aliases=["passport"],
            location_id=None,
            location_path="书房-抽屉",
            note=None,
        )
        action, updated = self.repository.upsert_item(
            item_id=None,
            name="passport",
            aliases=["护照"],
            location_id=None,
            location_path="卧室-保险柜",
            note="重要证件",
        )
        self.assertEqual(action, "updated")
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["name"], "护照")
        self.assertIn("passport", updated["aliases"])
        self.assertEqual(len(self.repository.item_history(original["id"])), 1)

    def test_nonempty_location_delete_is_rejected(self) -> None:
        item = self.repository.create_item(
            name="充电器",
            aliases=[],
            location_id=None,
            location_path="客厅-电视柜",
            note=None,
        )
        location_id = item["location"]["id"]
        with self.assertRaises(DomainError) as context:
            self.repository.delete_location(location_id)
        self.assertEqual(context.exception.code, "location_not_empty")
        self.repository.delete_item(item["id"])
        self.repository.delete_location(location_id)

    def test_location_path_validation_and_no_result(self) -> None:
        with self.assertRaises(DomainError):
            self.repository.resolve_location_path("书房--抽屉", create_missing=True)
        result = self.repository.search_items("不存在的物品")
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
