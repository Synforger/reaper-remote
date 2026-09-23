# Troubleshooting

## The page shows `REAPER: REAPER web interface unreachable`

REAPER is not running, or its web interface is off or on another port.
`curl 'http://127.0.0.1:8080/_/TRANSPORT'` on the Mac must print a
`TRANSPORT` line; if it does not, enable the interface (Setup step 2) or fix
`reaper_url`.

## Listen connects but stays silent

- The Mac output is `headphones`, so nothing reaches BlackHole. Switch to
  `multi` or `blackhole`.
- REAPER is stopped. The stream carries digital silence until something plays.
- The server lacks microphone permission, so macOS hands it zeros. Check
  System Settings → Privacy & Security → Microphone for the process that
  captures: the server itself (Terminal, or the Python binary of the launchd
  job).

Check the capture path without the phone:

```bash
curl -s -m 5 -o /tmp/probe.ogg http://127.0.0.1:8090/stream.ogg
ffmpeg -i /tmp/probe.ogg -af volumedetect -f null - 2>&1 | grep max_volume
```

`max_volume` around `-91 dB` means silence reached the encoder.

## Audio on iPhone plays too fast or sounds folded

That is iOS Safari playing the live Ogg/Opus stream. The page picks HLS
whenever the browser supports it natively, so this only happens on an older
page still cached in the browser: reload it. Check which stream a browser
uses with `audio.canPlayType("application/vnd.apple.mpegurl")` (non-empty
means HLS).

## Listen stops when the phone locks or the browser goes to the background

Mobile browsers may suspend media in background tabs. Keep the page in the
foreground, or add it to the home screen and check whether playback continues
there.

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
