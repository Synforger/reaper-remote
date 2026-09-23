-- reaper-remote: render the time selection (or the whole project when there is
-- none) into the directory reaper-remote names, then put the project's own
-- render settings back exactly as they were.
--
-- Register this file once via Actions > Show action list > New action >
-- Load ReaScript, copy its command ID (it starts with "_RS"), and write that ID
-- into `render.action` in reaper-remote's config.json.
--
-- reaper-remote passes the output directory through the ExtState
-- `reaper_remote/render_dir` right before it triggers this action.

local PROJ = 0
local RENDER_WITH_LAST_SETTINGS_AUTOCLOSE = 42230
local BOUNDS_ENTIRE_PROJECT = 1
local BOUNDS_TIME_SELECTION = 2
local SOURCE_MASTER_MIX = 0

local dir = reaper.GetExtState("reaper_remote", "render_dir")
if dir == "" then
  reaper.ShowConsoleMsg("reaper-remote: render_dir is not set; trigger this action from reaper-remote\n")
  return
end

local num_keys = { "RENDER_BOUNDSFLAG", "RENDER_SETTINGS", "RENDER_ADDTOPROJ" }
local str_keys = { "RENDER_FILE", "RENDER_PATTERN" }

local saved_num, saved_str = {}, {}
for _, k in ipairs(num_keys) do
  saved_num[k] = reaper.GetSetProjectInfo(PROJ, k, 0, false)
end
for _, k in ipairs(str_keys) do
  local _, v = reaper.GetSetProjectInfo_String(PROJ, k, "", false)
  saved_str[k] = v
end

local sel_start, sel_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
local bounds = (sel_end > sel_start) and BOUNDS_TIME_SELECTION or BOUNDS_ENTIRE_PROJECT

reaper.GetSetProjectInfo(PROJ, "RENDER_BOUNDSFLAG", bounds, true)
reaper.GetSetProjectInfo(PROJ, "RENDER_SETTINGS", SOURCE_MASTER_MIX, true)
reaper.GetSetProjectInfo(PROJ, "RENDER_ADDTOPROJ", 0, true)
reaper.GetSetProjectInfo_String(PROJ, "RENDER_FILE", dir, true)
reaper.GetSetProjectInfo_String(PROJ, "RENDER_PATTERN", "reaper-remote-$year$month$day-$hour$minute$second", true)

reaper.Main_OnCommand(RENDER_WITH_LAST_SETTINGS_AUTOCLOSE, 0)

for _, k in ipairs(num_keys) do
  reaper.GetSetProjectInfo(PROJ, k, saved_num[k], true)
end
for _, k in ipairs(str_keys) do
  reaper.GetSetProjectInfo_String(PROJ, k, saved_str[k], true)
end
