local mp = require('mp')
local Subtitle = require('subtitles.subtitle')
local normalizer = require('history.normalizer')
local h = require('helpers')

local function new(cfg_mgr, subs_observer)
    local self = {}

    local function make_id(sub)
        local stamp = tostring(os.time()) .. "-" .. tostring(math.floor((sub.start or 0) * 1000))
        return stamp:gsub("[^%w%-]", "-")
    end

    function self.current_record()
        local primary = Subtitle:now()
        if h.is_empty(primary) then
            return nil, "There's no visible subtitle."
        end
        local secondary = Subtitle:now('secondary')
        local sentence = subs_observer.clipboard_prepare(primary.text)
        local config = cfg_mgr.config()
        return {
            id = make_id(primary),
            sentence = sentence,
            normalized_sentence = normalizer.normalize(sentence, config),
            secondary = secondary and secondary.text or '',
            start_time = primary.start,
            end_time = primary['end'],
            snapshot_time = mp.get_property_number("time-pos", primary.start),
            video_path = mp.get_property("path") or '',
            filename = mp.get_property("filename") or '',
            profile = cfg_mgr.profiles().active,
        }, nil
    end

    return self
end

return {
    new = new,
}
