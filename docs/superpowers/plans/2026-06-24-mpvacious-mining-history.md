# MPVacious Mining History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a localhost browser mining history for Japanese sentence mining where Yomitan creates Anki notes immediately and mpvacious backfills screenshot/audio afterward.

**Architecture:** Keep mpvacious' Lua plugin as the MPV entry point and reuse `subs2srs.conf`, AnkiConnect, and the existing encoder modules. Add a `uv`-managed Python helper inside the installable `mpvacious/` directory to serve the history page and SQLite-backed API, then add Lua history modules to capture subtitles, start the helper, match Yomitan-created Anki notes, and update media from stored timings.

**Tech Stack:** mpv Lua APIs, existing mpvacious Lua helpers, AnkiConnect, `curl`, Python standard library HTTP server, SQLite, `uv`, `pytest`.

---

## File Structure

- Create `mpvacious/pyproject.toml`: `uv` project metadata, Python version, pytest dependency.
- Create `mpvacious/history_server/__init__.py`: package marker and version string.
- Create `mpvacious/history_server/__main__.py`: CLI entry point used by `uv run python -m history_server`.
- Create `mpvacious/history_server/store.py`: SQLite schema, record persistence, matching, status updates, retry transitions.
- Create `mpvacious/history_server/web.py`: localhost HTTP API and no-build HTML history page.
- Create `mpvacious/history_server/tests/test_store.py`: SQLite behavior tests.
- Create `mpvacious/history_server/tests/test_web.py`: HTTP API tests using a temporary DB and localhost port `0`.
- Create `mpvacious/history/normalizer.lua`: shared Lua normalization for capture and Anki note matching.
- Create `mpvacious/history/client.lua`: JSON HTTP client for the Python helper.
- Create `mpvacious/history/server_process.lua`: health check and `uv run` startup logic.
- Create `mpvacious/history/capture.lua`: current subtitle-to-history record construction.
- Create `mpvacious/history/controller.lua`: high-level orchestration used by `main.lua` and `new_note_checker.lua`.
- Modify `mpvacious/config/defaults.lua`: additive mining history defaults.
- Modify `mpvacious/config/default_config.conf`: documented config options.
- Modify `mpvacious/encoder/encoder.lua`: allow media jobs to use a supplied `source_path` and `snapshot_time`.
- Modify `mpvacious/anki/note_exporter.lua`: add history backfill path for a supplied record.
- Modify `mpvacious/anki/new_note_checker.lua`: try history matching before falling back to current-subtitle updates.
- Modify `mpvacious/main.lua`: initialize history controller, add dynamic global binding, run history tests.
- Modify `.gitignore`: ignore local SQLite DBs and Python virtualenv artifacts.
- Modify `README.md` and create `howto/mining_history.md`: user workflow and Yomitan setup.

## Task 0: Branch And Baseline

**Files:**
- Read: `docs/superpowers/specs/2026-06-24-mpvacious-mining-history-design.md`
- Read: `mpvacious/main.lua`
- Read: `mpvacious/anki/note_exporter.lua`
- Read: `mpvacious/anki/new_note_checker.lua`

- [ ] **Step 1: Create a feature branch**

Run:

```bash
git switch -c feature/mining-history
```

Expected: a new branch named `feature/mining-history`.

- [ ] **Step 2: Confirm the baseline worktree**

Run:

```bash
git status --short --branch
```

Expected: output starts with `## feature/mining-history` and no modified files.

- [ ] **Step 3: Read the approved design**

Run:

```bash
sed -n '1,260p' docs/superpowers/specs/2026-06-24-mpvacious-mining-history-design.md
```

Expected: the design describes approach 1, the local history page plus pending media queue.

## Task 1: Add The `uv` Python Project Skeleton

**Files:**
- Create: `mpvacious/pyproject.toml`
- Create: `mpvacious/history_server/__init__.py`
- Create: `mpvacious/history_server/__main__.py`
- Create: `mpvacious/history_server/tests/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write the Python project files**

Create `mpvacious/pyproject.toml` with this content:

```toml
[project]
name = "mpvacious-history-server"
version = "0.1.0"
description = "Local mining history helper for mpvacious"
readme = "../README.md"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["history_server/tests"]
pythonpath = ["."]
```

Create `mpvacious/history_server/__init__.py` with this content:

```python
__version__ = "0.1.0"
```

Create `mpvacious/history_server/__main__.py` with this content:

```python
from __future__ import annotations

from .web import main


if __name__ == "__main__":
    main()
