# Reference

## `config.json`

Read from `./config.json`, or from the path in `$REAPER_REMOTE_CONFIG`.
Unknown keys are rejected at startup, so a typo fails loudly.

| key | default | meaning |
|---|---|---|
| `host` | `127.0.0.1` | bind address. Keep loopback and publish with `tailscale serve` |
| `port` | `8090` | bind port |
| `reaper_url` | (required) | REAPER's web interface, e.g. `http://127.0.0.1:8080` |
| `stream.input` | (required) | CoreAudio input device to capture, e.g. `BlackHole 2ch` (as listed in Audio MIDI Setup). It is captured at the device's own sample rate and passed to the encoders unchanged |
| `stream.bitrate` | `128k` | Opus bitrate |
| `stream.ffmpeg` | `ffmpeg` | ffmpeg binary used by `reaper-remote publish` (name on `PATH` or full path) |
| `media.webrtc` | `http://127.0.0.1:8889` | mediamtx's WebRTC HTTP server (`webrtcAddress`) |
| `media.hls` | `http://127.0.0.1:8888` | mediamtx's HLS HTTP server (`hlsAddress`) |
| `media.path` | `reaper` | mediamtx path the audio is published to |
| `devices.headphones` | — | output device name for the `headphones` button |
| `devices.multi` | — | output device name for the `multi` button |
| `devices.blackhole` | — | output device name for the `blackhole` button |
| `devices.switch_audio_source` | `SwitchAudioSource` | SwitchAudioSource binary |
| `render.action` | (required in `render`) | command ID of `reaper/reaper-remote-render.lua` (`_RS…`) |
| `render.dir` | (required in `render`) | directory the rendered files go to; `~` is expanded |
| `render.timeout_s` | `600` | how long to wait for a render to finish |
| `timeline.action` | (required in `timeline`) | command ID of `reaper/reaper-remote-timeline.lua` (`_RS…`) |
| `loop.action` | (required in `loop`) | command ID of `reaper/reaper-remote-loop.lua` (`_RS…`) |

A device key that is left out does not get a button. Without a `render` block
the render button is hidden; without a `timeline` block the seek bar is, and
without a `loop` block a long press on it seeks instead of setting the loop.

## HTTP API

All paths are relative to where the server is mounted.

| method | path | response |
|---|---|---|
| `GET` | `/` | the UI (served with `Cache-Control: no-cache`) |
| `GET` | `/version` | `{"ui": "<fingerprint>"}` — a hash of the UI files at start-up; open pages reload themselves when it changes (not while listening) |
| `GET` | `/reaper/_/<commands>` | REAPER's web interface, passed through unchanged (`text/plain`, tab-separated lines). `<commands>` is `;`-separated, e.g. `TRANSPORT;TRACK` or `SET/TRACK/1/VOL/0.5`; a percent-encoded `%3B` (as some front proxies send it) is treated as `;` too. See [the command list](https://github.com/ReaTeam/Doc/blob/master/web_interface_modding.md) |
| `POST` | `/whep` | WHEP offer (`application/sdp`), relayed to mediamtx; answers `201` with the SDP answer and `Location: whep/<session>` |
| `PATCH`, `DELETE` | `/whep/<session>` | trickle ICE / end of a WHEP session, relayed to mediamtx |
| `GET` | `/llhls/<file>` | mediamtx's Low-Latency HLS for the path, relayed with its query string (start at `llhls/index.m3u8`) |
| `GET` | `/device` | `{"current": "multi", "name": "<device name>", "options": ["headphones", "multi", "blackhole"], "available": ["multi", "blackhole"]}`. `current` is `null` when the output is none of the configured devices; `available` lists the configured devices that exist right now (a headphone-jack output exists only while something is plugged in) |
| `POST` | `/device` | body `{"device": "headphones" \| "multi" \| "blackhole"}`; switches the Mac's system output and returns the same shape as `GET` |
| `GET` | `/render` | `{"enabled": true \| false}` |
| `POST` | `/render` | renders and returns `{"name": "<file>", "url": "renders/<file>"}` once the file has stopped growing |
| `GET` | `/renders/<file>` | a rendered file |
| `GET` | `/loop` | `{"enabled": true \| false}` |
| `POST` | `/loop` | body `{"start": <s>, "end": <s>}` (seconds, `0 <= start < end`); sets the loop points through the loop script, turns repeat on, and echoes the range |
| `GET` | `/timeline` | `{"enabled": false}`, or `{"enabled": true, "end": 163.5, "edges": [0.0, 1.74, …], "loop": {"start", "end"} or null, "regions": [{"id", "name", "start", "end", "color"}], "markers": [{"id", "name", "pos", "color"}]}` (seconds). `edges[i]` and `edges[i + 1]` bound measure `i + 1`; `color` is `0xaarrggbb`, `0` when none is set. Runs the timeline script on every call |

Errors are JSON `{"detail": "..."}`:

| status | when |
|---|---|
| `400` | `POST /device` with an unknown key; `POST /loop` with an empty or reversed range |
| `404` | device key, `render` or `loop` not configured; unknown rendered file |
| `409` | `POST /device` to a device that is not connected; `POST /render` while another render is running |
| `500` | SwitchAudioSource missing or failing |
| `502` | REAPER's web interface or mediamtx unreachable or erroring; `GET /timeline` when the script left no usable result (wrong `timeline.action`) |
| `504` | no rendered file appeared within `render.timeout_s` |

There is no authentication in the server itself: it listens on loopback, and
Tailscale decides who reaches it. See [SECURITY.md](../../SECURITY.md).

## `reaper-remote publish [RTSP_URL]`

Captures `stream.input` through CoreAudio and publishes it as Opus over RTSP.
mediamtx runs it on demand (see `mediamtx/mediamtx.example.yml`); without a
URL it publishes to `rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH`, the variables
mediamtx sets. The device must run at a rate Opus supports (48 kHz and its
divisors): the audio is never resampled, so any other rate is refused.
