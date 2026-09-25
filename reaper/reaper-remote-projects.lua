-- reaper-remote: publish the open project tabs, so the page can list them and
-- switch between them (with reaper-remote-project-select.lua).
--
-- Register this file once via Actions > Show action list > New action >
-- Load ReaScript, copy its command ID (it starts with "_RS"), and write that ID
-- into `projects.list_action` in reaper-remote's config.json.
--
-- The result goes to the ExtState `reaper_remote/projects` as JSON:
--   {"tabs":[{"index":0,"name":"song.RPP","dirty":false,"active":true}, ...]}
-- `name` is the file name only ("" for a project never saved). The script only
-- reads, and ends within the call: it must never defer (see the timeline script).

local function json_string(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' end
    if c == "\\" then return "\\\\" end
    return string.format("\\u%04x", c:byte())
  end) .. '"'
end

local function file_name(path)
  return (path or ""):match("([^/\\]+)$") or ""
end

local active = reaper.EnumProjects(-1, "")
local tabs = {}
local i = 0
while true do
  local proj, path = reaper.EnumProjects(i, "")
  if not proj then break end
  tabs[#tabs + 1] = string.format('{"index":%d,"name":%s,"dirty":%s,"active":%s}',
    i, json_string(file_name(path)), tostring(reaper.IsProjectDirty(proj) ~= 0), tostring(proj == active))
  i = i + 1
end

reaper.SetExtState("reaper_remote", "projects", '{"tabs":[' .. table.concat(tabs, ",") .. "]}", false)
