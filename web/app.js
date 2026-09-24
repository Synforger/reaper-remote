// reaper-remote UI. Every URL is relative so the page works wherever it is mounted
// (for example at /ext/reaper/ behind `tailscale serve --set-path`).

import {
  DB_MAX,
  DB_MIN,
  PLAYSTATE,
  dbToVolume,
  formatDb,
  labelStep,
  measureAtFraction,
  measureCount,
  measureRange,
  measureStart,
  nextMeasureStart,
  parseDbInput,
  parseReply,
  peakToPercent,
  previousMeasureStart,
  receiveInterval,
  receiveSnapshot,
  secondsToMeasure,
  volumeToSlider,
} from "./lib.js";
import { drawIcons, setIcon } from "./icons.js";

drawIcons();

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
// The last reported position and when it arrived, so the playhead can move
// smoothly between polls.
let reported = { seconds: 0, at: 0, playing: false };

function renderTransport(t) {
  playstate = t.playstate;
  repeat = t.repeat;
  const playing = t.playstate === PLAYSTATE.PLAYING || t.playstate === PLAYSTATE.RECORDING;
  reported = { seconds: t.seconds, at: performance.now(), playing };
  $("loop").classList.toggle("on", t.repeat);
  const icon = playing ? "pause" : "play";
  if ($("btn-play").dataset.icon !== icon) setIcon($("btn-play"), icon);
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

// -- seek bar -----------------------------------------------------------------
//
// Measures laid out at equal width, regions above them, the playhead on top.
// The region under the playhead is named over the position readout.
// Drag (or tap) anywhere to pick a measure: a bubble names it while the finger
// is down and the jump happens once, on release, so playback does not stutter.
// A tap on a region (or next to a marker) jumps to where it starts, and a long
// press sets the loop (see "gestures" below). The loop points show as a band.
// The layout comes from GET /timeline, which needs
// reaper/reaper-remote-timeline.lua; without it the row stays hidden.

const TIMELINE_REFRESH_MS = 5000;
const DRAG_THRESHOLD_PX = 6;
const MARKER_HIT_PX = 12;
// Extrapolate the playhead at most this far past the last poll.
const PLAYHEAD_LEAD_S = 1;

let timeline = null; // { edges, loop, regions, markers }
let timelineKey = "";
let seekDrag = null; // { startX, moved, target } while a finger is down

function measureX(measure) {
  return `${(measure / measureCount(timeline.edges)) * 100}%`;
}

function secondsX(seconds) {
  return measureX(secondsToMeasure(timeline.edges, seconds));
}

function regionColor(color, i) {
  // REAPER reports custom colours as 0xaarrggbb and 0 when none is set.
  if (color) return `#${(color & 0xffffff).toString(16).padStart(6, "0")}`;
  return i % 2 ? "var(--region-b)" : "var(--region-a)";
}

function renderTimeline() {
  const edges = timeline.edges;
  const count = measureCount(edges);

  const regions = $("regions");
  regions.replaceChildren(
    ...timeline.regions.map((r, i) => {
      const el = document.createElement("div");
      el.className = "region";
      el.style.left = secondsX(r.start);
      el.style.width = `calc(${secondsX(r.end)} - ${secondsX(r.start)})`;
      el.style.background = regionColor(r.color, i);
      el.textContent = r.name;
      el.title = r.name;
      return el;
    }),
    ...timeline.markers.map((m) => {
      const el = document.createElement("div");
      el.className = "marker";
      el.style.left = secondsX(m.pos);
      el.title = m.name;
      return el;
    }),
  );

  // A name that does not fit whole is left out rather than cut; only after
  // layout do the blocks have a width to compare against.
  for (const el of regions.querySelectorAll(".region")) {
    el.classList.remove("narrow");
    el.classList.toggle("narrow", el.scrollWidth > el.clientWidth);
  }

  const ruler = $("ruler");
  const step = labelStep(count, ruler.clientWidth);
  const ticks = [];
  for (let m = 1; m <= count; m += step) {
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.style.left = measureX(m - 1);
    tick.textContent = String(m);
    ticks.push(tick);
  }
  ruler.replaceChildren(...ticks);
  $("timeline").setAttribute("aria-valuemax", String(count));
}

async function loadTimeline() {
  let data;
  try {
    data = await (await request("timeline")).json();
  } catch (e) {
    showError(`Timeline: ${e.message}`);
    return;
  }
  for (const id of ["seek", "btn-prev-measure", "btn-next-measure"]) $(id).hidden = !data.enabled;
  if (!data.enabled) {
    timeline = null;
    $("section").textContent = "";
    return;
  }
  // Rebuild only when the layout changed; the playhead is drawn separately.
  const key = JSON.stringify([data.edges, data.loop, data.regions, data.markers]);
  timeline = { edges: data.edges, loop: data.loop, regions: data.regions, markers: data.markers };
  if (key !== timelineKey && !seekDrag) {
    timelineKey = key;
    renderTimeline();
    renderLoop();
  }
}

function drawPlayhead() {
  if (timeline) {
    const seconds = currentSeconds();
    const measure = secondsToMeasure(timeline.edges, seconds);
    $("playhead").style.left = measureX(measure);
    const region = timeline.regions.find((r) => r.start <= seconds && seconds < r.end);
    const name = region ? region.name : "";
    if ($("section").textContent !== name) $("section").textContent = name;
    $("timeline").setAttribute("aria-valuenow", String(Math.floor(measure) + 1));
  }
  requestAnimationFrame(drawPlayhead);
}

// -- gestures on the bar --
//
// A short press (or a press that starts moving) seeks. Holding still for
// LONG_PRESS_MS instead picks a loop: let go on a region to loop that region,
// or keep holding and slide to cover measures from where the finger went down.
// Either way nothing reaches REAPER until the finger lifts.

const LONG_PRESS_MS = 450;
let loopSettable = false; // GET /loop: the server can set the loop points

function regionAt(x) {
  const width = $("timeline").clientWidth;
  const xOf = (s) => (secondsToMeasure(timeline.edges, s) / measureCount(timeline.edges)) * width;
  const marker = timeline.markers.find((m) => Math.abs(xOf(m.pos) - x) <= MARKER_HIT_PX);
  const region = timeline.regions.find((r) => xOf(r.start) <= x && x < xOf(r.end));
  return { marker, region };
}

function measureUnder(x) {
  return measureAtFraction(timeline.edges, Math.min(1, Math.max(0, x / $("timeline").clientWidth)));
}

// What a short press at `x` (px from the bar's left edge) aims at: a marker or
// a region's start on the region lane, else the measure under the finger.
function seekTarget(x, onRegions) {
  if (onRegions) {
    const { marker, region } = regionAt(x);
    if (marker) return { seconds: marker.pos, label: marker.name || `Marker ${marker.id}` };
    if (region) return { seconds: region.start, label: region.name || `Region ${region.id}` };
  }
  const number = measureUnder(x);
  return { seconds: measureStart(timeline.edges, number), label: String(number) };
}

// What a long press aims at: the region under the finger on the region lane,
// else the measures from `anchor` to the one under the finger.
function loopTarget(x, onRegions, anchor) {
  if (onRegions && anchor === null) {
    const { region } = regionAt(x);
    if (region) {
      return { loop: true, start: region.start, end: region.end, label: `Loop ${region.name}` };
    }
  }
  const r = measureRange(timeline.edges, anchor ?? measureUnder(x), measureUnder(x));
  return { loop: true, start: r.start, end: r.end, label: `Loop ${r.label}` };
}

function showCue(target) {
  const bubble = $("bubble");
  bubble.textContent = target.label;
  if (target.loop) {
    const range = $("range");
    range.style.left = secondsX(target.start);
    range.style.width = `calc(${secondsX(target.end)} - ${secondsX(target.start)})`;
    range.hidden = false;
    $("cue").hidden = true;
    bubble.style.left = `calc((${secondsX(target.start)} + ${secondsX(target.end)}) / 2)`;
  } else {
    $("cue").style.left = secondsX(target.seconds);
    $("cue").hidden = false;
    $("range").hidden = true;
    bubble.style.left = secondsX(target.seconds);
  }
  bubble.hidden = false;
}

function hideCue() {
  $("cue").hidden = true;
  $("range").hidden = true;
  $("bubble").hidden = true;
}

const timelineEl = $("timeline");

timelineEl.addEventListener("pointerdown", (e) => {
  if (!timeline) return;
  timelineEl.setPointerCapture(e.pointerId);
  const x = e.clientX - timelineEl.getBoundingClientRect().left;
  const onRegions = $("regions").contains(e.target);
  const drag = { startX: x, onRegions, moved: false, anchor: null, timer: null };
  drag.target = seekTarget(x, onRegions);
  if (loopSettable) {
    drag.timer = setTimeout(() => {
      drag.timer = null;
      drag.target = loopTarget(x, onRegions, null);
      showCue(drag.target);
    }, LONG_PRESS_MS);
  }
  seekDrag = drag;
  showCue(drag.target);
});

timelineEl.addEventListener("pointermove", (e) => {
  const drag = seekDrag;
  if (!drag) return;
  const x = e.clientX - timelineEl.getBoundingClientRect().left;
  if (!drag.moved && Math.abs(x - drag.startX) < DRAG_THRESHOLD_PX) return;
  drag.moved = true;
  if (drag.target.loop) {
    // Sliding after the long press: measures from where the finger went down.
    drag.anchor ??= measureUnder(drag.startX);
    drag.target = loopTarget(x, drag.onRegions, drag.anchor);
  } else {
    // Moving before the long press: a scrub, wherever it started.
    clearTimeout(drag.timer);
    drag.timer = null;
    drag.target = seekTarget(x, false);
  }
  showCue(drag.target);
});

const endSeek = (commit) => {
  const drag = seekDrag;
  if (!drag) return;
  clearTimeout(drag.timer);
  seekDrag = null;
  hideCue();
  if (!commit) return;
  if (drag.target.loop) setLoop(drag.target.start, drag.target.end);
  else seekTo(drag.target.seconds);
};
timelineEl.addEventListener("pointerup", () => endSeek(true));
timelineEl.addEventListener("pointercancel", () => endSeek(false));

async function setLoop(start, end) {
  try {
    await request("loop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start, end }),
    });
    await Promise.all([loadTimeline(), poll()]);
  } catch (e) {
    showError(`Loop: ${e.message}`);
  }
}

