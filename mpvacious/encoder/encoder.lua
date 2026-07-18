--[[
Copyright: Ajatt-Tools and contributors; https://github.com/Ajatt-Tools
License: GNU GPL, version 3 or later; http://www.gnu.org/licenses/gpl.html

Encoder creates audio clips and snapshots, both animated and static.
]]

local mp = require('mp')
local utils = require('mp.utils')
local h = require('helpers')
local filename_factory = require('utils.filename_factory')
local msg = require('mp.msg')
local exec = require('encoder.executables')
local mpv_encoder = require('encoder.mpv')
local ffmpeg_encoder = require('encoder.ffmpeg')

local function config_provider(config)
    return { config = function() return config end }
end

local function make_encoder(initial_config)
    local state = {
        config = initial_config,
        encoder = nil,
        output_dir_path = nil,
    }
    local public = { snapshot = {}, audio = {} }

    local function initialize_backend()
        if h.is_empty(state.config) then
            error('encoder config not assigned')
        end
        local provider = config_provider(state.config)
        state.encoder = state.config.use_ffmpeg and ffmpeg_encoder.new(provider) or mpv_encoder.new(provider)
        state.encoder.set_avif_encoder()
    end

    local function pad_timings(padding, start_time, end_time, source_duration, historical)
        local duration = source_duration
        if not historical and duration == nil then
            duration = mp.get_property_number('duration')
        end
        start_time = math.max(0, start_time - padding)
        end_time = end_time + padding
        if duration ~= nil and end_time > duration then
            end_time = duration
        end
        return start_time, end_time
    end

    local function create_animated_snapshot(start_timestamp, end_timestamp, source_path, output_path, on_finish_fn, track_context)
        local args = state.encoder.make_animated_snapshot_args(
                source_path, output_path, start_timestamp, end_timestamp, track_context
        )
        h.subprocess { args = args, completion_fn = on_finish_fn }
    end

    local function create_static_snapshot(timestamp, source_path, output_path, on_finish_fn, use_player_screenshot, track_context)
        if not state.config.screenshot or not use_player_screenshot then
            local args = state.encoder.make_static_snapshot_args(source_path, output_path, timestamp, track_context)
            h.subprocess { args = args, completion_fn = on_finish_fn }
        else
            mp.command_native_async({ 'screenshot-to-file', output_path, 'video' }, on_finish_fn)
        end
    end

    local function report_creation_result(file_path, on_finish_fn)
        return function(success, result)
            if success and (result == nil or result.status == 0) and h.file_exists(file_path) then
                msg.info(string.format('Created file: %s', file_path))
                success = true
            else
                msg.error(string.format("Couldn't create file: %s", file_path))
                success = false
            end
            if type(on_finish_fn) == 'function' then
                on_finish_fn(success)
            end
            return success
        end
    end

    local function create_snapshot(start_timestamp, end_timestamp, current_timestamp, filename, on_finish_fn, source_path, use_player_screenshot, track_context)
        if h.is_empty(state.output_dir_path) then
            if type(on_finish_fn) == 'function' then on_finish_fn(false) end
            return msg.error("Output directory wasn't provided. Image file will not be created.")
        end
        local output_path = utils.join_path(state.output_dir_path, filename)
        local on_finish_wrap = report_creation_result(output_path, on_finish_fn)
        if state.config.animated_snapshot_enabled then
            create_animated_snapshot(start_timestamp, end_timestamp, source_path, output_path, on_finish_wrap, track_context)
        else
            create_static_snapshot(current_timestamp, source_path, output_path, on_finish_wrap, use_player_screenshot, track_context)
        end
    end

    local function background_play(file_path, on_finish)
        return h.subprocess {
            args = { exec.mpv, '--audio-display=no', '--force-window=no', '--keep-open=no', '--really-quiet', file_path },
            completion_fn = on_finish,
        }
    end

    local function create_audio(start_timestamp, end_timestamp, filename, padding, on_finish_fn, source_path, track_context, source_duration, historical)
        if h.is_empty(state.output_dir_path) then
            if type(on_finish_fn) == 'function' then on_finish_fn(false) end
            return msg.error("Output directory wasn't provided. Audio file will not be created.")
        end
        local output_path = utils.join_path(state.output_dir_path, filename)
        if padding > 0 then
            start_timestamp, end_timestamp = pad_timings(
                    padding, start_timestamp, end_timestamp, source_duration, historical
            )
        end
        local function start_encoding(args)
            local on_finish_wrap = function(success, result)
                local conversion_check = report_creation_result(output_path, on_finish_fn)
                if conversion_check(success, result) and state.config.preview_audio then
                    background_play(output_path, function() print('Played file: ' .. output_path) end)
                end
            end
            h.subprocess { args = args, completion_fn = on_finish_wrap }
        end
        state.encoder.make_audio_args(
                source_path, output_path, start_timestamp, end_timestamp, start_encoding, track_context
        )
    end

    local function make_snapshot_filename(source_filename, start_time, end_time, timestamp)
        if state.config.animated_snapshot_enabled then
            return filename_factory.make_filename_from(
                    source_filename, start_time, end_time, state.config.animated_snapshot_extension
            )
        end
        return filename_factory.make_filename_from(source_filename, timestamp, state.config.snapshot_extension)
    end

    local function make_audio_filename(source_filename, start_time, end_time)
        return filename_factory.make_filename_from(
                source_filename, start_time, end_time, state.config.audio_extension
        )
    end

    local function source_availability(sub, media_type)
        if sub.history_record == true then
            local captured = sub['has_' .. media_type]
            -- Legacy records use the source's deterministic default track and never
            -- inspect the worker's currently loaded file.
            return captured == nil or captured == true
        end
        if media_type == 'video' then
            return h.has_video_track()
        end
        return h.has_audio_track()
    end

    local function create_job(job_type, sub, audio_padding)
        local on_finish_fn
        local job = {}
        local historical = sub.history_record == true
        local source_path = sub.source_path or mp.get_property('path')
        local source_filename = sub.source_filename
                or (historical and 'history-media')
                or mp.get_property('filename')
                or 'media'
        if job_type == 'snapshot' and source_availability(sub, 'video') and not h.is_empty(state.config.image_field) then
            local current_timestamp = sub.snapshot_time or (historical and sub.start) or mp.get_property_number('time-pos', 0)
            job.filename = make_snapshot_filename(source_filename, sub.start, sub['end'], current_timestamp)
            local track_context
            if historical then
                track_context = {
                    history_record = true,
                    video_track_id = sub.video_track_id,
                    video_ff_index = sub.video_ff_index,
                }
            end
            job.run_async = function()
                create_snapshot(
                        sub.start, sub['end'], current_timestamp, job.filename, on_finish_fn,
                        source_path, not historical and h.is_empty(sub.source_path), track_context
                )
            end
        elseif job_type == 'audioclip' and source_availability(sub, 'audio') and not h.is_empty(state.config.audio_field) then
            job.filename = make_audio_filename(source_filename, sub.start, sub['end'])
            local track_context
            if historical then
                track_context = {
                    history_record = true,
                    audio_track_id = sub.audio_track_id,
                    audio_ff_index = sub.audio_ff_index,
                    audio_external_path = sub.audio_external_path,
                    capture_volume = sub.capture_volume,
                }
            end
            job.run_async = function()
                create_audio(
                        sub.start, sub['end'], job.filename, audio_padding or 0, on_finish_fn,
                        source_path, track_context, sub.source_duration, historical
                )
            end
        else
            job.filename = nil
            job.run_async = function()
                print(job_type .. ' will not be created.')
                if type(on_finish_fn) == 'function' then on_finish_fn(true) end
            end
        end
        job.on_finish = function(fn)
            on_finish_fn = fn
            return job
        end
        return job
    end

    function public.encoder()
        return state.encoder
    end

    function public.init(cfg_mgr)
        cfg_mgr.fail_if_not_ready()
        state.config = cfg_mgr.config()
        initialize_backend()
    end

    function public.set_output_dir(dir_path)
        state.output_dir_path = dir_path
    end

    function public.snapshot.create_job(sub)
        return create_job('snapshot', sub)
    end

    function public.snapshot.toggle_animation()
        state.config.animated_snapshot_enabled = not state.config.animated_snapshot_enabled
        h.notify('Animation ' .. (state.config.animated_snapshot_enabled and 'enabled' or 'disabled'), 'info', 2)
    end

    function public.audio.create_job(subtitle, padding)
        return create_job('audioclip', subtitle, padding)
    end

    if initial_config ~= nil then
        initialize_backend()
    end
    return public
end

local default_encoder = make_encoder(nil)

function default_encoder.new(config)
    return make_encoder(config)
end

return default_encoder
