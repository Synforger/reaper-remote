import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DB_MIN,
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
  projectLabel,
  receiveInterval,
  receiveSnapshot,
  secondsToMeasure,
  volumeToDb,
  volumeToSlider,
  withStereoOpus,
} from "../../web/lib.js";

test("parseReply reads transport and tracks", () => {
  const reply = [
    "TRANSPORT\t1\t12.500000\t1\t0:12.500\t5.2.00",
    "TRACK\t0\tMASTER\t512\t1.000000\t0.000000\t-120\t-120\t1.0\t3\t0\t0\t1\t0",
    "TRACK\t1\tDrums\t24\t0.501187\t-0.25\t-65\t-70\t1.0\t3\t0\t0\t1\t0x01ff0000",
    "",
  ].join("\n");
  const r = parseReply(reply);
  assert.deepEqual(r.transport, {
    playstate: 1,
    seconds: 12.5,
    repeat: true,
    position: "0:12.500",
    beats: "5.2.00",
  });
  assert.equal(r.tracks.length, 2);
  assert.equal(r.tracks[0].name, "MASTER");
  assert.equal(r.tracks[0].muted, false);
  const drums = r.tracks[1];
  assert.equal(drums.index, 1);
  assert.equal(drums.muted, true); // 8
  assert.equal(drums.soloed, true); // 16
  assert.equal(drums.pan, -0.25);
  assert.equal(drums.peakDb, -6.5);
});

test("parseReply ignores unknown lines", () => {
  const r = parseReply("NTRACK\t4\nCMDSTATE\t1007\t1\n");
  assert.equal(r.transport, null);
  assert.deepEqual(r.tracks, []);
});

test("volume and dB round-trip", () => {
  assert.equal(volumeToDb(1), 0);
  assert.equal(volumeToDb(0), -Infinity);
  assert.ok(Math.abs(volumeToDb(dbToVolume(-6)) + 6) < 1e-9);
  assert.equal(dbToVolume(DB_MIN), 0);
});

test("slider clamps to the fader range", () => {
  assert.equal(volumeToSlider(0), DB_MIN);
  assert.equal(volumeToSlider(1), 0);
  assert.equal(volumeToSlider(100), 12);
});

test("formatDb", () => {
  assert.equal(formatDb(0), "-inf");
  assert.equal(formatDb(1), "0.0");
  assert.equal(formatDb(2), "+6.0");
  assert.equal(formatDb(0.5), "-6.0");
});

test("peakToPercent", () => {
  assert.equal(peakToPercent(-120), 0);
  assert.equal(peakToPercent(0), 100);
  assert.equal(peakToPercent(6), 100);
  assert.equal(peakToPercent(-30), 50);
});

test("parseDbInput reads typed dB values", () => {
  assert.equal(parseDbInput("0"), 1);
  assert.ok(Math.abs(parseDbInput("-6") - dbToVolume(-6)) < 1e-12);
  assert.ok(Math.abs(parseDbInput("+3.5 dB") - dbToVolume(3.5)) < 1e-12);
  assert.ok(Math.abs(parseDbInput(".5") - dbToVolume(0.5)) < 1e-12);
  assert.equal(parseDbInput("-inf"), 0);
  assert.equal(parseDbInput("-90"), 0); // at or below the fader floor is silence
  assert.equal(parseDbInput("40"), dbToVolume(12)); // clamped to the fader top
  for (const bad of ["", "abc", "--3", "1e3", "3-"]) assert.equal(parseDbInput(bad), null, bad);
});

// Four measures; the last one is slower (3 s instead of 2 s).
const EDGES = [0, 2, 4, 6, 9];

test("secondsToMeasure maps through uneven measures and clamps", () => {
  assert.equal(measureCount(EDGES), 4);
  assert.equal(secondsToMeasure(EDGES, -1), 0);
  assert.equal(secondsToMeasure(EDGES, 0), 0);
  assert.equal(secondsToMeasure(EDGES, 3), 1.5);
  assert.equal(secondsToMeasure(EDGES, 7.5), 3.5);
  assert.equal(secondsToMeasure(EDGES, 9), 4);
  assert.equal(secondsToMeasure(EDGES, 99), 4);
});

test("measureStart and measureAtFraction pick whole measures", () => {
  assert.equal(measureStart(EDGES, 1), 0);
  assert.equal(measureStart(EDGES, 4), 6);
  assert.equal(measureStart(EDGES, 9), 6); // past the end: the last measure
  assert.equal(measureAtFraction(EDGES, 0), 1);
  assert.equal(measureAtFraction(EDGES, 0.26), 2);
  assert.equal(measureAtFraction(EDGES, 1), 4);
});

test("previous measure goes to the current start first, DAW style", () => {
  assert.equal(previousMeasureStart(EDGES, 5), 4); // mid measure 3 -> its start
  assert.equal(previousMeasureStart(EDGES, 4), 2); // at its start -> measure 2
  assert.equal(previousMeasureStart(EDGES, 4.02), 2); // within the slack counts as at the start
  assert.equal(previousMeasureStart(EDGES, 0), 0);
});

test("next measure never moves backwards", () => {
  assert.equal(nextMeasureStart(EDGES, 0), 2);
  assert.equal(nextMeasureStart(EDGES, 5.9), 6);
  assert.equal(nextMeasureStart(EDGES, 7), 9); // inside the last measure -> the end
  assert.equal(nextMeasureStart(EDGES, 9), 9);
});

