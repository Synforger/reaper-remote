# Troubleshooting

## The page shows `REAPER: REAPER web interface unreachable`

REAPER is not running, or its web interface is off or on another port.
`curl 'http://127.0.0.1:8080/_/TRANSPORT'` on the Mac must print a
`TRANSPORT` line; if it does not, enable the interface (Setup step 2) or fix
`reaper_url`.

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

That is by design: the page plays only while it is on screen. Going to the
home screen, another app or the lock screen stops playback and ends the
stream (the Mac stops capturing shortly after). Coming back resumes it when
the output is still Multi or BlackHole; if the phone asks for a tap first,
the dot stays grey until you tap Multi or BlackHole. Folding the host app's
panel does not count as leaving: the page stays visible and keeps playing.

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

## Render answers 504

The action did not produce a file in `render.dir` within `render.timeout_s`.
Check that `render.action` is the command ID of `reaper-remote-render.lua`
(Actions → the action → *Copy selected action command ID*), and that REAPER
has a render format configured (File → Render once by hand).

## Opening the page at `/ext/reaper` (no trailing slash) shows a broken page

The UI loads `app.js`, `style.css` and the API relative to the page URL, which
needs the trailing slash. Open `/ext/reaper/`.