```

Create `mpvacious/history_server/tests/__init__.py` as an empty file.

Append these lines to `.gitignore`:

```gitignore
.venv/
*.db
*.sqlite
*.sqlite3
mpvacious/history_server/.pytest_cache/
```

- [ ] **Step 2: Verify `uv` creates a lockfile**

Run:

```bash
uv lock --project mpvacious
```

Expected: command exits `0` and creates `mpvacious/uv.lock`.

- [ ] **Step 3: Verify the empty package entry point fails for the missing web module**

Run:

```bash
uv run --project mpvacious python -m history_server
```

Expected: FAIL with `ModuleNotFoundError: No module named 'history_server.web'`.

- [ ] **Step 4: Commit the skeleton**

Run:

```bash
git add .gitignore mpvacious/pyproject.toml mpvacious/uv.lock mpvacious/history_server
git commit -m "feat: add history server project skeleton"
```

Expected: commit succeeds.

## Task 2: Implement SQLite Store With Tests

**Files:**
- Create: `mpvacious/history_server/store.py`
- Create: `mpvacious/history_server/tests/test_store.py`

- [ ] **Step 1: Write failing store tests**

Create `mpvacious/history_server/tests/test_store.py` with this content:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from history_server.store import HistoryStore, InvalidStatusError


def make_record(record_id: str = "rec-1", sentence: str = "これはペンです。") -> dict[str, object]:
    return {
        "id": record_id,
        "sentence": sentence,
        "normalized_sentence": sentence,
        "secondary": "This is a pen.",
        "start_time": 1.25,
        "end_time": 2.75,
        "snapshot_time": 1.5,
        "video_path": "/tmp/video.mkv",
        "filename": "video.mkv",
        "profile": "subs2srs",
    }


def test_add_list_and_match_pending_record(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())

    records = store.list_records()
    assert len(records) == 1
    assert records[0]["id"] == "rec-1"
    assert records[0]["status"] == "pending_note"

    match = store.find_pending_by_normalized_sentence("これはペンです。", window_minutes=120)
    assert match is not None
    assert match["id"] == "rec-1"


def test_newest_unmatched_duplicate_wins(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("old"))
    store.add_record(make_record("new"))

    match = store.find_pending_by_normalized_sentence("これはペンです。", window_minutes=120)
    assert match is not None
    assert match["id"] == "new"


def test_status_update_and_retry(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())

    store.update_status("rec-1", status="matched_note", note_id=1234, error="")
    matched = store.get_record("rec-1")
    assert matched["status"] == "matched_note"
    assert matched["note_id"] == 1234

    store.update_status("rec-1", status="media_failed", note_id=1234, error="encoder failed")
    failed = store.get_record("rec-1")
    assert failed["status"] == "media_failed"
    assert failed["error"] == "encoder failed"

    retried = store.retry_record("rec-1")
    assert retried["status"] == "matched_note"
    assert retried["error"] == "retry requested"


def test_invalid_status_is_rejected(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())

    with pytest.raises(InvalidStatusError):
        store.update_status("rec-1", status="bad", note_id=None, error="")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_store.py -v
```

Expected: FAIL because `history_server.store` does not exist.

- [ ] **Step 3: Implement `HistoryStore`**

Create `mpvacious/history_server/store.py` with this content:

```python
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
        self.db_path = Path(db_path) if db_path else default_db_path()
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
                    status TEXT NOT NULL,
                    sentence TEXT NOT NULL,
                    normalized_sentence TEXT NOT NULL,
                    secondary TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    snapshot_time REAL NOT NULL,
                    video_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    note_id INTEGER,
                    error TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_records_pending_match
                ON records(status, normalized_sentence, created_at)
                """
            )

    def add_record(self, record: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO records (
                    id, status, sentence, normalized_sentence, secondary,
                    start_time, end_time, snapshot_time, video_path, filename,
                    profile, note_id, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["id"]),
                    "pending_note",
                    str(record["sentence"]),
                    str(record["normalized_sentence"]),
                    str(record.get("secondary", "")),
                    float(record["start_time"]),
                    float(record["end_time"]),
                    float(record["snapshot_time"]),
                    str(record["video_path"]),
                    str(record["filename"]),
                    str(record["profile"]),
                    None,
                    "",
                    now,
                    now,
                ),
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
                "SELECT * FROM records ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_pending_by_normalized_sentence(
        self,
        normalized_sentence: str,
        window_minutes: int,
    ) -> dict[str, Any] | None:
        created_after = int(time.time()) - int(window_minutes) * 60
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM records
                WHERE status = 'pending_note'
                  AND normalized_sentence = ?
                  AND created_at >= ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (normalized_sentence, created_after),
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
            conn.execute(
                """
                UPDATE records
                SET status = ?, note_id = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, note_id, error, int(time.time()), record_id),
            )
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_store.py -v
```

Expected: PASS for all four tests.

- [ ] **Step 5: Commit the store**

Run:

```bash
git add mpvacious/history_server/store.py mpvacious/history_server/tests/test_store.py
git commit -m "feat: add mining history SQLite store"
```

Expected: commit succeeds.

## Task 3: Add HTTP API And Browser Page

**Files:**
- Create: `mpvacious/history_server/web.py`
- Create: `mpvacious/history_server/tests/test_web.py`
- Modify: `mpvacious/history_server/__main__.py`

- [ ] **Step 1: Write failing HTTP tests**

Create `mpvacious/history_server/tests/test_web.py` with this content:

```python
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from history_server.store import HistoryStore
from history_server.web import make_server


def request_json(url: str, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def run_test_server(tmp_path: Path) -> tuple[str, object]:
    store = HistoryStore(tmp_path / "history.sqlite3")
    server = make_server("127.0.0.1", 0, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return f"http://{host}:{port}", server


def test_health_create_list_match_and_status(tmp_path: Path) -> None:
    base_url, server = run_test_server(tmp_path)
    try:
        assert request_json(f"{base_url}/health") == {"ok": True}

        payload = {
            "id": "rec-1",
            "sentence": "これはペンです。",
            "normalized_sentence": "これはペンです。",
            "secondary": "",
            "start_time": 1.0,
            "end_time": 2.0,
            "snapshot_time": 1.5,
            "video_path": "/tmp/video.mkv",
            "filename": "video.mkv",
            "profile": "subs2srs",
        }
        created = request_json(f"{base_url}/api/records", method="POST", payload=payload)
        assert created["record"]["id"] == "rec-1"

        listed = request_json(f"{base_url}/api/records")
        assert listed["records"][0]["id"] == "rec-1"

        matched = request_json(
            f"{base_url}/api/pending?normalized_sentence=%E3%81%93%E3%82%8C%E3%81%AF%E3%83%9A%E3%83%B3%E3%81%A7%E3%81%99%E3%80%82&window_minutes=120"
        )
        assert matched["record"]["id"] == "rec-1"

        status = request_json(
            f"{base_url}/api/records/rec-1/status",
            method="POST",
            payload={"status": "matched_note", "note_id": 123, "error": ""},
        )
        assert status["record"]["status"] == "matched_note"
    finally:
        server.shutdown()


def test_index_contains_selectable_sentence_markup(tmp_path: Path) -> None:
    base_url, server = run_test_server(tmp_path)
    try:
        with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert '<main id="records"' in html
        assert "Mpvacious Mining History" in html
    finally:
        server.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_web.py -v
```

