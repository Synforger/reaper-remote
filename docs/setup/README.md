# Setup

All steps run on the Mac that runs REAPER.

## 1. Install the tools

```bash
brew install uv mediamtx ffmpeg switchaudio-osx blackhole-2ch go-task
git clone https://github.com/Synforger/reaper-remote.git
cd reaper-remote
task setup
```

`task doctor` reports anything missing.

## 2. Enable REAPER's web interface

REAPER → Settings → Control/OSC/web → **Add** → *Web browser interface*.
Keep the default port 8080 (or put your port into `reaper_url`). Check it from
the Mac:

```bash
curl 'http://127.0.0.1:8080/_/TRANSPORT'
# TRANSPORT	0	0.000000	0	...
```

## 3. Route the Mac's output through BlackHole

The live stream captures BlackHole, so whatever should be heard remotely has
to reach BlackHole.

1. Open **Audio MIDI Setup** → **+** → *Create Multi-Output Device*.
2. Tick your usual output (for example headphones) and **BlackHole 2ch**.
   Put your usual output first and use it as the clock source.
3. In REAPER → Settings → Audio → Device, choose the system default output,
   so REAPER follows whatever the Mac is set to.

The three outputs the UI switches between are:

| key | device | you hear it on |
|---|---|---|
| `headphones` | your usual output | the Mac only |
| `multi` | the Multi-Output Device | the Mac and the phone |
| `blackhole` | BlackHole 2ch | the phone only |

List the exact names with `SwitchAudioSource -a -t output` and copy them into
`config.json`.

## 4. Create `config.json`

```bash
cp config.example.json config.json
```

Fill in the device names (see [Reference](../reference/README.md) for every
key). `config.json` is git-ignored; nothing machine-specific is committed.

## 5. (Optional) Register the REAPER scripts

Four features run REAPER actions that the repository ships as ReaScripts.
Register each one the same way:

1. REAPER → Actions → Show action list → **New action** → *Load ReaScript*,
   pick the script.
2. Right-click the new action → *Copy selected action command ID* (it starts with `_RS`).
3. Put it into `config.json` under the key below.

| script | key | what it gives the page |
|---|---|---|
| `reaper/reaper-remote-timeline.lua` | `timeline.action` | the seek bar: measures, regions, markers and the loop points; drag or tap to jump to a measure, tap a region to jump to its start |
| `reaper/reaper-remote-loop.lua` | `loop.action` | setting the loop from the seek bar: long-press a region to loop it, or long-press and slide to loop measures |
| `reaper/reaper-remote-projects.lua` and `reaper/reaper-remote-project-select.lua` | `projects.list_action` and `projects.select_action` | the project picker: the open tabs (unsaved ones marked), tap one to switch REAPER to it |
| `reaper/reaper-remote-render.lua` | `render.action` (and pick a `render.dir`) | the render button |

The timeline script only reads the project: it publishes where every measure
starts (from REAPER's tempo map, so tempo and time signature changes are
followed) and where the loop points are, and adds no undo point. The page runs
it every few seconds, so the seek bar follows edits.

The project scripts list the tabs and switch between them; nothing is saved
or closed, so no REAPER dialog can come up. A switch goes ahead only when the
chosen tab still has the name the page showed.

The loop script moves the loop points only (the play position and the time
selection stay), turns repeat on, and adds no undo point.

Register the scripts from where they will stay: an action keeps the path it
was loaded from, and while a script is missing REAPER shows an error dialog
that blocks every web request until it is closed.

The render script renders the time selection (or the whole project when there
is none) of the master mix into `render.dir`, using the project's current
render format, and restores the project's render settings afterwards.

Leave a block out to hide its feature.

## 6. Configure mediamtx

mediamtx distributes the live audio. Copy the example and point its
`runOnDemand` line at this checkout:

```bash
cp mediamtx/mediamtx.example.yml mediamtx/mediamtx.yml
# edit mediamtx/mediamtx.yml: /path/to/reaper-remote -> the absolute path of this checkout
mediamtx mediamtx/mediamtx.yml
```

Its HTTP servers listen on loopback only; reaper-remote relays to them. The
audio itself travels over WebRTC's UDP port 8189, which must be reachable from
the phone (on a tailnet it is, with no extra configuration). `mediamtx.yml` is
git-ignored.

## 7. Run it

```bash
task run
```

Open `http://127.0.0.1:8090/` on the Mac to check.

The first time someone listens, macOS asks whether the capturing process may
use the microphone. mediamtx starts that process (`reaper-remote publish`), so
the request is made on behalf of whatever started mediamtx: the terminal, or
the mediamtx binary when launchd starts it. Allow it: BlackHole is
an input device, and without that permission the stream is silent.

## 8. Reach it from the phone

```bash
tailscale serve --bg --set-path=/ext/reaper http://127.0.0.1:8090
```

Open `https://<your-mac>.<your-tailnet>.ts.net/ext/reaper/` (keep the trailing
slash). Serve strips the path prefix before forwarding, and the UI only uses
relative URLs, so any prefix works.

## 9. (Optional) Start at login

Save as `~/Library/LaunchAgents/com.example.reaper-remote.plist`, replacing
the two paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.reaper-remote</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/reaper-remote/.venv/bin/reaper-remote</string>
  </array>
  <key>WorkingDirectory</key><string>/path/to/reaper-remote</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.reaper-remote.plist
```

`PATH` must contain `ffmpeg` and `SwitchAudioSource` (or give their full paths
in `config.json`).

Run mediamtx the same way, with a second LaunchAgent whose `ProgramArguments`
are the mediamtx binary (`/opt/homebrew/bin/mediamtx`) and the absolute path
of `mediamtx/mediamtx.yml`. A server started by launchd asks for microphone access on
its own; allow it once.
