// reaper-remote UI. Every URL is relative so the page works wherever it is mounted
// (for example at /ext/reaper/ behind `tailscale serve --set-path`).

import {
  DB_MAX,
  DB_MIN,
  PLAYSTATE,
  dbToVolume,
  formatDb,
  parseReply,
  peakToPercent,
  volumeToSlider,
} from "./lib.js";

// REAPER action IDs (main section).
const ACTION = { PLAY: 1007, PAUSE: 1008, STOP: 1016, GO_TO_START: 40042 };

const POLL_MS = 500;
const FADER_SEND_MS = 60;
const DEVICE_REFRESH_MS = 10000;
const DEVICE_LABELS = { headphones: "Headphones", multi: "Multi", blackhole: "BlackHole" };

const $ = (id) => document.getElementById(id);

// -- errors -------------------------------------------------------------------

function showError(message) {
  const el = $("error");
  el.textContent = message;
  el.hidden = !message;
}

async function request(path, init) {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // Non-JSON error body: keep the status code.
    }
    throw new Error(detail);
  }
  return res;
}

async function reaper(commands) {
  const res = await request(`reaper/_/${commands}`);
  return res.text();
}

// -- transport ----------------------------------------------------------------

let playstate = PLAYSTATE.STOPPED;
let repeat = false;

function renderTransport(t) {
  playstate = t.playstate;
  repeat = t.repeat;
  const playing = t.playstate === PLAYSTATE.PLAYING || t.playstate === PLAYSTATE.RECORDING;
  $("btn-play").textContent = playing ? "⏸" : "▶";
  $("btn-repeat").classList.toggle("on", t.repeat);
  const pos = $("position");
  // With a beats-based timeline both strings are identical; show it once.
  pos.textContent = t.position === t.beats ? t.position : `${t.position}  ${t.beats}`;
  pos.classList.toggle("playing", playing);
}

$("btn-play").addEventListener("click", () => {
  const playing = playstate === PLAYSTATE.PLAYING || playstate === PLAYSTATE.RECORDING;
  send(String(playing ? ACTION.PAUSE : ACTION.PLAY));
});
$("btn-stop").addEventListener("click", () => send(String(ACTION.STOP)));
$("btn-start").addEventListener("click", () => send(String(ACTION.GO_TO_START)));
$("btn-repeat").addEventListener("click", () => send(`SET/REPEAT/${repeat ? 0 : 1}`));

async function send(commands) {
  try {
    await reaper(commands);
    await poll();
  } catch (e) {
    showError(`REAPER: ${e.message}`);
  }
}

// -- tracks -------------------------------------------------------------------

const rows = new Map(); // track index -> { root, slider, db, mute, solo, meter }
const dragging = new Set(); // track indices whose fader the user is holding

function trackRow(track) {
  const root = document.createElement("div");
  root.className = `track${track.index === 0 ? " master" : ""}`;

  const name = document.createElement("span");
  name.className = "name";

  const mute = document.createElement("button");
  mute.className = "mute";
  mute.textContent = "M";
  mute.addEventListener("click", () => send(`SET/TRACK/${track.index}/MUTE/-1`));

  const solo = document.createElement("button");
  solo.className = "solo";
  solo.textContent = "S";
  solo.addEventListener("click", () => send(`SET/TRACK/${track.index}/SOLO/-1`));
  if (track.index === 0) solo.disabled = true;

  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = String(DB_MIN);
  slider.max = String(DB_MAX);
  slider.step = "0.5";
  slider.setAttribute("aria-label", "Volume (dB)");

  const db = document.createElement("span");
  db.className = "db";

  const meter = document.createElement("div");
  meter.className = "meter";

  let lastSent = 0;
  let pending = null;
  const push = () => {
    pending = null;
    lastSent = Date.now();
    const volume = dbToVolume(Number(slider.value));
    db.textContent = formatDb(volume);
    reaper(`SET/TRACK/${track.index}/VOL/${volume.toFixed(6)}`).catch((e) =>
      showError(`REAPER: ${e.message}`),
    );
  };
  slider.addEventListener("pointerdown", () => dragging.add(track.index));
  const release = () => {
    dragging.delete(track.index);
    if (pending) {
      clearTimeout(pending);
      push();
    }
  };
  slider.addEventListener("pointerup", release);
  slider.addEventListener("pointercancel", release);
  slider.addEventListener("change", release);
  slider.addEventListener("input", () => {
    db.textContent = formatDb(dbToVolume(Number(slider.value)));
    const wait = FADER_SEND_MS - (Date.now() - lastSent);
    if (wait <= 0) push();
    else if (!pending) pending = setTimeout(push, wait);
  });

  root.append(name, mute, solo, slider, db, meter);
  return { root, name, slider, db, mute, solo, meter };
}

