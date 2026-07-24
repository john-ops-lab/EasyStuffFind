from __future__ import annotations

import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .database import Database
from .errors import DomainError, not_found, validation_error


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def clean_name(value: str, *, field: str, maximum: int) -> str:
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if not cleaned:
        raise validation_error(f"{field}不能为空", field=field)
    if len(cleaned) > maximum:
        raise validation_error(
            f"{field}不能超过 {maximum} 个字符",
            field=field,
            maximum=maximum,
        )
    return cleaned


def clean_aliases(values: list[str], item_name: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = {normalize_text(item_name)}
    for value in values:
        alias = clean_name(value, field="别名", maximum=200)
        normalized = normalize_text(alias)
        if normalized not in seen:
            seen.add(normalized)
            result.append(alias)
    if len(result) > 50:
        raise validation_error("别名最多 50 个", maximum=50)
    return result


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def parse_path(path: str) -> list[str]:
        cleaned = unicodedata.normalize("NFKC", path).strip()
        if not cleaned:
            raise validation_error("位置路径不能为空", field="location_path")
        parts = [part.strip() for part in cleaned.split("-")]
        if any(not part for part in parts):
            raise validation_error(
                "位置路径格式无效；请用半角 - 分隔非空层级",
                field="location_path",
            )
        if parts[0] == "全屋":
            parts = parts[1:]
        if not parts:
            raise validation_error("位置路径至少需要一个实际层级", field="location_path")
        if len(parts) > 20:
            raise validation_error("位置层级最多 20 层", maximum=20)
        for part in parts:
            if "-" in part:
                raise validation_error("位置名称中不能包含半角 -", value=part)
            clean_name(part, field="位置名称", maximum=100)
        return parts

    @staticmethod
    def _location_rows(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
        rows = connection.execute(
            """
            SELECT
                l.*,
                (SELECT COUNT(*) FROM locations c WHERE c.parent_id = l.id) AS child_count,
                (SELECT COUNT(*) FROM items i WHERE i.location_id = l.id) AS item_count
            FROM locations l
            ORDER BY l.name COLLATE NOCASE, l.id
            """
        ).fetchall()
        return {int(row["id"]): row for row in rows}

    @classmethod
    def _path_for(
        cls,
        location_id: int,
        rows: dict[int, sqlite3.Row],
    ) -> str:
        names: list[str] = []
        current_id: int | None = location_id
        visited: set[int] = set()
        while current_id is not None:
            if current_id in visited or current_id not in rows:
                raise RuntimeError("位置树存在循环或缺失父节点")
            visited.add(current_id)
            row = rows[current_id]
            names.append(str(row["name"]))
            current_id = (
                int(row["parent_id"]) if row["parent_id"] is not None else None
            )
        return "-".join(reversed(names))

    @classmethod
    def _location_to_dict(
        cls,
        row: sqlite3.Row,
        rows: dict[int, sqlite3.Row],
    ) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "parent_id": (
                int(row["parent_id"]) if row["parent_id"] is not None else None
            ),
            "name": str(row["name"]),
            "path": cls._path_for(int(row["id"]), rows),
            "child_count": int(row["child_count"]),
            "item_count": int(row["item_count"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def location_tree(self) -> dict[str, Any]:
        with self.database.read() as connection:
            rows = self._location_rows(connection)
            nodes = {
                location_id: {
                    **self._location_to_dict(row, rows),
                    "children": [],
                }
                for location_id, row in rows.items()
            }
            roots: list[dict[str, Any]] = []
            for location_id, node in nodes.items():
                parent_id = rows[location_id]["parent_id"]
                if parent_id is None:
                    roots.append(node)
                else:
                    nodes[int(parent_id)]["children"].append(node)
            return {
                "id": None,
                "name": "全屋",
                "path": "",
                "children": roots,
                "item_count": sum(int(row["item_count"]) for row in rows.values()),
            }

    def list_locations(self) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = self._location_rows(connection)
            return [
                self._location_to_dict(row, rows)
                for row in sorted(rows.values(), key=lambda item: int(item["id"]))
            ]

    def get_location(self, location_id: int) -> dict[str, Any]:
        with self.database.read() as connection:
            rows = self._location_rows(connection)
            row = rows.get(location_id)
            if row is None:
                raise not_found("位置", location_id)
            return self._location_to_dict(row, rows)

    def _resolve_location_path(
        self,
        connection: sqlite3.Connection,
        path: str,
        *,
        create_missing: bool,
    ) -> tuple[int, bool]:
        parts = self.parse_path(path)
        parent_id: int | None = None
        created = False
        now = utc_now()
        for name in parts:
            normalized = normalize_text(name)
            row = connection.execute(
                """
                SELECT id FROM locations
                WHERE normalized_name = ?
                  AND ((parent_id IS NULL AND ? IS NULL) OR parent_id = ?)
                """,
                (normalized, parent_id, parent_id),
            ).fetchone()
            if row is None:
                if not create_missing:
                    raise not_found("位置路径", path)
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO locations
                            (parent_id, name, normalized_name, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (parent_id, name, normalized, now, now),
                    )
                    location_id = int(cursor.lastrowid)
                    created = True
                except sqlite3.IntegrityError:
                    concurrent = connection.execute(
                        """
                        SELECT id FROM locations
                        WHERE normalized_name = ?
                          AND ((parent_id IS NULL AND ? IS NULL) OR parent_id = ?)
                        """,
                        (normalized, parent_id, parent_id),
                    ).fetchone()
                    if concurrent is None:
                        raise
                    location_id = int(concurrent["id"])
            else:
                location_id = int(row["id"])
            parent_id = location_id
        assert parent_id is not None
        return parent_id, created

    def resolve_location_path(
        self,
        path: str,
        *,
        create_missing: bool,
    ) -> tuple[dict[str, Any], bool]:
        with self.database.transaction() as connection:
            location_id, created = self._resolve_location_path(
                connection,
                path,
                create_missing=create_missing,
            )
            rows = self._location_rows(connection)
            return self._location_to_dict(rows[location_id], rows), created

    def create_location(self, name: str, parent_id: int | None) -> dict[str, Any]:
        name = clean_name(name, field="位置名称", maximum=100)
        if "-" in name:
            raise validation_error("位置名称中不能包含半角 -", field="name")
        with self.database.transaction() as connection:
            if parent_id is not None:
                parent = connection.execute(
                    "SELECT id FROM locations WHERE id = ?",
                    (parent_id,),
                ).fetchone()
                if parent is None:
                    raise not_found("父位置", parent_id)
            now = utc_now()
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO locations
                        (parent_id, name, normalized_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (parent_id, name, normalize_text(name), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise DomainError(
                    409,
                    "location_already_exists",
                    "同一层级下已存在该位置",
                    {"name": name, "parent_id": parent_id},
                ) from exc
            location_id = int(cursor.lastrowid)
            rows = self._location_rows(connection)
            return self._location_to_dict(rows[location_id], rows)

    def update_location(self, location_id: int, name: str) -> dict[str, Any]:
        name = clean_name(name, field="位置名称", maximum=100)
        if "-" in name:
            raise validation_error("位置名称中不能包含半角 -", field="name")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM locations WHERE id = ?",
                (location_id,),
            ).fetchone()
            if row is None:
                raise not_found("位置", location_id)
            try:
                connection.execute(
                    """
                    UPDATE locations
                    SET name = ?, normalized_name = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name, normalize_text(name), utc_now(), location_id),
                )
            except sqlite3.IntegrityError as exc:
                raise DomainError(
                    409,
                    "location_already_exists",
                    "同一层级下已存在该位置",
                    {"name": name},
                ) from exc
            rows = self._location_rows(connection)
            return self._location_to_dict(rows[location_id], rows)

    def delete_location(self, location_id: int) -> None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM locations WHERE id = ?",
                (location_id,),
            ).fetchone()
            if row is None:
                raise not_found("位置", location_id)
            child_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM locations WHERE parent_id = ?",
                    (location_id,),
                ).fetchone()[0]
            )
            item_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM items WHERE location_id = ?",
                    (location_id,),
                ).fetchone()[0]
            )
            if child_count or item_count:
                raise DomainError(
                    409,
                    "location_not_empty",
                    "位置下仍有子位置或物品，不能删除",
                    {"child_count": child_count, "item_count": item_count},
                )
            connection.execute("DELETE FROM locations WHERE id = ?", (location_id,))

    def search_locations(self, query: str) -> dict[str, Any]:
        normalized_query = normalize_text(
            clean_name(query, field="查询词", maximum=300)
        )
        with self.database.read() as connection:
            rows = self._location_rows(connection)
            candidates: list[tuple[int, dict[str, Any]]] = []
            for row in rows.values():
                location = self._location_to_dict(row, rows)
                normalized_name = normalize_text(location["name"])
                normalized_path = normalize_text(location["path"])
                if normalized_query in {normalized_name, normalized_path}:
                    score = 100
                elif normalized_query in normalized_path:
                    score = 80
                elif normalized_path in normalized_query:
                    score = 60
                else:
                    continue
                candidates.append((score, location))
            candidates.sort(key=lambda entry: (-entry[0], entry[1]["path"]))
            result = [entry[1] for entry in candidates]
            status = "none" if not result else "unique" if len(result) == 1 else "multiple"
            return {
                "status": status,
                "query": query,
                "count": len(result),
                "location": result[0] if len(result) == 1 else None,
                "candidates": result if len(result) > 1 else [],
            }

    @staticmethod
    def _prepare_location(
        connection: sqlite3.Connection,
        repository: "Repository",
        *,
        location_id: int | None,
        location_path: str | None,
        create_missing: bool,
    ) -> int:
        if (location_id is None) == (location_path is None):
            raise validation_error(
                "location_id 与 location_path 必须且只能提供一个",
                fields=["location_id", "location_path"],
            )
        if location_id is not None:
            row = connection.execute(
                "SELECT id FROM locations WHERE id = ?",
                (location_id,),
            ).fetchone()
            if row is None:
                raise not_found("位置", location_id)
            return location_id
        assert location_path is not None
        resolved_id, _ = repository._resolve_location_path(
            connection,
            location_path,
            create_missing=create_missing,
        )
        return resolved_id

    @classmethod
    def _item_to_dict(
        cls,
        row: sqlite3.Row,
        locations: dict[int, sqlite3.Row],
    ) -> dict[str, Any]:
        location_id = int(row["location_id"])
        photo = None
        if row["photo_filename"]:
            photo = {
                "content_type": str(row["photo_content_type"]),
                "updated_at": str(row["photo_updated_at"]),
            }
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "aliases": json.loads(str(row["aliases_json"])),
            "location": {
                "id": location_id,
                "path": cls._path_for(location_id, locations),
            },
            "note": row["note"],
            "photo": photo,
            "photo_url": None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _get_item_in_connection(
        self,
        connection: sqlite3.Connection,
        item_id: int,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise not_found("物品", item_id)
        return self._item_to_dict(row, self._location_rows(connection))

    def get_item(self, item_id: int) -> dict[str, Any]:
        with self.database.read() as connection:
            return self._get_item_in_connection(connection, item_id)

    def _insert_item(
        self,
        connection: sqlite3.Connection,
        *,
        name: str,
        aliases: list[str],
        location_id: int,
        note: str | None,
    ) -> int:
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO items
                (name, normalized_name, aliases_json, location_id, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                normalize_text(name),
                json.dumps(aliases, ensure_ascii=False),
                location_id,
                note,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    def create_item(
        self,
        *,
        name: str,
        aliases: list[str],
        location_id: int | None,
        location_path: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        name = clean_name(name, field="物品名称", maximum=200)
        aliases = clean_aliases(aliases, name)
        note = self._clean_note(note)
        with self.database.transaction() as connection:
            resolved_location_id = self._prepare_location(
                connection,
                self,
                location_id=location_id,
                location_path=location_path,
                create_missing=True,
            )
            item_id = self._insert_item(
                connection,
                name=name,
                aliases=aliases,
                location_id=resolved_location_id,
                note=note,
            )
            return self._get_item_in_connection(connection, item_id)

    @staticmethod
    def _clean_note(note: str | None) -> str | None:
        if note is None:
            return None
        cleaned = unicodedata.normalize("NFKC", note).strip()
        if len(cleaned) > 2000:
            raise validation_error("备注不能超过 2000 个字符", maximum=2000)
        return cleaned or None

    def _exact_item_ids(
        self,
        connection: sqlite3.Connection,
        name: str,
    ) -> list[int]:
        normalized = normalize_text(name)
        rows = connection.execute("SELECT id, normalized_name, aliases_json FROM items").fetchall()
        result: list[int] = []
        for row in rows:
            aliases = [normalize_text(value) for value in json.loads(row["aliases_json"])]
            if normalized == row["normalized_name"] or normalized in aliases:
                result.append(int(row["id"]))
        return result

    def upsert_item(
        self,
        *,
        item_id: int | None,
        name: str,
        aliases: list[str],
        location_id: int | None,
        location_path: str | None,
        note: str | None,
        aliases_provided: bool = True,
        note_provided: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        name = clean_name(name, field="物品名称", maximum=200)
        aliases = clean_aliases(aliases, name)
        cleaned_note = self._clean_note(note)
        with self.database.transaction() as connection:
            target_id = item_id
            matched_without_id = False
            if target_id is not None:
                exists = connection.execute(
                    "SELECT id FROM items WHERE id = ?",
                    (target_id,),
                ).fetchone()
                if exists is None:
                    raise not_found("物品", target_id)
            else:
                exact_ids = self._exact_item_ids(connection, name)
                if len(exact_ids) > 1:
                    locations = self._location_rows(connection)
                    candidates = [
                        self._item_to_dict(
                            connection.execute(
                                "SELECT * FROM items WHERE id = ?",
                                (candidate_id,),
                            ).fetchone(),
                            locations,
                        )
                        for candidate_id in exact_ids
                    ]
                    raise DomainError(
                        409,
                        "item_upsert_ambiguous",
                        "名称或别名命中多个物品，必须提供 item_id",
                        {"candidates": candidates},
                    )
                target_id = exact_ids[0] if exact_ids else None
                matched_without_id = target_id is not None

            resolved_location_id = self._prepare_location(
                connection,
                self,
                location_id=location_id,
                location_path=location_path,
                create_missing=True,
            )
            if target_id is None:
                created_id = self._insert_item(
                    connection,
                    name=name,
                    aliases=aliases,
                    location_id=resolved_location_id,
                    note=cleaned_note,
                )
                return "created", self._get_item_in_connection(connection, created_id)

            if matched_without_id:
                current = connection.execute(
                    "SELECT name, aliases_json FROM items WHERE id = ?",
                    (target_id,),
                ).fetchone()
                assert current is not None
                values: dict[str, Any] = {"location_id": resolved_location_id}
                if aliases_provided:
                    existing_aliases = json.loads(str(current["aliases_json"]))
                    values["aliases"] = [*existing_aliases, *aliases]
                if note_provided:
                    values["note"] = cleaned_note
            else:
                values = {
                    "name": name,
                    "location_id": resolved_location_id,
                }
                if aliases_provided:
                    values["aliases"] = aliases
                if note_provided:
                    values["note"] = cleaned_note
            self._update_item_values(connection, target_id, values)
            return "updated", self._get_item_in_connection(connection, target_id)

    def _update_item_values(
        self,
        connection: sqlite3.Connection,
        item_id: int,
        values: dict[str, Any],
    ) -> None:
        current = connection.execute(
            "SELECT * FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if current is None:
            raise not_found("物品", item_id)

        assignments: list[str] = []
        parameters: list[Any] = []
        if "name" in values:
            name = clean_name(values["name"], field="物品名称", maximum=200)
            assignments.extend(["name = ?", "normalized_name = ?"])
            parameters.extend([name, normalize_text(name)])
        if "aliases" in values:
            item_name = values.get("name", str(current["name"]))
            aliases = clean_aliases(values["aliases"], item_name)
            assignments.append("aliases_json = ?")
            parameters.append(json.dumps(aliases, ensure_ascii=False))
        if "note" in values:
            assignments.append("note = ?")
            parameters.append(self._clean_note(values["note"]))
        if "location_id" in values:
            new_location_id = int(values["location_id"])
            old_location_id = int(current["location_id"])
            if new_location_id != old_location_id:
                locations = self._location_rows(connection)
                if new_location_id not in locations:
                    raise not_found("位置", new_location_id)
                changed_at = utc_now()
                connection.execute(
                    """
                    INSERT INTO location_history
                        (item_id, old_location_id, new_location_id,
                         old_location_path, new_location_path, changed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        old_location_id,
                        new_location_id,
                        self._path_for(old_location_id, locations),
                        self._path_for(new_location_id, locations),
                        changed_at,
                    ),
                )
                assignments.append("location_id = ?")
                parameters.append(new_location_id)
        if assignments:
            assignments.append("updated_at = ?")
            parameters.append(utc_now())
            parameters.append(item_id)
            connection.execute(
                f"UPDATE items SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )

    def update_item(self, item_id: int, values: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as connection:
            location_fields = {"location_id", "location_path"} & values.keys()
            if location_fields:
                location_id = values.pop("location_id", None)
                location_path = values.pop("location_path", None)
                values["location_id"] = self._prepare_location(
                    connection,
                    self,
                    location_id=location_id,
                    location_path=location_path,
                    create_missing=True,
                )
            self._update_item_values(connection, item_id, values)
            return self._get_item_in_connection(connection, item_id)

    def move_item(
        self,
        item_id: int,
        *,
        location_id: int | None,
        location_path: str | None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            resolved_location_id = self._prepare_location(
                connection,
                self,
                location_id=location_id,
                location_path=location_path,
                create_missing=True,
            )
            self._update_item_values(
                connection,
                item_id,
                {"location_id": resolved_location_id},
            )
            return self._get_item_in_connection(connection, item_id)

    def list_items(
        self,
        *,
        location_id: int | None = None,
        recursive: bool = False,
    ) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            allowed_location_ids: set[int] | None = None
            if location_id is not None:
                exists = connection.execute(
                    "SELECT id FROM locations WHERE id = ?",
                    (location_id,),
                ).fetchone()
                if exists is None:
                    raise not_found("位置", location_id)
                if recursive:
                    descendant_rows = connection.execute(
                        """
                        WITH RECURSIVE descendants(id) AS (
                            SELECT id FROM locations WHERE id = ?
                            UNION ALL
                            SELECT l.id FROM locations l
                            JOIN descendants d ON l.parent_id = d.id
                        )
                        SELECT id FROM descendants
                        """,
                        (location_id,),
                    ).fetchall()
                    allowed_location_ids = {int(row["id"]) for row in descendant_rows}
                else:
                    allowed_location_ids = {location_id}
            rows = connection.execute(
                "SELECT * FROM items ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            locations = self._location_rows(connection)
            return [
                self._item_to_dict(row, locations)
                for row in rows
                if allowed_location_ids is None
                or int(row["location_id"]) in allowed_location_ids
            ]

    @staticmethod
    def _item_score(item: dict[str, Any], normalized_query: str) -> int | None:
        values = [item["name"], *item["aliases"]]
        best: int | None = None
        for value in values:
            normalized = normalize_text(value)
            if normalized == normalized_query:
                score = 100
            elif normalized_query in normalized:
                score = 80
            elif normalized in normalized_query:
                score = 60
            else:
                continue
            best = score if best is None else max(best, score)
        return best

    def search_items(self, query: str) -> dict[str, Any]:
        query = clean_name(query, field="查询词", maximum=300)
        normalized_query = normalize_text(query)
        with self.database.read() as connection:
            locations = self._location_rows(connection)
            candidates: list[tuple[int, dict[str, Any]]] = []
            for row in connection.execute("SELECT * FROM items").fetchall():
                item = self._item_to_dict(row, locations)
                score = self._item_score(item, normalized_query)
                if score is not None:
                    candidates.append((score, item))
            candidates.sort(
                key=lambda entry: (
                    -entry[0],
                    -int(entry[1]["id"]),
                )
            )
            items = [entry[1] for entry in candidates]
            status = "none" if not items else "unique" if len(items) == 1 else "multiple"
            return {
                "status": status,
                "query": query,
                "count": len(items),
                "item": items[0] if len(items) == 1 else None,
                "candidates": items if len(items) > 1 else [],
            }

    def delete_item(self, item_id: int) -> str | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT photo_filename FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise not_found("物品", item_id)
            filename = row["photo_filename"]
            connection.execute("DELETE FROM items WHERE id = ?", (item_id,))
            return str(filename) if filename else None

    def replace_photo_metadata(
        self,
        item_id: int,
        *,
        filename: str,
        content_type: str,
    ) -> tuple[str | None, dict[str, Any]]:
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT photo_filename FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if current is None:
                raise not_found("物品", item_id)
            updated_at = utc_now()
            connection.execute(
                """
                UPDATE items
                SET photo_filename = ?, photo_content_type = ?,
                    photo_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (filename, content_type, updated_at, updated_at, item_id),
            )
            old_filename = current["photo_filename"]
            return (
                str(old_filename) if old_filename else None,
                self._get_item_in_connection(connection, item_id),
            )

    def remove_photo_metadata(self, item_id: int) -> tuple[str | None, dict[str, Any]]:
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT photo_filename FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if current is None:
                raise not_found("物品", item_id)
            old_filename = current["photo_filename"]
            connection.execute(
                """
                UPDATE items
                SET photo_filename = NULL, photo_content_type = NULL,
                    photo_updated_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), item_id),
            )
            return (
                str(old_filename) if old_filename else None,
                self._get_item_in_connection(connection, item_id),
            )

    def photo_record(self, item_id: int) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT id, photo_filename, photo_content_type, photo_updated_at
                FROM items WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise not_found("物品", item_id)
            if not row["photo_filename"]:
                raise not_found("照片", item_id)
            return {
                "item_id": int(row["id"]),
                "filename": str(row["photo_filename"]),
                "content_type": str(row["photo_content_type"]),
                "updated_at": str(row["photo_updated_at"]),
            }

    def item_history(self, item_id: int) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            item = connection.execute(
                "SELECT id FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if item is None:
                raise not_found("物品", item_id)
            rows = connection.execute(
                """
                SELECT * FROM location_history
                WHERE item_id = ?
                ORDER BY changed_at DESC, id DESC
                """,
                (item_id,),
            ).fetchall()
            return [self._history_to_dict(row) for row in rows]

    def all_history(self, limit: int = 200) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise validation_error("limit 必须在 1 到 1000 之间", field="limit")
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT h.*, i.name AS item_name
                FROM location_history h
                JOIN items i ON i.id = h.item_id
                ORDER BY h.changed_at DESC, h.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    **self._history_to_dict(row),
                    "item_name": str(row["item_name"]),
                }
                for row in rows
            ]

    @staticmethod
    def _history_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "item_id": int(row["item_id"]),
            "old_location_id": (
                int(row["old_location_id"])
                if row["old_location_id"] is not None
                else None
            ),
            "new_location_id": (
                int(row["new_location_id"])
                if row["new_location_id"] is not None
                else None
            ),
            "old_location_path": row["old_location_path"],
            "new_location_path": str(row["new_location_path"]),
            "changed_at": str(row["changed_at"]),
        }
