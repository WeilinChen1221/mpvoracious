--[[
Copyright: Ajatt-Tools and contributors; https://github.com/Ajatt-Tools
License: GNU GPL, version 3 or later; http://www.gnu.org/licenses/gpl.html

Config management, validation, loading.
]]

local mpopt = require('mp.options')
local mputils = require('mp.utils')
local msg = require('mp.msg')
local h = require('helpers')
local defaults = require('config.defaults')
local cfg_utils = require('config.utils')

local default_profile_filename = 'subs2srs'
local profiles_filename = 'subs2srs_profiles'

local function make_config_mgr(dependencies)
    dependencies = dependencies or {}
    local read_options = dependencies.read_options or mpopt.read_options
    local create_config_file = dependencies.create_config_file or cfg_utils.create_config_file
    local profile_exists = dependencies.profile_exists or function(profile_name)
        local profile_path = mputils.join_path(h.find_mpv_script_opts_directory(), profile_name .. '.conf')
        local profile_info = mputils.file_info(profile_path)
        return profile_info and profile_info.is_file
    end
    local self = {
        config = nil,
        encoder = nil,
        profiles = nil,
        initial_config = {},
        init_done = false,
    }
    local public = {}

    local function remember_initial_config()
        if h.is_empty(self.initial_config) then
            self.initial_config = h.shallow_copy(self.config, self.initial_config)
        else
            msg.fatal("Ignoring. Initial config has been read already.")
        end
    end

    local function restore_initial_config()
        self.config = h.shallow_copy(self.initial_config, self.config)
    end

    local function read_profile_list()
        read_options(self.profiles, profiles_filename)
        msg.info("Read profile list. Defined profiles: " .. self.profiles.profiles)
    end

    local function read_profile(profile_name)
        read_options(self.config, profile_name)
        msg.info("Read config file: " .. profile_name)
    end

    local function read_default_config()
        read_profile(default_profile_filename)
    end

    function public.reload_from_disk()
        --- Loads default config file (subs2srs.conf), then overwrites it with current profile.
        if not h.is_empty(self.config) and not h.is_empty(self.profiles) then
            restore_initial_config()
            read_default_config()
            if self.profiles.active ~= default_profile_filename then
                read_profile(self.profiles.active)
            end
            cfg_utils.validate_config(self.config)
            if h.is_empty(self.encoder.encoder()) then
                error("encoder is not initialized.")
            end
            self.encoder.encoder().set_avif_encoder()
        else
            msg.fatal("Attempt to load config when init hasn't been done.")
        end
    end

    function public.next_profile()
        local first, next, new
        for profile in string.gmatch(self.profiles.profiles, '[^,]+') do
            if not first then
                first = profile
            end
            if profile == self.profiles.active then
                next = true
            elseif next then
                next = false
                new = profile
            end
        end
        if next == true or not new then
            new = first
        end
        self.profiles.active = new
        public.reload_from_disk()
    end

    function public.init(encoder)
        self.encoder = encoder
        create_config_file(default_profile_filename)
        self.config = h.shallow_copy(defaults.defaults)
        self.profiles = h.shallow_copy(defaults.profiles)

        -- 'subs2srs' is the main profile, it is always loaded. 'active profile' overrides it afterwards.
        -- initial state is saved to another table to maintain consistency when cycling through incomplete profiles.
        read_profile_list()
        read_default_config()
        remember_initial_config()
        if self.profiles.active ~= default_profile_filename then
            read_profile(self.profiles.active)
        end
        cfg_utils.validate_config(self.config)
        self.init_done = true
    end

    function public.is_init_done()
        return self.init_done
    end

    function public.fail_if_not_ready()
        if not self.init_done then
            error("config not loaded")
        end
    end

    function public.profiles()
        public.fail_if_not_ready()
        return self.profiles
    end

    function public.config()
        public.fail_if_not_ready()
        return self.config
    end

    function public.query(name)
        public.fail_if_not_ready()
        if self.config[name] == nil then
            error("config value is nil:" .. name)
        end
        return self.config[name]
    end

    local function profile_is_defined(profile_name)
        for name in string.gmatch(self.profiles.profiles, '[^,]+') do
            if name == profile_name then
                return true
            end
        end
        return false
    end

    function public.resolve_profile(profile_name)
        public.fail_if_not_ready()
        if h.is_empty(profile_name) or not profile_is_defined(profile_name) then
            return nil, string.format("Capture Profile '%s' is unavailable.", tostring(profile_name))
        end
        if not profile_exists(profile_name) then
            return nil, string.format("Capture Profile '%s' is unavailable.", profile_name)
        end

        local scoped = h.shallow_copy(defaults.defaults)
        local ok, validation_error = pcall(function()
            read_options(scoped, default_profile_filename)
            if profile_name ~= default_profile_filename then
                read_options(scoped, profile_name)
            end
            cfg_utils.validate_config(scoped)
        end)
        if not ok then
            return nil, string.format("Capture Profile '%s' is invalid: %s", profile_name, tostring(validation_error))
        end
        return scoped, nil
    end

    return public
end

return {
    new = make_config_mgr
}