Expected: FAIL because `history_server.web` does not exist.

- [ ] **Step 3: Implement the HTTP server**

Create `mpvacious/history_server/web.py` with this content:

```python
from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .store import HistoryStore

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mpvacious Mining History</title>
  <style>
    :root { color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Noto Sans CJK JP", sans-serif; }
    body { margin: 0; background: Canvas; color: CanvasText; }
    header { position: sticky; top: 0; padding: 12px 18px; border-bottom: 1px solid color-mix(in srgb, CanvasText 18%, transparent); background: Canvas; }
    h1 { margin: 0; font-size: 18px; font-weight: 650; }
    main { max-width: 980px; margin: 0 auto; padding: 16px; }
    article { border-bottom: 1px solid color-mix(in srgb, CanvasText 14%, transparent); padding: 14px 0; }
    .sentence { font-size: 22px; line-height: 1.75; user-select: text; }
    .secondary { opacity: .72; margin-top: 6px; line-height: 1.5; }
    .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 12px; opacity: .72; }
    .status { font-weight: 650; }
    button { font: inherit; padding: 4px 8px; }
  </style>
</head>
<body>
  <header><h1>Mpvacious Mining History</h1></header>
  <main id="records" aria-live="polite"></main>
  <script>
    const records = document.getElementById("records");
    const esc = (value) => String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[char]));
    async function retry(id) {
      await fetch(`/api/records/${encodeURIComponent(id)}/retry`, {method: "POST"});
      await load();
    }
    async function load() {
      const response = await fetch("/api/records");
      const data = await response.json();
      records.innerHTML = data.records.map((record) => `
        <article data-record-id="${esc(record.id)}">
          <div class="sentence">${esc(record.sentence)}</div>
          ${record.secondary ? `<div class="secondary">${esc(record.secondary)}</div>` : ""}
          <div class="meta">
            <span class="status">${esc(record.status)}</span>
            <span>${esc(record.filename)}</span>
            <span>${Number(record.start_time).toFixed(2)}-${Number(record.end_time).toFixed(2)}</span>
            ${record.error ? `<span>${esc(record.error)}</span>` : ""}
            ${record.status === "media_failed" ? `<button type="button" onclick="retry('${esc(record.id)}')">Retry</button>` : ""}
          </div>
        </article>
      `).join("");
    }
    load();
    setInterval(load, 2000);
  </script>
</body>
</html>
"""


class HistoryRequestHandler(BaseHTTPRequestHandler):
    store: HistoryStore

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/health":
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/records":
            self._send_json({"records": self.store.list_records()})
            return
        if parsed.path == "/api/pending":
            query = parse_qs(parsed.query)
            normalized = query.get("normalized_sentence", [""])[0]
            window = int(query.get("window_minutes", ["120"])[0])
            record = self.store.find_pending_by_normalized_sentence(unquote(normalized), window)
            self._send_json({"record": record})
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/records":
            self._send_json({"record": self.store.add_record(self._read_json())}, HTTPStatus.CREATED)
            return
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "records"] and parts[3] == "status":
            payload = self._read_json()
            record = self.store.update_status(
                parts[2],
                status=str(payload["status"]),
                note_id=payload.get("note_id"),
                error=str(payload.get("error", "")),
            )
            self._send_json({"record": record})
            return
        if len(parts) == 4 and parts[:2] == ["api", "records"] and parts[3] == "retry":
            self._send_json({"record": self.store.retry_record(parts[2])})
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def make_server(host: str, port: int, store: HistoryStore) -> ThreadingHTTPServer:
    class BoundHistoryRequestHandler(HistoryRequestHandler):
        pass

    BoundHistoryRequestHandler.store = store
    return ThreadingHTTPServer((host, port), BoundHistoryRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=44765)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    server = make_server(args.host, args.port, HistoryStore(args.db))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
```

- [ ] **Step 4: Run HTTP tests**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_web.py -v
```

Expected: PASS for both tests.

- [ ] **Step 5: Verify the server starts**

Run:

```bash
timeout 2 uv run --project mpvacious python -m history_server --host 127.0.0.1 --port 44765 --db /tmp/mpvacious-history-test.sqlite3
```

Expected: command exits after `timeout`; no Python import error appears.

- [ ] **Step 6: Commit the server**

Run:

```bash
git add mpvacious/history_server
git commit -m "feat: add mining history HTTP server"
```

Expected: commit succeeds.

## Task 4: Add Lua Normalizer With Tests

**Files:**
- Create: `mpvacious/history/normalizer.lua`
- Modify: `mpvacious/main.lua`

- [ ] **Step 1: Write the Lua normalizer module**

Create `mpvacious/history/normalizer.lua` with this content:

```lua
local h = require('helpers')