function renderTracks(tracks) {
  const box = $("tracks");
  const seen = new Set();
  for (const t of tracks) {
    seen.add(t.index);
    let row = rows.get(t.index);
    if (!row) {
      row = trackRow(t);
      rows.set(t.index, row);
    }
    // Keep DOM order equal to REAPER's track order.
    if (box.children[tracks.indexOf(t)] !== row.root) {
      box.insertBefore(row.root, box.children[tracks.indexOf(t)] ?? null);
    }
    row.name.textContent = t.name;
    row.name.title = t.name;
    row.mute.classList.toggle("on", t.muted);
    row.solo.classList.toggle("on", t.soloed);
    if (!dragging.has(t.index)) {
      row.slider.value = String(volumeToSlider(t.volume));
      row.db.textContent = formatDb(t.volume);
    }
    const pct = peakToPercent(t.peakDb);
    row.meter.style.width = `${pct}%`;
    row.meter.classList.toggle("hot", t.peakDb > 0);
  }
  for (const [index, row] of rows) {
    if (!seen.has(index)) {
      row.root.remove();
      rows.delete(index);
    }
  }
}

// -- polling ------------------------------------------------------------------

let polling = null;
let pollingActive = false;

async function poll() {
  const reply = parseReply(await reaper("TRANSPORT;TRACK"));
  if (reply.transport) renderTransport(reply.transport);
  renderTracks(reply.tracks);
  showError("");
}

function startPolling() {
  if (pollingActive) return;
  pollingActive = true;
  const tick = async () => {
    try {
      await poll();
    } catch (e) {
      showError(`REAPER: ${e.message}`);
    }
    // A tick that was in flight when polling stopped must not re-arm the timer.
    if (pollingActive) polling = setTimeout(tick, POLL_MS);
  };
  tick();
}

function stopPolling() {
  pollingActive = false;
  clearTimeout(polling);
  polling = null;
}

// Poll only while the page is on screen; audio keeps playing either way.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    startPolling();
    loadDevices().catch((e) => showError(`Output: ${e.message}`));
  } else stopPolling();
});

// Outputs appear and disappear (headphones plugged in or out), so refresh them.
setInterval(() => {
  if (document.visibilityState === "visible") loadDevices().catch(() => {});
}, DEVICE_REFRESH_MS);

// -- listen -------------------------------------------------------------------
//
// First choice is WebRTC (WHEP), a fraction of a second behind. If it cannot
// connect, or drops later, the page falls back to Low-Latency HLS (1–2 s
// behind), which plays wherever the browser has native HLS. Both come from
// mediamtx through this app's `whep` and `llhls/` routes.

const audio = $("audio");
const WHEP_CONNECT_TIMEOUT_MS = 6000;
const LLHLS_URL = "llhls/index.m3u8";
const canHls = audio.canPlayType("application/vnd.apple.mpegurl") !== "";

let listening = false;
let pc = null; // RTCPeerConnection while on WebRTC
let session = null; // WHEP session URL, for DELETE on stop
let mode = null; // "webrtc" | "llhls"

// The Listen button carries the state as its colour, and the words as its tooltip.
function setListenStatus(state, text) {
  const btn = $("btn-listen");
  btn.dataset.state = state;
  btn.title = `Listen: ${text}`;
}

function waitIceGathering(peer) {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => peer.iceGatheringState === "complete" && resolve();
    peer.addEventListener("icegatheringstatechange", done);
    // Host candidates are enough on a tailnet; do not wait forever for others.
    setTimeout(resolve, 1500);
  });
}

async function startWebRtc(stream) {
  const peer = new RTCPeerConnection();
  pc = peer;
  peer.addTransceiver("audio", { direction: "recvonly" });
  peer.addEventListener("track", (e) => {
    // Browsers do not start playback for tracks added to an already attached
    // stream; attach a stream holding the track and play again. The element was
    // started inside the tap, which lets this later play() through on phones.
    stream.addTrack(e.track);
    audio.srcObject = new MediaStream([e.track]);
    audio.play().catch(() => {});
  });
  await peer.setLocalDescription(await peer.createOffer());
  await waitIceGathering(peer);
  const res = await fetch("whep", {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: peer.localDescription.sdp,
  });
  if (res.status !== 201) throw new Error(`WHEP answered ${res.status}`);
  session = res.headers.get("Location");
  await peer.setRemoteDescription({ type: "answer", sdp: await res.text() });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("WebRTC did not connect")), WHEP_CONNECT_TIMEOUT_MS);
    peer.addEventListener("connectionstatechange", () => {
      if (peer.connectionState === "connected") {
        clearTimeout(timer);
        resolve();
      } else if (peer.connectionState === "failed") {
        clearTimeout(timer);
        reject(new Error("WebRTC connection failed"));
      }
    });
  });
  // A later drop (network change, the phone locking) falls back to LL-HLS.
  peer.addEventListener("connectionstatechange", () => {
    if (listening && pc === peer && ["failed", "disconnected"].includes(peer.connectionState)) {
      startLlHls("WebRTC dropped");
    }
  });
}

