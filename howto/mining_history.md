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

The existing `deck_name`, `model_name`, `sentence_field`, `audio_field`, and `image_field` settings are reused. Each capture remembers its Capture Profile. Later Media Resends keep each linked note's original audio/image target field names while refreshing encoding settings and templates from that Capture Profile.

## Workflow

1. Open a video in mpv.
2. Mpvoracious starts the local history helper in the background.
3. Press `Ctrl+Shift+n` on each sentence you want in history.
4. Open the history page at `http://127.0.0.1:44765`.
5. Use Yomitan on the browser page to create Anki notes.
6. Keep mpvoracious running so the new note timer can match notes and add media.

## Status and controls

Every Mining History Record shows an accessible text status next to a decorative colored light:

- `Waiting for note`: no Anki notes are linked.
- `Sending media`: initial delivery or Media Resend is queued or running.
- `Media ready`: the latest delivery succeeded for every linked note.
- `Media failed`: the latest settled delivery failed for at least one linked note.

Use `Resend Media` to regenerate media once and immediately replace the complete audio and image fields of every linked Anki note. There is no confirmation prompt. Resend never modifies sentence, secondary subtitle, Source Info/MiscInfo, tags, or any other field, and one note failing does not roll back successful siblings.

Use `Preview` to make mpv jump to the record's saved timestamp and keep the mpv window on top. `Delete` removes one record, `Clear Done` removes only records whose media is ready, and `Clear All` removes every Mining History Record.

The filter bar searches the complete database before pagination. Record Status and Capture Profile accept multiple selections; Source Info and Subtitle use substring matching; Linked Anki Note ID is an exact numeric match. Different filter categories combine, and `Clear filters` resets them. Source Info is the stable captured source description, not the current content of an Anki MiscInfo/Notes field.

For links created by older versions, the first resend adopts the Capture Profile's current audio and image field names only after verifying that they exist on the Anki note. Those target names then remain stable for future resends.
