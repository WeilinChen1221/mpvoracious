local h = require('helpers')
local make_client = require('history.client')
local make_capture = require('history.capture')
local make_server_process = require('history.server_process')

local function new()
    local self = {
        opened_page = false,
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

    function self.capture_current()
        if not self.enabled() then
            return h.notify("Mining history is disabled.", "info", 2)
        end
        self.server_process.ensure_running()
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

    return self
end

return {
    new = new,
}
