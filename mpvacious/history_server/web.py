from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .store import HistoryStore, InvalidStatusError


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mpvoracious Mining History</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: Canvas;
      color: CanvasText;
    }
    body {
      margin: 0;
      min-height: 100vh;
    }
    header, main {
      width: min(980px, calc(100% - 32px));
      margin: 0 auto;
    }
    header {
      padding: 28px 0 16px;
    }
    h1 {
      margin: 0;
      font-size: 1.65rem;
      line-height: 1.2;
      letter-spacing: 0;
    }
    main {
      display: grid;
      gap: 12px;
      padding-bottom: 28px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
      margin-top: 14px;
    }
    article {
      border: 1px solid color-mix(in srgb, CanvasText 20%, transparent);
      border-radius: 8px;
      padding: 14px;
      background: color-mix(in srgb, Canvas 94%, CanvasText 6%);
    }
    article[data-status="media_failed"] {
      border-color: #b42318;
    }
    .sentence {
      margin: 0 0 10px;
      font-size: 1.05rem;
      line-height: 1.5;
      user-select: text;
      white-space: pre-wrap;
    }
    .secondary {
      margin: -4px 0 10px;
      color: color-mix(in srgb, CanvasText 72%, transparent);
      white-space: pre-wrap;
    }
    dl {
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 6px 10px;
      margin: 0;
      font-size: 0.88rem;
    }
    dt {
      color: color-mix(in srgb, CanvasText 65%, transparent);
    }
    dd {
      margin: 0;
      overflow-wrap: anywhere;
    }
    .record-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    button {
      padding: 7px 10px;
      border: 1px solid color-mix(in srgb, CanvasText 25%, transparent);
      border-radius: 6px;
      background: Canvas;
      color: CanvasText;
      cursor: pointer;
    }
    button:disabled {
      cursor: default;
      opacity: 0.55;
    }
    button:hover {
      background: color-mix(in srgb, CanvasText 8%, Canvas);
    }
    button:disabled:hover {
      background: Canvas;
    }
    .empty {
      color: color-mix(in srgb, CanvasText 65%, transparent);
    }
  </style>
</head>
<body>
  <header>
    <h1>Mpvoracious Mining History</h1>
    <div class="toolbar">
      <button id="clear-done" type="button">Clear Done</button>
      <button id="clear-all" type="button">Clear All</button>
    </div>
  </header>
  <main id="records" aria-live="polite"></main>
  <script>
    const recordsEl = document.querySelector("#records");
    const clearDoneButton = document.querySelector("#clear-done");
    const clearAllButton = document.querySelector("#clear-all");

    function text(value) {
      return value === null || value === undefined || value === "" ? "-" : String(value);
    }

    function formatTime(seconds) {
      if (typeof seconds !== "number") return text(seconds);
      const minutes = Math.floor(seconds / 60);
      const rest = Math.max(0, seconds - minutes * 60).toFixed(2).padStart(5, "0");
      return `${minutes}:${rest}`;
    }

    function metadata(record) {
      return [
        ["Status", record.status],
        ["Note", record.note_id],
        ["Error", record.error],
        ["File", record.filename],
        ["Profile", record.profile],
        ["Range", `${formatTime(record.start_time)} - ${formatTime(record.end_time)}`],
      ];
    }

    function render(records) {
      recordsEl.replaceChildren();
      const doneCount = records.filter((record) => record.status === "media_done").length;
      clearDoneButton.disabled = doneCount === 0;
      clearDoneButton.title = doneCount === 0 ? "No completed records to clear" : `Clear ${doneCount} completed record${doneCount === 1 ? "" : "s"}`;
      clearAllButton.disabled = records.length === 0;
      clearAllButton.title = records.length === 0 ? "No records to clear" : `Clear all ${records.length} record${records.length === 1 ? "" : "s"}`;
      if (!records.length) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "No mining records yet.";
        recordsEl.append(empty);
        return;
      }
      for (const record of records) {
        const article = document.createElement("article");
        article.dataset.status = record.status;

        const sentence = document.createElement("p");
        sentence.className = "sentence";
        sentence.textContent = record.sentence;
        article.append(sentence);

        if (record.secondary) {
          const secondary = document.createElement("p");
          secondary.className = "secondary";
          secondary.textContent = record.secondary;
          article.append(secondary);
        }

        const list = document.createElement("dl");
        for (const [label, value] of metadata(record)) {
          const term = document.createElement("dt");
          term.textContent = label;
          const detail = document.createElement("dd");
          detail.textContent = text(value);
          list.append(term, detail);
        }
        article.append(list);

        const actions = document.createElement("div");
        actions.className = "record-actions";

        const previewButton = document.createElement("button");
        previewButton.type = "button";
        previewButton.textContent = "Preview";
        previewButton.addEventListener("click", async () => {
          await fetch(`/api/records/${encodeURIComponent(record.id)}/preview`, {method: "POST"});
        });
        actions.append(previewButton);

        if (record.status === "media_failed") {
          const retry = document.createElement("button");
          retry.type = "button";
          retry.textContent = "Retry";
          retry.addEventListener("click", async () => {
            await fetch(`/api/records/${encodeURIComponent(record.id)}/retry`, {method: "POST"});
            await load();
          });
          actions.append(retry);
        }

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.textContent = "Delete";
        deleteButton.addEventListener("click", async () => {
          if (!confirm("Delete this mining record?")) return;
          await fetch(`/api/records/${encodeURIComponent(record.id)}`, {method: "DELETE"});
          await load();
        });
        actions.append(deleteButton);
        article.append(actions);

        recordsEl.append(article);
      }
    }

    clearDoneButton.addEventListener("click", async () => {
      if (clearDoneButton.disabled) return;
      if (!confirm("Clear all completed mining records?")) return;
      await fetch("/api/records/clear-done", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: "{}",
      });
      await load();
    });

    clearAllButton.addEventListener("click", async () => {
      if (clearAllButton.disabled) return;
      if (!confirm("Clear all mining records?")) return;
      await fetch("/api/records/clear-all", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: "{}",
      });
      await load();
    });

    async function load() {
      const response = await fetch("/api/records");
      if (!response.ok) return;
      const payload = await response.json();
      render(payload.records || []);
    }

    load();
    setInterval(load, 3000);
  </script>
