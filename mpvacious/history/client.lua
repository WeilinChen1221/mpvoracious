local utils = require('mp.utils')
local platform = require('platform.init')
local h = require('helpers')

local function new(cfg_mgr)
    local self = {}

    local function base_url()
        return cfg_mgr.query("mining_history_url"):gsub("/$", "")
    end

    local function parse_result(result)
        if h.is_empty(result) or result.status ~= 0 or h.is_empty(result.stdout) then
            return nil, "history server unavailable"
        end
        local parsed = utils.parse_json(result.stdout)
        if h.is_empty(parsed) then
            return nil, "history server returned invalid JSON"
        end
        return parsed, nil
    end

    local function url_encode(str)
        return tostring(str):gsub("\n", "\r\n"):gsub("([^%w%-_%.~])", function(char)
            return string.format("%%%02X", string.byte(char))
        end)
    end

    local function post(path, payload, completion_fn)
        local request_json, error = utils.format_json(payload)
        if error ~= nil or request_json == "null" then
            if completion_fn then
                completion_fn(nil, "failed to format JSON")
            end
            return nil
        end
        return platform.json_curl_request {
            url = base_url() .. path,
            request_json = request_json,
            suppress_log = true,
            completion_fn = function(success, result, error_msg)
                if not success or error_msg then
                    return completion_fn and completion_fn(nil, tostring(error_msg))
                end
                local parsed, parse_error = parse_result(result)
                return completion_fn and completion_fn(parsed, parse_error)
            end
        }
    end

    local function get_sync(path)
        local result = platform.curl_request {
            args = { '-s', '--max-time', '2', base_url() .. path },
            suppress_log = true,
        }
        return parse_result(result)
    end

    function self.health()
        local parsed, error = get_sync('/health')
        return parsed and parsed.ok == true, error
    end

    function self.create_record(record, completion_fn)
        return post('/api/records', record, completion_fn)
    end

    function self.find_pending(normalized_sentence)
        local escaped = url_encode(normalized_sentence)
        return get_sync('/api/pending?normalized_sentence=' .. escaped .. '&window_minutes=' .. tostring(cfg_mgr.query("mining_history_match_window_minutes")))
    end

    function self.list_records()
        return get_sync('/api/records')
    end

    function self.consume_preview()
        return get_sync('/api/preview')
    end

    function self.update_status(record_id, status, note_id, error, completion_fn)
        return post('/api/records/' .. url_encode(record_id) .. '/status', {
            status = status,
            note_id = note_id,
            error = error or '',
        }, completion_fn)
    end

    return self
end

return {
    new = new,
}
