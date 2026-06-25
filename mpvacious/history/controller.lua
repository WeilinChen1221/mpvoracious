local mp = require('mp')
local h = require('helpers')
local make_client = require('history.client')
local make_capture = require('history.capture')
local make_server_process = require('history.server_process')

local preview_poll_interval_seconds = 1
local pending_preview_after_load

local function preview_timestamp(record)
    return tonumber(record.snapshot_time) or tonumber(record.start_time) or 0
end

local function finish_preview(record)
    mp.set_property("ontop", "yes")
    mp.commandv("seek", preview_timestamp(record), "absolute+exact")
    mp.set_property("pause", "yes")
    h.notify("Previewing mining history record.", "info", 1)
end

local function on_preview_file_loaded()
    local record = pending_preview_after_load
    pending_preview_after_load = nil
    mp.unregister_event(on_preview_file_loaded)
    if record then
        finish_preview(record)
    end
end

local function preview_record(record)
    if h.is_empty(record.video_path) then
        return h.notify("Mining history preview has no video path.", "warn", 3)
    end
    if (mp.get_property("path") or "") == record.video_path then
        return finish_preview(record)
    end
    pending_preview_after_load = record
    mp.unregister_event(on_preview_file_loaded)
    mp.register_event("file-loaded", on_preview_file_loaded)
    mp.commandv("loadfile", record.video_path, "replace")
end

local function new()
    local self = {
        opened_page = false,
        preview_timer = nil,
    }

    function self.init(cfg_mgr, subs_observer)
        self.cfg_mgr = cfg_mgr
        self.client = make_client.new(cfg_mgr)
        self.capture = make_capture.new(cfg_mgr, subs_observer)
        self.server_process = make_server_process.new(cfg_mgr, self.client)
    end

    function self.enabled()
        return self.cfg_mgr and self.cfg_mgr.query("mining_history_enabled") == true
    end

    function self.handle_preview_request()
        if not self.enabled() then
            return
        end
        local parsed = self.client.consume_preview()
        if parsed and parsed.record then
            preview_record(parsed.record)
        end
    end

    function self.start_preview_timer()
        if not self.enabled() or self.preview_timer ~= nil then
            return
        end
        self.preview_timer = mp.add_periodic_timer(preview_poll_interval_seconds, self.handle_preview_request)
    end

    function self.capture_current()
        if not self.enabled() then
            return h.notify("Mining history is disabled.", "info", 2)
        end
        self.server_process.ensure_running()
        self.start_preview_timer()
        local record, error = self.capture.current_record()
        if error then
            return h.notify(error, "warn", 2)
        end
        self.client.create_record(record, function(_, request_error)
            if request_error then
                return h.notify("Mining history failed: " .. request_error, "error", 4)
            end
            h.notify("Sent subtitle to mining history.", "info", 1)
            if self.cfg_mgr.query("mining_history_open_browser") == true and self.opened_page == false then
                self.opened_page = true
                self.server_process.open_page()
            end
        end)
    end

    function self.find_pending_for_sentence(normalized_sentence)
        if not self.enabled() then
            return nil
        end
        self.server_process.ensure_running()
        local parsed = self.client.find_pending(normalized_sentence)
        return parsed and parsed.record or nil
    end

    function self.update_status(record_id, status, note_id, error)
        if not self.enabled() then
            return
        end
        self.client.update_status(record_id, status, note_id, error or '', function(_, request_error)
            if request_error then
                h.notify("Mining history status update failed: " .. request_error, "warn", 3)
            end
        end)
    end

    function self.records_waiting_for_retry()
        if not self.enabled() then
            return {}
        end
        local parsed = self.client.list_records()
        local ret = {}
        for _, record in ipairs(parsed and parsed.records or {}) do
            if record.status == "matched_note" and record.note_id ~= nil and record.error == "retry requested" then
                table.insert(ret, record)
            end
        end
        return ret
    end

    return self
end

return {
    new = new,
}
