# MPVacious Mining History Design

Date: 2026-06-24

## Goal

Build this fork of mpvacious into a Japanese sentence-mining workflow that lets the user mark subtitle sentences quickly from MPV, mine them later from a local browser history page with Yomitan, and backfill screenshot/audio into the Anki notes that Yomitan creates.

The workflow must keep compatibility with the user's existing mpvacious configuration and remain suitable for a normal Git/GitHub fork.

## Requirements

- Keep the repository managed with Git and suitable for later GitHub publication.
- Add a keyboard shortcut that marks the sentence for the current timestamp and sends it to a mining history.
- The mining history must be a local browser page where Yomitan can scan/select words across consecutive sentences.
- Yomitan creates the final Anki note. The note's sentence field is populated by Yomitan's `{sentence}` template.
- The user must not have to wait for screenshot or audio generation before moving to the next sentence.
- Preserve compatibility with the current mpvacious `subs2srs.conf` config, including deck/model/field/media options.
- If Python is used, run and manage it with `uv`.

## Chosen Approach

Use a local history page plus a pending media queue.

MPV/Lua captures subtitle records and sends them to a local Python helper. The helper stores records in SQLite and serves a browser page at localhost. Yomitan runs on that browser page and creates normal Anki notes. mpvacious extends its existing new-note polling flow so it can match those newly created Anki notes back to pending history records, generate media from the stored subtitle timings, and update the note afterward.

This approach keeps marking fast, avoids replacing Yomitan or AnkiConnect, and reuses mpvacious' existing config and encoder behavior.

## Non-Goals

- Do not replace mpvacious' existing `Ctrl+n`, selected-note update, or quick-card flows.
- Do not require users to migrate away from `subs2srs.conf`.
- Do not make the Python helper generate media. Media generation stays in MPV/Lua because existing encoder code depends on MPV state and mpvacious config.
- Do not build a large history-management app in the first version.

## Architecture

### Existing Components Kept

- `mpvacious/main.lua` remains the MPV entry point.
- `subs2srs.conf` remains the main config file.
- Existing config values continue to control Anki deck/model/fields, audio/image templates, audio padding, encoder choice, and browsing behavior.
- The current AnkiConnect wrapper remains the main Anki API layer.
- Existing encoder modules remain responsible for audio and image creation.

### New Lua Components

Add `mpvacious/history/` modules:

- `capture.lua`: collects the current subtitle record from the existing subtitle observer and current MPV state.
- `client.lua`: sends JSON requests to the local history helper.
- `matcher.lua`: normalizes sentence text and selects pending records that correspond to newly created Anki notes.
- `status.lua`: updates record status after note matching, media success, media failure, or retry.
- `server_process.lua`: starts the Python helper with `uv run` if enabled and not already reachable.

### New Python Components

Add a `history_server/` package managed by `uv`:

- `pyproject.toml` defines the package, dependencies, and test tooling.
- SQLite stores history records.
- A lightweight HTTP server exposes JSON APIs and the browser page.
- Static browser assets live in the package or an adjacent `static/` directory.

The helper is started by Lua with a command equivalent to:

```sh
uv run python -m history_server
```

The exact command should be built from the plugin directory so it works when installed under MPV's `scripts/mpvacious/` directory.

## Data Model

Each history record stores:

- `id`: generated stable id.
- `status`: one of `pending_note`, `matched_note`, `media_done`, `media_failed`.
- `sentence`: primary subtitle text shown in history.
- `normalized_sentence`: normalized value used for matching.
- `secondary`: secondary subtitle text, if available.
- `start_time`: subtitle/audio start time.
- `end_time`: subtitle/audio end time.
- `snapshot_time`: timestamp used for static screenshot capture.
- `video_path`: source media path.
- `filename`: media filename displayed to the user.
- `profile`: active mpvacious profile when captured.
- `note_id`: Anki note id after matching.
- `error`: last media or API error, if any.
- `created_at` and `updated_at`.

The SQLite database path defaults to an mpvacious-owned data directory and can be overridden in config.

## Config

New options are additive. Existing configs continue to load because defaults are supplied in Lua.

```conf
mining_history_enabled=yes
mining_history_key=Ctrl+Shift+n
mining_history_url=http://127.0.0.1:44765
mining_history_open_browser=yes
mining_history_db=
mining_history_match_window_minutes=120
```

Behavior:

- If `mining_history_enabled=no`, all new history behavior is disabled.
- `mining_history_key` controls the new global key binding.
- `mining_history_url` controls the local helper URL.
- `mining_history_open_browser=yes` opens the page on first successful capture or through a menu command.
- `mining_history_db` can point to a custom SQLite file. Empty means default.
- `mining_history_match_window_minutes` limits how far back pending records are considered for new note matching.

