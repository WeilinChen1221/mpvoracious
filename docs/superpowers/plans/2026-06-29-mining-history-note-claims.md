# Mining History Note Claims Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Mining History Anki note use its captured record while preventing multiple mpv processes from updating the same note.

**Architecture:** The existing Python history server becomes the single synchronization point. SQLite atomically maps each Anki note ID to the newest matching captured record; Lua consumes the explicit claim result and only invokes the current-mpv fallback after a confirmed miss.

**Tech Stack:** Python 3.11 stdlib, SQLite, pytest, mpv Lua, curl.

---

### Task 1: Atomic SQLite Note Claims

**Files:**
- Modify: `mpvacious/history_server/store.py`
- Test: `mpvacious/history_server/tests/test_store.py`

- [ ] **Step 1: Write failing claim tests**

Add the imports and tests below to `test_store.py`:

```python
import threading
from concurrent.futures import ThreadPoolExecutor


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
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run --project mpvacious pytest \
  mpvacious/history_server/tests/test_store.py::test_different_notes_reuse_the_same_history_record \
  mpvacious/history_server/tests/test_store.py::test_note_is_claimed_once_across_concurrent_workers -v
```

Expected: both tests fail with `AttributeError: 'HistoryStore' object has no attribute 'claim_note'`.

- [ ] **Step 3: Add the claims schema and atomic operation**

In `_init_schema`, add:

```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS note_claims (
        note_id INTEGER PRIMARY KEY,
        record_id TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """
)
conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_note_claims_record
    ON note_claims (record_id)
    """
)
conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_records_match
    ON records (normalized_sentence, created_at DESC, sequence DESC)
    """
)
```

Add this method to `HistoryStore`:

```python
def claim_note(
    self,
    note_id: int,
    normalized_sentence: str,
    window_minutes: int,
) -> dict[str, Any]:
    if note_id <= 0 or not normalized_sentence or window_minutes < 0:
        raise ValueError("invalid note claim")
    cutoff = time.time() - (window_minutes * 60)
    with self._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claimed = conn.execute(
            "SELECT 1 FROM note_claims WHERE note_id = ?",
            (note_id,),
        ).fetchone()
        if claimed is not None:
            return {"status": "already_claimed", "record": None}
        record = conn.execute(
            """
            SELECT * FROM records
            WHERE normalized_sentence = ? AND created_at >= ?
            ORDER BY created_at DESC, sequence DESC
            LIMIT 1
            """,
            (normalized_sentence, cutoff),
        ).fetchone()
        if record is None:
            return {"status": "unmatched", "record": None}
        conn.execute(
            "INSERT INTO note_claims (note_id, record_id, created_at) VALUES (?, ?, ?)",
            (note_id, record["id"], time.time()),
        )
        return {"status": "claimed", "record": dict(record)}
```

- [ ] **Step 4: Run the claim tests and verify GREEN**

Run the command from Step 2. Expected: `2 passed`.

- [ ] **Step 5: Write a failing cleanup test**

Add this parameterized test:

```python
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
```

- [ ] **Step 6: Run the cleanup test and verify RED**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_store.py::test_removing_records_releases_their_note_claims -v
```

Expected: all three cases report `already_claimed` instead of `claimed`.

- [ ] **Step 7: Delete claims with their records**

Add these statements inside the existing transactions:

```python
# delete_record, before deleting the record
conn.execute("DELETE FROM note_claims WHERE record_id = ?", (record_id,))

# clear_done_records, before deleting completed records
conn.execute(
    """
    DELETE FROM note_claims
    WHERE record_id IN (SELECT id FROM records WHERE status = 'media_done')
    """
)

# clear_all_records
conn.execute("DELETE FROM note_claims")
```

- [ ] **Step 8: Run the store suite and verify GREEN**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_store.py -v
```

Expected: all store tests pass.

- [ ] **Step 9: Commit the store change**

```bash
git add mpvacious/history_server/store.py mpvacious/history_server/tests/test_store.py
git commit -m "feat(history): claim Anki notes atomically"
```

### Task 2: Claim HTTP Endpoint

**Files:**
- Modify: `mpvacious/history_server/web.py`
- Test: `mpvacious/history_server/tests/test_web.py`

- [ ] **Step 1: Write the failing endpoint test**

