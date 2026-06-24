from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


VALID_STATUSES = {"pending_note", "matched_note", "media_done", "media_failed"}


class InvalidStatusError(ValueError):
    pass


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "mpvacious" / "mining_history.sqlite3"


class HistoryStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    sentence TEXT NOT NULL,
                    normalized_sentence TEXT NOT NULL,
                    secondary TEXT NOT NULL DEFAULT '',
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    snapshot_time REAL NOT NULL,
                    video_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note_id INTEGER,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_records_pending_match
                ON records (normalized_sentence, created_at DESC, id DESC)
                WHERE status = 'pending_note'
                """
            )

    def add_record(self, record: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        values = {
            "id": record["id"],
            "sentence": record["sentence"],
            "normalized_sentence": record["normalized_sentence"],
            "secondary": record.get("secondary", ""),
            "start_time": record["start_time"],
            "end_time": record["end_time"],
            "snapshot_time": record["snapshot_time"],
            "video_path": record["video_path"],
            "filename": record["filename"],
            "profile": record["profile"],
            "status": "pending_note",
            "note_id": None,
            "error": "",
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO records (
                    id,
                    sentence,
                    normalized_sentence,
                    secondary,
                    start_time,
                    end_time,
                    snapshot_time,
                    video_path,
                    filename,
                    profile,
                    status,
                    note_id,
                    error,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :sentence,
                    :normalized_sentence,
                    :secondary,
                    :start_time,
                    :end_time,
                    :snapshot_time,
                    :video_path,
                    :filename,
                    :profile,
                    :status,
                    :note_id,
                    :error,
                    :created_at,
                    :updated_at
                )
                """,
                values,
            )
        return self.get_record(str(record["id"]))

    def get_record(self, record_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return dict(row)

    def list_records(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM records
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_pending_by_normalized_sentence(
        self, normalized_sentence: str, window_minutes: int
    ) -> dict[str, Any] | None:
        cutoff = time.time() - (window_minutes * 60)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM records
                WHERE normalized_sentence = ?
                    AND status = 'pending_note'
                    AND created_at >= ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (normalized_sentence, cutoff),
            ).fetchone()
        return dict(row) if row is not None else None

    def update_status(
        self,
        record_id: str,
        status: str,
        note_id: int | None,
        error: str,
    ) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise InvalidStatusError(status)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE records
                SET status = ?,
                    note_id = ?,
                    error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, note_id, error, time.time(), record_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(record_id)
        return self.get_record(record_id)

    def retry_record(self, record_id: str) -> dict[str, Any]:
        record = self.get_record(record_id)
        if record["status"] != "media_failed":
            return record
        return self.update_status(
            record_id,
            status="matched_note",
            note_id=record["note_id"],
            error="retry requested",
        )
