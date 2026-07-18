local mp = require('mp')

local function test()
    local root = assert(os.getenv("MPVACIOUS_ROOT"))
    package.path = root .. "/?.lua;" .. package.path
    assert(type(require('history.client').new) == "function")
    assert(type(require('history.controller').new) == "function")
    local defaults = require('config.defaults')
    local cfg_utils = require('config.utils')
    local h = require('helpers')
    local encoder = require('encoder.encoder')
    local exporter = require('anki.note_exporter').new()
    local source_info = require('history.source_info')
    local history_controller_module = require('history.controller')
    local config_manager_module = require('config.cfg_mgr')
    local checker = require('anki.new_note_checker')

    assert(checker.classify_claim({ status = "claimed", record = { id = "rec-1" } }) == "claimed")
    assert(checker.classify_claim({ status = "already_claimed" }) == "handled")
    assert(checker.classify_claim({ status = "unmatched" }) == "fallback")
    assert(checker.classify_claim(nil, "server unavailable") == "retry")
    assert(checker.classify_claim({ status = "unexpected" }) == "retry")

    local config = h.deep_copy(defaults.defaults)
    config.use_ffmpeg = false
    config.loudnorm = false
    config.tie_volumes = true
    config.audio_field = 'Audio'
    config.image_field = 'Picture'
    cfg_utils.validate_config(config)

    local scoped_encoder = encoder.new(config)
    local sub = {
        start = 1,
        ['end'] = 2,
        snapshot_time = 1.5,
        source_path = '/captured/video.mkv',
        source_filename = 'Captured Episode 03.mkv',
        video_track_id = '4',
        video_ff_index = '3',
        audio_track_id = '7',
        audio_external_path = '/captured/external.flac',
        capture_volume = 55,
        has_audio = true,
        has_video = true,
        history_record = true,
    }
    local audio_job = scoped_encoder.audio.create_job(sub, 0)
    local image_job = scoped_encoder.snapshot.create_job(sub)
    assert(audio_job.filename:find('capturedepisode03', 1, true) ~= nil)
    assert(image_job.filename:find('capturedepisode03', 1, true) ~= nil)

    local image_args = scoped_encoder.encoder().make_static_snapshot_args(
            '/captured/video.mkv', '/tmp/output.avif', 1.5,
            { history_record = true, video_track_id = '4', video_ff_index = '3' }
    )
    assert(h.contains(image_args, '--vid=4'))

    local audio_args
    scoped_encoder.encoder().make_audio_args(
            '/captured/video.mkv', '/tmp/output.ogg', 1, 2,
            function(args) audio_args = args end,
            {
                history_record = true,
                audio_track_id = '7',
                audio_external_path = '/captured/external.flac',
                capture_volume = 55,
            }
    )
    assert(audio_args[2] == '/captured/external.flac')
    assert(h.contains(audio_args, '--aid=auto'))
    assert(h.contains(audio_args, '--volume=55'))

    local fields = exporter.history_media_fields(
            config, 'StableAudio', 'StableImage', 'new.ogg', 'new.avif'
    )
    assert(fields.StableAudio == '[sound:new.ogg]')
    assert(fields.StableImage == '<img alt="snapshot" src="new.avif">')
    assert(fields.SentKanji == nil)
    assert(fields.Notes == nil)

    local record_sub = exporter.history_subtitle {
        sentence = '文', start_time = 1, end_time = 2, snapshot_time = 1.5,
        video_path = '/captured/video.mkv', filename = 'captured.mkv',
        video_track_id = '4', video_ff_index = '3',
        audio_track_id = '7', audio_external_path = '/captured/external.flac',
    }
    assert(record_sub.history_record == true)
    assert(record_sub.source_path == '/captured/video.mkv')
    assert(record_sub.audio_track_id == '7')
    assert(record_sub.video_track_id == '4')
    local resend_sub = exporter.history_subtitle {
        sentence = '文', start_time = 1, end_time = 2, snapshot_time = 1.5,
        video_path = '/captured/video.mkv', filename = 'captured.mkv', resend_nonce = '5-token',
    }
    assert(resend_sub.source_filename == 'captured-resend-5-token')

    local info = source_info.format(config, {
        filename = 'Show Episode 03.mkv', video_path = '/captured/video.mkv', snapshot_time = 65,
    })
    assert(info:find('01m05s000ms', 1, true) ~= nil)

    local scoped_manager = config_manager_module.new {
        create_config_file = function() end,
        profile_exists = function() return true end,
        read_options = function(target, name)
            if name == 'subs2srs_profiles' then
                target.profiles = 'subs2srs,profile_test'
                target.active = 'profile_test'
            elseif name == 'subs2srs' then
                target.audio_field = 'BaseAudio'
            elseif name == 'profile_test' then
                target.audio_field = 'ProfileAudio'
            end
        end,
    }
    scoped_manager.init({})
    local active_config = scoped_manager.config()
    active_config.audio_field = 'RuntimeOnlyAudio'
    local resolved_config, resolve_error = scoped_manager.resolve_profile('profile_test')
    assert(resolve_error == nil)
    assert(resolved_config.audio_field == 'ProfileAudio')
    assert(active_config.audio_field == 'RuntimeOnlyAudio')
    assert(scoped_manager.profiles().active == 'profile_test')

    local finalized = false
    local reported = {}
    local controller = history_controller_module.new()
    controller.resend_busy = true
    controller.client = {
        report_resend = function(_, _, note_id, state, _, completion)
            reported[note_id] = state
            completion({}, nil)
        end,
        adopt_targets = function(_, _, _, _, _, completion)
            completion({ link = {} }, nil)
        end,
        renew_resend = function(_, _, completion)
            completion({}, nil)
        end,
        finalize_resend = function(_, _, error, completion)
            assert(error == '')
            finalized = true
            completion({}, nil)
        end,
    }
    controller.resend_fn = function(record, links, callbacks)
        assert(record.resend_nonce:find('9%-lease%-to', 1) == 1)
        assert(#links == 2)
        callbacks.on_result(1001, 'done', '')
        callbacks.on_result(1002, 'failed', 'rejected')
        callbacks.on_finish(nil)
    end
    controller.process_resend_lease {
        generation_id = 9,
        lease_token = 'lease-token-value',
        record = { linked_notes = { { note_id = 1001 }, { note_id = 1002 } } },
    }
    assert(finalized == true)
    assert(controller.resend_busy == false)
    assert(reported[1001] == 'done')
    assert(reported[1002] == 'failed')
end

local success, error = pcall(test)
if success then
    mp.msg.info("TESTS PASSED")
else
    mp.msg.error("TESTS FAILED: " .. tostring(error))
end
mp.commandv("quit", success and 0 or 1)
