# Roadmap — Synforger/reaper-remote

> A personal project. This page says what works today and what is not planned.

## Works today

- Transport: play / pause / stop / go to start / repeat, with the current position
- Per-track fader (dB), mute and solo, with a peak meter
- Live audio of the Mac's output through mediamtx: WebRTC first (well under a second behind), Low-Latency HLS as the fallback; captured only while someone listens, never altered
- Switching the Mac's system output between three configured devices
- One-tap render of the time selection (or the whole project), playable in the page
- Runs as an iframe under any path prefix (all URLs are relative)

## Planned

- Nothing committed yet.

## Not planned

- Authentication inside the server: access control is Tailscale's job (see [SECURITY.md](SECURITY.md))
- Windows / Linux: output switching and capture use macOS-only tools
- A replacement for REAPER's own web interface pages: this is a small remote, not a full control surface

## Bug reports / feature requests

- Security issues: [SECURITY.md](SECURITY.md)
- Everything else: GitHub Issues (pull requests welcome). Responses are best effort.
