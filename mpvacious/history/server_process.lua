local h = require('helpers')
local executables = require('encoder.executables')

local function new(cfg_mgr, client)
    local self = {
        started = false,
    }

    local function parse_host_port(url)
        local host, port = url:match('^https?://([^:/]+):?(%d*)')
        return host or '127.0.0.1', port ~= '' and port or '44765'
    end

    local function uv_args()
        local plugin_dir = h.find_mpvacious_dir()
        local host, port = parse_host_port(cfg_mgr.query("mining_history_url"))
        local args = {
            executables.find_exec('uv'),
            'run',
            '--isolated',
            '--no-dev',
            '--project',
            plugin_dir,
            'python',
            '-m',
            'history_server',
            '--host',
            host,
            '--port',
            tostring(port),
        }
        local db_path = cfg_mgr.query("mining_history_db")
        if not h.is_empty(db_path) then
            table.insert(args, '--db')
            table.insert(args, db_path)
        end
        return args
    end

    function self.ensure_running()
        local ok = client.health()
        if ok then
            return true
        end
        if self.started then
            return false
        end
        self.started = true
        h.subprocess_detached { args = uv_args(), suppress_log = true }
        return true
    end

    function self.open_page()
        local platform = require('platform.init')
        return h.subprocess_detached {
            args = { platform.open_utility, cfg_mgr.query("mining_history_url") },
            suppress_log = true,
        }
    end

    return self
end

return {
    new = new,
}
