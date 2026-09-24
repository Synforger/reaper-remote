// Pure helpers for the REAPER web API: response parsing and volume math.
// No DOM access here, so the same file runs in the browser and under `node --test`.

export const PLAYSTATE = { STOPPED: 0, PLAYING: 1, PAUSED: 2, RECORDING: 5, RECORD_PAUSED: 6 };

export const TRACK_FLAG = { MUTED: 8, SOLOED: 16 };

// Fader range in dB. The bottom of the slider means -inf (volume 0).
export const DB_MIN = -60;
export const DB_MAX = 12;

// Parse a REAPER reply (lines of tab-separated tokens) into transport + tracks.
export function parseReply(text) {
  const out = { transport: null, tracks: [], repeat: null };
  for (const line of text.split("\n")) {
    const tok = line.split("\t");
    switch (tok[0]) {
      case "TRANSPORT":
        out.transport = {
          playstate: Number(tok[1]),
          seconds: Number(tok[2]),
          repeat: Number(tok[3]) !== 0,
          position: tok[4] ?? "",
          beats: tok[5] ?? "",
        };
        break;
      case "TRACK": {
        const flags = Number(tok[3]);
        out.tracks.push({
          index: Number(tok[1]),
          name: tok[2],
          flags,
          muted: (flags & TRACK_FLAG.MUTED) !== 0,
          soloed: (flags & TRACK_FLAG.SOLOED) !== 0,
          volume: Number(tok[4]),
          pan: Number(tok[5]),
          peakDb: Number(tok[6]) / 10,
        });
        break;
      }
      case "GET/REPEAT":
        out.repeat = Number(tok[1]) !== 0;
        break;
      default:
        break;
    }
  }
  return out;
}

export function volumeToDb(volume) {
  if (!(volume > 0)) return -Infinity;
  return 20 * Math.log10(volume);
}

export function dbToVolume(db) {
  if (!Number.isFinite(db) || db <= DB_MIN) return 0;
  return 10 ** (db / 20);
}

// Slider position (DB_MIN..DB_MAX) for a REAPER volume, clamped to the fader range.
export function volumeToSlider(volume) {
  const db = volumeToDb(volume);
  if (db === -Infinity) return DB_MIN;
  return Math.min(DB_MAX, Math.max(DB_MIN, db));
}

export function formatDb(volume) {
  const db = volumeToDb(volume);
  if (db === -Infinity || db <= DB_MIN) return "-inf";
  return `${db > 0 ? "+" : ""}${db.toFixed(1)}`;
}

// Meter width in percent for a peak in dB (DB_MIN -> 0 %, 0 dB -> 100 %).
export function peakToPercent(peakDb) {
  if (!Number.isFinite(peakDb) || peakDb <= DB_MIN) return 0;
  return Math.min(100, ((peakDb - DB_MIN) / -DB_MIN) * 100);
}

// A typed fader value: "-6", "+3.5", "0", "-inf" (or anything at or below
// DB_MIN) -> REAPER volume, clamped to DB_MAX. null when it is not a number.
export function parseDbInput(text) {
  const s = String(text).trim().toLowerCase().replace(/db$/, "").trim();
  if (s === "-inf" || s === "inf" || s === "-∞") return 0;
  if (!/^[+-]?(\d+(\.\d*)?|\.\d+)$/.test(s)) return null;
  return dbToVolume(Math.min(DB_MAX, Number(s)));
}

// -- timeline -------------------------------------------------------------------
//
// `edges` come from GET /timeline: edges[i] and edges[i + 1] (seconds) bound
// measure i + 1. The seek bar gives every measure the same width, so a
// position is drawn at its measure index plus the fraction of that measure.

export function measureCount(edges) {
  return edges.length - 1;
}

// Seconds -> position in measures from the start (0 = start of measure 1),
// clamped to the timeline.
export function secondsToMeasure(edges, seconds) {
  const n = measureCount(edges);
  if (!(seconds > edges[0])) return 0;
  if (seconds >= edges[n]) return n;
  let lo = 0;
  let hi = n; // edges[lo] <= seconds < edges[hi]
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (edges[mid] <= seconds) lo = mid;
    else hi = mid;
  }
  return lo + (seconds - edges[lo]) / (edges[lo + 1] - edges[lo]);
}

