local mp = require('mp')
local h = require('helpers')
local make_client = require('history.client')
local make_capture = require('history.capture')
local make_server_process = require('history.server_process')

local preview_poll_interval_seconds = 1
local resend_poll_interval_seconds = 1
local resend_renew_interval_seconds = 10
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
        resend_timer = nil,
        resend_busy = false,
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

    function self.start_background()
        if not self.enabled() or self.cfg_mgr.query("mining_history_autostart") ~= true then
            return
        end
        self.server_process.ensure_running()
        self.start_preview_timer()
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

    function self.claim_note(note_id, normalized_sentence)
        self.server_process.ensure_running()
        return self.client.claim_note(note_id, normalized_sentence)
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

    function self.remove_missing_note(record_id, note_id)
        self.client.remove_missing_note(record_id, note_id, function(_, request_error)
            if request_error then
                h.notify('Mining history missing-note update failed: ' .. tostring(request_error), 'warn', 3)
            end
        end)
    end

    local function append_error(existing, new_error)
        if h.is_empty(new_error) then
            return existing
        elseif h.is_empty(existing) then
            return tostring(new_error)
        else
            return existing .. '; ' .. tostring(new_error)
        end
    end

    function self.process_resend_lease(lease)
        local generation_id = lease.generation_id
        local lease_token = lease.lease_token
        local pending_reports = 0
        local exporter_finished = false
        local finalizing = false
        local final_error = nil
        local renew_timer

        local function stop_renewal()
            if renew_timer ~= nil then
                renew_timer:kill()
                renew_timer = nil
            end
        end

        local function maybe_finalize()
            if not exporter_finished or pending_reports > 0 or finalizing then
                return
            end
            finalizing = true
            stop_renewal()
            self.client.finalize_resend(generation_id, lease_token, final_error or '', function(_, request_error)
                if request_error then
                    h.notify('Mining history resend finalization failed: ' .. tostring(request_error), 'warn', 4)
                end
                self.resend_busy = false
            end)
        end

        renew_timer = mp.add_periodic_timer(resend_renew_interval_seconds, function()
            self.client.renew_resend(generation_id, lease_token, function(_, request_error)
                if request_error then
                    final_error = append_error(final_error, 'lease renewal failed: ' .. tostring(request_error))
                end
            end)
        end)

        lease.record.resend_nonce = tostring(generation_id) .. '-' .. lease_token:sub(1, 8)
        local callbacks = {
            on_result = function(note_id, state, error)
                pending_reports = pending_reports + 1
                self.client.report_resend(
                        generation_id,
                        lease_token,
                        note_id,
                        state,
                        error or '',
                        function(_, request_error)
                            if request_error then
                                final_error = append_error(
                                        final_error,
                                        string.format('failed to record Note %s result: %s', tostring(note_id), tostring(request_error))
                                )
                            end
                            pending_reports = pending_reports - 1
                            maybe_finalize()
                        end
                )
            end,
            adopt_targets = function(note_id, audio_field, image_field, on_finish)
                self.client.adopt_targets(
                        generation_id,
                        lease_token,
                        note_id,
                        audio_field,
                        image_field,
                        function(parsed, request_error)
                            on_finish(not h.is_empty(parsed) and h.is_empty(request_error), request_error)
                        end
                )
            end,
            on_finish = function(error)
                final_error = append_error(final_error, error)
                exporter_finished = true
                maybe_finalize()
            end,
        }
        local ok, resend_error = pcall(
                self.resend_fn,
                lease.record,
                lease.record.linked_notes or {},
                callbacks
        )
        if not ok then
            callbacks.on_finish('resend worker failed: ' .. tostring(resend_error))
        end
    end

    function self.handle_resend_request()
        if not self.enabled() or self.resend_busy or h.is_empty(self.resend_fn) then
            return
        end
        self.resend_busy = true
        self.client.lease_resend(function(parsed, request_error)
            if request_error or h.is_empty(parsed) or h.is_empty(parsed.lease) then
                self.resend_busy = false
                return
            end
            self.process_resend_lease(parsed.lease)
        end)
    end

    function self.start_resend_worker(resend_fn)
        if not self.enabled() or self.resend_timer ~= nil then
            return
        end
        self.resend_fn = resend_fn
        self.resend_timer = mp.add_periodic_timer(resend_poll_interval_seconds, self.handle_resend_request)
    end

    return self
end

return {
    new = new,
}
