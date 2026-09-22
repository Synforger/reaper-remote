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
