from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from history_server.store import HistoryStore
from history_server.web import make_server


def make_record(record_id: str = "rec-1") -> dict[str, object]:
    return {
        "id": record_id,
        "sentence": "これはペンです。",
        "normalized_sentence": "これはペンです。",
        "secondary": "This is a pen.",
        "start_time": 1.25,
        "end_time": 2.75,
        "snapshot_time": 1.5,
        "video_path": "/tmp/video.mkv",
        "filename": "video.mkv",
        "profile": "subs2srs",
    }


class WebTestServer:
    def __init__(self, db_path: Path) -> None:
        self.store = HistoryStore(db_path)
        self.server = make_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def request_json(
    server: WebTestServer,
    path: str,
    payload: dict[str, Any] | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        server.base_url + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers["Content-Type"].startswith("application/json")
        return json.loads(response.read().decode("utf-8"))


def test_health_records_pending_status_and_index(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        assert request_json(server, "/health") == {"ok": True}

        created = request_json(server, "/api/records", make_record())
        assert created["id"] == "rec-1"
        assert created["status"] == "pending_note"

        records_response = request_json(server, "/api/records")
        assert [record["id"] for record in records_response["records"]] == ["rec-1"]

        query = urllib.parse.urlencode(
            {"normalized_sentence": "これはペンです。", "window_minutes": "120"}
        )
        pending_response = request_json(server, f"/api/pending?{query}")
        assert pending_response["record"]["id"] == "rec-1"

        updated = request_json(
            server,
            "/api/records/rec-1/status",
            {"status": "matched_note", "note_id": 4321, "error": ""},
        )
        assert updated["status"] == "matched_note"
        assert updated["note_id"] == 4321
        assert updated["error"] == ""

        failed = request_json(
            server,
            "/api/records/rec-1/status",
            {"status": "media_failed", "note_id": 4321, "error": "encoder failed"},
        )
        assert failed["status"] == "media_failed"

        retried = request_json(server, "/api/records/rec-1/retry", {})
        assert retried["status"] == "matched_note"
        assert retried["error"] == "retry requested"

        with urllib.request.urlopen(server.base_url + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert '<main id="records"' in html
        assert "Mpvoracious Mining History" in html
    finally:
        server.close()


def test_claim_endpoint_reuses_record_and_rejects_duplicate_worker(
    tmp_path: Path,
) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record())
        payload = {
            "note_id": 1001,
            "normalized_sentence": "これはペンです。",
            "window_minutes": 120,
        }

        first = request_json(server, "/api/claims", payload)
        duplicate = request_json(server, "/api/claims", payload)
        payload["note_id"] = 1002
        second_card = request_json(server, "/api/claims", payload)
        payload.update(note_id=1003, normalized_sentence="一致しません")
        unmatched = request_json(server, "/api/claims", payload)

        assert first["status"] == "claimed"
        assert first["record"]["video_path"] == "/tmp/video.mkv"
        assert duplicate == {"status": "already_claimed", "record": None}
        assert second_card["record"]["id"] == "rec-1"
        assert unmatched == {"status": "unmatched", "record": None}
    finally:
        server.close()


def test_delete_record_endpoint_removes_one_record(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record("keep"))
        request_json(server, "/api/records", make_record("delete"))

        deleted = request_json(server, "/api/records/delete", method="DELETE")

        assert deleted == {"deleted": 1}
        records_response = request_json(server, "/api/records")
        assert [record["id"] for record in records_response["records"]] == ["keep"]
    finally:
        server.close()


def test_clear_done_endpoint_removes_only_completed_media(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record("pending"))
        request_json(server, "/api/records", make_record("done"))
        request_json(server, "/api/records", make_record("failed"))
        request_json(
            server,
            "/api/records/done/status",
            {"status": "media_done", "note_id": 1001, "error": ""},
        )
        request_json(
            server,
            "/api/records/failed/status",
            {"status": "media_failed", "note_id": 1002, "error": "encoder failed"},
        )

        deleted = request_json(server, "/api/records/clear-done", {})

        assert deleted == {"deleted": 1}
        records_response = request_json(server, "/api/records")
        assert {record["id"] for record in records_response["records"]} == {
            "pending",
            "failed",
        }
    finally:
        server.close()


def test_clear_all_endpoint_removes_every_record(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record("first"))
        request_json(server, "/api/records", make_record("second"))
        request_json(server, "/api/records/first/preview", {})

        deleted = request_json(server, "/api/records/clear-all", {})

        assert deleted == {"deleted": 2}
        records_response = request_json(server, "/api/records")
        assert records_response["records"] == []
        preview_response = request_json(server, "/api/preview")
        assert preview_response == {"record": None}
    finally:
        server.close()


def test_preview_endpoint_queues_consumable_record(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record("rec-1"))

        queued = request_json(server, "/api/records/rec-1/preview", {})
        first_preview = request_json(server, "/api/preview")
        second_preview = request_json(server, "/api/preview")

        assert queued["record"]["id"] == "rec-1"
        assert first_preview["record"]["id"] == "rec-1"
        assert second_preview == {"record": None}
    finally:
        server.close()