function closeWebRtc() {
  if (session) fetch(session, { method: "DELETE" }).catch(() => {});
  if (pc) pc.close();
  pc = null;
  session = null;
}

let llhlsRetried = false;

function startLlHls(reason) {
  closeWebRtc();
  llhlsRetried = false;
  if (!canHls) {
    stopListening();
    showError(`Audio: ${reason}, and this browser has no native HLS to fall back to.`);
    return;
  }
  mode = "llhls";
  audio.srcObject = null;
  audio.src = LLHLS_URL;
  audio.play().catch(() => {
    // Outside the tap, a phone may refuse to start playback: ask for one more.
    setListenStatus("buffering", "tap Listen again to resume");
    listening = false;
  });
}

function startListening() {
  listening = true;
  mode = "webrtc";
  setListenStatus("connecting", "connecting…");
  // Start playback inside the tap, on a stream that tracks are added to later;
  // phones only allow audio to start from a user gesture.
  const stream = new MediaStream();
  audio.srcObject = stream;
  audio.play().catch(() => {});
  startWebRtc(stream).catch((e) => listening && startLlHls(e.message));
}

function stopListening() {
  listening = false;
  mode = null;
  setListenStatus("off", "off");
  closeWebRtc();
  audio.pause();
  audio.srcObject = null;
  audio.removeAttribute("src");
  audio.load();
}

$("btn-listen").addEventListener("click", () => (listening ? stopListening() : startListening()));
// Leaving the page ends the WebRTC session at once, rather than after
// mediamtx notices the silence (about 30 s), so the capture stops sooner.
window.addEventListener("pagehide", () => listening && closeWebRtc());
audio.addEventListener("playing", () => {
  if (!listening) return;
  setListenStatus("live", mode === "webrtc" ? "live over WebRTC" : "live over LL-HLS, 1–2 s behind");
});
audio.addEventListener("waiting", () => listening && setListenStatus("buffering", "buffering…"));
audio.addEventListener("error", () => {
  if (!listening || mode !== "llhls") return;
  if (!llhlsRetried) {
    // A player can fail on a stream that has only just started; try once more.
    llhlsRetried = true;
    setTimeout(() => {
      if (!listening) return;
      audio.src = LLHLS_URL;
      audio.play().catch(() => {});
    }, 1000);
    return;
  }
  stopListening();
  showError("Audio stream failed. Is mediamtx running, and the Mac output routed to the capture device?");
});

// -- output device ------------------------------------------------------------

async function loadDevices(state) {
  const data = state ?? (await (await request("device")).json());
  const box = $("devices");
  box.replaceChildren(
    ...data.options.map((key) => {
      const b = document.createElement("button");
      b.textContent = DEVICE_LABELS[key] ?? key;
      b.classList.toggle("on", data.current === key);
      // An output such as a headphone jack exists only while something is plugged in.
      b.disabled = !data.available.includes(key);
      b.title = b.disabled ? `${DEVICE_LABELS[key] ?? key}: not connected` : "";
      b.addEventListener("click", () => setDevice(key));
      return b;
    }),
  );
  box.hidden = data.options.length === 0;
}

async function setDevice(key) {
  try {
    const res = await request("device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: key }),
    });
    await loadDevices(await res.json());
  } catch (e) {
    showError(`Output: ${e.message}`);
  }
}

// -- render -------------------------------------------------------------------

$("btn-render").addEventListener("click", async () => {
  const btn = $("btn-render");
  btn.disabled = true;
  btn.textContent = "…";
  try {
    const data = await (await request("render", { method: "POST" })).json();
    btn.title = `Rendered: ${data.name}`;
    const player = $("render-audio");
    player.src = data.url;
    player.hidden = false;
  } catch (e) {
    showError(`Render: ${e.message}`);
  } finally {
    btn.textContent = "⤓";
    btn.disabled = false;
  }
});

// -- boot ---------------------------------------------------------------------

async function boot() {
  startPolling();
  try {
    await loadDevices();
  } catch (e) {
    showError(`Output: ${e.message}`);
  }
  // Render is optional: show the button only when the server has it configured.
  try {
    $("btn-render").hidden = !(await (await request("render")).json()).enabled;
  } catch {
    $("btn-render").hidden = true;
  }
}

boot();
