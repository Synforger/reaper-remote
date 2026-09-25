-- reaper-remote: set the loop points to the range reaper-remote names.
--
-- Register this file once via Actions > Show action list > New action >
-- Load ReaScript, copy its command ID (it starts with "_RS"), and write that ID
-- into `loop.action` in reaper-remote's config.json.
--
-- reaper-remote passes the range through the ExtState `reaper_remote/loop` as
-- "<start seconds>,<end seconds>" right before it triggers this action. Only
-- the loop points move: the play position and the time selection stay where
-- they are, so playback does not jump. Like the timeline script it ends at once
-- and never defers, so a second call can never find it still running.

local PROJ = 0

local value = reaper.GetExtState("reaper_remote", "loop")
local s, e = value:match("^([%d%.]+),([%d%.]+)$")
s, e = tonumber(s), tonumber(e)
if not s or not e or e <= s then
  reaper.ShowConsoleMsg("reaper-remote: loop range is missing or invalid; trigger this action from reaper-remote\n")
  return
end

reaper.GetSet_LoopTimeRange2(PROJ, true, true, s, e, false)