local this = {}

function this.normalize(text, config)
    if h.is_empty(text) then
        return ''
    end
    text = h.unescape_special_characters(text)
    text = h.remove_html_tags(text)
    text = h.trim(text)
    if config and config.nuke_spaces == true and h.contains_non_latin_letters(text) then
        text = h.remove_all_spaces(text)
    end
    return text
end

function this.run_tests()
    h.assert_equals(this.normalize('  これは　ペンです。  ', { nuke_spaces = false }), 'これは ペンです。')
    h.assert_equals(this.normalize('これは ペン です。', { nuke_spaces = true }), 'これはペンです。')
    h.assert_equals(this.normalize('&lt;b&gt;語&lt;/b&gt;', { nuke_spaces = false }), '語')
    h.assert_equals(this.normalize('<b>語</b>', { nuke_spaces = false }), '語')
end

return this
```

- [ ] **Step 2: Wire tests into `main.lua`**

Add this require near the other `local` requires in `mpvacious/main.lua`:

```lua
local history_normalizer = require('history.normalizer')
```

Update `run_tests()` in `mpvacious/main.lua` to call the normalizer tests:

```lua
local function run_tests()
    h.run_tests()
    note_exporter.run_tests()
    history_normalizer.run_tests()
end
```

- [ ] **Step 3: Run MPV test harness**

Run with the local video file selected for MPV verification:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: MPV logs include `TESTS PASSED`.

- [ ] **Step 4: Commit the normalizer**

Run:

```bash
git add mpvacious/history/normalizer.lua mpvacious/main.lua
git commit -m "feat: add history sentence normalizer"
```

Expected: commit succeeds.

## Task 5: Add Lua History Client And Server Startup

**Files:**
- Create: `mpvacious/history/client.lua`
- Create: `mpvacious/history/server_process.lua`

- [ ] **Step 1: Implement `history/client.lua`**

Create `mpvacious/history/client.lua` with this content:

```lua
local utils = require('mp.utils')
local platform = require('platform.init')
local h = require('helpers')

local function new(cfg_mgr)
    local self = {}

    local function base_url()
        return cfg_mgr.query("mining_history_url"):gsub("/$", "")
    end

    local function parse_result(result)
        if h.is_empty(result) or result.status ~= 0 or h.is_empty(result.stdout) then
            return nil, "history server unavailable"
        end
        local parsed = utils.parse_json(result.stdout)
        if h.is_empty(parsed) then
            return nil, "history server returned invalid JSON"
        end
        return parsed, nil
    end

    local function url_encode(str)
        return tostring(str):gsub("\n", "\r\n"):gsub("([^%w%-_%.~])", function(char)
            return string.format("%%%02X", string.byte(char))
        end)
    end

    local function post(path, payload, completion_fn)
        local request_json, error = utils.format_json(payload)
        if error ~= nil or request_json == "null" then
            if completion_fn then
                completion_fn(nil, "failed to format JSON")
            end
            return nil
        end
        return platform.json_curl_request {
            url = base_url() .. path,
            request_json = request_json,
            suppress_log = true,
            completion_fn = function(success, result, error_msg)
                if not success or error_msg then
                    return completion_fn and completion_fn(nil, tostring(error_msg))
                end
                local parsed, parse_error = parse_result(result)
                return completion_fn and completion_fn(parsed, parse_error)
            end
        }
    end

    local function get_sync(path)
        local result = platform.curl_request {
            args = { '-s', '--max-time', '2', base_url() .. path },
            suppress_log = true,
        }
        return parse_result(result)
    end

    function self.health()
        local parsed, error = get_sync('/health')
        return parsed and parsed.ok == true, error
    end

    function self.create_record(record, completion_fn)
        return post('/api/records', record, completion_fn)
    end

    function self.find_pending(normalized_sentence)
        local escaped = url_encode(normalized_sentence)
        return get_sync('/api/pending?normalized_sentence=' .. escaped .. '&window_minutes=' .. tostring(cfg_mgr.query("mining_history_match_window_minutes")))
    end

    function self.update_status(record_id, status, note_id, error, completion_fn)
        return post('/api/records/' .. url_encode(record_id) .. '/status', {
            status = status,
            note_id = note_id,
            error = error or '',
        }, completion_fn)
    end

    return self
end

return {
    new = new,
}
```

- [ ] **Step 2: Implement `history/server_process.lua`**

Create `mpvacious/history/server_process.lua` with this content:

```lua
local utils = require('mp.utils')
local h = require('helpers')

local function new(cfg_mgr, client)
    local self = {
        started = false,
    }

    local function parse_host_port(url)
        local host, port = url:match('^https?://([^:/]+):?(%d*)')
        return host or '127.0.0.1', port ~= '' and port or '44765'
    end

    local function uv_args()
        local plugin_dir = h.find_mpvacious_dir()
        local host, port = parse_host_port(cfg_mgr.query("mining_history_url"))
        local args = {
            'uv',
            'run',
            '--project',
            plugin_dir,
            'python',
            '-m',
            'history_server',
            '--host',
            host,
            '--port',
            tostring(port),
        }
        local db_path = cfg_mgr.query("mining_history_db")
        if not h.is_empty(db_path) then
            table.insert(args, '--db')
            table.insert(args, db_path)
        end
        return args
    end

    function self.ensure_running()
        local ok = client.health()
        if ok then
            return true
        end
        if self.started then
            return false
        end
        self.started = true
        h.subprocess_detached { args = uv_args(), suppress_log = true }
        return true
    end

    function self.open_page()
        local platform = require('platform.init')
        return h.subprocess_detached {
            args = { platform.open_utility, cfg_mgr.query("mining_history_url") },
            suppress_log = true,
        }
    end

    return self
