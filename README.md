# reaper-remote

> Control REAPER and listen to its output from a phone browser, over your own tailnet.

reaper-remote is a small server that runs on the Mac next to REAPER. Open it
in a phone browser and you get the transport (play / pause / stop / repeat),
a fader with mute and solo for every track, a live stream of what the Mac is
playing, a switch for the Mac's system output, and a one-tap render of the
time selection.

It is built to sit inside another page as an iframe (for example a chat app
that mounts extensions at `/ext/<id>/`): every URL in the UI is relative, so
the same process works at `/` and under any path prefix.

## How it works

```
phone browser ──https──▶ tailscale serve ──▶ reaper-remote (127.0.0.1:8090)
      │                                        ├─ /reaper/_/…  ─▶ REAPER web interface (127.0.0.1:8080)
      │                                        ├─ /device      ─▶ SwitchAudioSource (Mac system output)
      │                                        ├─ /render      ─▶ REAPER action (reaper/reaper-remote-render.lua)
      │                                        └─ /whep, /llhls/… ─▶ mediamtx (127.0.0.1:8889 / 8888)
      │                                                                 ▲ RTSP (Opus)
      │                                                    reaper-remote publish ◀─ CoreAudio ◀─ BlackHole 2ch ◀─ Mac output
      └──────── WebRTC audio (UDP 8189, over the tailnet) ◀── mediamtx
```

- The server binds to loopback only. Reaching it from the phone is left to
  [Tailscale Serve](https://tailscale.com/kb/1312/serve), which also gives
  you HTTPS and limits access to your tailnet.
- The phone plays the Mac's audio whenever the Mac output is Multi-Output or
  BlackHole, and stops when it is Headphones: choosing the output is choosing
  where you listen. A dot next to the switch shows the phone's state. Audio
  plays only while the page is on screen and resumes when you come back.
- Live audio is distributed by [mediamtx](https://github.com/bluenviron/mediamtx):
  WebRTC (WHEP) first, a fraction of a second behind, with Low-Latency HLS
  (1–2 seconds) as the fallback. reaper-remote relays the signalling and the
  playlists, so the page and its audio share one origin and one mount.
- mediamtx starts `reaper-remote publish` when the first listener arrives and
  stops it after the last one leaves. It captures the loopback device
  ([BlackHole](https://github.com/ExistentialAudio/BlackHole)) through CoreAudio
  and encodes it to Opus untouched: no gain, limiting or resampling.
- REAPER follows the Mac's system output, so switching the output to a
  Multi-Output Device (headphones + BlackHole) lets you hear the mix locally
  and remotely at the same time.

## Requirements

- macOS with REAPER, its web interface enabled (Preferences → Control/OSC/web → Add → Web browser interface)
- [uv](https://docs.astral.sh/uv/), [mediamtx](https://github.com/bluenviron/mediamtx),
  [ffmpeg](https://ffmpeg.org/) with libopus,
  [SwitchAudioSource](https://github.com/deweller/switchaudio-osx),
  [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)
- [Tailscale](https://tailscale.com/) on the Mac and the phone (for remote access)

```bash
brew install uv mediamtx ffmpeg switchaudio-osx blackhole-2ch go-task
```

## Quick start

```bash
git clone https://github.com/Synforger/reaper-remote.git
cd reaper-remote
task setup                              # uv sync
cp config.example.json config.json      # then fill in your device names
cp mediamtx/mediamtx.example.yml mediamtx/mediamtx.yml   # then set the path to this checkout
mediamtx mediamtx/mediamtx.yml &        # the audio distribution
task run                                # serves http://127.0.0.1:8090/
```

Publish it on your tailnet (path is up to you):

```bash
tailscale serve --bg --set-path=/ext/reaper http://127.0.0.1:8090
```

Then open `https://<your-mac>.<your-tailnet>.ts.net/ext/reaper/` on the phone.

Step-by-step setup (audio routing, the render script, running at login) is in
[`docs/setup/`](docs/setup/README.md).

## Documentation

- Setup: [`docs/setup/`](docs/setup/README.md)
- Configuration and HTTP API: [`docs/reference/`](docs/reference/README.md)
- Troubleshooting: [`docs/troubleshooting/`](docs/troubleshooting/README.md)
- Contributing: [`docs/internals/`](docs/internals/README.md)

## License

Apache-2.0 ([`LICENSE`](LICENSE)). Dependencies are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); vulnerability reports go
through [`SECURITY.md`](SECURITY.md).
