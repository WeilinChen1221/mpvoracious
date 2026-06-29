from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_different_notes_reuse_the_same_history_record(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())

    first = store.claim_note(1001, "これはペンです。", window_minutes=120)
    store.update_status("rec-1", status="media_done", note_id=1001, error="")
    second = store.claim_note(1002, "これはペンです。", window_minutes=120)

    assert first["status"] == "claimed"
    assert second["status"] == "claimed"
    assert first["record"]["video_path"] == "/tmp/video.mkv"
    assert second["record"]["id"] == "rec-1"


def test_note_is_claimed_once_across_concurrent_workers(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    barrier = threading.Barrier(2)

    def claim() -> dict[str, object]:
        barrier.wait()
        return store.claim_note(1001, "これはペンです。", window_minutes=120)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))

    assert sorted(result["status"] for result in results) == [
        "already_claimed",
        "claimed",
    ]


def test_insertion_order_breaks_created_at_ties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("history_server.store.time.time", lambda: 1000.0)
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("z-old"))
    store.add_record(make_record("a-new"))

    records = store.list_records()
    assert [record["id"] for record in records] == ["a-new", "z-old"]

    match = store.find_pending_by_normalized_sentence("これはペンです。", window_minutes=120)
    assert match is not None
    assert match["id"] == "a-new"


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


def test_delete_record_removes_one_record(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("keep"))
    store.add_record(make_record("delete"))

    store.delete_record("delete")

    assert [record["id"] for record in store.list_records()] == ["keep"]
    with pytest.raises(KeyError):
        store.get_record("delete")


def test_clear_done_records_removes_only_completed_media(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("pending"))
    store.add_record(make_record("done"))
    store.add_record(make_record("failed"))
    store.update_status("done", status="media_done", note_id=1001, error="")
    store.update_status("failed", status="media_failed", note_id=1002, error="encoder failed")

    deleted = store.clear_done_records()

    assert deleted == 1
    assert {record["id"] for record in store.list_records()} == {"pending", "failed"}


def test_clear_all_records_removes_records_and_pending_preview(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("first"))
    store.add_record(make_record("second"))
    store.queue_preview("first")

    deleted = store.clear_all_records()

    assert deleted == 2
    assert store.list_records() == []
    assert store.consume_preview_request() is None


@pytest.mark.parametrize("removal", ["delete", "clear_done", "clear_all"])
def test_removing_records_releases_their_note_claims(
    tmp_path: Path, removal: str
) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    assert store.claim_note(1001, "これはペンです。", 120)["status"] == "claimed"

    if removal == "delete":
        store.delete_record("rec-1")
    elif removal == "clear_done":
        store.update_status("rec-1", "media_done", 1001, "")
        store.clear_done_records()
    else:
        store.clear_all_records()

    store.add_record(make_record())
    assert store.claim_note(1001, "これはペンです。", 120)["status"] == "claimed"


def test_preview_request_is_consumed_once(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("rec-1"))

    queued = store.queue_preview("rec-1")
    first = store.consume_preview_request()
    second = store.consume_preview_request()

    assert queued["id"] == "rec-1"
    assert first is not None
    assert first["id"] == "rec-1"
    assert second is None