Add:

```python
def test_claim_endpoint_reuses_record_and_rejects_duplicate_worker(
    tmp_path: Path,
) -> None:
    server = WebTestServer(tmp_path / "history.sqlite3")
    try:
        request_json(server, "/api/records", make_record())
        payload = {
            "note_id": 1001,
            "normalized_sentence": "これはペンです。",
            "window_minutes": 120,
        }

        first = request_json(server, "/api/claims", payload)
        duplicate = request_json(server, "/api/claims", payload)
        payload["note_id"] = 1002
        second_card = request_json(server, "/api/claims", payload)
        payload.update(note_id=1003, normalized_sentence="一致しません")
        unmatched = request_json(server, "/api/claims", payload)

        assert first["status"] == "claimed"
        assert first["record"]["video_path"] == "/tmp/video.mkv"
        assert duplicate == {"status": "already_claimed", "record": None}
        assert second_card["record"]["id"] == "rec-1"
        assert unmatched == {"status": "unmatched", "record": None}
    finally:
        server.close()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_web.py::test_claim_endpoint_reuses_record_and_rejects_duplicate_worker -v
```

Expected: fail with HTTP 404 for `/api/claims`.

- [ ] **Step 3: Implement the endpoint**

Add this route before record-action parsing in `do_POST`:

```python
if parsed.path == "/api/claims":
    self._handle_claim()
    return
```

Add the handler:

```python
def _handle_claim(self) -> None:
    payload = self._read_json()
    if not isinstance(payload, dict):
        self._send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
        return
    try:
        result = self.store.claim_note(
            note_id=int(payload["note_id"]),
            normalized_sentence=str(payload["normalized_sentence"]),
            window_minutes=int(payload["window_minutes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    self._send_json(result)
```

- [ ] **Step 4: Run the web suite and verify GREEN**

Run:

```bash
uv run --project mpvacious pytest mpvacious/history_server/tests/test_web.py -v
```

Expected: all web tests pass.

- [ ] **Step 5: Commit the endpoint**

```bash
git add mpvacious/history_server/web.py mpvacious/history_server/tests/test_web.py
git commit -m "feat(history): expose atomic note claims"
```

### Task 3: Make Lua Honor Global Claims

**Files:**
- Modify: `mpvacious/history/client.lua`
- Modify: `mpvacious/history/controller.lua`
- Modify: `mpvacious/anki/new_note_checker.lua`
- Create: `mpvacious/anki/tests/test_new_note_checker.lua`

- [ ] **Step 1: Add the failing Lua claim test**

Create `mpvacious/anki/tests/test_new_note_checker.lua`:

```lua
local mp = require('mp')

local function test()
    local root = assert(os.getenv("MPVACIOUS_ROOT"))
    package.path = root .. "/?.lua;" .. package.path
    local checker = require('anki.new_note_checker')

    assert(checker.classify_claim({ status = "claimed", record = { id = "rec-1" } }) == "claimed")
    assert(checker.classify_claim({ status = "already_claimed" }) == "handled")
    assert(checker.classify_claim({ status = "unmatched" }) == "fallback")
    assert(checker.classify_claim(nil, "server unavailable") == "retry")
    assert(checker.classify_claim({ status = "unexpected" }) == "retry")
end

local success, error = pcall(test)
if success then
    mp.msg.info("TESTS PASSED")
else
    mp.msg.error("TESTS FAILED: " .. tostring(error))
end
mp.commandv("quit", success and 0 or 1)
```

- [ ] **Step 2: Run the self-check and verify RED**

Run the focused mpv script test:

```bash
MPVACIOUS_ROOT="$PWD/mpvacious" mpv --no-config --idle=yes \
  --script=mpvacious/anki/tests/test_new_note_checker.lua
```

Expected: nonzero exit with `TESTS FAILED` because `classify_claim` is absent.

- [ ] **Step 3: Make JSON POST usable synchronously**

Replace the final request in `history/client.lua`'s `post` helper with:

```lua
local request = {
    url = base_url() .. path,
    request_json = request_json,
    suppress_log = true,
}
if not completion_fn then
    return parse_result(platform.json_curl_request(request))
end
request.completion_fn = function(success, result, error_msg)
    if not success or error_msg then
        return completion_fn(nil, tostring(error_msg))
    end
    local parsed, parse_error = parse_result(result)
    return completion_fn(parsed, parse_error)
end
return platform.json_curl_request(request)
```

