# mpvoracious

mpvoracious is a hard fork of mpvacious focused on Japanese sentence mining with mpv, Yomitan, Anki, and AnkiConnect.

It keeps the original mpvacious media workflow, then adds a browser-based Mining History flow:

- Press a key in mpv to send the current subtitle sentence to Mining History.
- Open the local Mining History page and use Yomitan normally on consecutive sentences.
- Let Yomitan create Anki notes with `{sentence}` in your sentence field.
- mpvoracious matches those notes in the background and adds the corresponding screenshot and audio clip later.
- Preview sources, resend media, filter the complete history, delete records, clear completed records, or clear all records from the Mining History page.

The helper server is managed with `uv` and starts automatically when mpv loads, so you do not need to manually open any helper script.

## Requirements

- mpv v0.41.0 or newer
- Anki
- AnkiConnect
- Yomitan configured for Anki note creation
- curl
- uv
- FFmpeg, if your mpv build cannot encode the requested audio/image formats
- xclip or wl-copy on Linux if you use clipboard features

## Installation

### Install from Release

Download the latest release from:

```text
https://github.com/WeilinChen1221/mpvoracious/releases/latest
```

Extract `mpvoracious_<version>.zip` into your mpv scripts directory.

Typical locations:

| OS | mpv scripts directory |
| --- | --- |
| Linux/macOS | `~/.config/mpv/scripts/` |
| Windows | `C:/Users/Username/AppData/Roaming/mpv/scripts/` |
| Windows portable | `mpv.exe folder/portable_config/scripts/` |

The result should look like:

```text
~/.config/mpv/scripts/
`-- mpvoracious/
    |-- main.lua
    |-- helpers.lua
    |-- history_server/
    `-- ...
```

Copy `subs2srs.conf` from the release into your mpv script options directory if you do not already have one:

```text
~/.config/mpv/script-opts/subs2srs.conf
```

The config filename stays `subs2srs.conf` for compatibility with mpvacious setups.

### Install with Script

Linux/macOS:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/WeilinChen1221/mpvoracious/HEAD/scripts/install.sh)"
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/WeilinChen1221/mpvoracious/HEAD/scripts/install.ps1 | iex
```

### Development Install

Clone the repository and symlink the local source tree into mpv:

```sh
git clone git@github.com:WeilinChen1221/mpvoracious.git
cd mpvoracious
bash scripts/symlink.sh
```

The development symlink points the mpv script folder `mpvoracious` at the repository's internal `mpvacious/` source directory.

## Yomitan Setup

Configure Yomitan to create Anki notes using the same note type and field names as `subs2srs.conf`.

For Mining History, the important mapping is:

```text
Sentence field = {sentence}
```

mpvoracious matches new Anki notes by normalizing the text in this sentence field and comparing it to pending Mining History records.

## Mining History Workflow

1. Open a video in mpv.
2. mpvoracious starts the local Mining History helper in the background.
3. Press `Ctrl+Shift+n` on each subtitle sentence you want to mine.
4. Open `http://127.0.0.1:44765`.
5. Use Yomitan on the Mining History page to create Anki notes.
6. Keep mpv and Anki running while mpvoracious matches the new notes and backfills media.

Mining History controls:

- `Preview`: load the source video in mpv, seek to the saved timestamp, pause, and keep mpv on top.
- `Resend Media`: immediately regenerate media and completely replace the audio and image fields on every linked Anki note. It does not ask for confirmation and never changes sentence, secondary subtitle, Source Info/MiscInfo, tags, or other fields.
- Filters: narrow the complete stored history by one or more Record Status or Capture Profile values, Source Info, primary/secondary subtitle text, or an exact Linked Anki Note ID. `Clear filters` resets the filter bar.
- `Delete`: remove one record.
- `Clear Done`: remove records whose media was successfully added.
- `Clear All`: remove every history record.

Each record shows a text label and decorative status light:

- `Waiting for note` means the record has no linked Anki notes.
- `Sending media` means an initial delivery or Media Resend is queued or running.
- `Media ready` means every linked note's latest media delivery succeeded.
- `Media failed` means at least one linked note's latest settled delivery failed.

`Source Info` is captured from the source filename, path, episode, and timestamp using the Capture Profile and remains stable afterward. A record can remain linked to several Anki notes, and their delivery results are tracked independently.

Media targets are also stable per linked note. Existing history databases adopt target field names once on their first resend: mpvoracious reads the Capture Profile's current audio/image field names, verifies those fields on the note, saves them, and keeps using them even if field configuration changes later. Encoding quality, padding, format, templates, and encoder settings are refreshed from the record's Capture Profile for each resend.

The default Mining History settings are:

```conf
mining_history_enabled=yes
mining_history_autostart=yes
mining_history_key=Ctrl+Shift+n
mining_history_url=http://127.0.0.1:44765
mining_history_open_browser=yes
mining_history_db=
mining_history_match_window_minutes=120
```

## Common Key Bindings

These script-binding names are intentionally kept compatible with mpvacious.

```text
a             script-binding mpvacious-menu-open
Ctrl+n        script-binding mpvacious-export-note
Ctrl+Shift+n  script-binding mpvacious-send-to-mining-history
Ctrl+m        script-binding mpvacious-update-last-note
Ctrl+b        script-binding mpvacious-update-selected-note
H             script-binding mpvacious-sub-seek-back
L             script-binding mpvacious-sub-seek-forward
Ctrl+h        script-binding mpvacious-sub-rewind
Ctrl+H        script-binding mpvacious-sub-replay
```

## Configuration

The default config file is [mpvacious/config/default_config.conf](mpvacious/config/default_config.conf).

Most existing mpvacious configs should continue to work. The fork adds Mining History settings and keeps the original `deck_name`, `model_name`, `sentence_field`, `secondary_field`, `audio_field`, and `image_field` settings.

## Release Builds

Create a release archive locally:

```sh
make BRANCH=HEAD VERSION=v26.6.25.0
```

This produces:

```text
.github/RELEASE/mpvoracious_v26.6.25.0.zip
.github/RELEASE/subs2srs.conf
```

## License

mpvoracious is distributed under the GNU General Public License v3.0 or later, following the original mpvacious license.

This repository is a hard fork. It is not a pull request staging branch for the upstream project.