// The loop points as a band on the bar, lit while repeat is on.
function renderLoop() {
  const band = $("loop");
  const loop = timeline?.loop;
  band.hidden = !loop;
  if (!loop) return;
  band.style.left = secondsX(loop.start);
  band.style.width = `calc(${secondsX(loop.end)} - ${secondsX(loop.start)})`;
}

function seekTo(seconds) {
  // Show the jump right away instead of waiting for the next poll.
  reported = { ...reported, seconds, at: performance.now() };
  send(`SET/POS/${seconds.toFixed(6)}`);
}

// The position now: the last report, carried forward while playing.
function currentSeconds() {
  return reported.playing
    ? reported.seconds + Math.min(PLAYHEAD_LEAD_S, (performance.now() - reported.at) / 1000)
    : reported.seconds;
}

$("btn-prev-measure").addEventListener("click", () => {
  if (timeline) seekTo(previousMeasureStart(timeline.edges, currentSeconds()));
});
$("btn-next-measure").addEventListener("click", () => {
  if (timeline) seekTo(nextMeasureStart(timeline.edges, currentSeconds()));
});

// Labels thin out or fill in as the bar changes width (rotation, host resize).
new ResizeObserver(() => timeline && renderTimeline()).observe(timelineEl);

setInterval(() => {
  if (document.visibilityState === "visible") loadTimeline();
}, TIMELINE_REFRESH_MS);

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

  // The dB readout doubles as a text field: tap it, type "-6", "+3" or "-inf".
  const db = document.createElement("span");
  db.className = "db";
  db.setAttribute("role", "button");
  db.title = "Type a value in dB";
  db.addEventListener("click", () => editDb(track.index, db, slider));

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

