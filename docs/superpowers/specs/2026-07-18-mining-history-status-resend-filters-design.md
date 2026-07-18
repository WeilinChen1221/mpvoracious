# Mining History Status, Media Resend, and Filtering Design

Date: 2026-07-18

## Goal

Make Mining History easier to read and manage without weakening its association between captured source context and Anki notes:

- add an accessible status light and clear status labels;
- replace the single-note retry behavior with a deterministic Media Resend for every Linked Anki Note;
- filter the complete stored history by status, Source Info, subtitle text, Capture Profile, and Linked Anki Note ID.

The domain language is defined in [`CONTEXT.md`](../../../CONTEXT.md). Per-note delivery aggregation and stable target fields are recorded in [ADR 0001](../../adr/0001-track-media-delivery-per-linked-note.md) and [ADR 0002](../../adr/0002-stabilize-target-fields-but-refresh-encoding-settings.md).

## Current Constraints

The existing implementation cannot safely implement these features as presentation-only changes:

- `records.status` and `records.note_id` describe only the latest media attempt, although `note_claims` allows several notes to reuse one record.
- `Retry` is available only for `media_failed`, queues only the latest `note_id`, and reuses an exporter path that appends rather than replaces media.
- The history exporter constructs sentence, secondary, MiscInfo, audio, image, and tags together. Reusing it for resend would touch fields outside the agreed boundary.
- `GET /api/records` returns only the newest 200 records, so browser-side filtering would silently exclude older matches.
- Mining History does not store Source Info. Existing MiscInfo substitution reads live mpv filename and time properties, which may no longer describe the captured record.
- Configuration, encoder jobs, audio-track selection, and media filename generation retain active-player state. A resend handled by another mpv process could otherwise use the wrong profile, source filename, or track.

## Record Status

Record Status remains represented by the existing API codes for compatibility, but the webpage presents domain-facing labels and a colored dot immediately before the label.

| API code | Web label | Light | Meaning |
| --- | --- | --- | --- |
| `pending_note` | Waiting for note | Gray | The record has no Linked Anki Notes. |
| `matched_note` | Sending media | Amber | Initial delivery or Media Resend is queued or running. |
| `media_done` | Media ready | Green | Every Linked Anki Note's latest Media Delivery succeeded. |
| `media_failed` | Media failed | Red | A settled delivery batch has at least one failed Linked Anki Note. |

The status text remains visible and is the accessible name; the dot is decorative and marked `aria-hidden="true"`, so meaning never depends on color. Existing dark/light color-scheme support must be preserved.

Record Status is an aggregate of per-note delivery state:

1. No links means `pending_note`.
2. A queued or active batch means `matched_note`, even if an earlier delivery had failed.
3. When the batch settles, any failed linked delivery means `media_failed`.
4. Otherwise, all linked deliveries succeeded and the result is `media_done`.

When Anki confirms that a note no longer exists, its link is removed and the aggregate is recalculated. A network, Anki, or AnkiConnect failure never removes a link.

## Media Resend Semantics

Each record with one or more Linked Anki Notes shows a `Resend Media` button. The existing `Retry` action is removed. The button starts immediately without a confirmation dialog and is disabled while the same record already has queued or active media work.

A Media Resend:

- targets every existing Anki Note linked to the selected Mining History Record;
- regenerates media once from the record's captured source path, timings, snapshot time, and captured track context;
- uses the current media-generation settings and templates from the record's Capture Profile;
- completely replaces each note's stable audio and image Media Targets;
- never changes sentence, secondary subtitle, Source Info/MiscInfo, tags, or any other field;
- does not delete old files from Anki's media directory, because other notes may still reference them.

The Capture Profile and all target notes are preflighted before generation. If the profile is unavailable or invalid, the entire request fails before any Anki fields are changed and existing media remains intact.

After media is successfully generated, each note receives one `updateNoteFields` request containing only its audio and image target fields. Updates are best-effort across notes: successful siblings are not rolled back when another note fails. The per-note results are retained, the aggregate becomes `media_failed`, and a later Media Resend attempts every remaining link again.

If Anki explicitly returns no note for a linked ID, that link is removed and the other notes continue. If Anki or AnkiConnect is unavailable, no link is removed and the request remains failed/retryable.