end

return {
    new = new,
}
```

- [ ] **Step 3: Run Lua syntax checks through MPV test harness**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: no Lua module-load error for `history.client` or `history.server_process`.

- [ ] **Step 4: Commit the client and server process modules**

Run:

```bash
git add mpvacious/history/client.lua mpvacious/history/server_process.lua
git commit -m "feat: add history server Lua client"
```

Expected: commit succeeds.

## Task 6: Capture Current Subtitle Into History

**Files:**
- Create: `mpvacious/history/capture.lua`
- Create: `mpvacious/history/controller.lua`
- Modify: `mpvacious/config/defaults.lua`
- Modify: `mpvacious/config/default_config.conf`
- Modify: `mpvacious/main.lua`

- [ ] **Step 1: Add config defaults**

Add these entries to `this.defaults` in `mpvacious/config/defaults.lua` near the "New note timer" section:

```lua
    -- Mining history
    mining_history_enabled = true,
    mining_history_key = "Ctrl+Shift+n",
    mining_history_url = "http://127.0.0.1:44765",
    mining_history_open_browser = true,
    mining_history_db = "",
    mining_history_match_window_minutes = 120,
```

Add this documented section to `mpvacious/config/default_config.conf` after the new note timer settings:

```conf
##
## Mining history
##

# Send the current subtitle to a local browser mining history.
mining_history_enabled=yes

# Global mpv key binding for sending the current subtitle to history.
mining_history_key=Ctrl+Shift+n

# Local history helper URL.
mining_history_url=http://127.0.0.1:44765

# Open the history page after the first successful capture.
mining_history_open_browser=yes

# Optional SQLite database path. Leave empty to use the helper default.
mining_history_db=

# Only match Yomitan-created notes against pending history records from this many minutes.
mining_history_match_window_minutes=120
```

- [ ] **Step 2: Implement record capture**

Create `mpvacious/history/capture.lua` with this content:

```lua
local mp = require('mp')
local Subtitle = require('subtitles.subtitle')
local normalizer = require('history.normalizer')
local h = require('helpers')

local function new(cfg_mgr, subs_observer)
    local self = {}

    local function make_id(sub)
        local stamp = tostring(os.time()) .. "-" .. tostring(math.floor((sub.start or 0) * 1000))
        return stamp:gsub("[^%w%-]", "-")
    end

    function self.current_record()
        local primary = Subtitle:now()
        if h.is_empty(primary) then
            return nil, "There's no visible subtitle."
        end
        local secondary = Subtitle:now('secondary')
        local sentence = subs_observer.clipboard_prepare(primary.text)
        local config = cfg_mgr.config()
        return {
            id = make_id(primary),
            sentence = sentence,
            normalized_sentence = normalizer.normalize(sentence, config),
            secondary = secondary and secondary.text or '',
            start_time = primary.start,
            end_time = primary['end'],
            snapshot_time = mp.get_property_number("time-pos", primary.start),
            video_path = mp.get_property("path") or '',
            filename = mp.get_property("filename") or '',
            profile = cfg_mgr.profiles().active,
        }, nil
    end

    return self
end

return {
    new = new,
}
```

- [ ] **Step 3: Implement the controller**

Create `mpvacious/history/controller.lua` with this content:

```lua
local h = require('helpers')
local make_client = require('history.client')
local make_capture = require('history.capture')
local make_server_process = require('history.server_process')

local function new()
    local self = {
        opened_page = false,
    }

    function self.init(cfg_mgr, subs_observer)
        self.cfg_mgr = cfg_mgr
        self.client = make_client.new(cfg_mgr)
        self.capture = make_capture.new(cfg_mgr, subs_observer)
        self.server_process = make_server_process.new(cfg_mgr, self.client)
    end

    function self.enabled()
        return self.cfg_mgr and self.cfg_mgr.query("mining_history_enabled") == true
    end

    function self.capture_current()
        if not self.enabled() then
            return h.notify("Mining history is disabled.", "info", 2)
        end
        self.server_process.ensure_running()
        local record, error = self.capture.current_record()
        if error then
            return h.notify(error, "warn", 2)
        end
        self.client.create_record(record, function(_, request_error)
            if request_error then
                return h.notify("Mining history failed: " .. request_error, "error", 4)
            end
            h.notify("Sent subtitle to mining history.", "info", 1)
            if self.cfg_mgr.query("mining_history_open_browser") == true and self.opened_page == false then
                self.opened_page = true
                self.server_process.open_page()
            end
        end)
    end

    function self.find_pending_for_sentence(normalized_sentence)
        if not self.enabled() then
            return nil
        end
        self.server_process.ensure_running()
        local parsed = self.client.find_pending(normalized_sentence)
        return parsed and parsed.record or nil
    end

    function self.update_status(record_id, status, note_id, error)
        if not self.enabled() then
            return
        end
        self.client.update_status(record_id, status, note_id, error or '', function(_, request_error)
            if request_error then
                h.notify("Mining history status update failed: " .. request_error, "warn", 3)
            end
        end)
    end

    return self
end

