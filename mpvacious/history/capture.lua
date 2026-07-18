local mp = require('mp')
local Subtitle = require('subtitles.subtitle')
local normalizer = require('history.normalizer')
local source_info = require('history.source_info')
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
        local audio_track = h.get_active_track('audio')
        local video_track = h.get_active_track('video')
        local record = {
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
            video_track_id = video_track and (video_track.id or mp.get_property('vid')) or nil,
            video_ff_index = video_track and video_track['ff-index'] or nil,
            audio_track_id = audio_track and (audio_track.id or mp.get_property('aid')) or nil,
            audio_ff_index = audio_track and audio_track['ff-index'] or nil,
            audio_external_path = audio_track and audio_track.external == true and audio_track['external-filename'] or '',
            has_audio = h.has_audio_track(),
            has_video = h.has_video_track(),
            source_duration = mp.get_property_number('duration'),
            capture_volume = mp.get_property_number('volume', 100),
        }
        record.source_info = source_info.format(config, record)
        return record, nil
    end

    return self
end

return {
    new = new,
}
