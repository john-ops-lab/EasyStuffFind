from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(length(name) BETWEEN 1 AND 100)
);

CREATE UNIQUE INDEX uq_locations_parent_name
ON locations(COALESCE(parent_id, 0), normalized_name);

CREATE INDEX idx_locations_parent ON locations(parent_id);

CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    note TEXT,
    photo_filename TEXT,
    photo_content_type TEXT,
    photo_updated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(length(name) BETWEEN 1 AND 200)
);

CREATE INDEX idx_items_name ON items(normalized_name);
CREATE INDEX idx_items_location ON items(location_id);

CREATE TABLE location_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    old_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    new_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    old_location_path TEXT,
    new_location_path TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE INDEX idx_history_item_time ON location_history(item_id, changed_at DESC);

PRAGMA user_version = 1;
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库 Schema 版本 {version} 高于应用支持版本 {SCHEMA_VERSION}"
                )
            if version == 0:
                connection.executescript(SCHEMA_V1)
            connection.execute("PRAGMA journal_mode = WAL")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()
