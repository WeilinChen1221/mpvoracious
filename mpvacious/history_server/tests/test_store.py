from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from history_server.store import (
    HistoryStore,
    InvalidCursorError,
    InvalidStatusError,
    NoLinkedNotesError,
    StaleLeaseError,
)


def make_record(
    record_id: str = "rec-1",
    sentence: str = "これはペンです。",
    *,
    profile: str = "subs2srs",
    source_info: str = "Video EP01 (00m01s500ms)",
) -> dict[str, object]:
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
        "profile": profile,
        "source_info": source_info,
        "video_track_id": "1",
        "video_ff_index": "0",
        "audio_track_id": "2",
        "audio_ff_index": "1",
        "audio_external_path": "/tmp/audio.flac",
        "has_audio": True,
        "has_video": True,
        "source_duration": 24.0,
        "capture_volume": 70.0,
    }


def records(store: HistoryStore, **kwargs: object) -> list[dict[str, object]]:
    return store.list_records(**kwargs)["records"]


def claim(
    store: HistoryStore,
    note_id: int,
    record_sentence: str = "これはペンです。",
    profile: str = "subs2srs",
) -> dict[str, object]:
    return store.claim_note(
        note_id,
        record_sentence,
        120,
        profile,
        "SentAudio",
        "Image",
    )