function editDb(index, db, slider) {
  if (dragging.has(index)) return;
  dragging.add(index); // polling leaves the row alone while the value is typed
  const input = document.createElement("input");
  input.type = "text";
  input.className = "db-input";
  input.value = db.textContent;
  input.enterKeyHint = "done";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Volume (dB)");
  db.replaceChildren(input);
  input.focus();
  input.select();

  const before = db.textContent;
  let done = false;
  const close = (text) => {
    done = true;
    dragging.delete(index);
    db.textContent = text;
  };
  // Enter keeps an invalid value open and marks it; leaving the field (a tap
  // elsewhere, the keyboard closed) drops it instead, so the field never traps
  // the finger.
  const commit = (keepOpenIfInvalid) => {
    if (done) return;
    const volume = parseDbInput(input.value);
    if (volume === null) {
      if (keepOpenIfInvalid) input.classList.add("invalid");
      else close(before);
      return;
    }
    slider.value = String(volumeToSlider(volume));
    close(formatDb(volume));
    reaper(`SET/TRACK/${index}/VOL/${volume.toFixed(6)}`)
      .then(poll)
      .catch((e) => showError(`REAPER: ${e.message}`));
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit(true);
    else if (e.key === "Escape" && !done) close(before);
  });
  input.addEventListener("input", () => input.classList.remove("invalid"));
  input.addEventListener("blur", () => commit(false));
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

