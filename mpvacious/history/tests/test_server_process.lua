local mp = require('mp')

local function test()
    local root = assert(os.getenv('MPVACIOUS_ROOT'))
    package.path = root .. '/?.lua;' .. package.path

    local h = require('helpers')
    local launched
    local launch_count = 0
    local original_find_dir = h.find_mpvacious_dir
    local original_subprocess_detached = h.subprocess_detached

    h.find_mpvacious_dir = function()
        return '/mock/mpvoracious'
    end
    h.subprocess_detached = function(options)
        launch_count = launch_count + 1
        launched = options
        return true
    end

    package.loaded['history.server_process'] = nil
    package.loaded['encoder.executables'] = {
        find_exec = function(name)
            assert(name == 'uv')
            return '/mock/homebrew/bin/uv'
        end,
    }

    local server_process = require('history.server_process').new({
        query = function(name)
            local config = {
                mining_history_url = 'http://127.0.0.1:44765',
                mining_history_db = '/mock/history.sqlite3',
            }
            return config[name]
        end,
    }, {
        health = function()
            return false
        end,
    })

    assert(server_process.ensure_running() == true)
    assert(launch_count == 1)
    assert(launched.args[1] == '/mock/homebrew/bin/uv')
    assert(launched.args[2] == 'run')
    assert(launched.args[3] == '--isolated')
    assert(launched.args[4] == '--no-dev')
    assert(launched.args[5] == '--project')
    assert(launched.args[6] == '/mock/mpvoracious')
    assert(launched.args[7] == 'python')
    assert(launched.args[8] == '-m')
    assert(launched.args[9] == 'history_server')
    assert(launched.args[10] == '--host')
    assert(launched.args[11] == '127.0.0.1')
    assert(launched.args[12] == '--port')
    assert(launched.args[13] == '44765')
    assert(launched.args[14] == '--db')
    assert(launched.args[15] == '/mock/history.sqlite3')

    assert(server_process.ensure_running() == false)
    assert(launch_count == 1)

    h.find_mpvacious_dir = original_find_dir
    h.subprocess_detached = original_subprocess_detached
end

local success, error = pcall(test)
if success then
    mp.msg.info('TESTS PASSED')
else
    mp.msg.error('TESTS FAILED: ' .. tostring(error))
end
mp.commandv('quit', success and 0 or 1)
