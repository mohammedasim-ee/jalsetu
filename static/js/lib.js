/* JalSetu pure helpers (no DOM). Tested with node: node --test static/js/lib.test.js */
(function (root) {
  "use strict";
  const MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function nf(n, d = 0) {
    if (n === null || n === undefined || !isFinite(n)) return "–";
    const s = Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
    return s.replace(/^-/, "−");
  }
  function signed(n, d = 0) {
    if (n === null || n === undefined || !isFinite(n)) return "–";
    return (n > 0 ? "+" : "") + nf(n, d);
  }
  function inr(n) { return "₹" + nf(n, 0); }
  /** "2026-09-28" -> "28 Sep 2026"; "2026-08" -> "Aug 2026"; "2024" -> "2024"; epoch seconds -> date */
  function fdate(v) {
    if (v === null || v === undefined || v === "") return "–";
    if (typeof v === "number") { const d = new Date(v * 1000); return `${d.getDate()} ${MON3[d.getMonth()]} ${d.getFullYear()}`; }
    const p = String(v).split("-").map(Number);
    if (p.length === 1) return String(p[0]);
    if (p.length === 2) return `${MON3[p[1] - 1]} ${p[0]}`;
    return `${p[2]} ${MON3[p[1] - 1]} ${p[0]}`;
  }
  function ago(sec, now = Date.now() / 1000) {
    const s = Math.max(0, now - sec);
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }
  function departurePct(actual, normal) { return normal > 0 ? (actual - normal) / normal * 100 : 0; }

  /** Model inputs for a year from 12 monthly values, the previous year's 12, and the 12-month climatology. */
  function seasonFeatures(year, prev, clim) {
    const sum = (a, i, j) => a.slice(i, j).reduce((x, y) => x + y, 0);
    return {
      jun_dep_pct: departurePct(year[5], clim[5]),
      jul_dep_pct: departurePct(year[6], clim[6]),
      premonsoon_dep_pct: departurePct(sum(year, 2, 5), sum(clim, 2, 5)),
      prev_ond_dep_pct: prev ? departurePct(sum(prev, 9, 12), sum(clim, 9, 12)) : 0,
      jjas_dep_pct: departurePct(sum(year, 5, 9), sum(clim, 5, 9)),
    };
  }
  function levelClass(level) {
    return { LOW: "p-ok", MODERATE: "p-warn", HIGH: "p-crit", CRITICAL: "p-crit", ALERT: "p-crit", WARNING: "p-crit", WATCH: "p-warn" }[level] || "p-idle";
  }
  const STATUS = { SUBMITTED: "Submitted", UNDER_REVIEW: "Under review", VERIFIED: "Verified", RESOLVED: "Resolved", REJECTED: "Rejected" };
  function statusLabel(s) { return STATUS[s] || s; }
  function statusClass(s) { return { VERIFIED: "p-ok", RESOLVED: "p-ok", UNDER_REVIEW: "p-warn", REJECTED: "p-crit" }[s] || "p-idle"; }
  /** Plain-language explanation for one IS 10500 result row. */
  function qualityExplanation(r) {
    const lim = r.kind === "range" ? `${r.acceptable[0]}–${r.acceptable[1]}` : r.acceptable;
    if (r.status === "ok") return r.kind === "zero" ? "None detected, as required." : `Within the acceptable limit (${lim}).`;
    if (r.status === "high") return `Above the acceptable limit (${lim}) but within the permissible limit (${r.permissible}), allowed only when no better source exists.`;
    if (r.status === "invalid") return "Not a possible value; check the number.";
    if (r.kind === "zero") return "Must be zero in drinking water; any detection fails the standard.";
    if (r.kind === "range") return `Outside the required range ${lim}.`;
    return r.permissible === null || r.permissible === undefined ? `Above ${lim}; the standard allows no relaxation.` : `Above the permissible limit (${r.permissible}).`;
  }
  /** Linear scale helper for charts. */
  function scale(d0, d1, r0, r1) { return v => d1 === d0 ? r0 : r0 + (v - d0) / (d1 - d0) * (r1 - r0); }
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const s of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (s * p >= v) return +(s * p).toPrecision(12);
    return 10 * p;
  }
  function provText(o) {
    const parts = [];
    if (o.source) parts.push(o.source);
    if (o.period) parts.push("period " + o.period);
    if (o.as_of) parts.push("data as of " + fdate(o.as_of));
    if (o.retrieved) parts.push("retrieved " + fdate(o.retrieved));
    return parts.join(" · ");
  }

  const L = { MON3, esc, nf, signed, inr, fdate, ago, departurePct, seasonFeatures, levelClass, statusLabel, statusClass, qualityExplanation, scale, niceMax, provText };
  if (typeof module !== "undefined" && module.exports) module.exports = L; else root.JL = L;
})(typeof window !== "undefined" ? window : globalThis);