return {
    new = new,
}
```

- [ ] **Step 4: Wire capture into `main.lua`**

Add this require near the other requires:

```lua
local make_history_controller = require('history.controller')
```

Add this singleton near the existing `note_exporter` and `cfg_mgr` singletons:

```lua
local history_controller = make_history_controller.new()
```

Add the controller to `self` near the other exported objects:

```lua
self.history_controller = history_controller
```

Add this helper near `global_binds_menu:add_global_bindings()`:

```lua
local function add_history_global_binding()
    if cfg_mgr.query("mining_history_enabled") ~= true then
        return
    end
    local item = {
        key = cfg_mgr.query("mining_history_key"),
        name = "mpvacious-send-to-mining-history",
        fn = _run { history_controller.capture_current },
        text = "Send current subtitle to mining history",
        force = true,
    }
    table.insert(global_binds_menu.bindings_switch.all_items(), item)
end
```

In `main()`, initialize history after `subs_observer.init(menu, cfg_mgr)`:

```lua
        history_controller.init(cfg_mgr, subs_observer)
```

Call `add_history_global_binding()` immediately before `global_binds_menu:add_global_bindings()`:

```lua
        add_history_global_binding()
        global_binds_menu:add_global_bindings()
```

- [ ] **Step 5: Run MPV and capture one subtitle**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file with subtitles}"
mpv "$VIDEO_FILE"
```

Press `Ctrl+Shift+n` while a subtitle is visible.

Expected: OSD says `Sent subtitle to mining history.` and the browser opens `http://127.0.0.1:44765`.

- [ ] **Step 6: Commit capture wiring**

Run:

```bash
git add mpvacious/config/defaults.lua mpvacious/config/default_config.conf mpvacious/history/capture.lua mpvacious/history/controller.lua mpvacious/main.lua
git commit -m "feat: capture subtitles to mining history"
```

Expected: commit succeeds.

## Task 7: Allow Encoder Jobs To Use Stored Source Paths

**Files:**
- Modify: `mpvacious/encoder/encoder.lua`

- [ ] **Step 1: Update `create_audio` to accept a source path**

In `mpvacious/encoder/encoder.lua`, change the function signature:

```lua
local create_audio = function(start_timestamp, end_timestamp, filename, padding, on_finish_fn, source_path)
```

Replace this line inside that function:

```lua
        local source_path = mp.get_property("path")
```

with:

```lua
        source_path = source_path or mp.get_property("path")
```

- [ ] **Step 2: Update job creation to read optional record fields**

In `create_job`, replace the snapshot branch body with:

```lua
        current_timestamp = sub.snapshot_time or mp.get_property_number("time-pos", 0)
        local source_path = sub.source_path or mp.get_property("path")
        job.filename = make_snapshot_filename(sub['start'], sub['end'], current_timestamp)
        job.run_async = function()
            create_snapshot(sub['start'], sub['end'], current_timestamp, job.filename, on_finish_fn, source_path)
        end
```

Change the `create_snapshot` signature:

```lua
local create_snapshot = function(start_timestamp, end_timestamp, current_timestamp, filename, on_finish_fn, source_path)
```

Replace this line inside `create_snapshot`:

```lua
        local source_path = mp.get_property("path")
```

with:

```lua
        source_path = source_path or mp.get_property("path")
```

In the audio branch of `create_job`, replace `job.run_async` with:

```lua
        local source_path = sub.source_path or mp.get_property("path")
        job.run_async = function()
            create_audio(sub['start'], sub['end'], job.filename, audio_padding, on_finish_fn, source_path)
        end
```

- [ ] **Step 3: Run MPV test harness**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: `TESTS PASSED`.

- [ ] **Step 4: Manually verify normal note creation still creates media**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file with subtitles}"
mpv "$VIDEO_FILE"
```

Press `Ctrl+n` on a visible subtitle.

Expected: Anki receives a note and configured screenshot/audio files are created.

- [ ] **Step 5: Commit encoder source-path support**

Run:

```bash
git add mpvacious/encoder/encoder.lua
git commit -m "feat: support history source paths in encoder jobs"
```

Expected: commit succeeds.

## Task 8: Backfill Matched Notes From History Records

**Files:**
- Modify: `mpvacious/anki/note_exporter.lua`

- [ ] **Step 1: Add a history subtitle builder**

In `mpvacious/anki/note_exporter.lua`, add this local function after `update_notes`:

```lua
    local function subtitle_from_history_record(record)
        return {
            text = record.sentence,
            secondary = record.secondary or '',
            start = tonumber(record.start_time),
            ['end'] = tonumber(record.end_time),
            snapshot_time = tonumber(record.snapshot_time),
            source_path = record.video_path,
        }
    end
```

- [ ] **Step 2: Add a history media updater**

Add this function after `subtitle_from_history_record`:

```lua
    local function update_note_from_history_record(note_id, record, on_finish)
        maybe_reload_config()
        local sub = subtitle_from_history_record(record)
        if h.is_empty(sub.source_path) then
            if on_finish then
                on_finish(false, "history record has no video path")
            end
            return
        end

        local anki_media_dir = self.ankiconnect.get_media_dir_path()
        if h.is_empty(anki_media_dir) then
            if on_finish then
                on_finish(false, "couldn't find Anki media directory")
            end
            return
        end

        self.encoder.set_output_dir(anki_media_dir)
        self.forvo.set_output_dir(anki_media_dir)

        local snapshot = self.encoder.snapshot.create_job(sub)
        local audio = self.encoder.audio.create_job(sub, audio_padding())
        local new_data = construct_note_fields(sub.text, sub.secondary, snapshot.filename, audio.filename)
        local remaining = 2
        local media_ok = true

        local function media_finished(success)
            if success == false then
                media_ok = false
            end
            remaining = remaining - 1
            if remaining > 0 then
                return
            end
            if media_ok == false then
                if on_finish then
                    on_finish(false, "media creation failed")
                end
                return
            end
            self.ankiconnect.append_media(
                    note_id,
                    make_new_note_data(self.ankiconnect.get_note_fields(note_id), h.deep_copy(new_data), { overwrite = false }),
                    substitute_fmt(self.config.note_tag),
                    function(error)
                        if on_finish then
                            on_finish(h.is_empty(error), error)
                        end
                    end
            )
        end

        snapshot.on_finish(media_finished).run_async()
        audio.on_finish(media_finished).run_async()
    end