</body>
</html>
"""


class HistoryHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], store: HistoryStore) -> None:
        super().__init__(server_address, HistoryRequestHandler)
        self.store = store


class HistoryRequestHandler(BaseHTTPRequestHandler):
    server: HistoryHTTPServer

    @property
    def store(self) -> HistoryStore:
        return self.server.store

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
            self._handle_pending(parsed.query)
            return
        if parsed.path == "/api/preview":
            self._handle_consume_preview()
            return
        self._send_not_found()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/records":
            self._handle_create_record()
            return
        if parsed.path == "/api/claims":
            self._handle_claim()
            return
        if parsed.path == "/api/records/clear-done":
            self._handle_clear_done()
            return
        if parsed.path == "/api/records/clear-all":
            self._handle_clear_all()
            return

        record_id, action = self._parse_record_action(parsed.path)
        if record_id is not None and action == "status":
            self._handle_update_status(record_id)
            return
        if record_id is not None and action == "retry":
            self._handle_retry(record_id)
            return
        if record_id is not None and action == "preview":
            self._handle_queue_preview(record_id)
            return

        self._send_not_found()

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        record_id = self._parse_record_id(parsed.path)
        if record_id is not None:
            self._handle_delete_record(record_id)
            return
        self._send_not_found()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _handle_pending(self, query: str) -> None:
        params = parse_qs(query)
        normalized_sentence = params.get("normalized_sentence", [""])[0]
        try:
            window_minutes = int(params.get("window_minutes", ["120"])[0])
        except ValueError:
            window_minutes = 120
        record = self.store.find_pending_by_normalized_sentence(
            normalized_sentence,
            window_minutes,
        )
        self._send_json({"record": record})

    def _handle_create_record(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            record = self.store.add_record(payload)
        except (KeyError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record, HTTPStatus.CREATED)

    def _handle_claim(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = self.store.claim_note(
                note_id=int(payload["note_id"]),
                normalized_sentence=str(payload["normalized_sentence"]),
                window_minutes=int(payload["window_minutes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _handle_update_status(self, record_id: str) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            record = self.store.update_status(
                record_id,
                status=str(payload.get("status", "")),
                note_id=payload.get("note_id"),
                error=str(payload.get("error", "")),
            )
        except KeyError:
            self._send_not_found()
            return
        except (InvalidStatusError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record)

    def _handle_retry(self, record_id: str) -> None:
        try:
            record = self.store.retry_record(record_id)
        except KeyError:
            self._send_not_found()
            return
        self._send_json(record)

    def _handle_delete_record(self, record_id: str) -> None:
        try:
            self.store.delete_record(record_id)
        except KeyError:
            self._send_not_found()
            return
        self._send_json({"deleted": 1})

    def _handle_clear_done(self) -> None:
        self._send_json({"deleted": self.store.clear_done_records()})

    def _handle_clear_all(self) -> None:
        self._send_json({"deleted": self.store.clear_all_records()})

    def _handle_queue_preview(self, record_id: str) -> None:
        try:
            record = self.store.queue_preview(record_id)
        except KeyError:
            self._send_not_found()
            return
        self._send_json({"record": record})

    def _handle_consume_preview(self) -> None:
        self._send_json({"record": self.store.consume_preview_request()})

    def _parse_record_id(self, path: str) -> str | None:
        prefix = "/api/records/"
        if not path.startswith(prefix):
            return None
        suffix = path[len(prefix) :]
        if not suffix or "/" in suffix:
            return None
        return unquote(suffix)

    def _parse_record_action(self, path: str) -> tuple[str | None, str | None]:
        prefix = "/api/records/"
        if not path.startswith(prefix):
            return None, None
        suffix = path[len(prefix) :]
        parts = suffix.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None, None
        return unquote(parts[0]), parts[1]

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(
        self,
        body: dict[str, Any] | list[Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_not_found(self) -> None:
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def make_server(host: str, port: int, store: HistoryStore) -> ThreadingHTTPServer:
    return HistoryHTTPServer((host, port), store)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve mpvoracious mining history")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=44765)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()

    store = HistoryStore(args.db)
    server = make_server(args.host, args.port, store)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
