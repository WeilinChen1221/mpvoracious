from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .store import (
    HistoryStore,
    InvalidCursorError,
    InvalidStatusError,
    NoLinkedNotesError,
    StaleLeaseError,
)


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
      --border: color-mix(in srgb, CanvasText 20%, transparent);
      --muted: color-mix(in srgb, CanvasText 65%, transparent);
      --surface: color-mix(in srgb, Canvas 94%, CanvasText 6%);
      --waiting: #6b7280;
      --sending: #b45309;
      --ready: #15803d;
      --failed: #b42318;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --waiting: #9ca3af;
        --sending: #fbbf24;
        --ready: #4ade80;
        --failed: #fb7185;
      }
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; }
    header, main { width: min(1080px, calc(100% - 32px)); margin: 0 auto; }
    header { padding: 28px 0 16px; }
    h1 { margin: 0; font-size: 1.65rem; line-height: 1.2; }
    main { display: grid; gap: 12px; padding-bottom: 28px; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; margin-top: 14px; }
    .filters {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin-top: 18px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
    }
    .filters label { display: grid; gap: 5px; color: var(--muted); font-size: .82rem; }
    .filters input, .filters select {
      width: 100%;
      min-height: 36px;
      padding: 6px 8px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: Canvas;
      color: CanvasText;
      font: inherit;
    }
    .filters select[multiple] { min-height: 86px; }
    .filter-actions { display: flex; align-items: end; }
    article { border: 1px solid var(--border); border-radius: 8px; padding: 14px; background: var(--surface); }
    article[data-status="media_failed"] { border-color: var(--failed); }
    .sentence { margin: 0 0 10px; font-size: 1.05rem; line-height: 1.5; user-select: text; white-space: pre-wrap; }
    .secondary { margin: -4px 0 10px; color: color-mix(in srgb, CanvasText 72%, transparent); white-space: pre-wrap; }
    dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 10px; margin: 0; font-size: .88rem; }
    dt { color: var(--muted); }
    dd { margin: 0; overflow-wrap: anywhere; }
    .status { display: inline-flex; align-items: center; gap: 7px; }
    .status-dot { width: .7em; height: .7em; border-radius: 50%; flex: 0 0 auto; background: var(--waiting); }
    .status[data-status="matched_note"] .status-dot { background: var(--sending); }
    .status[data-status="media_done"] .status-dot { background: var(--ready); }
    .status[data-status="media_failed"] .status-dot { background: var(--failed); }
    .record-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    button { padding: 7px 10px; border: 1px solid color-mix(in srgb, CanvasText 25%, transparent); border-radius: 6px; background: Canvas; color: CanvasText; cursor: pointer; }
    button:disabled { cursor: default; opacity: .55; }
    button:hover:not(:disabled) { background: color-mix(in srgb, CanvasText 8%, Canvas); }
    .empty { color: var(--muted); }
    #load-more { justify-self: center; }
  </style>