```

- [ ] **Step 3: Export the history updater**

Add this entry to the returned table:

```lua
        update_note_from_history_record = update_note_from_history_record,
```

- [ ] **Step 4: Run MPV test harness**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: `TESTS PASSED`.

- [ ] **Step 5: Commit history backfill support**

Run:

```bash
git add mpvacious/anki/note_exporter.lua
git commit -m "feat: backfill Anki media from history records"
```

Expected: commit succeeds.

## Task 9: Match New Yomitan Notes Against History

**Files:**
- Modify: `mpvacious/anki/new_note_checker.lua`
- Modify: `mpvacious/main.lua`

- [ ] **Step 1: Extend `new_note_checker.init` signature**

In `mpvacious/anki/new_note_checker.lua`, change:

```lua
    local function init(ankiconnect, update_notes_fn, cfg_mgr)
```

to:

```lua
    local function init(ankiconnect, update_notes_fn, update_history_note_fn, history_controller, cfg_mgr)
```

Inside that function, add:

```lua
        self.update_history_note_fn = update_history_note_fn
        self.history_controller = history_controller
```

- [ ] **Step 2: Add history matching helper**

In `new_note_checker.lua`, add this require at the top:

```lua
local normalizer = require('history.normalizer')
```

Add this local function before `process_new_notes`:

```lua
    local function try_update_from_history(note_id, note_fields)
        if h.is_empty(self.history_controller) or not self.history_controller.enabled() then
            return false
        end
        local sentence = note_fields[self.config.sentence_field]
        if h.is_empty(sentence) then
            return false
        end
        local normalized = normalizer.normalize(sentence, self.config)
        local record = self.history_controller.find_pending_for_sentence(normalized)
        if h.is_empty(record) then
            return false
        end
        self.history_controller.update_status(record.id, "matched_note", note_id, "")
        self.update_history_note_fn(note_id, record, function(success, error)
            if success then
                self.history_controller.update_status(record.id, "media_done", note_id, "")
            else
                self.history_controller.update_status(record.id, "media_failed", note_id, error or "media backfill failed")
            end
        end)
        return true
    end
```

- [ ] **Step 3: Use history matching before fallback updates**

Inside `process_new_notes`, replace this block:

```lua
                if not h.is_empty(note_fields) and note_fields[self.config.sentence_field] ~= nil and is_note_recent(note_id) and has_no_media(note_fields) then
                    -- Note matches our criteria, update it (just like pressing Ctrl+M does).
                    table.insert(to_update, note_id)
                end
```

with:

```lua
                if not h.is_empty(note_fields) and note_fields[self.config.sentence_field] ~= nil and is_note_recent(note_id) and has_no_media(note_fields) then
                    if not try_update_from_history(note_id, note_fields) then
                        table.insert(to_update, note_id)
                    end
                end
```

- [ ] **Step 4: Wire the new init call in `main.lua`**

Replace the existing `new_note_checker.init` call in `main.lua`:

```lua
        new_note_checker.init(ankiconnect, menu:with_update { note_exporter.update_notes }, cfg_mgr)
```

with:

```lua
        new_note_checker.init(
                ankiconnect,
                menu:with_update { note_exporter.update_notes },
                note_exporter.update_note_from_history_record,
                history_controller,
                cfg_mgr
        )
```

- [ ] **Step 5: Run MPV test harness**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: `TESTS PASSED`.

- [ ] **Step 6: Commit history matching**

Run:

```bash
git add mpvacious/anki/new_note_checker.lua mpvacious/main.lua
git commit -m "feat: match new Anki notes to mining history"
```

Expected: commit succeeds.

## Task 10: Add Retry Support From The History Page

**Files:**
- Modify: `mpvacious/history/controller.lua`
- Modify: `mpvacious/anki/new_note_checker.lua`

- [ ] **Step 1: Add matched-record lookup API to Lua client**

In `mpvacious/history/client.lua`, add this function before `update_status`:

```lua
    function self.list_records()
        return get_sync('/api/records')
    end
```

- [ ] **Step 2: Add a retry processor to the controller**

In `mpvacious/history/controller.lua`, add:

```lua
    function self.records_waiting_for_retry()
        if not self.enabled() then
            return {}
        end
        local parsed = self.client.list_records()
        local ret = {}
        for _, record in ipairs(parsed and parsed.records or {}) do
            if record.status == "matched_note" and record.note_id ~= nil and record.error == "retry requested" then
                table.insert(ret, record)
            end
        end
        return ret
    end
```

- [ ] **Step 3: Process retry records on each timer tick**

In `new_note_checker.lua`, add this function before `check_for_new_notes`:

```lua
    local function process_history_retries()
        if h.is_empty(self.history_controller) or not self.history_controller.enabled() then
            return
        end
        for _, record in ipairs(self.history_controller.records_waiting_for_retry()) do
            self.update_history_note_fn(record.note_id, record, function(success, error)
                if success then
                    self.history_controller.update_status(record.id, "media_done", record.note_id, "")
                else
                    self.history_controller.update_status(record.id, "media_failed", record.note_id, error or "media retry failed")
                end
            end)
        end
    end
