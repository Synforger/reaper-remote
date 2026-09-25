# Troubleshooting

## The page shows `REAPER: REAPER web interface unreachable`

REAPER is not running, or its web interface is off or on another port.
`curl 'http://127.0.0.1:8080/_/TRANSPORT'` on the Mac must print a
`TRANSPORT` line; if it does not, enable the interface (Setup step 2) or fix
`reaper_url`.

If it hangs instead of answering, look at REAPER's screen: while a dialog is
open (a *ReaScript error* or *ReaScript task control* among them) REAPER
answers no web request at all. Close it. *ReaScript task control* ("already
running in the background") means a script reaper-remote triggers defers; the
shipped ones never do, and a test keeps it that way. A *ReaScript error* that says a file cannot be read means an action
in `config.json` points at a script that was moved or deleted; register the
script again (Setup step 5) and update the command ID.

## Audio is choppy on the phone

While the phone listens over WebRTC, the page writes what it received to the
server log every 5 seconds, with the time:

```
2026-09-24 19:40:05 INFO:     reaper_remote: listen mode=webrtc seconds=5.0 received=250 lost=0 loss_pct=0.0 discarded=0 jitter_ms=3.0 concealed_pct=0.0 concealment_events=0 buffer_ms=60.0 rtt_ms=41.0 from 100.x.y.z
2026-09-24 19:40:10 WARNING:     reaper_remote: listen GAP mode=webrtc seconds=5.0 received=248 lost=2 loss_pct=0.8 discarded=0 jitter_ms=12.5 concealed_pct=0.4 concealment_events=1 buffer_ms=85.0 rtt_ms=41.0 from 100.x.y.z
```

An interval in which audio went missing is marked `GAP` and logged as a
warning, so `grep 'listen GAP'` finds every dropout without knowing when it
was heard.

- `lost` / `loss_pct`: packets that never arrived. Each one is a gap the
  phone has to fill in.
- `discarded`: packets that arrived too late to be played — late rather than
  lost.
- `jitter_ms`: how unevenly packets arrive. `buffer_ms` is how long the phone
  holds audio to smooth that out.
- `concealed_pct` / `concealment_events`: how much of what was played was
  made up to cover missing audio — what is heard as a crackle or dropout.
- `rtt_ms`: the round trip to the phone.

A switch to LL-HLS is logged as `listen GAP mode=llhls event=fallback` with
its reason, and each stall on LL-HLS as `event=waiting`. Compare the lines from
around a dropout with those from clean listening.

## The dot is green but nothing is heard

- The Mac output is `headphones`, so nothing reaches BlackHole. Switch to
  `multi` or `blackhole`.
- REAPER is stopped. The stream carries digital silence until something plays.
- The capturing process lacks microphone permission, so macOS hands it zeros.
  mediamtx starts it, so check System Settings → Privacy & Security →
  Microphone for what started mediamtx (Terminal, or the mediamtx binary of
  the launchd job).

Check the capture path without the phone:

```bash
ffmpeg -i http://127.0.0.1:8090/llhls/index.m3u8 -t 5 -af volumedetect -f null - 2>&1 | grep max_volume
```

`max_volume` around `-91 dB` means silence reached the encoder.

## Opening the page with Multi or BlackHole selected stays silent

Phones only start audio from a tap on the page. Tap Multi or BlackHole (the
one already selected works too); the dot next to them turns amber, then
green.

## The dot stays amber, or audio plays 1–2 s late instead of instantly

WebRTC could not connect and the page fell back to Low-Latency HLS. The audio
travels on UDP port 8189 of the Mac: check that mediamtx is running and that
the port is reachable from the phone (on a tailnet it normally is). The
mediamtx log shows each session and the candidate pair it used.

## Audio stops when the phone locks or the app goes to the background

That is the default: the page plays only while it is on screen. Going to the
home screen, another app or the lock screen stops playback and ends the
stream (the Mac stops capturing shortly after). Coming back resumes it when
the output is still Multi or BlackHole; if the phone asks for a tap first,
the dot stays grey until you tap Multi or BlackHole. Folding the host app's
panel does not count as leaving: the page stays visible and keeps playing.

Turn on **BG** (next to the output buttons) to keep playing in the
background instead. Each phone remembers the choice. Whether audio really
continues once the page is out of sight is up to the phone's browser.

## Audio is choppy, or much shorter than real time

The capture must not drop samples. reaper-remote reads the device through
CoreAudio for this reason: ffmpeg's avfoundation input was measured keeping
only about 1.3 s of every 8.6 s from a loopback device while REAPER played.
If you changed `stream.input`, check that the name matches the input device
in Audio MIDI Setup exactly.

## An output button is greyed out

That device does not exist right now. On a Mac, the headphone-jack output
appears only while something is plugged into the jack. Plug it in; the page
picks it up within ten seconds.

## The render button is missing

There is no `render` block in `config.json`. See Setup step 5.

## The seek bar is missing, or long presses only seek

The seek bar needs a `timeline` block in `config.json`, and setting the loop
needs a `loop` block. See Setup step 5.

## The page shows `Timeline: the timeline script left no result`

`timeline.action` is not the command ID of `reaper-remote-timeline.lua`.
Copy it again from the action list (Actions → the action → *Copy selected
action command ID*).

## Render answers 504

The action did not produce a file in `render.dir` within `render.timeout_s`.
Check that `render.action` is the command ID of `reaper-remote-render.lua`
(Actions → the action → *Copy selected action command ID*), and that REAPER
has a render format configured (File → Render once by hand).

## Opening the page at `/ext/reaper` (no trailing slash) shows a broken page

The UI loads `app.js`, `style.css` and the API relative to the page URL, which
needs the trailing slash. Open `/ext/reaper/`.
