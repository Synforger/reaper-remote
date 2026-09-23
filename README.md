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
                                               ├─ /reaper/_/…  ─▶ REAPER web interface (127.0.0.1:8080)
                                               ├─ /stream.ogg  ◀─ ffmpeg ◀─ BlackHole 2ch ◀─ Mac output
                                               ├─ /hls/…       ◀─ ffmpeg ◀─ (same capture, for HLS players)
                                               ├─ /device      ─▶ SwitchAudioSource (Mac system output)
                                               └─ /render      ─▶ REAPER action (reaper/reaper-remote-render.lua)
```

- The server binds to loopback only. Reaching it from the phone is left to
  [Tailscale Serve](https://tailscale.com/kb/1312/serve), which also gives
  you HTTPS and limits access to your tailnet.
- Audio is captured from a loopback device ([BlackHole](https://github.com/ExistentialAudio/BlackHole))
  and encoded only while someone is listening, by one encoder shared among all
  listeners. Browsers with native HLS (Safari on iOS and macOS, recent Chrome)
  get AAC over HLS, 4–8 seconds behind; others get Ogg/Opus, 1–3 seconds behind.
- REAPER follows the Mac's system output, so switching the output to a
  Multi-Output Device (headphones + BlackHole) lets you hear the mix locally
  and remotely at the same time.

## Requirements

- macOS with REAPER, its web interface enabled (Preferences → Control/OSC/web → Add → Web browser interface)
- [uv](https://docs.astral.sh/uv/), [ffmpeg](https://ffmpeg.org/) with libopus,
  [SwitchAudioSource](https://github.com/deweller/switchaudio-osx),
  [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole)
- [Tailscale](https://tailscale.com/) on the Mac and the phone (for remote access)

```bash
brew install uv ffmpeg switchaudio-osx blackhole-2ch go-task
```

## Quick start

```bash
git clone https://github.com/Synforger/reaper-remote.git
cd reaper-remote
task setup                              # uv sync
cp config.example.json config.json      # then fill in your device names
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
