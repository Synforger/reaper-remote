-- reaper-remote: publish where every measure starts and where the loop is, so
-- the seek bar can lay the project out in measures, seek to them and show the
-- loop.
--
-- Register this file once via Actions > Show action list > New action >
-- Load ReaScript, copy its command ID (it starts with "_RS"), and write that ID
-- into `timeline.action` in reaper-remote's config.json.
--
-- The result goes to the ExtState `reaper_remote/timeline` as
--   <project end in seconds>|<measure 1 start>,<measure 2 start>,...|<loop start>,<loop end>
-- The list runs one entry past the measure that holds the project end, so it
-- holds both edges of every measure and at least one measure. REAPER's tempo
-- map decides every edge, so tempo and time signature changes need nothing here.
--
-- The script only reads the project and ends as soon as it has written the
-- result. It must not defer: a deferred script counts as running until REAPER's
-- next idle cycle, and a call arriving before that (reaper-remote runs it every
-- few seconds) opens a modal "already running" dialog that blocks every web
-- request until someone answers it.

local PROJ = 0
-- Guards the loop against a runaway tempo map; about 70 minutes at 120 BPM in 4/4.
local MAX_MEASURES = 2000

-- The project end is the later of the last item and the last marker or region,
-- so a song sketched out in regions before any audio exists still has a length.
local length = reaper.GetProjectLength(PROJ)
local i = 0
while true do
  local ok, is_region, pos, stop = reaper.EnumProjectMarkers(i)
  if ok == 0 then break end
  length = math.max(length, is_region and stop or pos)
  i = i + 1
end

local edges = {}
for m = 0, MAX_MEASURES do
  local t = reaper.TimeMap2_beatsToTime(PROJ, 0, m)
  edges[#edges + 1] = string.format("%.6f", t)
  if m > 0 and t >= length then break end
end

-- The loop points (equal when no loop is set).
local loop_start, loop_end = reaper.GetSet_LoopTimeRange2(PROJ, false, true, 0, 0, false)

reaper.SetExtState("reaper_remote", "timeline",
  string.format("%.6f", length) .. "|" .. table.concat(edges, ",")
    .. string.format("|%.6f,%.6f", loop_start, loop_end), false)