```

Change `check_for_new_notes()` to:

```lua
    local function check_for_new_notes()
        process_history_retries()
        return find_notes_added_today(process_new_notes)
    end
```

- [ ] **Step 4: Run MPV test harness**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: `TESTS PASSED`.

- [ ] **Step 5: Commit retry processing**

Run:

```bash
git add mpvacious/history/client.lua mpvacious/history/controller.lua mpvacious/anki/new_note_checker.lua
git commit -m "feat: retry failed history media backfills"
```

Expected: commit succeeds.

## Task 11: End-To-End Manual Verification

**Files:**
- No code changes unless verification finds a defect.

- [ ] **Step 1: Start Anki and confirm AnkiConnect health**

Run:

```bash
curl -s http://127.0.0.1:8765 -X POST -d '{"action":"version","version":6}'
```

Expected: JSON response has `"error": null`.

- [ ] **Step 2: Start MPV and capture consecutive subtitles**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local Japanese video file with subtitles}"
mpv "$VIDEO_FILE"
```

Press `Ctrl+Shift+n` on three consecutive subtitle lines.

Expected: OSD confirms each capture and the browser page lists three records.

- [ ] **Step 3: Mine a word with Yomitan**

On `http://127.0.0.1:44765`, scan a word from the first captured sentence and create an Anki note using the user's Yomitan Anki profile.

Expected: Anki creates the note immediately and the configured sentence field contains the full browser sentence.

- [ ] **Step 4: Confirm media backfill**

Wait for the `new_note_timer_interval_seconds` interval.

Expected:

- history page record status changes from `pending_note` to `matched_note` and then `media_done`;
- Anki note has configured audio and image fields filled;
- MPV remains usable while media is created.

- [ ] **Step 5: Confirm existing mpvacious flow still works**

Press `Ctrl+n` on a visible subtitle.

Expected: mpvacious creates a normal note with sentence, audio, and image fields as it did before this feature.

- [ ] **Step 6: Commit any verification fixes**

If defects were fixed during this task, commit them:

```bash
git add mpvacious
git commit -m "fix: stabilize mining history verification"
```

Expected: either no commit is needed or the commit succeeds.

## Task 12: Documentation

**Files:**
- Create: `howto/mining_history.md`
- Modify: `README.md`

- [ ] **Step 1: Add the workflow guide**

Create `howto/mining_history.md` with this content:

```markdown
# Mining History

Mining history lets you send visible subtitle lines from mpv to a local browser page, mine words with Yomitan, and let mpvacious add screenshot and audio fields after Yomitan creates the Anki note.

## Requirements

- mpvacious installed from this fork.
- `uv` available in `PATH`.
- Anki with AnkiConnect enabled.
- Yomitan configured to create Anki notes and send `{sentence}` to the same sentence field configured in `subs2srs.conf`.

## Configuration

The default shortcut is `Ctrl+Shift+n`.

```conf
mining_history_enabled=yes
mining_history_key=Ctrl+Shift+n
mining_history_url=http://127.0.0.1:44765
mining_history_open_browser=yes
mining_history_db=
mining_history_match_window_minutes=120
```

The existing `deck_name`, `model_name`, `sentence_field`, `audio_field`, and `image_field` settings are reused.

## Workflow

1. Open a video in mpv.
2. Press `Ctrl+Shift+n` on each sentence you want in history.
3. Open the history page at `http://127.0.0.1:44765`.
4. Use Yomitan on the browser page to create Anki notes.
5. Keep mpvacious running so the new note timer can match notes and add media.

If media creation fails, press `Retry` on the history page while mpvacious is running.
```

- [ ] **Step 2: Link the guide from README**

In `README.md`, add one bullet under the howto list:

```markdown
* [Mining history](howto/mining_history.md)
```

Add this key binding to the key binding table:

```text
Ctrl+Shift+n script-binding mpvacious-send-to-mining-history
```

- [ ] **Step 3: Commit documentation**

Run:

```bash
git add README.md howto/mining_history.md
git commit -m "docs: document mining history workflow"
```

Expected: commit succeeds.

## Task 13: Final Verification And Release Readiness

**Files:**
- Read: `git status`
- Read: `git log`

- [ ] **Step 1: Run Python tests**

Run:

```bash
uv run --project mpvacious pytest -v
```

Expected: all Python tests pass.

- [ ] **Step 2: Run MPV Lua tests**

Run:

```bash
VIDEO_FILE="${MPVACIOUS_TEST_VIDEO:?set MPVACIOUS_TEST_VIDEO to a local video file}"
MPVACIOUS_TEST=TRUE mpv "$VIDEO_FILE"
```

Expected: `TESTS PASSED`.

- [ ] **Step 3: Check packaging still builds**

Run:

```bash
make VERSION=v0.0.0-mining-history-test
```

Expected: archive creation succeeds and includes `mpvacious/pyproject.toml`, `mpvacious/uv.lock`, and `mpvacious/history_server/`.

- [ ] **Step 4: Inspect worktree**

Run:

```bash
git status --short --branch
```

Expected: clean worktree on `feature/mining-history`.

- [ ] **Step 5: Summarize commits**

Run:

```bash
git log --oneline --decorate origin/master..HEAD
```

Expected: shows the mining history implementation commits in task order.