</head>
<body>
  <header>
    <h1>Mpvoracious Mining History</h1>
    <div class="toolbar">
      <button id="clear-done" type="button">Clear Done</button>
      <button id="clear-all" type="button">Clear All</button>
    </div>
    <form id="filters" class="filters">
      <label>Record Status
        <select id="status-filter" multiple>
          <option value="pending_note">Waiting for note</option>
          <option value="matched_note">Sending media</option>
          <option value="media_done">Media ready</option>
          <option value="media_failed">Media failed</option>
        </select>
      </label>
      <label>Source Info
        <input id="source-filter" type="search" autocomplete="off">
      </label>
      <label>Subtitle
        <input id="subtitle-filter" type="search" autocomplete="off">
      </label>
      <label>Capture Profile
        <select id="profile-filter" multiple></select>
      </label>
      <label>Linked Anki Note ID
        <input id="note-filter" type="number" min="1" step="1" inputmode="numeric">
      </label>
      <div class="filter-actions"><button id="clear-filters" type="button">Clear filters</button></div>
    </form>
  </header>
  <main>
    <section id="records" aria-live="polite"></section>
    <button id="load-more" type="button" hidden>Load more</button>
  </main>
  <script>
    const recordsEl = document.querySelector("#records");
    const filtersEl = document.querySelector("#filters");
    const statusFilter = document.querySelector("#status-filter");
    const sourceFilter = document.querySelector("#source-filter");
    const subtitleFilter = document.querySelector("#subtitle-filter");
    const profileFilter = document.querySelector("#profile-filter");
    const noteFilter = document.querySelector("#note-filter");
    const clearFiltersButton = document.querySelector("#clear-filters");
    const clearDoneButton = document.querySelector("#clear-done");
    const clearAllButton = document.querySelector("#clear-all");
    const loadMoreButton = document.querySelector("#load-more");
    const statusLabels = {
      pending_note: "Waiting for note",
      matched_note: "Sending media",
      media_done: "Media ready",
      media_failed: "Media failed",
    };
    let renderedRecords = [];
    let nextCursor = null;
    let requestSerial = 0;
    let filterTimer = null;

    function selectedValues(select) {
      return Array.from(select.selectedOptions, (option) => option.value);
    }

    function queryParams(cursor) {
      const params = new URLSearchParams();
      for (const status of selectedValues(statusFilter)) params.append("status", status);
      for (const profile of selectedValues(profileFilter)) params.append("profile", profile);
      if (sourceFilter.value.trim()) params.set("source_info", sourceFilter.value.trim());
      if (subtitleFilter.value.trim()) params.set("subtitle", subtitleFilter.value.trim());
      if (noteFilter.value.trim()) params.set("note_id", noteFilter.value.trim());
      if (cursor) params.set("cursor", cursor);
      return params;
    }

    function text(value) {
      return value === null || value === undefined || value === "" ? "-" : String(value);
    }

    function formatTime(seconds) {
      if (typeof seconds !== "number") return text(seconds);
      const minutes = Math.floor(seconds / 60);
      const rest = Math.max(0, seconds - minutes * 60).toFixed(2).padStart(5, "0");
      return `${minutes}:${rest}`;
    }

    function statusDetail(record) {
      const wrapper = document.createElement("span");
      wrapper.className = "status";
      wrapper.dataset.status = record.status;
      const dot = document.createElement("span");
      dot.className = "status-dot";
      dot.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.textContent = statusLabels[record.status] || record.status;
      wrapper.append(dot, label);
      return wrapper;
    }

    function metadata(record) {
      return [
        ["Status", statusDetail(record)],
        ["Source Info", record.source_info],
        ["Linked Anki Notes", record.linked_note_ids && record.linked_note_ids.length ? record.linked_note_ids.join(", ") : null],
        ["Error", record.error],
        ["File", record.filename],
        ["Capture Profile", record.profile],
        ["Range", `${formatTime(record.start_time)} - ${formatTime(record.end_time)}`],
      ];
    }

    function render(records) {
      recordsEl.replaceChildren();
      const doneCount = records.filter((record) => record.status === "media_done").length;
      clearDoneButton.disabled = doneCount === 0;
      clearDoneButton.title = doneCount === 0 ? "No visible completed records to clear" : "Clear completed records";
      clearAllButton.disabled = records.length === 0;
      clearAllButton.title = records.length === 0 ? "No visible records" : "Clear all mining records";
      if (!records.length) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "No mining records match the current filters.";
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
          if (value instanceof Node) detail.append(value);
          else detail.textContent = text(value);
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
        if (record.linked_note_count > 0) {
          const resend = document.createElement("button");
          resend.type = "button";
          resend.textContent = "Resend Media";
          resend.disabled = record.status === "matched_note" || record.media_work_active === true;
          resend.title = resend.disabled ? "Media delivery is already queued or running" : "Replace audio and image fields on every linked note";
          resend.addEventListener("click", async () => {
            resend.disabled = true;
            await fetch(`/api/records/${encodeURIComponent(record.id)}/resend`, {method: "POST"});
            await load();
          });
          actions.append(resend);
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

    function updateProfiles(profiles) {
      const selected = new Set(selectedValues(profileFilter));
      profileFilter.replaceChildren();
      for (const profile of profiles || []) {
        const option = document.createElement("option");
        option.value = profile;
        option.textContent = profile;
        option.selected = selected.has(profile);
        profileFilter.append(option);
      }
    }

    async function load(options = {}) {
      const append = options.append === true;
      const serial = ++requestSerial;
      const params = queryParams(append ? nextCursor : null);
      const response = await fetch(`/api/records?${params.toString()}`);
      if (!response.ok || serial !== requestSerial) return;
      const payload = await response.json();
      if (serial !== requestSerial) return;
      updateProfiles(payload.profiles);
      renderedRecords = append ? renderedRecords.concat(payload.records || []) : (payload.records || []);
      nextCursor = payload.next_cursor || null;
      loadMoreButton.hidden = !nextCursor;
      render(renderedRecords);
    }

    function scheduleFilteredLoad() {
      clearTimeout(filterTimer);
      requestSerial += 1;
      renderedRecords = [];
      nextCursor = null;
      loadMoreButton.hidden = true;
      render([]);
      filterTimer = setTimeout(() => load(), 180);
    }

    filtersEl.addEventListener("input", scheduleFilteredLoad);
    filtersEl.addEventListener("change", scheduleFilteredLoad);
    filtersEl.addEventListener("submit", (event) => event.preventDefault());
    clearFiltersButton.addEventListener("click", () => {
      statusFilter.selectedIndex = -1;
      profileFilter.selectedIndex = -1;
      sourceFilter.value = "";
      subtitleFilter.value = "";
      noteFilter.value = "";
      load();
    });
    loadMoreButton.addEventListener("click", () => load({append: true}));
    clearDoneButton.addEventListener("click", async () => {
      if (clearDoneButton.disabled || !confirm("Clear all completed mining records?")) return;
      await fetch("/api/records/clear-done", {method: "POST"});
      await load();
    });
    clearAllButton.addEventListener("click", async () => {
      if (clearAllButton.disabled || !confirm("Clear all mining records?")) return;
      await fetch("/api/records/clear-all", {method: "POST"});
      await load();
    });
    load();
    setInterval(() => load(), 3000);
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
        elif parsed.path == "/health":
            self._send_json({"ok": True})
        elif parsed.path == "/api/records":
            self._handle_list_records(parsed.query)
        elif parsed.path == "/api/pending":
            self._handle_pending(parsed.query)
        elif parsed.path == "/api/preview":
            self._send_json({"record": self.store.consume_preview_request()})
        else:
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
            self._send_json({"deleted": self.store.clear_done_records()})
            return
        if parsed.path == "/api/records/clear-all":
            self._send_json({"deleted": self.store.clear_all_records()})
            return
        if parsed.path == "/api/resends/lease":
            self._handle_lease_resend()
            return

        generation_id, action = self._parse_resend_action(parsed.path)
        if generation_id is not None:
            if action == "renew":
                self._handle_renew_resend(generation_id)
            elif action == "targets":
                self._handle_adopt_targets(generation_id)
            elif action == "result":
                self._handle_resend_result(generation_id)
            elif action == "complete":
                self._handle_finalize_resend(generation_id)
            else:
                self._send_not_found()
            return

        record_id, action = self._parse_record_action(parsed.path)
        if record_id is not None and action == "status":
            self._handle_update_status(record_id)
        elif record_id is not None and action == "missing-note":
            self._handle_remove_missing_note(record_id)
        elif record_id is not None and action == "resend":
            self._handle_queue_resend(record_id)
        elif record_id is not None and action == "preview":
            self._handle_queue_preview(record_id)
        else:
            self._send_not_found()

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        record_id = self._parse_record_id(parsed.path)
        if record_id is None:
            self._send_not_found()
            return
        try:
            self.store.delete_record(record_id)
        except KeyError:
            self._send_not_found()
            return
        self._send_json({"deleted": 1})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _handle_list_records(self, query: str) -> None:
        params = parse_qs(query, keep_blank_values=True)
        statuses = [value for value in params.get("status", []) if value]
        profiles = [value for value in params.get("profile", []) if value]
        source_info = params.get("source_info", [""])[0]
        subtitle = params.get("subtitle", [""])[0]
        try:
            note_value = params.get("note_id", [""])[0]
            note_id = int(note_value) if note_value else None
            limit_value = params.get("limit", ["200"])[0]
            limit = int(limit_value)
            cursor_value = params.get("cursor", [""])[0]
            cursor = self.store.decode_cursor(cursor_value) if cursor_value else None
            page = self.store.list_records(
                statuses=statuses,
                source_info=source_info,
                subtitle=subtitle,
                profiles=profiles,
                note_id=note_id,
                limit=limit,
                cursor=cursor,
            )
        except (InvalidCursorError, InvalidStatusError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(page)

    def _handle_pending(self, query: str) -> None:
        params = parse_qs(query)
        normalized_sentence = params.get("normalized_sentence", [""])[0]
        try:
            window_minutes = int(params.get("window_minutes", ["120"])[0])
        except ValueError:
            window_minutes = 120
        record = self.store.find_pending_by_normalized_sentence(
            normalized_sentence, window_minutes
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
                profile=str(payload.get("profile", "")),
                audio_field=str(payload.get("audio_field", "")),
                image_field=str(payload.get("image_field", "")),
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
            note_id = payload.get("note_id")
            if note_id is not None:
                note_id = int(note_id)
            record = self.store.update_status(
                record_id,
                status=str(payload.get("status", "")),
                note_id=note_id,
                error=str(payload.get("error", "")),
            )
        except KeyError:
            self._send_not_found()
            return
        except (InvalidStatusError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(record)

    def _handle_queue_resend(self, record_id: str) -> None:
        try:
            result = self.store.queue_resend(record_id)
        except KeyError:
            self._send_not_found()
            return
        except NoLinkedNotesError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        self._send_json(result, HTTPStatus.ACCEPTED)

    def _handle_remove_missing_note(self, record_id: str) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            record = self.store.remove_missing_note(record_id, int(payload["note_id"]))
        except KeyError:
            self._send_not_found()
            return
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"record": record})

    def _handle_lease_resend(self) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            lease_seconds = int(payload.get("lease_seconds", 30))
            lease = self.store.lease_resend(lease_seconds)
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"lease": lease})

    def _handle_renew_resend(self, generation_id: int) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            expires_at = self.store.renew_resend_lease(
                generation_id,
                str(payload.get("lease_token", "")),
                int(payload.get("lease_seconds", 30)),
            )
        except StaleLeaseError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"lease_expires_at": expires_at})

    def _handle_adopt_targets(self, generation_id: int) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            link = self.store.adopt_media_targets(
                generation_id,
                str(payload.get("lease_token", "")),
                int(payload["note_id"]),
                str(payload.get("audio_field", "")),
                str(payload.get("image_field", "")),
            )
        except StaleLeaseError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        except KeyError:
            self._send_not_found()
            return
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"link": link})

    def _handle_resend_result(self, generation_id: int) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            record = self.store.report_resend_delivery(
                generation_id,
                str(payload.get("lease_token", "")),
                int(payload["note_id"]),
                str(payload.get("state", "")),
                str(payload.get("error", "")),
            )
        except StaleLeaseError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        except KeyError:
            self._send_not_found()
            return
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"record": record})

    def _handle_finalize_resend(self, generation_id: int) -> None:
        payload = self._read_json()
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            record = self.store.finalize_resend(
                generation_id,
                str(payload.get("lease_token", "")),
                str(payload.get("error", "")),
            )
        except StaleLeaseError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        self._send_json({"record": record})

    def _handle_queue_preview(self, record_id: str) -> None:
        try:
            record = self.store.queue_preview(record_id)
        except KeyError:
            self._send_not_found()
            return
        self._send_json({"record": record})

    @staticmethod
    def _parse_record_id(path: str) -> str | None:
        prefix = "/api/records/"
        if not path.startswith(prefix):
            return None
        suffix = path[len(prefix) :]
        return unquote(suffix) if suffix and "/" not in suffix else None

    @staticmethod
    def _parse_record_action(path: str) -> tuple[str | None, str | None]:
        prefix = "/api/records/"
        if not path.startswith(prefix):
            return None, None
        parts = path[len(prefix) :].split("/")
        if len(parts) != 2 or not all(parts):
            return None, None
        return unquote(parts[0]), parts[1]

    @staticmethod
    def _parse_resend_action(path: str) -> tuple[int | None, str | None]:
        prefix = "/api/resends/"
        if not path.startswith(prefix):
            return None, None
        parts = path[len(prefix) :].split("/")
        if len(parts) != 2 or not all(parts):
            return None, None
        try:
            generation_id = int(parts[0])
        except ValueError:
            return None, None
        return generation_id, parts[1]

    def _read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return None
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
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