## Stable Targets and Profile Resolution

When a note is first claimed, its active `audio_field` and `image_field` names are stored on that link as its Media Targets. Later configuration changes do not redirect existing notes to new fields.

Legacy `note_claims` rows do not have target names. On their first resend only:

1. Resolve the record's Capture Profile.
2. Read that profile's current audio and image field names.
3. Query the Anki note and verify that every non-empty target exists.
4. Persist the verified names as the link's stable Media Targets.
5. Fail without changing the note if a target cannot be verified.

The configuration manager needs a scoped profile resolver that returns an independent, validated configuration without changing the user's active profile. Media jobs must accept this explicit configuration rather than temporarily mutating the singleton config shared by normal mpvacious commands.

Media generation must also be record-aware rather than current-player-aware. In particular, job creation and filename generation must use the record's source filename/path, timing, and captured audio/video track context. They must not infer those values from whichever file the worker mpv process is currently playing.

## Persistence Model

Extend the record-note relationship so it owns Media Target and Media Delivery data. The exact SQLite migration may remain additive for compatibility, but the relationship needs the equivalent of:

- `note_id` and `record_id`;
- stable `audio_field` and `image_field` target names;
- delivery state (`pending`, `in_progress`, `done`, or `failed`);
- last delivery error and update time.

`records.status` may remain as a materialized aggregate for API compatibility and indexed status filtering, but it must be recalculated transactionally from linked delivery state. `records.note_id` is no longer authoritative. Record API responses expose `linked_note_count` and the linked IDs needed by the webpage instead of presenting a single latest note as the relationship.

Add `source_info` to records. New captures calculate it from captured filename, path, episode, and timestamp using the Capture Profile's `miscinfo_format`; it is stable after capture and is independent of later edits to an Anki Notes/MiscInfo field. Legacy rows receive a deterministic filename-and-timestamp fallback so they remain displayable and searchable without querying Anki.

Capture enough source context to regenerate from the original selected tracks, including an external audio path when applicable. Legacy records without track data use a deterministic default-track fallback and must never borrow track state from the worker's currently loaded video.

## Resend Coordination

The Python history server remains the synchronization point between the webpage and potentially several mpv processes.

- `POST /api/records/{id}/resend` creates or coalesces a pending resend generation and returns `202 Accepted`.
- A worker endpoint atomically leases one pending generation to one mpv process. Concurrent workers cannot process the same generation.
- The lease has a token and expiry/renewal mechanism so a crashed worker does not strand the record in Sending Media forever.
- Per-note completion updates are accepted only for the active generation and lease token, preventing a late worker from overwriting newer results.
- Finalizing or expiring a generation recalculates the record aggregate.

Repeated clicks while work is queued or active do not create duplicate jobs. The normal three-second webpage refresh continues to show progress, and the button stays disabled until the batch settles.

## Filtering

Filtering is performed in SQLite before pagination, over the complete stored history. The initial filter bar contains:

- **Record Status**: multi-select using the four web labels;
- **Source Info**: case-insensitive substring match;
- **Subtitle**: one substring search across primary and secondary subtitle text;
- **Capture Profile**: multi-select;
- **Linked Anki Note ID**: exact numeric match.

Different filter categories combine with `AND`; multiple selected values within Status or Capture Profile combine with `OR`. Empty controls impose no restriction. A clear action resets all controls. Auto-refresh must retain active filters and must not briefly render unfiltered records.

Extend `GET /api/records` with parameterized query values equivalent to:

```text
status=pending_note&status=media_failed
source_info=episode+3
subtitle=見つけた
profile=subs2srs&profile=subs2srs_english
note_id=1234567890
limit=200&cursor=...
```

Results remain newest-first using `(created_at, sequence)` as a stable cursor. The response includes a next cursor when more filtered results exist. Applying filters before the limit guarantees that an older matching record is not hidden merely because it falls outside the current unfiltered top 200.

The webpage remains embedded HTML/CSS/JavaScript with no frontend build pipeline. Text is inserted with DOM `textContent`, and SQL filters use bound parameters.

## API and Store Changes

The implementation will need to evolve these existing boundaries:

- `HistoryStore.list_records(...)`: accept the filter set and cursor, join or query `note_claims` for exact note IDs, and return linked-note summaries.
- `HistoryStore.claim_note(...)`: accept Capture Profile and Media Target names, restrict matching to the appropriate profile, and initialize per-note delivery state.
- Status updates: identify both record and note/generation instead of overwriting one record-level `note_id`.
- Record capture: accept stable Source Info and captured track context.
- Record deletion and clear operations: continue removing links and also remove or cancel resend generations.
- The Lua history client/controller: queue and lease resend generations rather than scanning for the `error == "retry requested"` sentinel.
- The Anki wrapper/exporter: add a media-only replacement operation; do not route Media Resend through `make_new_note_data`, `join_fields`, MiscInfo substitution, tagging, or Forvo handling.

## Failure Handling

- Missing/invalid Capture Profile: fail the whole generation before field writes and retain existing media.
- Missing source file or unsupported source: fail the generation with a visible record error.
- Media creation failure: write no Anki fields and mark all attempted deliveries failed.
- Confirmed missing Anki note: remove only that link, then continue and recalculate status.
- AnkiConnect unavailable or ambiguous response: keep links, retain the error, and allow a later resend.
- One note update rejected: keep successful sibling updates, mark that note failed, and show Media Failed after the batch settles.
- Worker crash: allow the lease to expire and return the generation to a claimable state.
- Stale worker completion: reject it by generation and lease token.

Errors shown in each record should summarize the batch and identify failed note IDs without replacing the stored per-note errors.

## Testing

Python store tests:

- schema migration preserves existing records and claims;
- multiple linked notes store independent stable targets and delivery outcomes;
- aggregate status covers no links, active work, all success, partial failure, and removal of a missing note;
- resend requests coalesce, lease atomically across concurrent workers, expire safely, and reject stale completion;
- filters apply before pagination and use the specified AND/OR semantics;
- Source Info and exact linked-note filters include records older than the first unfiltered page;
- delete, Clear Done, and Clear All clean up links and resend generations.

HTTP tests:

- filtered record query parsing and cursors;
- linked-note summaries in responses;
- resend rejects records without links and queues eligible records;
- concurrent worker claims have exactly one winner;
- malformed filters, note IDs, cursors, and stale tokens return useful 4xx responses;
- the index contains all filter controls, accessible status labels, and Resend Media instead of Retry.

Lua tests:

- scoped Capture Profile resolution does not mutate the active profile;
- claim requests capture stable Media Target names and Capture Profile;
- media filenames, source paths, timings, and track selection come from the history record;
- resend replaces only audio/image targets and leaves all other fields byte-for-byte unchanged;
- legacy targets are adopted only after field verification;
- unavailable profiles fail before generation;
- missing notes are distinguished from AnkiConnect outages;
- partial multi-note completion is reported without rollback.

Manual verification:

1. Capture records under two profiles and create two Anki notes from the same record.
2. Confirm status lights and labels follow the aggregate transitions.
3. Add manual content to both media fields, change encoder settings, and click Resend Media.
4. Confirm both notes' complete media fields are replaced while all non-media fields and tags remain unchanged.
5. Delete one linked note, resend, and confirm the surviving note succeeds without a permanent failure from the deleted note.
6. Stop Anki, resend, and confirm links are retained and Media Failed is visible.
7. Run two mpv processes and confirm only one leases a resend generation.
8. Add more than 200 records and confirm every filter can find an older match.
9. Confirm active filters survive automatic refresh and light/dark status colors remain legible.

## Documentation Updates During Implementation

- Update the Mining History controls in `README.md` and `howto/mining_history.md`.
- Explain the four web status labels and their aggregate meaning.
- Document that Resend Media overwrites every linked note's entire audio/image fields immediately and does not ask for confirmation.
- Document the initial filter set and Source Info terminology.
- Note the one-time target adoption rule for legacy history databases.

## Non-Goals

- No bulk resend across several Mining History Records.
- No live search of arbitrary Anki fields or user-edited MiscInfo/Notes content.
- No sentence, secondary subtitle, tag, or other-field changes during Media Resend.
- No automatic cleanup of orphaned files in Anki's media directory.
- No cross-note rollback or promise of an atomic Anki transaction.
- No arbitrary field-mapping migration through Media Resend.
- No frontend framework or build pipeline.