// The start (seconds) of measure `number` (1-based), clamped to the timeline.
export function measureStart(edges, number) {
  const i = Math.min(measureCount(edges) - 1, Math.max(0, Math.round(number) - 1));
  return edges[i];
}

// The measure number (1-based) under a fraction 0..1 of the bar's width.
export function measureAtFraction(edges, fraction) {
  const n = measureCount(edges);
  return Math.min(n, Math.max(1, Math.floor(fraction * n) + 1));
}

// The span of measures a..b (1-based, either order, both included), in seconds.
export function measureRange(edges, a, b) {
  const n = measureCount(edges);
  const first = Math.min(n, Math.max(1, Math.min(a, b)));
  const last = Math.min(n, Math.max(1, Math.max(a, b)));
  return {
    start: edges[first - 1],
    end: edges[last],
    label: first === last ? String(first) : `${first}–${last}`,
  };
}

// Where "previous measure" goes, DAW style: back to the start of the current
// measure, or one further when already (nearly) there.
export function previousMeasureStart(edges, seconds, slack = 0.05) {
  const m = secondsToMeasure(edges, seconds);
  const current = Math.floor(m);
  const into = m - current;
  const target = into * (edges[current + 1] - edges[current]) > slack ? current : current - 1;
  return edges[Math.max(0, target)];
}

// Where "next measure" goes: the start of the following measure, or the end of
// the timeline from inside the last one.
export function nextMeasureStart(edges, seconds) {
  const n = measureCount(edges);
  return edges[Math.min(n, Math.floor(secondsToMeasure(edges, seconds)) + 1)];
}

// Label every `step` measures (1, 1+step, ...) so labels are at least
// `minPx` apart on a bar `widthPx` wide.
export function labelStep(count, widthPx, minPx = 28) {
  const perMeasure = widthPx / Math.max(1, count);
  for (const step of [1, 2, 4, 8, 16, 32, 64, 128]) {
    if (perMeasure * step >= minPx) return step;
  }
  return 256;
}

// -- listening stats ----------------------------------------------------------
//
// While the phone listens over WebRTC, the page samples the browser's own
// receive counters and reports each interval, so choppy audio can be told
// apart: packets lost on the way, or packets arriving unevenly.

// The counters that matter, from an RTCStatsReport (or any iterable of stats).
export function receiveSnapshot(report, at) {
  const snap = {
    at,
    received: 0,
    lost: 0,
    jitter: 0,
    concealed: 0,
    samples: 0,
    events: 0,
    delay: 0,
    emitted: 0,
    rtt: null,
  };
  for (const s of report.values ? report.values() : report) {
    if (s.type === "inbound-rtp" && s.kind === "audio") {
      snap.received = s.packetsReceived ?? 0;
      snap.lost = s.packetsLost ?? 0;
      snap.jitter = s.jitter ?? 0;
      snap.concealed = s.concealedSamples ?? 0;
      snap.samples = s.totalSamplesReceived ?? 0;
      snap.events = s.concealmentEvents ?? 0;
      snap.delay = s.jitterBufferDelay ?? 0;
      snap.emitted = s.jitterBufferEmittedCount ?? 0;
    } else if (s.type === "candidate-pair" && s.nominated && s.currentRoundTripTime != null) {
      snap.rtt = s.currentRoundTripTime;
    }
  }
  return snap;
}

// What happened between two snapshots. Jitter and round trip are the latest
// values; the rest are per interval.
export function receiveInterval(prev, cur) {
  const received = cur.received - prev.received;
  const lost = Math.max(0, cur.lost - prev.lost);
  const samples = cur.samples - prev.samples;
  const emitted = cur.emitted - prev.emitted;
  const round = (x, digits = 1) => Math.round(x * 10 ** digits) / 10 ** digits;
  return {
    seconds: round((cur.at - prev.at) / 1000),
    received,
    lost,
    loss_pct: received + lost > 0 ? round((lost / (received + lost)) * 100, 2) : 0,
    jitter_ms: round(cur.jitter * 1000),
    concealed_pct: samples > 0 ? round(((cur.concealed - prev.concealed) / samples) * 100, 2) : 0,
    concealment_events: cur.events - prev.events,
    buffer_ms: emitted > 0 ? round(((cur.delay - prev.delay) / emitted) * 1000) : null,
    rtt_ms: cur.rtt == null ? null : round(cur.rtt * 1000),
  };
}
