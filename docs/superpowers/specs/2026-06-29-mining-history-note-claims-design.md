# Mining History Note Claims Design

## Goal

Ensure every Anki card created from Mining History receives the sentence, audio, and picture from the history record captured when the mining shortcut was pressed, even when several cards use the same sentence or several mpv processes are open.

## Root Cause

The first matching note changes its history record from `pending_note`, so later notes with the same sentence no longer find it. They fall through to the generic new-note updater, which reads the current subtitle and frame from whichever mpv process is polling Anki. Multiple mpv processes can also process the same note concurrently.

## Design

The existing history server will atomically claim each Anki note ID:

- Add a SQLite `note_claims` table keyed by `note_id` and storing the selected `record_id`.
- Add one store operation and HTTP endpoint that accept `note_id`, normalized sentence, and match-window minutes.
- In one `BEGIN IMMEDIATE` transaction, reject an already-claimed note, select the newest history record with the same normalized sentence inside the match window, and insert the claim.
- Matching records remain reusable by different note IDs, regardless of record status. This lets several cards made from one sentence use the same captured media.
- The claim result is explicit: `claimed`, `already_claimed`, `unmatched`, or `error`.
- The Lua note checker treats `claimed` and `already_claimed` as handled. Only `unmatched` may use the existing current-mpv fallback. An `error` leaves the note eligible for the next polling cycle.
- Existing status and retry behavior remains unchanged. For a record shared by several cards, the displayed `note_id` and status describe the latest media attempt.
- Deleting or clearing records also deletes their claims.

When identical sentence text exists in several history records, the newest captured matching record wins, preserving the current ordering rule.

## Data Flow

1. An mpv process detects a new Anki note and reads its configured sentence field.
2. It asks the shared history server to claim the note.
3. The first process to claim that note receives the stored history record; other processes receive `already_claimed` and do nothing.
4. The winning process generates media from the record's `video_path`, subtitle timings, and snapshot timestamp, then updates the note.
5. A different note ID with the same sentence can claim and reuse the same record.

## Error Handling

- Server or JSON errors keep the note out of the generic current-frame fallback and out of the local ignore list, because ownership is unknown and writing current mpv state could corrupt fields. The next timer tick retries it.
- A confirmed `unmatched` response preserves the existing generic updater behavior.
- Media-generation failures continue to set `media_failed` and remain retryable from Mining History.

## Tests

- Two different note IDs can claim the same captured record, including after its status changes.
- Concurrent claims for one note ID produce exactly one winner.
- A second mpv process receives `already_claimed` and does not run the current-frame updater.
- No matching history record still uses the existing fallback.
- A claim error neither falls back nor ignores the note permanently.
- Existing history server tests and the mpv Lua self-check remain green.

## Non-Goals

- No new background worker or dependency.
- No browser/Yomitan changes.
- No redesign of record-level status for multiple cards.
