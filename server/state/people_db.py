"""People and their saved preferences, in a local SQLite database.

The database is created on first use. If it is empty, the people and preferences already in memory.json are
imported once, so existing saved preferences carry over. After that, the database is the only source for them.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from state.store import STATE_DIRECTORY, load_json


DB_FILE = STATE_DIRECTORY / "household.db"
_ready_for: Path | None = None


def _connect() -> sqlite3.Connection:
    global _ready_for
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if _ready_for != DB_FILE:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
                person_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (
                person_id TEXT NOT NULL REFERENCES people(person_id),
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (person_id, key)
            );
            """
        )
        if connection.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0:
            _import_from_json(connection)
        connection.commit()
        _ready_for = DB_FILE
    return connection


@contextmanager
def _db():
    """A connection that commits on success and is always closed, so the file is never left locked."""
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _import_from_json(connection: sqlite3.Connection) -> None:
    """One-time import of the people in memory.json, so saved preferences carry over."""
    for person_id, person in load_json("memory.json").get("people", {}).items():
        connection.execute("INSERT INTO people (person_id, display_name) VALUES (?, ?)", (person_id, person["display_name"]))
        for key, value in person.get("preferences", {}).items():
            connection.execute("INSERT INTO preferences (person_id, key, value) VALUES (?, ?, ?)", (person_id, key, json.dumps(value)))


def person_exists(person_id: str) -> bool:
    with _db() as connection:
        return connection.execute("SELECT 1 FROM people WHERE person_id = ?", (person_id,)).fetchone() is not None


def person_ids() -> list[str]:
    with _db() as connection:
        return [row["person_id"] for row in connection.execute("SELECT person_id FROM people ORDER BY person_id")]


def display_name(person_id: str) -> str | None:
    with _db() as connection:
        row = connection.execute("SELECT display_name FROM people WHERE person_id = ?", (person_id,)).fetchone()
        return row["display_name"] if row else None


def get_person(person_id: str) -> dict[str, Any] | None:
    """One person's display name and every saved preference. None if the person is not known."""
    with _db() as connection:
        row = connection.execute("SELECT display_name FROM people WHERE person_id = ?", (person_id,)).fetchone()
        if row is None:
            return None
        preferences = {
            pref["key"]: json.loads(pref["value"])
            for pref in connection.execute("SELECT key, value FROM preferences WHERE person_id = ? ORDER BY key", (person_id,))
        }
        return {"display_name": row["display_name"], "preferences": preferences}


def set_preference(person_id: str, key: str, value: Any) -> Any:
    """Save one preference and return the value it replaced (None if it was not set)."""
    with _db() as connection:
        previous = connection.execute("SELECT value FROM preferences WHERE person_id = ? AND key = ?", (person_id, key)).fetchone()
        connection.execute(
            "INSERT INTO preferences (person_id, key, value) VALUES (?, ?, ?) ON CONFLICT(person_id, key) DO UPDATE SET value = excluded.value",
            (person_id, key, json.dumps(value)),
        )
        connection.commit()
        return json.loads(previous["value"]) if previous else None
