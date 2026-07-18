from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from history_server.store import HistoryStore
from history_server.web import make_server


def make_record(record_id: str = "rec-1", *, profile: str = "subs2srs") -> dict[str, object]:
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
        "profile": profile,
        "source_info": "Video EP01 (00m01s500ms)",
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
        server.base_url + path, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers["Content-Type"].startswith("application/json")
        return json.loads(response.read().decode("utf-8"))


def request_error(
    server: WebTestServer,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        request_json(server, path, payload)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    raise AssertionError("request unexpectedly succeeded")


def claim_payload(note_id: int = 1001) -> dict[str, object]:
    return {
        "note_id": note_id,
        "normalized_sentence": "これはペンです。",
        "window_minutes": 120,
        "profile": "subs2srs",
        "audio_field": "SentAudio",
        "image_field": "Image",
    }


def test_health_records_claim_delivery_and_index(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        assert request_json(server, "/health") == {"ok": True}
        created = request_json(server, "/api/records", make_record())
        assert created["status"] == "pending_note"

        claim = request_json(server, "/api/claims", claim_payload())
        assert claim["record"]["status"] == "matched_note"
        assert claim["link"]["audio_field"] == "SentAudio"
        done = request_json(
            server,
            "/api/records/rec-1/status",
            {"status": "media_done", "note_id": 1001, "error": ""},
        )
        assert done["status"] == "media_done"

        with urllib.request.urlopen(server.base_url + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert "Waiting for note" in html
        assert "Sending media" in html
        assert "Media ready" in html
        assert "Media failed" in html
        assert 'setAttribute("aria-hidden", "true")' in html
        assert "Source Info" in html
        assert "Capture Profile" in html
        assert "Linked Anki Note ID" in html
        assert "Resend Media" in html
        assert ">Retry<" not in html
    finally:
        server.close()


def test_claim_endpoint_reuses_record_and_rejects_duplicate_worker(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record())
        first = request_json(server, "/api/claims", claim_payload(1001))
        duplicate = request_json(server, "/api/claims", claim_payload(1001))
        second = request_json(server, "/api/claims", claim_payload(1002))

        assert first["status"] == "claimed"
        assert duplicate["status"] == "already_claimed"
        assert duplicate["record"] is None
        assert second["record"]["linked_note_ids"] == [1001, 1002]
    finally:
        server.close()


def test_filtered_records_and_cursor_validation(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        for index in range(5):
            record = make_record(f"rec-{index}", profile="english" if index % 2 else "subs2srs")
            record["sentence"] = "needle" if index == 0 else f"sentence {index}"
            record["normalized_sentence"] = record["sentence"]
            record["source_info"] = "Special Episode" if index == 0 else f"Episode {index}"
            request_json(server, "/api/records", record)

        query = urllib.parse.urlencode(
            [("source_info", "special"), ("subtitle", "needle"), ("profile", "subs2srs"), ("limit", "1")]
        )
        page = request_json(server, f"/api/records?{query}")
        assert [record["id"] for record in page["records"]] == ["rec-0"]
        assert page["profiles"] == ["english", "subs2srs"]

        first = request_json(server, "/api/records?limit=2")
        second = request_json(
            server, "/api/records?" + urllib.parse.urlencode({"limit": 2, "cursor": first["next_cursor"]})
        )
        assert len(first["records"]) == len(second["records"]) == 2
        assert request_error(server, "/api/records?status=wrong")[0] == 400
        assert request_error(server, "/api/records?note_id=abc")[0] == 400
        assert request_error(server, "/api/records?cursor=bad")[0] == 400
    finally:
        server.close()


def test_resend_endpoints_coalesce_lease_and_finalize(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record())
        code, body = request_error(server, "/api/records/rec-1/resend", {})
        assert code == 409
        assert "linked" in body["error"]

        request_json(server, "/api/claims", claim_payload())
        first = request_json(server, "/api/records/rec-1/resend", {})
        second = request_json(server, "/api/records/rec-1/resend", {})
        assert first["coalesced"] is False
        assert second["coalesced"] is True

        with ThreadPoolExecutor(max_workers=2) as executor:
            leases = list(executor.map(lambda _: request_json(server, "/api/resends/lease", {}), range(2)))
        winners = [item["lease"] for item in leases if item["lease"] is not None]
        assert len(winners) == 1
        lease = winners[0]
        generation_id = lease["generation_id"]
        token = lease["lease_token"]

        result = request_json(
            server,
            f"/api/resends/{generation_id}/result",
            {"lease_token": token, "note_id": 1001, "state": "done"},
        )
        assert result["record"]["status"] == "matched_note"
        completed = request_json(
            server,
            f"/api/resends/{generation_id}/complete",
            {"lease_token": token},
        )
        assert completed["record"]["status"] == "media_done"
        assert request_error(
            server,
            f"/api/resends/{generation_id}/result",
            {"lease_token": token, "note_id": 1001, "state": "failed"},
        )[0] == 409
    finally:
        server.close()


def test_legacy_target_adoption_endpoint(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record())
        payload = claim_payload()
        payload["audio_field"] = ""
        payload["image_field"] = ""
        request_json(server, "/api/claims", payload)
        generation = request_json(server, "/api/records/rec-1/resend", {})["generation"]
        lease = request_json(server, "/api/resends/lease", {})["lease"]

        adopted = request_json(
            server,
            f"/api/resends/{generation['id']}/targets",
            {
                "lease_token": lease["lease_token"],
                "note_id": 1001,
                "audio_field": "Audio",
                "image_field": "Picture",
            },
        )
        assert adopted["link"]["audio_field"] == "Audio"
        assert adopted["link"]["image_field"] == "Picture"
    finally:
        server.close()


def test_confirmed_missing_note_endpoint_removes_only_that_link(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record())
        request_json(server, "/api/claims", claim_payload(1001))
        request_json(server, "/api/claims", claim_payload(1002))

        result = request_json(
            server, "/api/records/rec-1/missing-note", {"note_id": 1001}
        )

        assert result["record"]["linked_note_ids"] == [1002]
        assert result["record"]["status"] == "matched_note"
    finally:
        server.close()


def test_delete_clear_and_preview_endpoints(tmp_path: Path) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record("keep"))
        request_json(server, "/api/records", make_record("delete"))
        queued = request_json(server, "/api/records/keep/preview", {})
        assert queued["record"]["id"] == "keep"
        assert request_json(server, "/api/preview")["record"]["id"] == "keep"
        assert request_json(server, "/api/preview") == {"record": None}

        assert request_json(server, "/api/records/delete", method="DELETE") == {"deleted": 1}
        assert request_json(server, "/api/records/clear-all", {}) == {"deleted": 1}
        assert request_json(server, "/api/records")["records"] == []
    finally:
        server.close()
