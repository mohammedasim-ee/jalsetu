// Frontend unit tests (pure helpers). Run: node --test static/js/
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./lib.js");

test("escapes HTML so user text can't run as code", () => {
  assert.equal(L.esc('<img src=x onerror="a()">&'), "&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;");
  assert.equal(L.esc(null), "");
});

test("number formatting uses Indian grouping and a real minus sign", () => {
  assert.equal(L.nf(1234567), "12,34,567");
  assert.equal(L.nf(-48.4, 1), "−48.4");
  assert.equal(L.signed(5), "+5");
  assert.equal(L.nf(NaN), "–");
  assert.equal(L.inr(8400), "₹8,400");
});

test("dates in all three precisions", () => {
  assert.equal(L.fdate("2026-09-28"), "28 Sep 2026");
  assert.equal(L.fdate("2026-08"), "Aug 2026");
  assert.equal(L.fdate("2024"), "2024");
  assert.equal(L.fdate(""), "–");
});

test("relative time", () => {
  assert.equal(L.ago(1000, 1030), "just now");
  assert.equal(L.ago(0, 7200), "2 h ago");
  assert.equal(L.ago(0, 3 * 86400), "3 d ago");
});

test("season features match the server's definitions", () => {
  const clim = Array(12).fill(10);
  const yr = [10, 10, 5, 5, 5, 5, 5, 10, 10, 10, 10, 10];
  const f = L.seasonFeatures(yr, Array(12).fill(10), clim);
  assert.equal(f.jun_dep_pct, -50);
  assert.equal(f.jul_dep_pct, -50);
  assert.equal(f.premonsoon_dep_pct, -50);
  assert.equal(f.prev_ond_dep_pct, 0);
  assert.equal(f.jjas_dep_pct, -25);
});

test("status and level classes", () => {
  assert.equal(L.levelClass("HIGH"), "p-crit");
  assert.equal(L.levelClass("WATCH"), "p-warn");
  assert.equal(L.statusLabel("UNDER_REVIEW"), "Under review");
  assert.equal(L.statusClass("VERIFIED"), "p-ok");
});

test("water-quality explanations cover each outcome", () => {
  assert.match(L.qualityExplanation({ status: "ok", kind: "max", acceptable: 500 }), /acceptable/);
  assert.match(L.qualityExplanation({ status: "high", kind: "max", acceptable: 500, permissible: 2000 }), /permissible limit \(2000\)/);
  assert.match(L.qualityExplanation({ status: "unsafe", kind: "max", acceptable: 45, permissible: null }), /no relaxation/);
  assert.match(L.qualityExplanation({ status: "unsafe", kind: "zero", acceptable: 0 }), /zero/);
  assert.match(L.qualityExplanation({ status: "unsafe", kind: "range", acceptable: [6.5, 8.5] }), /6.5–8.5/);
});

test("chart scale and nice max", () => {
  const s = L.scale(0, 100, 0, 200);
  assert.equal(s(50), 100);
  assert.equal(L.niceMax(873), 1000);
  assert.equal(L.niceMax(1100), 1200);
  assert.equal(L.niceMax(250), 250);
  assert.equal(L.niceMax(0), 1);
});

test("provenance line", () => {
  assert.equal(L.provText({ source: "IMD", as_of: "2026-09-28", period: "1 Jun – 28 Sep 2026" }), "IMD · period 1 Jun – 28 Sep 2026 · data as of 28 Sep 2026");
});
