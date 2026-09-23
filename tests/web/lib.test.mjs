import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DB_MIN,
  dbToVolume,
  formatDb,
  parseReply,
  peakToPercent,
  volumeToDb,
  volumeToSlider,
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
