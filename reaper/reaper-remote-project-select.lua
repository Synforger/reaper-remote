-- reaper-remote: switch to the project tab reaper-remote names.
--
-- Register this file once via Actions > Show action list > New action >
-- Load ReaScript, copy its command ID (it starts with "_RS"), and write that ID
-- into `projects.select_action` in reaper-remote's config.json.
--
-- reaper-remote passes "<index>/<file name>" through the ExtState
-- `reaper_remote/project_select` right before it triggers this action. The tab
-- is switched only when the tab at that index still has that name, so a tab
-- opened or closed since the page listed them never sends it to the wrong one.
-- Only the tab changes: nothing is saved or closed. The outcome goes to
-- `reaper_remote/project_select_result` as "ok" or "error: <reason>". The
-- script ends within the call and never defers (see the timeline script).

local function done(result)
  reaper.SetExtState("reaper_remote", "project_select_result", result, false)
end

local function file_name(path)
  return (path or ""):match("([^/\\]+)$") or ""
end

local want = reaper.GetExtState("reaper_remote", "project_select")
local index, name = want:match("^(%d+)/(.*)$")
index = tonumber(index)
if not index then
  done("error: no tab named; trigger this action from reaper-remote")
  return
end

local proj, path = reaper.EnumProjects(index, "")
if not proj then
  done("error: there is no tab " .. index)
  return
end
if file_name(path) ~= name then
  done("error: tab " .. index .. " is no longer " .. (name ~= "" and name or "(untitled)"))
  return
end

reaper.SelectProjectInstance(proj)
done("ok")