def test_add_list_and_match_pending_record(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    created = store.add_record(make_record())

    assert created["source_info"] == "Video EP01 (00m01s500ms)"
    assert created["has_audio"] is True
    assert created["video_track_id"] == "1"
    assert [record["id"] for record in records(store)] == ["rec-1"]
    assert store.list_records()["profiles"] == ["subs2srs"]
    match = store.find_pending_by_normalized_sentence("これはペンです。", 120)
    assert match is not None
    assert match["id"] == "rec-1"


def test_missing_source_info_gets_deterministic_fallback(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    record = make_record()
    record["source_info"] = ""

    created = store.add_record(record)

    assert created["source_info"] == "video.mkv (00m01s500ms)"


def test_insertion_order_breaks_created_at_ties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("history_server.store.time.time", lambda: 1000.0)
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("z-old"))
    store.add_record(make_record("a-new"))

    assert [record["id"] for record in records(store)] == ["a-new", "z-old"]


def test_claim_restricts_profile_and_stores_stable_targets(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record("jp", profile="subs2srs"))
    store.add_record(make_record("en", profile="subs2srs_english"))

    result = claim(store, 1001, profile="subs2srs")

    assert result["status"] == "claimed"
    assert result["record"]["id"] == "jp"
    assert result["link"]["audio_field"] == "SentAudio"
    assert result["link"]["image_field"] == "Image"
    assert result["record"]["status"] == "matched_note"
    assert result["record"]["linked_note_ids"] == [1001]


def test_different_notes_have_independent_delivery_and_aggregate_status(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    claim(store, 1001)
    claim(store, 1002)

    store.update_status("rec-1", "media_done", 1001, "")
    assert store.get_record("rec-1")["status"] == "matched_note"

    failed = store.update_status("rec-1", "media_failed", 1002, "Anki rejected update")
    assert failed["status"] == "media_failed"
    assert failed["error"] == "Note 1002: Anki rejected update"
    assert {link["note_id"]: link["delivery_state"] for link in failed["linked_notes"]} == {
        1001: "done",
        1002: "failed",
    }

    ready = store.update_status("rec-1", "media_done", 1002, "")
    assert ready["status"] == "media_done"
    assert ready["error"] == ""


def test_note_is_claimed_once_across_concurrent_workers(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    barrier = threading.Barrier(2)

    def run_claim() -> dict[str, object]:
        barrier.wait()
        return claim(store, 1001)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_claim(), range(2)))

    assert sorted(result["status"] for result in results) == [
        "already_claimed",
        "claimed",
    ]


def test_invalid_status_and_cursor_are_rejected(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())

    with pytest.raises(InvalidStatusError):
        store.update_status("rec-1", "bad", 1001, "")
    with pytest.raises(InvalidStatusError):
        store.list_records(statuses=["bad"])
    with pytest.raises(InvalidCursorError):
        store.decode_cursor("not-a-cursor")


def test_resend_coalesces_and_only_one_worker_leases(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    with pytest.raises(NoLinkedNotesError):
        store.queue_resend("rec-1")
    claim(store, 1001)
    store.update_status("rec-1", "media_failed", 1001, "first failure")

    first = store.queue_resend("rec-1")
    second = store.queue_resend("rec-1")

    assert first["coalesced"] is False
    assert second["coalesced"] is True
    assert first["generation"]["id"] == second["generation"]["id"]
    assert store.get_record("rec-1")["status"] == "matched_note"

    barrier = threading.Barrier(2)

    def lease() -> dict[str, object] | None:
        barrier.wait()
        return store.lease_resend()

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(lambda _: lease(), range(2)))
    assert sum(item is not None for item in leases) == 1


def test_resend_adopts_legacy_targets_and_rejects_stale_completion(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    store.claim_note(1001, "これはペンです。", 120, "subs2srs", "", "")
    generation = store.queue_resend("rec-1")["generation"]
    lease = store.lease_resend()
    assert lease is not None

    adopted = store.adopt_media_targets(
        generation["id"], lease["lease_token"], 1001, "NewAudio", "NewImage"
    )
    assert adopted["audio_field"] == "NewAudio"
    store.report_resend_delivery(
        generation["id"], lease["lease_token"], 1001, "done"
    )
    completed = store.finalize_resend(generation["id"], lease["lease_token"])
    assert completed["status"] == "media_done"

    with pytest.raises(StaleLeaseError):
        store.report_resend_delivery(
            generation["id"], lease["lease_token"], 1001, "failed", "late"
        )


def test_expired_lease_is_requeued_and_old_token_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr("history_server.store.time.time", lambda: clock[0])
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    claim(store, 1001)
    generation = store.queue_resend("rec-1")["generation"]
    first = store.lease_resend(lease_seconds=5)
    assert first is not None
    clock[0] = 1006.0

    with pytest.raises(StaleLeaseError):
        store.report_resend_delivery(
            generation["id"], first["lease_token"], 1001, "done"
        )
    second = store.lease_resend(lease_seconds=5)
    assert second is not None
    assert second["lease_token"] != first["lease_token"]
    assert second["record"]["linked_notes"][0]["delivery_state"] == "in_progress"


def test_missing_note_is_unlinked_and_siblings_continue(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    claim(store, 1001)
    claim(store, 1002)
    generation = store.queue_resend("rec-1")["generation"]
    lease = store.lease_resend()
    assert lease is not None

    store.report_resend_delivery(generation["id"], lease["lease_token"], 1001, "missing")
    store.report_resend_delivery(generation["id"], lease["lease_token"], 1002, "done")
    record = store.finalize_resend(generation["id"], lease["lease_token"])

    assert record["linked_note_ids"] == [1002]
    assert record["status"] == "media_done"


def test_confirmed_missing_note_outside_resend_recalculates_aggregate(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    claim(store, 1001)

    record = store.remove_missing_note("rec-1", 1001)

    assert record["linked_note_count"] == 0
    assert record["status"] == "pending_note"


def test_filters_run_before_cursor_pagination_with_and_or_semantics(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    for index in range(8):
        record = make_record(
            f"rec-{index}",
            sentence="古い一致" if index == 0 else f"sentence {index}",
            profile="english" if index % 2 else "subs2srs",
            source_info="Special Episode" if index == 0 else f"Episode {index}",
        )
        store.add_record(record)
    claim(store, 9001, "古い一致", "subs2srs")
    store.update_status("rec-0", "media_failed", 9001, "failed")

    page = store.list_records(
        statuses=["pending_note", "media_failed"],
        source_info="special",
        subtitle="一致",
        profiles=["subs2srs", "english"],
        note_id=9001,
        limit=2,
    )
    assert [record["id"] for record in page["records"]] == ["rec-0"]

    first = store.list_records(limit=3)
    second = store.list_records(
        limit=3, cursor=store.decode_cursor(first["next_cursor"])
    )
    assert len(first["records"]) == 3
    assert len(second["records"]) == 3
    assert set(record["id"] for record in first["records"]).isdisjoint(
        record["id"] for record in second["records"]
    )


def test_schema_migration_preserves_records_and_claims(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE records (
                sequence INTEGER NOT NULL, id TEXT PRIMARY KEY, sentence TEXT NOT NULL,
                normalized_sentence TEXT NOT NULL, secondary TEXT NOT NULL DEFAULT '',
                start_time REAL NOT NULL, end_time REAL NOT NULL, snapshot_time REAL NOT NULL,
                video_path TEXT NOT NULL, filename TEXT NOT NULL, profile TEXT NOT NULL,
                status TEXT NOT NULL, note_id INTEGER, error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE note_claims (
                note_id INTEGER PRIMARY KEY, record_id TEXT NOT NULL, created_at REAL NOT NULL
            );
            INSERT INTO records VALUES (
                1, 'legacy', '文', '文', '', 1, 2, 1.5, '/video.mkv', 'video.mkv',
                'subs2srs', 'media_failed', 1234, 'old error', 10, 11
            );
            INSERT INTO note_claims VALUES (1234, 'legacy', 10);
            """
        )

    store = HistoryStore(db_path)
    record = store.get_record("legacy")

    assert record["source_info"] == "video.mkv (00m01s500ms)"
    assert record["linked_notes"][0]["delivery_state"] == "failed"
    assert record["linked_notes"][0]["audio_field"] == ""
    assert record["status"] == "media_failed"


@pytest.mark.parametrize("removal", ["delete", "clear_done", "clear_all"])
def test_removing_records_cleans_claims_and_generations(
    tmp_path: Path, removal: str
) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    claim(store, 1001)
    if removal != "clear_done":
        store.queue_resend("rec-1")

    if removal == "delete":
        store.delete_record("rec-1")
    elif removal == "clear_done":
        store.update_status("rec-1", "media_done", 1001, "")
        assert store.clear_done_records() == 1
    else:
        assert store.clear_all_records() == 1

    store.add_record(make_record())
    assert claim(store, 1001)["status"] == "claimed"


def test_preview_request_is_consumed_once(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.add_record(make_record())
    store.queue_preview("rec-1")

    assert store.consume_preview_request()["id"] == "rec-1"
    assert store.consume_preview_request() is None
