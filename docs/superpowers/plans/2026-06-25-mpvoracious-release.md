# Mpvoracious Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the fork into the `mpvoracious` hard fork, autostart the mining-history helper when mpv loads, and publish a GitHub Release.

**Architecture:** Keep the installed mpv script directory as `mpvacious` for compatibility with existing configs and mpv script-bindings. Rebrand repository-facing docs, release metadata, installer URLs, release checker URLs, and release assets to `mpvoracious`. Add one config option that autostarts the uv-backed mining history server during mpvacious initialization.

**Tech Stack:** Lua for mpv integration, Python stdlib/SQLite history helper managed by `uv`, GNU Make release packaging, GitHub CLI for repository metadata and release publication.

---

### Task 1: Mining History Autostart

**Files:**
- Modify: `mpvacious/config/defaults.lua`
- Modify: `mpvacious/config/default_config.conf`
- Modify: `mpvacious/history/controller.lua`
- Modify: `mpvacious/main.lua`
- Modify: `howto/mining_history.md`

- [ ] **Step 1: Add config default**

Add `mining_history_autostart = true` next to the existing mining-history settings in `mpvacious/config/defaults.lua`.

- [ ] **Step 2: Add example config**

Add `mining_history_autostart=yes` to `mpvacious/config/default_config.conf` with a comment explaining that mpvoracious starts the local history helper when mpv loads.

- [ ] **Step 3: Add controller method**

Add `history_controller.start_background()` that checks `enabled()`, checks `mining_history_autostart`, starts the helper with `server_process.ensure_running()`, and starts the preview timer.

- [ ] **Step 4: Call startup method**

Call `history_controller.start_background()` from `main.lua` after `history_controller.init(...)` and before timers are needed.

- [ ] **Step 5: Verify**

Run `MPVACIOUS_TEST=TRUE mpv ...` and expect `TESTS PASSED`.

### Task 2: Hard Fork Branding

**Files:**
- Modify: `README.md`
- Modify: `Makefile`
- Modify: `.github/workflows/auto-release.yml`
- Modify: `.github/RELEASE/release-boilerplate.md`
- Modify: `.github/ISSUE_TEMPLATE/issue.md`
- Modify: `.github/ISSUE_TEMPLATE/config.yml`
- Modify: `.github/FUNDING.yml`
- Modify: `scripts/install.sh`
- Modify: `scripts/install.ps1`
- Modify: `scripts/symlink.sh`
- Modify: `mpvacious/utils/release_checker.lua`
- Modify: `mpvacious/pyproject.toml`
- Modify: `mpvacious/history_server/web.py`
- Modify: `mpvacious/history_server/store.py`
- Modify: `mpvacious/history_server/tests/test_web.py`
- Modify: `mpvacious/main.lua`
- Modify: `mpvacious/config/default_config.conf`
- Modify: `howto/mining_history.md`

- [ ] **Step 1: Rename public identity**

Rewrite `README.md` around `# mpvoracious`, focused on Japanese sentence mining with mpv, Yomitan, AnkiConnect, and mining history.

- [ ] **Step 2: Update release/install metadata**

Set `PROJECT := mpvoracious` in `Makefile`, update GitHub Actions release name, release boilerplate, install scripts, and release checker repo to `WeilinChen1221/mpvoracious`.

- [ ] **Step 3: Preserve compatibility**

Keep `PACKAGE := subs2srs`, config filename `subs2srs.conf`, installed internal script folder `mpvacious` in the archive, and existing `mpvacious-*` script-binding names.

- [ ] **Step 4: Update visible app text**

Change browser page title/header and docs from "Mpvacious Mining History" to "Mpvoracious Mining History"; keep storage path under `mpvacious` unless intentionally migrating data.

- [ ] **Step 5: Verify**

Run `uv run --project mpvacious pytest -v` and expect 14 passed.

### Task 3: Release and GitHub Publication

**Files:**
- Modify: `mpvacious/version.json`

- [ ] **Step 1: Set release version**

Use release tag `v26.6.25.0` and update `mpvacious/version.json` through `make VERSION=v26.6.25.0 version`.

- [ ] **Step 2: Verify package**

Run `make BRANCH=HEAD VERSION=v26.6.25.0`, then verify the zip contains the history Lua modules, history server, `pyproject.toml`, and `uv.lock`.

- [ ] **Step 3: Commit and merge**

Commit the implementation on `feature/mpvoracious-release`, merge it into `master`, and push `master`.

- [ ] **Step 4: Rename repository**

Use GitHub CLI to rename `WeilinChen1221/mpvacious` to `WeilinChen1221/mpvoracious` and update the description to "Hard fork of mpvacious focused on Yomitan-based Japanese sentence mining with background mining history."

- [ ] **Step 5: Publish release**

Create tag `v26.6.25.0`, push it, and publish a GitHub Release with `.github/RELEASE/mpvoracious_v26.6.25.0.zip` and `.github/RELEASE/subs2srs.conf`.

