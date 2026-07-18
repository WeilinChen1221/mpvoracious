local h = require('helpers')

local this = {}

local function formatted_filename(filename, config)
    filename = h.remove_extension(filename or '')
    filename = h.remove_common_resolutions(filename)
    local start_idx, end_idx, episode = h.get_episode_number(filename)

    if config.tag_del_episode_num == true and not h.is_empty(start_idx) then
        if config.tag_del_after_episode_num == true then
            filename = filename:sub(1, start_idx)
        else
            filename = filename:sub(1, start_idx) .. filename:sub(end_idx + 1, -1)
        end
    end
    if config.tag_nuke_brackets == true then
        filename = h.remove_text_in_brackets(filename)
    end
    if config.tag_nuke_parentheses == true then
        filename = h.remove_filename_text_in_parentheses(filename)
    end
    if config.tag_filename_lowercase == true then
        filename = filename:lower()
    end
    filename = h.remove_leading_trailing_spaces(filename)
    filename = filename:gsub(' ', '_'):gsub('_%-_', '_')
    filename = h.remove_leading_trailing_dashes(filename)
    return filename, episode or ''
end

function this.format(config, record)
    local filename, episode = formatted_filename(record.filename, config)
    local format = config.miscinfo_format or ''
    local result = format
            :gsub('%%n', filename)
            :gsub('%%d', episode)
            :gsub('%%t', h.human_readable_time(tonumber(record.snapshot_time) or 0))
            :gsub('%%e', os.getenv('SUBS2SRS_TAGS') or '')
            :gsub('%%f', record.video_path or '')
    result = h.remove_leading_trailing_spaces(result)
    if h.is_empty(result) then
        local display_name = h.is_empty(record.filename) and 'Unknown source' or record.filename
        result = string.format('%s (%s)', display_name, h.human_readable_time(tonumber(record.snapshot_time) or 0))
    end
    return result
end

return this