Add:

```lua
function self.claim_note(note_id, normalized_sentence)
    return post('/api/claims', {
        note_id = note_id,
        normalized_sentence = normalized_sentence,
        window_minutes = cfg_mgr.query("mining_history_match_window_minutes"),
    })
end
```

- [ ] **Step 4: Add the controller pass-through**

Add to `history/controller.lua`:

```lua
function self.claim_note(note_id, normalized_sentence)
    self.server_process.ensure_running()
    return self.client.claim_note(note_id, normalized_sentence)
end
```

- [ ] **Step 5: Implement claim classification and note handling**

Define the helper above the factory:

```lua
local function classify_claim(claim, error)
    if not h.is_empty(error) or type(claim) ~= "table" then
        return "retry"
    elseif claim.status == "claimed" and not h.is_empty(claim.record) then
        return "claimed"
    elseif claim.status == "already_claimed" then
        return "handled"
    elseif claim.status == "unmatched" then
        return "fallback"
    end
    return "retry"
end
```

Export the same helper from the module return table:

```lua
return {
    new = make_anki_new_note_checker,
    classify_claim = classify_claim,
}
```

Change `try_update_from_history` to return actions and use the claim endpoint:

```lua
local function try_update_from_history(note_id, note_fields)
    if h.is_empty(self.history_controller) or not self.history_controller.enabled() then
        return "fallback"
    end
    local sentence = note_fields[self.config.sentence_field]
    if h.is_empty(sentence) then
        return "fallback"
    end
    local normalized = normalizer.normalize(sentence, self.config)
    local claim, claim_error = self.history_controller.claim_note(note_id, normalized)
    local action = classify_claim(claim, claim_error)
    if action ~= "claimed" then
        if action == "retry" then
            mp.msg.warn("Mining history claim failed: " .. tostring(claim_error or "invalid response"))
        end
        return action
    end
    local record = claim.record
    self.history_controller.update_status(record.id, "matched_note", note_id, "")
    self.update_history_note_fn(note_id, record, function(success, error)
        if success then
            self.history_controller.update_status(record.id, "media_done", note_id, "")
        else
            self.history_controller.update_status(record.id, "media_failed", note_id, error or "media backfill failed")
        end
    end)
    return "handled"
end
```

In `process_new_notes`, replace the current history/fallback block and unconditional ignore with:

```lua
local should_ignore = true
if not h.is_empty(note_fields)
        and note_fields[self.config.sentence_field] ~= nil
        and is_note_recent(note_id)
        and has_no_media(note_fields) then
    local action = try_update_from_history(note_id, note_fields)
    if action == "fallback" then
        table.insert(to_update, note_id)
    elseif action == "retry" then
        should_ignore = false
    end
end
if should_ignore then
    add_to_ignore_list(note_id)
end
```

- [ ] **Step 6: Run the Lua claim test and verify GREEN**

Run:

```bash
MPVACIOUS_ROOT="$PWD/mpvacious" mpv --no-config --idle=yes \
  --script=mpvacious/anki/tests/test_new_note_checker.lua
```

Expected: zero exit with `TESTS PASSED`.

- [ ] **Step 7: Commit the Lua integration**

```bash
git add mpvacious/history/client.lua mpvacious/history/controller.lua \
  mpvacious/anki/new_note_checker.lua mpvacious/anki/tests/test_new_note_checker.lua
git commit -m "fix(history): keep card media bound to captured records"
```

### Task 4: Full Regression Verification

**Files:**
- Verify only; no production file changes.

- [ ] **Step 1: Run every Python test**

```bash
uv run --project mpvacious pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the mpv Lua claim test again**

```bash
MPVACIOUS_ROOT="$PWD/mpvacious" mpv --no-config --idle=yes \
  --script=mpvacious/anki/tests/test_new_note_checker.lua
```

Expected: zero exit with `TESTS PASSED`.

- [ ] **Step 3: Check the final diff**

```bash
git diff --check HEAD~3..HEAD
git status --short
```

Expected: no whitespace errors; only pre-existing untracked user files remain.
