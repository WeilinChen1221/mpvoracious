# Mining History

Mining history lets you send visible subtitle lines from mpv to a local browser page, mine words with Yomitan, and let mpvoracious add screenshot and audio fields after Yomitan creates the Anki note.

## Requirements

- mpvoracious installed from this fork.
- `uv` available in `PATH`.
- Anki with AnkiConnect enabled.
- Yomitan configured to create Anki notes and send `{sentence}` to the same sentence field configured in `subs2srs.conf`.

## Configuration

The default shortcut is `Ctrl+Shift+n`.

```conf
mining_history_enabled=yes
mining_history_autostart=yes
mining_history_key=Ctrl+Shift+n
mining_history_url=http://127.0.0.1:44765
mining_history_open_browser=yes
mining_history_db=
mining_history_match_window_minutes=120
```

The existing `deck_name`, `model_name`, `sentence_field`, `audio_field`, and `image_field` settings are reused.

## Workflow

1. Open a video in mpv.
2. Mpvoracious starts the local history helper in the background.
3. Press `Ctrl+Shift+n` on each sentence you want in history.
4. Open the history page at `http://127.0.0.1:44765`.
5. Use Yomitan on the browser page to create Anki notes.
6. Keep mpvoracious running so the new note timer can match notes and add media.

If media creation fails, press `Retry` on the history page while mpvoracious is running.
Press `Preview` to make mpv jump to that record's saved timestamp and keep the mpv
window on top. Press `Delete` on a row to remove that record from the history page.
Press `Clear Done` to remove only records whose media has already been added
successfully. Press `Clear All` to remove every mining history record.