// Poll only while the page is on screen.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    startPolling();
    loadTimeline();
    loadDevices().catch((e) => showError(`Output: ${e.message}`));
  } else stopPolling();
});

// Outputs appear and disappear (headphones plugged in or out), so refresh them.
setInterval(() => {
  if (document.visibilityState === "visible") loadDevices().catch(() => {});
}, DEVICE_REFRESH_MS);

// -- listen -------------------------------------------------------------------
//
// The phone plays the Mac's audio whenever the Mac output includes the capture
// device (Multi or BlackHole) and stops when it is Headphones. Phones only let
// audio start from a tap, so a tap on Multi / BlackHole starts it; on opening
// the page with one already selected, playback is attempted and, if the phone
// refuses, waits for that tap.
//
// First choice is WebRTC (WHEP), a fraction of a second behind. If it cannot
// connect, or drops later, the page falls back to Low-Latency HLS (1–2 s
// behind), which plays wherever the browser has native HLS. Both come from
// mediamtx through this app's `whep` and `llhls/` routes.
//
// While on WebRTC the page reports the receive counters every STATS_MS to the
// server log (POST listen-stats), and a fall back to LL-HLS with its reason.

const audio = $("audio");
const WHEP_CONNECT_TIMEOUT_MS = 6000;
const LLHLS_URL = "llhls/index.m3u8";
const STATS_MS = 5000;
const canHls = audio.canPlayType("application/vnd.apple.mpegurl") !== "";

let listening = false;
let pc = null; // RTCPeerConnection while on WebRTC
let session = null; // WHEP session URL, for DELETE on stop
let mode = null; // "webrtc" | "llhls"
let statsTimer = null;

const LISTEN_OUTPUTS = new Set(["multi", "blackhole"]);
const TAP_TO_LISTEN = "tap Multi or BlackHole to listen";

// The dot carries the state as its colour, and the words as its tooltip.
function setListenStatus(state, text) {
  const dot = $("listen-dot");
  dot.dataset.state = state;
  dot.title = `Phone audio: ${text}`;
}

// A play() refused for lack of a tap: give up quietly until the next tap.
function onPlayRefused(e) {
  if (!listening || e?.name !== "NotAllowedError") return;
  stopListening();
  setListenStatus("off", TAP_TO_LISTEN);
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
  if (pc !== peer) {
    // Listening stopped while the offer was in flight: end the new session now.
    const late = res.headers.get("Location");
    if (late) fetch(late, { method: "DELETE" }).catch(() => {});
    throw new Error("stopped");
  }
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
  reportStats(peer);
  // A later drop (network change, the phone locking) falls back to LL-HLS.
  peer.addEventListener("connectionstatechange", () => {
    if (listening && pc === peer && ["failed", "disconnected"].includes(peer.connectionState)) {
      startLlHls("WebRTC dropped");
    }
  });
}