test("labelStep keeps labels apart", () => {
  assert.equal(labelStep(8, 320), 1); // 40 px per measure
  assert.equal(labelStep(94, 300), 16); // about 3 px per measure
  assert.equal(labelStep(4000, 100), 256);
});

test("measureRange spans whole measures in either direction", () => {
  assert.deepEqual(measureRange(EDGES, 2, 3), { start: 2, end: 6, label: "2–3" });
  assert.deepEqual(measureRange(EDGES, 3, 2), { start: 2, end: 6, label: "2–3" });
  assert.deepEqual(measureRange(EDGES, 4, 4), { start: 6, end: 9, label: "4" });
  assert.deepEqual(measureRange(EDGES, 0, 99), { start: 0, end: 9, label: "1–4" });
});

test("receiveSnapshot picks the audio receive counters and the round trip", () => {
  const report = new Map([
    ["a", { type: "inbound-rtp", kind: "audio", packetsReceived: 500, packetsLost: 4, jitter: 0.012,
            concealedSamples: 960, totalSamplesReceived: 480000, concealmentEvents: 2, packetsDiscarded: 3,
            jitterBufferDelay: 43200, jitterBufferEmittedCount: 480000 }],
    ["b", { type: "candidate-pair", nominated: true, currentRoundTripTime: 0.041 }],
    ["c", { type: "candidate-pair", nominated: false, currentRoundTripTime: 0.9 }],
    ["d", { type: "inbound-rtp", kind: "video", packetsReceived: 9999 }],
  ]);
  const s = receiveSnapshot(report, 1000);
  assert.equal(s.received, 500);
  assert.equal(s.lost, 4);
  assert.equal(s.discarded, 3);
  assert.equal(s.rtt, 0.041);
});

test("receiveInterval reports loss, concealment and buffer per interval", () => {
  const prev = { at: 0, received: 1000, lost: 10, jitter: 0.01, concealed: 0, samples: 480000,
                 events: 3, discarded: 1, delay: 43200, emitted: 480000, rtt: 0.04 };
  const cur = { at: 5000, received: 1245, lost: 15, jitter: 0.0183, concealed: 4800, samples: 720000,
                events: 5, discarded: 4, delay: 64800, emitted: 720000, rtt: 0.052 };
  assert.deepEqual(receiveInterval(prev, cur), {
    seconds: 5,
    received: 245,
    lost: 5,
    loss_pct: 2,
    discarded: 3,
    jitter_ms: 18.3,
    concealed_pct: 2,
    concealment_events: 2,
    buffer_ms: 90,
    rtt_ms: 52,
  });
});

test("receiveInterval stays finite with nothing received", () => {
  const snap = { at: 0, received: 0, lost: 0, jitter: 0, concealed: 0, samples: 0, events: 0,
                 discarded: 0, delay: 0, emitted: 0, rtt: null };
  const r = receiveInterval(snap, { ...snap, at: 5000 });
  assert.equal(r.loss_pct, 0);
  assert.equal(r.concealed_pct, 0);
  assert.equal(r.buffer_ms, null);
  assert.equal(r.rtt_ms, null);
});

test("withStereoOpus asks for stereo on every Opus payload and nothing else", () => {
  const sdp = [
    "v=0",
    "m=audio 9 UDP/TLS/RTP/SAVPF 111 63 9",
    "a=rtpmap:111 opus/48000/2",
    "a=rtcp-fb:111 transport-cc",
    "a=fmtp:111 minptime=10;useinbandfec=1",
    "a=rtpmap:63 red/48000/2",
    "a=fmtp:63 111/111",
    "a=rtpmap:9 G722/8000",
    "",
  ].join("\r\n");
  const out = withStereoOpus(sdp).split("\r\n");
  assert.ok(out.includes("a=fmtp:111 minptime=10;useinbandfec=1;stereo=1;sprop-stereo=1"));
  assert.ok(out.includes("a=fmtp:63 111/111")); // not Opus: untouched
  assert.equal(out.length, sdp.split("\r\n").length);
});

test("withStereoOpus replaces an existing stereo choice and adds a missing fmtp", () => {
  const mono = "a=rtpmap:96 opus/48000/2\na=fmtp:96 stereo=0;useinbandfec=1\n";
  assert.equal(withStereoOpus(mono), "a=rtpmap:96 opus/48000/2\na=fmtp:96 useinbandfec=1;stereo=1;sprop-stereo=1\n");
  const bare = "a=rtpmap:96 opus/48000/2\na=sendrecv\n";
  assert.equal(withStereoOpus(bare), "a=rtpmap:96 opus/48000/2\na=fmtp:96 stereo=1;sprop-stereo=1\na=sendrecv\n");
  assert.equal(withStereoOpus(withStereoOpus(mono)), withStereoOpus(mono)); // idempotent
});

test("projectLabel names untitled tabs and marks unsaved ones", () => {
  assert.equal(projectLabel({ name: "1.RPP", dirty: false }), "1.RPP");
  assert.equal(projectLabel({ name: "2.RPP", dirty: true }), "2.RPP •");
  assert.equal(projectLabel({ name: "", dirty: true }), "(untitled) •");
});