## User Workflow

1. Start MPV with mpvacious installed.
2. Press the configured history shortcut on a subtitle line.
3. MPV immediately sends the sentence to history and shows a short OSD confirmation.
4. The local history page shows the sentence without waiting for audio or screenshot creation.
5. Continue marking consecutive sentences.
6. In the browser history page, use Yomitan to select a target word from any sentence.
7. Yomitan creates the final Anki note using the user's normal Anki/Yomitan settings, including `{sentence}` into the sentence field.
8. mpvacious detects the new note, matches its sentence field to the pending history record, generates media from the stored timing, and updates that note's configured audio/image fields.

## Matching Rules

When mpvacious sees a recent Anki note with the configured deck/model and no media:

1. Read the configured `sentence_field`.
2. Normalize note text and pending history text by:
   - removing HTML tags,
   - unescaping HTML entities,
   - trimming leading/trailing whitespace,
   - collapsing repeated whitespace,
   - applying the same Japanese space removal behavior as `nuke_spaces=yes` where appropriate.
3. Query pending history records within `mining_history_match_window_minutes`.
4. Pick an exact normalized sentence match.
5. If multiple pending records match, pick the newest unmatched record.
6. Store the note id and set the history status to `matched_note`.
7. Generate media and update the note.

This is deterministic and compatible with Yomitan's `{sentence}` field behavior.

## Media Backfill

The note exporter needs a new path that updates a note from a supplied history record instead of the current MPV subtitle selection.

That path should:

- construct a subtitle-like object from the stored sentence, secondary text, start time, and end time;
- use the existing encoder configuration for snapshot and audio jobs;
- use the existing field templates for audio/image HTML;
- update only the matched note id;
- set history status to `media_done` on success;
- set history status to `media_failed` and store the error on failure.

Normal mpvacious note creation and update commands should keep their current behavior.

## History Page

The first version should be simple and functional:

- list records newest-first by default;
- preserve consecutive sentence order when filtering or browsing;
- show status for each sentence;
- expose sentence text in normal selectable HTML so Yomitan can scan it;
- include a retry action for failed media records;
- include enough source metadata to identify the video and timestamp.

The page should not require a frontend build pipeline.

## API Sketch

The helper exposes local-only endpoints:

- `GET /`: history browser page.
- `GET /api/records`: list records.
- `POST /api/records`: add a captured subtitle record.
- `GET /api/pending?sentence=...`: find matching pending records.
- `POST /api/records/{id}/status`: update status, note id, or error.
- `POST /api/records/{id}/retry`: mark a failed record for retry.
- `GET /health`: helper readiness check.

All endpoints bind to `127.0.0.1` by default.

## Error Handling

- If the Python helper is unavailable, Lua attempts to start it with `uv run`.
- If startup fails, MPV shows an OSD error and normal mpvacious behavior continues.
- If AnkiConnect is unavailable, history capture continues and matching waits until Anki is available.
- If media generation fails, the history record remains visible as `media_failed`.
- Failed media can be retried from the page.
- If no matching history record is found for a Yomitan-created note, the note is ignored by the history backfill path and existing mpvacious behavior is not disrupted.

## Git And Release Shape

- Work should happen on a feature branch.
- Commit the design spec before implementation.
- Add Python files, `pyproject.toml`, and `uv.lock` when implementation begins.
- Update `.gitignore` so local SQLite history files are not committed.
- Keep existing `make install` and development symlink flows working.
- Update README/howto docs for the new mining history workflow before release.
- Existing GitHub release automation can remain unless the final fork needs renamed release assets.

## Testing

Lua:

- Add focused tests for sentence normalization.
- Add tests for duplicate sentence matching policy.
- Add tests or manual harness coverage for updating from a supplied history record.

Python:

- Use `uv run pytest`.
- Test record creation, listing, matching query behavior, status updates, retry transitions, and SQLite persistence.

Manual verification:

1. Start MPV with a Japanese video and subtitles.
2. Press the history shortcut on several consecutive subtitles.
3. Confirm the browser page shows them immediately.
4. Use Yomitan on a sentence and create an Anki note.
5. Confirm the note appears immediately with the sentence field populated.
6. Confirm mpvacious later fills the configured audio and image fields.
7. Confirm normal `Ctrl+n` mpvacious note creation still works.

## Implementation Boundaries

Keep the first implementation narrow:

- Do not add authentication because the helper binds to localhost only.
- Do not add sync, cloud storage, or multi-device history.
- Do not build advanced search or tagging until the basic workflow is reliable.
- Do not change existing field semantics or user config names.