function postStats(body) {
  fetch("listen-stats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => {}); // a lost report must never disturb listening
}

function reportStats(peer) {
  clearInterval(statsTimer);
  let prev = null;
  statsTimer = setInterval(async () => {
    if (pc !== peer) {
      clearInterval(statsTimer);
      return;
    }
    const cur = receiveSnapshot(await peer.getStats(), performance.now());
    if (prev) postStats({ mode: "webrtc", ...receiveInterval(prev, cur) });
    prev = cur;
  }, STATS_MS);
}

function closeWebRtc() {
  clearInterval(statsTimer);
  statsTimer = null;
  if (session) fetch(session, { method: "DELETE" }).catch(() => {});
  if (pc) pc.close();
  pc = null;
  session = null;
}

let llhlsRetried = false;

function startLlHls(reason) {
  closeWebRtc();
  postStats({ mode: "llhls", event: "fallback", reason });
  llhlsRetried = false;
  if (!canHls) {
    stopListening();
    showError(`Audio: ${reason}, and this browser has no native HLS to fall back to.`);
    return;
  }
  mode = "llhls";
  audio.srcObject = null;
  audio.src = LLHLS_URL;
  audio.play().catch(onPlayRefused);
}

function startListening() {
  listening = true;
  mode = "webrtc";
  setListenStatus("connecting", "connecting…");
  // Start playback inside the tap, on a stream that tracks are added to later;
  // phones only allow audio to start from a user gesture.
  const stream = new MediaStream();
  audio.srcObject = stream;
  audio.play().catch(onPlayRefused);
  startWebRtc(stream).catch((e) => listening && startLlHls(e.message));
}

function stopListening() {
  listening = false;
  if (reloadPending) location.reload();
  mode = null;
  setListenStatus("off", "off");
  closeWebRtc();
  audio.pause();
  audio.srcObject = null;
  audio.removeAttribute("src");
  audio.load();
}

// Leaving the page ends the WebRTC session at once, rather than after
// mediamtx notices the silence (about 30 s), so the capture stops sooner.
window.addEventListener("pagehide", () => listening && closeWebRtc());
audio.addEventListener("playing", () => {
  if (!listening) return;
  setListenStatus("live", mode === "webrtc" ? "live over WebRTC" : "live over LL-HLS, 1–2 s behind");
});
audio.addEventListener("waiting", () => {
  if (!listening) return;
  setListenStatus("buffering", "buffering…");
  if (mode === "llhls") postStats({ mode: "llhls", event: "waiting" });
});
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

// Audio plays only while the app is on screen. Going to the background (home
// screen, another app, the lock screen) stops it and ends the WebRTC session;
// coming back resumes it if the Mac output still includes the capture device.
// Folding the host's panel keeps the page visible, so it keeps playing.
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState === "hidden") {
    if (listening) {
      resumeOnVisible = true;
      stopListening();
      setListenStatus("off", "paused while in the background");
    }
    return;
  }
  if (!resumeOnVisible) return;
  resumeOnVisible = false;
  setListenStatus("off", "off");
  try {
    await loadDevices(); // the output may have changed meanwhile
  } catch {
    return;
  }
  // Without a tap the phone may refuse; the dot then waits for one.
  if (!listening && LISTEN_OUTPUTS.has(lastOutput)) startListening();
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
  followOutput(data.current);
}

let autoplayTried = false;
let lastOutput = null; // the Mac output as last reported by the server
let resumeOnVisible = false;

// Keep playback in step with the Mac output when it changes without a tap here
// (another device, the Mac itself, or on opening the page).
function followOutput(current) {
  lastOutput = current;
  if (!LISTEN_OUTPUTS.has(current)) {
    if (listening) stopListening();
  } else if (!listening && !autoplayTried) {
    // Once per page: without a tap the phone will most likely refuse.
    autoplayTried = true;
    startListening();
  }
}

async function setDevice(key) {
  // Decide playback inside the tap, before any await: phones only allow audio
  // to start from within the tap's own event handler.
  autoplayTried = true;
  if (LISTEN_OUTPUTS.has(key)) {
    if (!listening) startListening();
  } else if (listening) {
    stopListening();
  }
  try {
    const res = await request("device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: key }),
    });
    await loadDevices(await res.json());
  } catch (e) {
    showError(`Output: ${e.message}`);
    // The switch failed: follow whatever the output really is.
    loadDevices().catch(() => {});
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
    setIcon(btn, "render");
    btn.disabled = false;
  }
});

// -- self-update ---------------------------------------------------------------
//
// The server reports a fingerprint of its UI files. When it changes (a new
// version was deployed and the server restarted), reload so the page never
// keeps calling routes that no longer exist. Not while listening: that waits
// until Listen is stopped.

const VERSION_CHECK_MS = 30000;
let loadedUi = null;
let reloadPending = false;

async function checkVersion() {
  let ui;
  try {
    ui = (await (await request("version")).json()).ui;
  } catch {
    return; // server restarting or unreachable: try again next time
  }
  if (loadedUi === null) loadedUi = ui;
  else if (ui !== loadedUi) {
    if (listening) reloadPending = true;
    else location.reload();
  }
}

setInterval(() => document.visibilityState === "visible" && checkVersion(), VERSION_CHECK_MS);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") checkVersion();
});

// -- boot ---------------------------------------------------------------------

async function boot() {
  checkVersion();
  startPolling();
  loadTimeline();
  requestAnimationFrame(drawPlayhead);
  // Setting the loop is optional too: without it a long press stays a seek.
  request("loop")
    .then((r) => r.json())
    .then((d) => (loopSettable = d.enabled))
    .catch(() => (loopSettable = false));
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
