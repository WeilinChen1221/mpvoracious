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

    function self.claim_note(note_id, normalized_sentence)
        return post('/api/claims', {
            note_id = note_id,
            normalized_sentence = normalized_sentence,
            window_minutes = cfg_mgr.query("mining_history_match_window_minutes"),
            profile = cfg_mgr.profiles().active,
            audio_field = cfg_mgr.query("audio_field"),
            image_field = cfg_mgr.query("image_field"),
        })
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

    function self.remove_missing_note(record_id, note_id, completion_fn)
        return post('/api/records/' .. url_encode(record_id) .. '/missing-note', {
            note_id = note_id,
        }, completion_fn)
    end

    function self.lease_resend(completion_fn)
        return post('/api/resends/lease', { lease_seconds = 30 }, completion_fn)
    end

    function self.renew_resend(generation_id, lease_token, completion_fn)
        return post('/api/resends/' .. tostring(generation_id) .. '/renew', {
            lease_token = lease_token,
            lease_seconds = 30,
        }, completion_fn)
    end

    function self.adopt_targets(generation_id, lease_token, note_id, audio_field, image_field, completion_fn)
        return post('/api/resends/' .. tostring(generation_id) .. '/targets', {
            lease_token = lease_token,
            note_id = note_id,
            audio_field = audio_field,
            image_field = image_field,
        }, completion_fn)
    end

    function self.report_resend(generation_id, lease_token, note_id, state, error, completion_fn)
        return post('/api/resends/' .. tostring(generation_id) .. '/result', {
            lease_token = lease_token,
            note_id = note_id,
            state = state,
            error = error or '',
        }, completion_fn)
    end

    function self.finalize_resend(generation_id, lease_token, error, completion_fn)
        return post('/api/resends/' .. tostring(generation_id) .. '/complete', {
            lease_token = lease_token,
            error = error or '',
        }, completion_fn)
    end

    return self
end

return {
    new = new,
}
