/* JalSetu frontend. Talks only to the JalSetu API on the same origin; no keys or secrets in this file. */
"use strict";
const { esc, nf, signed, inr, fdate, ago, levelClass, statusLabel, statusClass, qualityExplanation, scale, niceMax, provText, seasonFeatures, MON3 } = window.JL;
const $ = id => document.getElementById(id);
const GH = "https://github.com/mohammedasim-ee/jalsetu/blob/main/";
const S = { user: null, token: null, meta: null, health: null, rain: null, monthly: null, reports: [], tw: null, mapReady: false, pickReady: false };

// ---------------------------------------------------------------- storage (per-browser convenience only)
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};

// ---------------------------------------------------------------- API client
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (S.token) headers.authorization = "Bearer " + S.token;
  let body = opts.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") { body = JSON.stringify(body); headers["content-type"] = "application/json"; }
  let r;
  try { r = await fetch("/api" + path, { method: opts.method || "GET", headers, body }); }
  catch (e) { throw { msg: "Can't reach the JalSetu server. Check your connection.", status: 0 }; }
  let j = null;
  try { j = await r.json(); } catch (e) { /* non-JSON */ }
  if (!r.ok) {
    if (r.status === 401 && S.token && !path.startsWith("/auth/")) { setUser(null, null); }
    throw { msg: (j && j.error) || (r.status === 413 ? "That file is too large." : "Something went wrong (" + r.status + ")."), status: r.status };
  }
  return j;
}
function toast(msg) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3600); }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function statusBadge(st) { return `<span class="st ${esc(st || "")}">${esc(st || "unknown")}</span>`; }
function provHtml(o) {
  const bits = [];
  if (o.source) bits.push(`<span>Source: ${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.source)}</a>` : esc(o.source)}</span>`);
  if (o.period) bits.push(`<span>Period: ${esc(o.period)}</span>`);
  if (o.as_of) bits.push(`<span>Data as of: ${esc(fdate(o.as_of))}</span>`);
  if (o.retrieved) bits.push(`<span>Last updated in JalSetu: ${esc(fdate(o.retrieved))}</span>`);
  bits.push(`<span>Status: ${statusBadge(o.stale ? "stale" : o.status)}</span>`);
  return `<div class="prov">${bits.join("")}</div>`;
}

// ---------------------------------------------------------------- tabs
const VIEWS = ["overview", "rain", "map", "report", "exchange", "quality", "recharge"];
function show(v) {
  if (!VIEWS.includes(v)) v = "overview";
  VIEWS.forEach(x => { $("v-" + x).hidden = x !== v; });
  document.querySelectorAll("nav.tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.v === v)));
  store.set("jalsetu.tab", v);
  if (v === "map") initMap();
  if (v === "report") initPickMap();
  if (v === "rain") loadRain();
  window.scrollTo({ top: 0 });
}
document.querySelectorAll("nav.tabs button").forEach(b => b.addEventListener("click", () => show(b.dataset.v)));

// ---------------------------------------------------------------- accounts
function setUser(token, user) {
  S.token = token; S.user = user;
  store.set("jalsetu.token", token);
  renderAcct(); renderExchangeForms();
}
function renderAcct() {
  const a = $("acct");
  if (!S.user) { a.innerHTML = `<button class="small ghost" id="loginBtn" type="button">Log in</button>`; $("loginBtn").onclick = () => openAuth("login"); return; }
  a.innerHTML = `<span class="who">${esc(S.user.name)} · ${esc(S.user.role)}</span>${S.user.role === "admin" ? `<a class="small" href="/admin" style="color:var(--accent);font-size:13px">Admin</a>` : ""}<button class="small plain" id="logoutBtn" type="button">Log out</button>`;
  $("logoutBtn").onclick = async () => { try { await api("/auth/logout", { method: "POST" }); } catch (e) { /* already gone */ } setUser(null, null); toast("Logged out."); };
}
let authMode = "login";
function openAuth(mode) { setAuthMode(mode); $("authErr").textContent = ""; $("authDlg").showModal(); $("aEmail").focus(); }
function setAuthMode(m) {
  authMode = m; $("modeLogin").setAttribute("aria-pressed", String(m === "login")); $("modeReg").setAttribute("aria-pressed", String(m === "register"));
  $("regFields").hidden = m !== "register"; $("authTitle").textContent = m === "login" ? "Log in" : "Create account";
  $("authSubmit").textContent = m === "login" ? "Log in" : "Create account"; $("aPass").autocomplete = m === "login" ? "current-password" : "new-password";
}
$("modeLogin").onclick = () => setAuthMode("login"); $("modeReg").onclick = () => setAuthMode("register");
$("authClose").onclick = () => $("authDlg").close();
$("aRole").onchange = () => { $("aOrgWrap").hidden = $("aRole").value !== "organization"; };
$("authForm").addEventListener("submit", async e => {
  e.preventDefault(); $("authErr").textContent = "";
  const body = { email: $("aEmail").value.trim(), password: $("aPass").value };
  if (authMode === "register") Object.assign(body, { name: $("aName").value.trim(), role: $("aRole").value, organization: $("aOrg").value.trim() || null });
  $("authSubmit").disabled = true;
  try {
    const j = await api(authMode === "login" ? "/auth/login" : "/auth/register", { method: "POST", body });
    setUser(j.token, j.user); $("authDlg").close(); $("aPass").value = ""; toast(`Welcome, ${j.user.name}.`);
  } catch (err) { $("authErr").textContent = err.msg; }
  finally { $("authSubmit").disabled = false; }
});

// ---------------------------------------------------------------- overview
function riskGauge(r) {
  return `<div class="gauge lvl-${esc(r.level)}" style="--v:${r.score}"><span><b>${nf(r.score, 0)}</b><small>/ 100</small></span></div>`;
}
async function loadOverview() {
  let o;
  try { o = await api("/overview"); } catch (e) { $("riskPanel").innerHTML = `<p class="err">${esc(e.msg)}</p>`; return; }
  const r = o.risk;
  const maxPts = Math.max(...r.components.map(c => c.points), 1);
  $("riskPanel").innerHTML = `
    <div class="row between"><h2>Bengaluru water risk</h2><span class="pill ${levelClass(r.level)}">${esc(r.level)}</span></div>
    <div class="risk">${riskGauge(r)}<div style="display:flex;flex-direction:column;gap:6px;min-width:0">
      <p style="font-size:14.5px"><b>Why ${nf(r.score, 0)}?</b> The score adds up six weighted indicators. Each is scaled 0–100 between documented anchor points, so every point can be traced to an official figure.</p>
      <p class="src">Computed ${esc(ago(r.computed_at))} · config ${esc(r.config_version)} · <a href="${GH}docs/water-risk-methodology.md" target="_blank" rel="noopener">methodology</a></p></div></div>
    <div class="contrib lvl-${esc(r.level)}" role="table" aria-label="Contributing factors">
      ${r.components.map(c => `<span role="cell" title="${esc(c.why_anchor)}">${esc(c.indicator)}<br><small class="muted">${esc(nf(c.value, 1))}${esc(c.unit)} → ${nf(c.normalised, 0)}/100 × ${c.weight}</small></span>
        <span class="tr" role="cell" aria-hidden="true"><i style="width:${(c.points / maxPts * 100).toFixed(1)}%"></i></span>
        <span class="pts" role="cell">+${nf(c.points, 1)}</span>`).join("")}
    </div>
    <details><summary class="label" style="cursor:pointer">Full explanation and data freshness</summary>
      <ul style="font-size:13.5px;margin:8px 0;padding-left:18px">${r.explanation.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <table class="t"><thead><tr><th>Indicator</th><th>Data as of</th><th>Status</th><th>Source</th></tr></thead><tbody>
      ${r.components.map(c => `<tr><td>${esc(c.indicator)}</td><td>${esc(fdate(c.as_of))}${c.days_old !== null ? `<br><small class="muted">${c.days_old} days old</small>` : ""}</td><td>${statusBadge(c.stale ? "stale" : c.status)}</td><td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.source)}</a>` : esc(c.source)}</td></tr>`).join("")}
      </tbody></table></details>`;
  // warnings
  $("warnCount").textContent = o.warnings.length ? o.warnings.length + " active" : "";
  $("warnings").innerHTML = o.warnings.length ? o.warnings.map(w => `<div class="warn ${esc(w.level)}">
      <div class="row between"><b>${esc(w.title)}</b><span class="pill ${levelClass(w.level)}">${esc(w.level)}</span></div>
      <span style="font-size:13.5px">Trigger: ${esc(w.trigger)}</span>
      <span class="src">Indicator: ${esc(w.indicator)}${w.data_as_of ? " · data as of " + esc(fdate(w.data_as_of)) : ""}${w.first_seen ? " · first raised " + esc(ago(w.first_seen)) : ""}</span>
      <details><summary class="label" style="cursor:pointer">Suggested actions</summary><ul>${w.actions.map(a => `<li>${esc(a)}</li>`).join("")}</ul></details></div>`).join("")
    : `<div class="empty">No warning rule is triggered by the current data.</div>`;
  renderIndicatorCards(o.indicators, o.rainfall_context);
}
function card(title, value, desc, provObj, extra = "") {
  return `<div class="card"><span class="label">${esc(title)}</span><span class="v">${value}</span><span class="d">${desc}</span>${extra}${provHtml(provObj)}</div>`;
}
async function renderIndicatorCards(ind, ctx) {
  const rain = ind.rainfall_current_season, u = rain.districts[0];
  const tot = ind.reservoir_readings.find(r => r.id === "cauvery_total");
  const dams = ind.reservoir_readings.filter(r => r.id !== "cauvery_total");
  const gw = ind.groundwater, ds = ind.demand_supply, lq = ind.lake_quality_summary;
  let tw = null, fc = null;
  try { [tw, fc] = await Promise.all([api("/treated-water"), api("/forecast?month=" + ((new Date().getMonth() + 1) % 12 + 1))]); } catch (e) { /* cards below still render */ }
  const offerKl = tw ? tw.offers.filter(o => !o.is_demo).reduce((a, o) => a + o.qty_kl_per_day, 0) : null;
  const cards = [
    card("Rainfall", `${signed(u.departure_pct, 0)}%`, `${esc(u.name)}: ${nf(u.actual_mm, 1)} mm vs normal ${nf(u.normal_mm, 1)} mm (anomaly ${nf(u.anomaly_mm, 1)} mm). ${esc(rain.districts[1].name)}: ${signed(rain.districts[1].departure_pct, 0)}%.`, rain),
    card("Reservoirs", `${nf(tot.pct_full, 1)}%`, `Cauvery reservoirs: ${nf(tot.storage_tmc, 2)} of ${nf(tot.capacity_tmc, 2)} TMC. ${dams.map(d => `${esc(d.reservoir)} ${nf(d.pct_full, 1)}%`).join(", ")}.`, { ...tot, as_of: tot.date }),
    card("Groundwater (official)", `${nf(gw.official_assessment.stage_of_extraction_pct, 1)}%`, `Stage of extraction, ${esc(gw.official_assessment.district)}: over-exploited (CGWB: above 100%). ${esc(gw.official_assessment.assessment)}.`, gw.official_assessment),
    card("Groundwater (modelled)", `${nf(gw.city_water_balance.extraction_ratio, 1)}×`, `About ${nf(gw.city_water_balance.pumped_mld)} MLD pumped vs ${nf(gw.city_water_balance.recharge_mld)} MLD natural recharge (estimate). ${nf(gw.borewells_dried.dried)} of ${nf(gw.borewells_dried.total)} borewells dried in 2024.`, gw.city_water_balance),
    card("Demand pressure", `${nf(ds.gap_share * 100, 0)}% gap`, `Demand ${nf(ds.demand_mld)} MLD (${esc(ds.demand_as_of)}) vs supply ${nf(ds.supply_mld)} MLD (${esc(fdate(ds.supply_as_of))}). ${esc(ds.note)}`, { source: ds.supply_source + "; " + ds.demand_source, url: ds.supply_url, as_of: ds.supply_as_of, retrieved: ds.retrieved, status: ds.status }),
    card("Lake quality", `${lq.lakes_class_a_to_c} of ${lq.lakes_monitored}`, `lakes met KSPCB class A–C (${esc(lq.period)}); about ${nf(lq.share_class_e_avg * 100)}% were in class E, the worst.`, lq),
    card("Reuse potential", offerKl === null ? "–" : `${nf(offerKl)} kL/day`, `Treated water currently offered on the JalSetu exchange (excluding demo rows). Citywide, ${nf(ind.sewage.untreated_mld)} of ${nf(ind.sewage.generated_mld)} MLD of sewage is left untreated.`, ind.sewage),
    card("Forecast", fc ? `${nf(fc.forecast_mm, 0)} mm` : "–", fc ? `Expected ${MON3[fc.month - 1]} rainfall, South Interior Karnataka. ${esc(fc.method)}` : "Forecast unavailable.", { source: fc ? `Model: ${fc.model.name} v${fc.model.version}, trained ${fdate(fc.model.trained_at.slice(0, 10))} on IMD sub-divisional data` : "", status: "modelled" }),
  ];
  $("indCards").innerHTML = cards.join("");
}
async function loadHotspots() {
  try {
    const h = await api("/hotspots");
    const max = Math.max(1, ...h.areas.map(a => a.reports));
    $("hotspots").innerHTML = (h.areas.length ? h.areas.slice(0, 8).map(a => `<div class="hot"><span>${esc(a.area)}</span><span class="tr"><i style="width:${a.reports / max * 100}%"></i></span><span class="num">${a.reports}</span></div>`).join("")
      : `<div class="empty">No community reports in the last 30 days.</div>`) +
      (h.tanker.reports ? `<p style="font-size:13.5px;margin-top:8px">Tanker prices reported: ${h.tanker.reports}, average <b class="num">${inr(h.tanker.avg_rs_per_1000l)}</b> per 1,000 L.</p>` : "");
  } catch (e) { $("hotspots").innerHTML = `<p class="err">${esc(e.msg)}</p>`; }
}
async function loadRiskHistory() {
  try {
    const h = await api("/risk/history?limit=20");
    $("histCount").textContent = h.count ? h.count + " snapshots" : "";
    $("riskHist").innerHTML = h.count ? `<table class="t"><thead><tr><th>When</th><th>Score</th><th>Level</th></tr></thead><tbody>${h.history.map(x => `<tr><td>${esc(fdate(x.computed_at))} <small class="muted">${esc(ago(x.computed_at))}</small></td><td class="num">${nf(x.score, 1)}</td><td><span class="pill ${levelClass(x.level)}">${esc(x.level)}</span></td></tr>`).join("")}</tbody></table><p class="src">${esc(h.note)}</p>`
      : `<div class="empty">${esc(h.note)}</div>`;
  } catch (e) { $("riskHist").innerHTML = `<p class="err">${esc(e.msg)}</p>`; }
}

// ---------------------------------------------------------------- rainfall + ML
async function loadRain() {
  if (S.rain) return;
  try {
    const [rain, hist, models] = await Promise.all([api("/rainfall"), api("/rainfall/history?monthly=true"), api("/ml/models")]);
    S.rain = rain; S.monthly = hist.monthly; S.seasons = hist.seasons; S.models = models;
  } catch (e) { $("seasonChart").innerHTML = `<p class="err">${esc(e.msg)}</p>`; return; }
  const cur = S.rain.current_season;
  $("rainbars").innerHTML = cur.districts.map(d => {
    const mx = Math.max(d.actual_mm, d.normal_mm) * 1.1;
    return `<div class="rb"><span>${esc(d.name)}</span><span class="tr"><i style="width:${d.actual_mm / mx * 100}%"></i><b style="left:${d.normal_mm / mx * 100}%"></b></span>
      <span class="cap">${nf(d.actual_mm, 1)} mm of ${nf(d.normal_mm, 1)} mm normal · anomaly ${nf(d.anomaly_mm, 1)} mm (${signed(d.departure_pct, 1)}%)</span></div>`;
  }).join("");
  $("rainSrc").innerHTML = provHtml(cur);
  const H = S.rain.historical;
  const span = `${H.years[0]}–${H.years[1]}`;
  $("nYears").textContent = H.years[1] - H.years[0] + 1; $("baseYears").textContent = span; $("trainYears").textContent = span; $("meanYears").textContent = span;
  $("seasonChart").innerHTML = seasonChart(S.seasons, H.jjas_mean_mm);
  const mk = H.mann_kendall_jjas, tr = H.trend_jjas;
  $("trendText").innerHTML = `Monsoon (Jun–Sep) mean: <b class="num">${nf(H.jjas_mean_mm, 0)} mm</b>. Linear trend <b class="num">${signed(tr.slope_per_decade, 1)} mm per decade</b> (95% CI ${nf(tr.ci95_per_decade[0], 1)} to ${nf(tr.ci95_per_decade[1], 1)}); Mann-Kendall test: ${esc(mk.trend)} (p = ${mk.p_value}). Seasons: ${Object.entries(H.jjas_category_counts).map(([k, v]) => `${esc(k)} ${v}`).join(", ")}. This official regional series is available to JalSetu only up to ${H.years[1]}; the 2026 season is shown at the top of this tab from IMD district bulletins, which are a different series.`;
  $("histSrc").innerHTML = `Source: <a href="${esc(H.source.dataset_page)}" target="_blank" rel="noopener">${esc(H.source.name)}</a> (copy used: <a href="${esc(H.source.copy_used)}" target="_blank" rel="noopener">GitHub mirror</a>). ${esc(H.source.limitations)} ${statusBadge("historical")}`;
  const years = [...new Set(S.monthly.map(m => m.year))];
  $("anYear").innerHTML = years.slice().reverse().map(y => `<option>${y}</option>`).join("");
  $("anYear").onchange = () => { $("anomChart").innerHTML = anomalyChart(+$("anYear").value); };
  $("anomChart").innerHTML = anomalyChart(years[years.length - 1]);
  $("mlYear").innerHTML = `<option value="">Choose…</option>` + years.slice(1).reverse().map(y => `<option>${y}</option>`).join("");
  renderEval(); loadForecast(); renderAnomalies();
  $("anM").innerHTML = MON3.map((m, i) => `<option value="${i + 1}" ${i === 2 ? "selected" : ""}>${m}</option>`).join("");
}
function yearMonths(y) { return S.monthly.filter(m => m.year === y).sort((a, b) => a.month - b.month).map(m => m.rain_mm); }
function seasonChart(seasons, mean) {
  const W = 800, Hh = 230, P = { l: 40, r: 8, t: 10, b: 24 };
  const max = niceMax(Math.max(...seasons.map(s => s.jjas_mm)));
  const x = scale(0, seasons.length, P.l, W - P.r), y = scale(0, max, Hh - P.b, P.t);
  const bw = (W - P.l - P.r) / seasons.length - 1;
  const bars = seasons.map((s, i) => `<rect x="${x(i).toFixed(1)}" y="${y(s.jjas_mm).toFixed(1)}" width="${bw.toFixed(1)}" height="${(Hh - P.b - y(s.jjas_mm)).toFixed(1)}" fill="${s.jjas_category.includes("eficient") ? "var(--crit)" : "var(--rain)"}" opacity="${s.jjas_category.includes("eficient") ? 1 : .6}"><title>${s.year}: ${nf(s.jjas_mm, 0)} mm (${signed(s.jjas_departure_pct, 0)}%, ${s.jjas_category})</title></rect>`).join("");
  const ma = seasons.map((s, i) => s.jjas_ma10_mm === null ? null : `${(x(i) + bw / 2).toFixed(1)},${y(s.jjas_ma10_mm).toFixed(1)}`).filter(Boolean).join(" ");
  const ticks = [0, max / 2, max].map(v => `<text x="${P.l - 4}" y="${y(v) + 3}" text-anchor="end">${nf(v)}</text><line class="axis" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/>`).join("");
  const yrs = seasons.filter(s => s.year % 20 === 0 || s.year === 1901).map(s => `<text x="${x(seasons.indexOf(s)) + bw / 2}" y="${Hh - 6}" text-anchor="middle">${s.year}</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Jun–Sep rainfall ${seasons[0].year} to ${seasons[seasons.length - 1].year} with deficient seasons highlighted">${ticks}${bars}
    <line x1="${P.l}" x2="${W - P.r}" y1="${y(mean)}" y2="${y(mean)}" stroke="var(--muted)" stroke-dasharray="4 3"/>
    <polyline points="${ma}" fill="none" stroke="var(--ink)" stroke-width="2"/>${yrs}<text x="${P.l}" y="${P.t + 2}" dx="4">mm</text></svg>`;
}
function anomalyChart(year) {
  const clim = S.rain.historical.climatology.map(c => c.mean_mm);
  const v = yearMonths(year).map((m, i) => m - clim[i]);
  const W = 800, Hh = 200, P = { l: 40, r: 8, t: 10, b: 22 };
  const m = niceMax(Math.max(...v.map(Math.abs), 10));
  const x = scale(0, 12, P.l, W - P.r), y = scale(-m, m, Hh - P.b, P.t);
  const bw = (W - P.l - P.r) / 12 - 6;
  const bars = v.map((a, i) => `<rect x="${x(i) + 3}" y="${Math.min(y(a), y(0))}" width="${bw}" height="${Math.abs(y(a) - y(0))}" fill="${a < 0 ? "var(--crit)" : "var(--rain)"}"><title>${MON3[i]} ${year}: ${nf(a + clim[i], 1)} mm, anomaly ${signed(a, 1)} mm</title></rect><text x="${x(i) + 3 + bw / 2}" y="${Hh - 6}" text-anchor="middle">${MON3[i]}</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Monthly rainfall anomaly for ${year}"><line class="axis" x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}"/>
    <text x="${P.l - 4}" y="${y(m) + 3}" text-anchor="end">+${nf(m)}</text><text x="${P.l - 4}" y="${y(-m) + 3}" text-anchor="end">−${nf(m)}</text>${bars}</svg>`;
}
$("mlYear").addEventListener("change", () => {
  const y = +$("mlYear").value; if (!y) { $("mlActual").textContent = ""; return; }
  const clim = S.rain.historical.climatology.map(c => c.mean_mm);
  const f = seasonFeatures(yearMonths(y), yearMonths(y - 1), clim);
  $("mlJun").value = f.jun_dep_pct.toFixed(1); $("mlJul").value = f.jul_dep_pct.toFixed(1);
  $("mlPre").value = f.premonsoon_dep_pct.toFixed(1); $("mlOnd").value = f.prev_ond_dep_pct.toFixed(1);
  $("mlActual").innerHTML = `What actually happened in ${y}: Jun–Sep ${signed(f.jjas_dep_pct, 1)}% (${f.jjas_dep_pct <= -20 ? "<b>deficient</b>" : "not deficient"}). Note: this year was part of the training data.`;
});
$("mlForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("mlOut").innerHTML = `<div class="loading">Running the model…</div>`;
  try {
    const r = await api("/ml/predict", { method: "POST", body: { jun_dep_pct: +$("mlJun").value, jul_dep_pct: +$("mlJul").value, premonsoon_dep_pct: +($("mlPre").value || 0), prev_ond_dep_pct: +($("mlOnd").value || 0) } });
    const mx = Math.max(...r.explanation.contributions.map(c => Math.abs(c.contribution)), 0.01);
    $("mlOut").innerHTML = `<div class="verdict ${r.probability_deficient >= .5 ? "crit" : "ok"}"><b>Risk score ${nf(r.probability_deficient * 100, 0)} / 100: ${r.predicted_deficient ? "likely deficient" : "not likely deficient"}</b>
      <span style="font-size:13.5px">Simple rule (June–July ≤ −20%): ${r.rule_baseline_deficient ? "deficient" : "not deficient"}. The model was trained with balanced class weights, so treat the score as a ranking, not a calibrated chance.</span></div>
      <h3>Why: contribution of each input</h3><p class="src">${esc(r.explanation.method)}. Base value ${nf(r.explanation.base_value * 100, 0)}; contributions add up to the score.</p>
      ${r.explanation.contributions.map(c => `<div class="bar-pn"><span style="width:44%">${esc(c.label)} <small class="muted">${signed(c.value, 1)}%</small></span><span class="tr"><span class="mid"></span><i style="${c.contribution >= 0 ? `left:50%;width:${c.contribution / mx * 50}%;background:var(--crit)` : `right:50%;width:${-c.contribution / mx * 50}%;background:var(--ok)`}"></i></span><span class="num" style="width:48px;text-align:right">${signed(c.contribution * 100, 1)}</span></div>`).join("")}
      <p class="src">Model: ${esc(r.model.name)} · version ${esc(r.model.version)} · trained ${esc(fdate(r.model.trained_at.slice(0, 10)))} · data ${esc(r.model.data_sha256)} · generated ${esc(new Date(r.generated_at * 1000).toLocaleString("en-IN"))}</p>`;
  } catch (err) { $("mlOut").innerHTML = `<p class="err">${esc(err.msg)}</p>`; }
});
function renderEval() {
  const c = S.models.classification, f = S.models.forecasting;
  const names = { majority_class: "Always 'not deficient'", "rule_jun_jul_le_-20": "Rule: June–July ≤ −20%", logistic_regression: "Logistic regression", random_forest: "Random Forest" };
  const cm = c.cv_results[c.selected].confusion_matrix;
  $("mlEval").innerHTML = `<h3>Deficient-monsoon classifier</h3>
    <p class="src">Time-series validation: ${c.folds.length} folds, each trained only on earlier years and tested on the next decade (${c.folds[0].test[0]}–${c.folds[c.folds.length - 1].test[1]}, ${c.cv_results.random_forest.n} test seasons, ${c.cv_results.random_forest.positives} deficient).</p>
    <div class="tw"><table class="t"><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC AUC</th></tr></thead><tbody>
    ${Object.entries(c.cv_results).map(([k, v]) => `<tr class="${k === c.selected ? "sel" : ""}"><td>${esc(names[k] || k)}${k === c.selected ? " (selected)" : ""}</td><td class="num">${nf(v.accuracy, 3)}</td><td class="num">${nf(v.precision, 3)}</td><td class="num">${nf(v.recall, 3)}</td><td class="num">${nf(v.f1, 3)}</td><td class="num">${v.roc_auc === undefined ? "–" : nf(v.roc_auc, 3)}</td></tr>`).join("")}
    </tbody></table></div>
    <p style="font-size:13.5px">Confusion matrix (selected): ${cm.tp} deficient seasons caught, ${cm.fn} missed, ${cm.fp} false alarms, ${cm.tn} correct 'normal'. <b>${esc(c.selection_note)}</b> Only ${c.cv_results.random_forest.positives} deficient seasons fall in the test years, so these numbers carry wide uncertainty.</p>
    <h3>Next-month rainfall forecast</h3><p class="src">Trained ${f.split.train[0]}–${f.split.train[1]}, tested ${f.split.test[0]}–${f.split.test[1]} (${f.results.climatology.n} months).</p>
    <div class="tw"><table class="t"><thead><tr><th>Model</th><th>MAE (mm)</th><th>RMSE (mm)</th><th>R²</th><th>Skill vs average</th></tr></thead><tbody>
    ${Object.entries(f.results).map(([k, v]) => `<tr class="${k === f.selected ? "sel" : ""}"><td>${esc(k.replace(/_/g, " "))}${k === f.selected ? " (selected)" : ""}</td><td class="num">${nf(v.mae, 1)}</td><td class="num">${nf(v.rmse, 1)}</td><td class="num">${nf(v.r2, 3)}</td><td class="num">${signed(v.skill_vs_climatology_mae * 100, 1)}%</td></tr>`).join("")}
    </tbody></table></div><p style="font-size:13.5px">No model beat the long-term monthly average, so JalSetu uses the average and says so. Full report: <a href="${GH}MODEL_REPORT.md" target="_blank" rel="noopener">MODEL_REPORT.md</a>.</p>`;
}
async function loadForecast() {
  const m = (new Date().getMonth() + 1) % 12 + 1;
  try {
    const [f, bt] = await Promise.all([api("/forecast?month=" + m), api("/forecast/backtest?start=2011")]);
    const W = 800, Hh = 190, P = { l: 40, r: 8, t: 10, b: 22 };
    const max = niceMax(Math.max(...bt.rows.map(r => Math.max(r.actual, r.random_forest))));
    const x = scale(0, bt.rows.length - 1, P.l, W - P.r), y = scale(0, max, Hh - P.b, P.t);
    const line = (k, col, dash) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? `stroke-dasharray="${dash}"` : ""} points="${bt.rows.map((r, i) => `${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`).join(" ")}"/>`;
    const yrs = bt.rows.map((r, i) => r.month === 1 ? `<text x="${x(i)}" y="${Hh - 6}">${r.year}</text>` : "").join("");
    $("fcOut").innerHTML = `<p style="font-size:14.5px"><b>${MON3[f.month - 1]}: about ${nf(f.forecast_mm, 0)} mm</b> expected (South Interior Karnataka). ${esc(f.method)}</p>
      <svg class="chart" viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Out-of-sample forecasts versus actual monthly rainfall ${bt.rows[0].year}–${bt.rows[bt.rows.length - 1].year}"><line class="axis" x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}"/><text x="${P.l - 4}" y="${y(max) + 3}" text-anchor="end">${max}</text>
      ${line("actual", "var(--rain)")}${line("climatology", "var(--muted)", "4 3")}${line("random_forest", "var(--warn)")}${yrs}</svg>
      <div class="legend"><span><i style="background:var(--rain)"></i>Actual</span><span><i style="background:var(--muted)"></i>Monthly average (selected)</span><span><i style="background:var(--warn)"></i>Random Forest</span></div>
      <p class="src">${esc(bt.note)} Model: ${esc(f.model.name)} v${esc(f.model.version)} · generated ${esc(new Date(f.generated_at * 1000).toLocaleString("en-IN"))}</p>`;
  } catch (e) { $("fcOut").innerHTML = `<p class="err">${esc(e.msg)}</p>`; }
}
function renderAnomalies() {
  const a = S.models.anomaly;
  $("anomList").innerHTML = `<p style="font-size:13.5px">The model flagged ${a.agreement.isolation_forest_flags} of ${nf(S.monthly.length - 2)} months as unusual. It caught ${a.agreement.both} of the ${a.agreement.rule_abs_z_ge_3_flags} months that are 3+ standard deviations from normal. There are no labelled 'true anomalies', so this is agreement with a rule, not accuracy.</p>
    <div class="tw"><table class="t"><thead><tr><th>Month</th><th>Rain</th><th>Normal</th><th>z</th></tr></thead><tbody>${a.flagged.slice(0, 8).map(r => `<tr><td>${MON3[r.month - 1]} ${r.year}</td><td class="num">${nf(r.rain_mm, 1)} mm</td><td class="num">${nf(r.normal_mm, 1)} mm</td><td class="num">${signed(r.z, 1)}</td></tr>`).join("")}</tbody></table></div>`;
}
$("anForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const r = await api("/ml/anomaly", { method: "POST", body: { month: +$("anM").value, rain_mm: +$("anR").value, prev_month_mm: +$("anP1").value, prev2_month_mm: +$("anP2").value } });
    $("anOut").innerHTML = `<div class="verdict ${r.anomalous ? "warn" : "ok"}"><b>${r.anomalous ? "Unusual month" : "Within the normal range"}</b><span style="font-size:13.5px">Normal ${nf(r.normal_mm, 1)} mm; z = ${signed(r.z, 2)}; model score ${r.score} (below 0 = unusual). Model ${esc(r.model.name)} v${esc(r.model.version)}.</span></div>`;
  } catch (err) { $("anOut").innerHTML = `<p class="err">${esc(err.msg)}</p>`; }
});

// ---------------------------------------------------------------- map
let MAP, LAYERS = {};
async function initMap() {
  if (S.mapReady) { setTimeout(() => MAP.invalidateSize(), 50); return; }
  if (!window.L) { $("map").innerHTML = `<p class="err" style="padding:12px">The map library didn't load.</p>`; return; }
  S.mapReady = true;
  MAP = L.map("map", { zoomControl: true }).setView([12.97, 77.59], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(MAP);
  let wards, lakes, hot, reps, tw, layers;
  try { [wards, lakes, hot, reps, tw, layers] = await Promise.all([api("/gis/wards"), api("/lakes"), api("/hotspots"), api("/reports?limit=200"), api("/treated-water"), api("/gis/layers")]); }
  catch (e) { toast(e.msg); return; }
  const byWard = Object.fromEntries(hot.wards.map(w => [w.ward_no, w.reports]));
  const max = Math.max(1, ...hot.wards.map(w => w.reports));
  LAYERS.wards = L.geoJSON(wards, {
    style: f => { const n = byWard[f.properties.ward_no] || 0; return { color: "#0B7572", weight: 1, fillColor: "#C23B2E", fillOpacity: n ? 0.15 + 0.5 * n / max : 0.03 }; },
    onEachFeature: (f, layer) => layer.on("click", () => wardInfo(f, reps.reports, lakes.lakes, byWard[f.properties.ward_no] || 0)),
  }).addTo(MAP);
  LAYERS.lakes = L.layerGroup(lakes.lakes.map(l => L.circleMarker([l.lat, l.lng], { radius: 8, color: "#3B6FB6", fillColor: "#3B6FB6", fillOpacity: .8 })
    .bindPopup(`<b>${esc(l.name)}</b><br>Area: ${esc(l.area_ha)} ha${l.ward ? `<br>Ward ${l.ward.ward_no}: ${esc(l.ward.name)}` : ""}<br>Quality data: ${l.observations.observations ? l.observations.observations + " observations" : "none available for this lake"}<br><small>Location: <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.source)}</a></small>`))).addTo(MAP);
  S.mapReports = reps.reports;
  LAYERS.reports = L.layerGroup().addTo(MAP);
  drawReports();
  LAYERS.exchange = L.layerGroup([
    ...tw.offers.map(o => L.circleMarker([o.lat, o.lng], { radius: 7, color: "#0B7572", fillColor: "#0B7572", fillOpacity: .9 }).bindPopup(`<b>Offer${o.is_demo ? " (DEMO)" : ""}</b><br>${esc(o.organization)}<br>${nf(o.qty_kl_per_day)} kL/day, ${esc(o.treatment_level)} treatment`)),
    ...tw.requests.map(q => L.circleMarker([q.lat, q.lng], { radius: 7, color: "#B7791F", fillColor: "#B7791F", fillOpacity: .9 }).bindPopup(`<b>Request${q.is_demo ? " (DEMO)" : ""}</b><br>${esc(q.requester)}<br>${nf(q.qty_kl_per_day)} kL/day for ${esc(q.purpose)}`)),
  ]).addTo(MAP);
  L.control.layers(null, { "Wards (report shading)": LAYERS.wards, "Lakes": LAYERS.lakes, "Community reports": LAYERS.reports, "Treated-water exchange": LAYERS.exchange }, { collapsed: window.innerWidth < 700 }).addTo(MAP);
  $("mapSrc").innerHTML = `Wards: <a href="${esc(layers.wards.url)}" target="_blank" rel="noopener">${esc(layers.wards.source)}</a> (${esc(layers.wards.license)}). Lakes: ${esc(layers.lakes.source)}. Reports placed on an area's approximate centre unless the reporter picked a point. <b>${esc(layers.ward_risk.note)}</b>`;
  setTimeout(() => MAP.invalidateSize(), 60);
}
function drawReports() {
  if (!LAYERS.reports) return;
  LAYERS.reports.clearLayers();
  const cat = $("fCat").value, st = $("fStatus").value;
  (S.mapReports || []).filter(r => r.lat && (!cat || r.category === cat) && (!st || r.status === st)).forEach(r => {
    L.circleMarker([r.lat, r.lng], { radius: 6, color: "#C23B2E", fillColor: "#C23B2E", fillOpacity: r.status === "VERIFIED" || r.status === "RESOLVED" ? .9 : .4 })
      .bindPopup(`<b>${esc(r.category_label)}${r.is_demo ? " (DEMO)" : ""}</b><br>${esc(r.area)}${r.ward ? ` · ward ${r.ward.ward_no}` : ""}<br>Status: ${esc(statusLabel(r.status))}<br>${esc(r.description || "")}<br><small>${esc(ago(r.created_at))}</small>`)
      .addTo(LAYERS.reports);
  });
}
$("fCat").onchange = drawReports; $("fStatus").onchange = drawReports;
function wardInfo(f, reps, lakes, n) {
  const p = f.properties;
  const inWard = reps.filter(r => r.ward && r.ward.ward_no === p.ward_no);
  const lk = lakes.filter(l => l.ward && l.ward.ward_no === p.ward_no);
  $("wardInfo").innerHTML = `<h3>Ward ${p.ward_no}: ${esc(p.name)}</h3><dl class="kv"><dt>Area</dt><dd>${nf(p.area_km2, 2)} km²</dd><dt>Reports (30 days)</dt><dd>${n}</dd><dt>Lakes</dt><dd>${lk.length ? lk.map(l => esc(l.name)).join(", ") : "none in JalSetu's list"}</dd></dl>
    ${inWard.slice(0, 5).map(r => `<div class="item"><span>${esc(r.category_label)} · <span class="pill ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span><small>${esc(r.description || "")}</small></span><span class="muted" style="font-size:12px">${esc(ago(r.created_at))}</span></div>`).join("")}
    <p class="src">Ward-level rainfall, groundwater and supply data are not publicly available, so JalSetu does not compute a ward risk score.</p>`;
}

// ---------------------------------------------------------------- report form
let PICK, PICK_MARK, PICKED = null;
function initPickMap() {
  if (S.pickReady || !window.L) { if (PICK) setTimeout(() => PICK.invalidateSize(), 50); return; }
  S.pickReady = true;
  PICK = L.map("pickMap").setView([12.97, 77.59], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(PICK);
  PICK.on("click", e => setPicked(e.latlng.lat, e.latlng.lng, "Point placed on the map."));
  setTimeout(() => PICK.invalidateSize(), 60);
}
function setPicked(lat, lng, note) {
  PICKED = { lat: +lat.toFixed(5), lng: +lng.toFixed(5) };
  if (PICK_MARK) PICK_MARK.setLatLng([lat, lng]); else if (PICK) PICK_MARK = L.marker([lat, lng]).addTo(PICK);
  $("locNote").textContent = `${note} (${PICKED.lat}, ${PICKED.lng})`;
}
$("useLoc").onclick = () => {
  if (!navigator.geolocation) { toast("Location isn't available in this browser."); return; }
  navigator.geolocation.getCurrentPosition(p => { setPicked(p.coords.latitude, p.coords.longitude, "Your location."); if (PICK) PICK.setView([p.coords.latitude, p.coords.longitude], 15); },
    () => toast("Couldn't get your location. Pick an area or tap the map."), { timeout: 8000 });
};
$("rCat").onchange = () => { $("tankerWrap").hidden = $("rCat").value !== "tanker"; };
async function shrink(f, max) {
  try {
    const bmp = await createImageBitmap(f), s = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas"); c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height); if (bmp.close) bmp.close();
    const b = await new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
    return b ? new File([b], "photo.jpg", { type: "image/jpeg" }) : f;
  } catch (e) { return f; }
}
let repBusy = false;
$("repForm").addEventListener("submit", async e => {
  e.preventDefault(); if (repBusy) return; repBusy = true; $("repErr").textContent = "";
  const fd = new FormData(), cat = $("rCat").value;
  fd.append("category", cat); fd.append("description", $("rDesc").value.trim());
  if (PICKED) { fd.append("lat", PICKED.lat); fd.append("lng", PICKED.lng); if ($("rArea").value) fd.append("area", $("rArea").value); }
  else if ($("rArea").value) fd.append("area", $("rArea").value);
  else { $("repErr").textContent = "Choose an area, use your location, or tap the map."; repBusy = false; return; }
  if (cat === "tanker") { fd.append("price", $("rPrice").value); fd.append("litres", $("rLitres").value); }
  const f0 = $("rPhoto").files[0];
  const btn = $("repBtn"); btn.disabled = true; btn.textContent = "Saving…";
  try {
    if (f0) { const f = await shrink(f0, 1280); if (f.size > 4 * 1024 * 1024) throw { msg: "That photo is too large. Choose a smaller one." }; fd.append("photo", f); }
    const r = await api("/reports", { method: "POST", body: fd });
    $("repForm").reset(); $("tankerWrap").hidden = true; PICKED = null; if (PICK_MARK) { PICK.removeLayer(PICK_MARK); PICK_MARK = null; } $("locNote").textContent = "Or tap the map to place the report exactly.";
    toast(r.ai && r.ai.cls === "bad" ? "Saved. The photo didn't match, so it won't count toward hotspots." : "Report saved. An admin will review it.");
    loadReports(); loadHotspots(); if (S.mapReady) { S.mapReports.unshift(r); drawReports(); }
  } catch (err) { $("repErr").textContent = err.msg; }
  finally { btn.disabled = false; btn.textContent = "Submit report"; repBusy = false; }
});
async function loadReports() {
  try {
    const j = await api("/reports?limit=30");
    $("repCount").textContent = j.reports.length + " shown";
    $("reports").innerHTML = j.reports.length ? j.reports.map(r => `<div class="item"><span><b>${esc(r.category_label)}</b> · ${esc(r.area)}${r.ward ? ` <small style="display:inline">(ward ${r.ward.ward_no})</small>` : ""} <span class="pill ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span>${r.is_demo ? ` <span class="st demo">demo</span>` : ""}
      ${r.category === "tanker" && r.price ? ` · <span class="num">${inr(r.price)}</span> for <span class="num">${nf(r.litres)} L</span>` : ""}<small>${esc(r.description || "")}</small>
      ${r.photo_url ? `<img src="${esc(r.photo_url)}" alt="Photo for this report" loading="lazy" style="display:block;margin-top:6px;border-radius:6px;max-height:110px">` : ""}${r.ai ? `<span class="aiv ${esc(r.ai.cls)}">${esc(r.ai.text)}</span>` : ""}</span>
      <span class="muted" style="font-size:12px;white-space:nowrap">${esc(ago(r.created_at))}</span></div>`).join("")
      : `<div class="empty">No reports yet. Be the first to report a water problem in your area.</div>`;
  } catch (e) { $("reports").innerHTML = `<p class="err">${esc(e.msg)}</p>`; }
}

// ---------------------------------------------------------------- exchange
function renderExchangeForms() {
  const u = S.user;
  $("exLogin").hidden = !!u;
  $("offerPanel").hidden = !(u && (u.role === "organization" || u.role === "admin"));
  $("reqPanel").hidden = !u;
  if (u && u.organization && !$("oOrg").value) $("oOrg").value = u.organization;
  loadExchange();
}
async function loadExchange() {
  let tw;
  try { tw = await api("/treated-water"); } catch (e) { $("offers").innerHTML = `<p class="err">${esc(e.msg)}</p>`; return; }
  S.tw = tw;
  const mine = x => S.user && (x.user_id === S.user.id || S.user.role === "admin");
  $("exFacts").innerHTML = `<div class="fact"><b class="num">₹${tw.treated_price.rs_per_kl}/kL</b><span>BWSSB treated-water price (${esc(fdate(tw.treated_price.as_of))})</span><a href="${esc(tw.treated_price.url)}" target="_blank" rel="noopener">${esc(tw.treated_price.source)}</a></div>
    <div class="fact"><b class="num">${tw.offers.length} / ${tw.requests.length}</b><span>open offers / requests on JalSetu</span></div>`;
  $("offCount").textContent = tw.offers.length + " open";
  $("offers").innerHTML = tw.offers.length ? tw.offers.map(o => `<div class="item"><span><b>${esc(o.organization)}</b>${o.is_demo ? ` <span class="st demo">demo</span>` : ""} · ${esc(o.area || "map point")}<small>${nf(o.qty_kl_per_day)} kL/day · ${esc(o.treatment_level)} · ${esc(fdate(o.available_from))} to ${esc(fdate(o.available_to))} · for ${o.reuse_categories.map(c => esc(tw.reuse_categories[c] || c)).join(", ")}${o.quality_notes ? " · " + esc(o.quality_notes) : ""}</small></span>
    ${mine(o) ? `<button class="plain" type="button" data-close-offer="${o.id}" aria-label="Close offer ${esc(o.organization)}">Close</button>` : ""}</div>`).join("") : `<div class="empty">No offers yet.</div>`;
  $("requests").innerHTML = tw.requests.length ? tw.requests.map(q => `<div class="panel" style="padding:10px;gap:6px"><div class="row between"><span><b>${esc(q.requester)}</b>${q.is_demo ? ` <span class="st demo">demo</span>` : ""} · ${esc(q.area || "map point")}</span>
      <span class="row" style="gap:4px"><button class="small" type="button" data-match="${q.id}">Find matches</button>${mine(q) ? `<button class="plain" type="button" data-close-req="${q.id}">Close</button>` : ""}</span></div>
      <small class="muted">${nf(q.qty_kl_per_day)} kL/day for ${esc(tw.reuse_categories[q.purpose] || q.purpose)} · ${esc(fdate(q.needed_from))} to ${esc(fdate(q.needed_to))} · needs ${esc(q.min_treatment)} or better</small><div id="m-${q.id}"></div></div>`).join("") : `<div class="empty">No requests yet.</div>`;
}
document.addEventListener("click", async e => {
  const t = e.target.closest("[data-match],[data-close-offer],[data-close-req]"); if (!t) return;
  if (t.dataset.match) {
    const box = $("m-" + t.dataset.match); box.innerHTML = `<div class="loading">Ranking offers…</div>`;
    try {
      const j = await api(`/matches?request_id=${t.dataset.match}&include_blocked=true&fresh_rs_per_kl=${Math.max(0, +$("freshPrice").value || 0)}`);
      const res = j.results[0];
      box.innerHTML = (res.matches.length ? res.matches.map((m, i) => `<div class="match ${m.eligible ? "" : "un"}"><b>${m.eligible ? "#" + (i + 1) + " " : "Not eligible: "}${esc(m.offer.organization)} · score ${nf(m.score * 100, 0)}/100</b>
          <span>${m.eligible ? esc(m.reasons.join(" · ")) + ` · saves about <b>${inr(m.saving_rs_per_day)}</b>/day` : esc(m.blocked_by.join("; "))}</span>
          ${m.eligible ? `<small class="muted">distance ${nf(m.parts.distance * 100)} · quantity ${nf(m.parts.quantity * 100)} · availability ${nf(m.parts.availability * 100)} (weights ${j.weights.distance}/${j.weights.quantity}/${j.weights.availability})</small>` : ""}</div>`).join("") : `<div class="empty">No offers to compare yet.</div>`)
        + (res.unmet ? `<div class="match un"><b>Unmet: ${nf(res.unmet_kl_per_day)} kL/day</b><span>No single eligible offer covers the full request.</span></div>` : "");
    } catch (err) { box.innerHTML = `<p class="err">${esc(err.msg)}</p>`; }
  } else {
    const isOffer = !!t.dataset.closeOffer, id = t.dataset.closeOffer || t.dataset.closeReq;
    try { await api(`/treated-water/${isOffer ? "offers" : "requests"}/${id}`, { method: "DELETE" }); toast("Closed."); loadExchange(); } catch (err) { toast(err.msg); }
  }
});
$("offerForm").addEventListener("submit", async e => {
  e.preventDefault(); $("offerErr").textContent = "";
  const cats = [...document.querySelectorAll("#oCats input:checked")].map(i => i.value);
  if (!cats.length) { $("offerErr").textContent = "Tick at least one approved reuse category."; return; }
  const num = v => v === "" ? null : +v;
  try {
    await api("/treated-water/offers", { method: "POST", body: { organization: $("oOrg").value.trim(), area: $("oArea").value, qty_kl_per_day: +$("oQty").value, treatment_level: $("oTreat").value,
      available_from: $("oFrom").value, available_to: $("oTo").value, reuse_categories: cats, quality_notes: $("oNotes").value.trim(), bod_mg_l: num($("oBod").value), tss_mg_l: num($("oTss").value) } });
    toast("Offer added."); $("offerForm").reset(); if (S.user.organization) $("oOrg").value = S.user.organization; loadExchange();
  } catch (err) { $("offerErr").textContent = err.msg; }
});
$("reqForm").addEventListener("submit", async e => {
  e.preventDefault(); $("reqErr").textContent = "";
  try {
    await api("/treated-water/requests", { method: "POST", body: { requester: $("qName").value.trim(), area: $("qArea").value, qty_kl_per_day: +$("qQty").value, purpose: $("qPurpose").value,
      needed_from: $("qFrom").value, needed_to: $("qTo").value, min_treatment: $("qMin").value } });
    toast("Request added. Press 'Find matches' to rank offers."); $("reqForm").reset(); loadExchange();
  } catch (err) { $("reqErr").textContent = err.msg; }
});

// ---------------------------------------------------------------- quality
const QV = {};
async function initQuality() {
  const j = await api("/water-quality");
  S.limits = j.limits;
  $("qBody").innerHTML = j.limits.map(l => `<tr><td>${esc(l.label)} <small class="muted">${esc(l.unit)}</small></td>
    <td><input id="q-${l.key}" type="number" step="any" min="0" inputmode="decimal" aria-label="${esc(l.label)} result"></td>
    <td class="num" style="font-size:12.5px">${l.kind === "range" ? `${l.acceptable[0]}–${l.acceptable[1]}` : l.kind === "zero" ? "0 (absent)" : `${l.acceptable} / ${l.permissible === null ? "no relaxation" : l.permissible}`}</td>
    <td id="qs-${l.key}"><span class="pill p-idle">–</span></td></tr>`).join("");
  j.limits.forEach(l => $("q-" + l.key).addEventListener("input", e => { const v = e.target.value; if (v === "") delete QV[l.key]; else QV[l.key] = +v; checkQ(); }));
}
const checkQ = debounce(async () => {
  let r;
  try { r = await api("/water-quality/check", { method: "POST", body: { values: QV } }); } catch (e) { $("qVerdict").innerHTML = `<p class="err">${esc(e.msg)}</p>`; return; }
  S.limits.forEach(l => {
    const x = r.results.find(y => y.key === l.key);
    const cell = $("qs-" + l.key);
    if (!x) { cell.innerHTML = `<span class="pill p-idle">–</span>`; return; }
    const cls = { ok: "p-ok", high: "p-warn", unsafe: "p-crit", invalid: "p-idle" }[x.status], lab = { ok: "Safe", high: "High", unsafe: "Unsafe", invalid: "Invalid" }[x.status];
    cell.innerHTML = `<span class="pill ${cls}" title="${esc(qualityExplanation({ ...x, kind: l.kind }))}">${lab}</span>`;
  });
  const V = { safe: ["ok", "Meets IS 10500 for the values entered"], only_if_no_other_source: ["warn", "Usable only if there is no better source"], unsafe: ["crit", "Not safe to drink"] }[r.verdict];
  $("qVerdict").innerHTML = V ? `<div class="verdict ${V[0]}"><b>${V[1]}</b><ul style="margin:4px 0 0;padding-left:18px;font-size:13.5px">${r.results.filter(x => x.status !== "ok").map(x => `<li><b>${esc(x.label)}</b> ${esc(nf(x.value, 2))}: ${esc(qualityExplanation({ ...x, kind: S.limits.find(l => l.key === x.key).kind }))}</li>`).join("")}</ul>
    ${r.bacteria_found ? `<span style="font-size:13.5px">Bacteria were found. Boiling or disinfecting is the usual first step; get advice from your local health authority.</span>` : ""}<span class="src">Only the parameters you entered were checked.</span></div>` : "";
}, 200);
$("labPhoto").addEventListener("change", async e => {
  const f = e.target.files[0]; e.target.value = ""; if (!f) return;
  $("labNote").textContent = "AI is reading the report…";
  const fd = new FormData(); fd.append("photo", await shrink(f, 2000));
  try {
    const j = await api("/ai/lab-report", { method: "POST", body: fd });
    let n = 0; for (const [k, v] of Object.entries(j.values)) { const inp = $("q-" + k); if (inp) { inp.value = v; QV[k] = v; n++; } }
    checkQ(); $("labNote").textContent = n ? `AI read ${n} values. Check them against the report.` : "AI couldn't find any values. Type them in.";
  } catch (err) { $("labNote").textContent = err.msg; }
});
async function loadLakes() {
  try {
    const j = await api("/lakes");
    const s = j.city_summary;
    $("lakeList").innerHTML = `<p style="font-size:14px">KSPCB monitored <b>${s.lakes_monitored} lakes</b> (${esc(s.period)}): <b>${s.lakes_class_a_to_c}</b> met class A–C; about <b>${nf(s.share_class_e_avg * 100)}%</b> were class E, the worst.</p>${provHtml(s)}
      <div class="tw"><table class="t"><thead><tr><th>Lake</th><th>Ward</th><th>Area</th><th>Quality data</th></tr></thead><tbody>${j.lakes.map(l => `<tr><td><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)}</a></td><td>${l.ward ? `${l.ward.ward_no} ${esc(l.ward.name)}` : "outside BBMP"}</td><td class="num">${esc(l.area_ha)} ha</td><td>${l.observations.observations ? `${l.observations.observations} obs., last ${esc(fdate(l.observations.last))}` : `<span class="muted">not available</span>`}</td></tr>`).join("")}</tbody></table></div>
      <p class="src">Per-lake KSPCB readings are not available to JalSetu yet; an admin can add them with their source. Locations: Wikipedia, one article per lake.</p>`;
  } catch (e) { $("lakeList").innerHTML = `<p class="err">${esc(e.msg)}</p>`; }
}

// ---------------------------------------------------------------- recharge
const runRwh = debounce(async () => {
  const n = id => Math.max(0, +$(id).value || 0);
  const body = { length_ft: n("sL"), width_ft: n("sW"), built: $("sAge").value, roof_sqm: n("roof"), paved_sqm: n("paved"), monthly_bill_rs: n("bill"),
    runoff_coefficient: Math.min(1, Math.max(0.05, +$("runoff").value || 0.8)), collection_efficiency: Math.min(1, Math.max(0.05, +$("eff").value || 1)),
    rainfall_series: $("rseries").value, annual_rain_mm: $("annual").value === "" ? null : n("annual") };
  let r;
  try { r = await api("/rwh", { method: "POST", body }); } catch (e) { $("rwhOut").innerHTML = `<p class="err">${esc(e.msg)}</p>`; return; }
  const mx = Math.max(...r.monthly_harvest_kl, 0.1);
  $("rwhOut").innerHTML = `<div class="verdict ${r.mandatory ? "warn" : "ok"}"><b>${r.mandatory ? "Rainwater harvesting is mandatory for this site" : "Not mandatory for this site"}</b><span style="font-size:13.5px">Site ${nf(r.site_sqft)} sq ft (${nf(r.site_sqm, 1)} m²); BWSSB threshold ${nf(r.threshold_sqft)} sq ft for ${body.built === "new" ? "buildings from 2009" : "older buildings"}.</span></div>
    <div class="out"><div class="fact"><b class="num">${nf(r.yearly_harvest_kl, 1)} kL</b><span>could be collected in a year</span></div><div class="fact"><b class="num">${nf(r.min_storage_litres)} L</b><span>minimum storage BWSSB requires (20 L/m² roof + 10 L/m² paved)</span></div>
    ${r.mandatory ? `<div class="fact"><b class="num">${inr(r.first_year_penalty_avoided_rs)}</b><span>penalty avoided in the first year (50% of bill for 3 months, then 100%)</span></div>` : ""}<div class="fact"><b class="num">${nf(r.annual_rain_mm, 0)} mm</b><span>annual rainfall used</span></div></div>
    <div class="months" role="img" aria-label="Monthly harvest">${r.monthly_harvest_kl.map((v, i) => `<div class="c"><em>${nf(v, v < 10 ? 1 : 0)}</em><i style="height:${v / mx * 100}%"></i><span>${MON3[i][0]}</span></div>`).join("")}</div>
    <p class="src"><b>${esc(r.formula)}</b>. 1 mm of rain on 1 m² = 1 litre. ${esc(r.assumptions)}. Rainfall: <a href="${esc(r.rainfall_source.url)}" target="_blank" rel="noopener">${esc(r.rainfall_source.label)}</a> ${statusBadge(r.rainfall_source.status)}. <a href="${GH}docs/rainwater-harvesting-methodology.md" target="_blank" rel="noopener">Methodology</a>.</p>`;
}, 200);
["sL", "sW", "sAge", "roof", "paved", "bill", "runoff", "eff", "rseries", "annual"].forEach(id => $(id).addEventListener("input", runRwh));
$("rwhForm").addEventListener("submit", e => e.preventDefault());

// ---------------------------------------------------------------- start
async function start() {
  const token = store.get("jalsetu.token");
  if (token) { S.token = token; try { S.user = (await api("/auth/me")).user; } catch (e) { S.token = null; store.set("jalsetu.token", null); } }
  renderAcct();
  try {
    const [h, m] = await Promise.all([api("/health"), api("/meta")]);
    S.health = h; S.meta = m;
    $("srvBadge").textContent = `Live server · ${h.database} · models v${h.models ? h.models.version : "–"}`;
    $("srvBadge").style.color = "var(--ok)"; $("srvBadge").style.background = "var(--ok-soft)";
    $("demoBanner").hidden = !h.data_mode.startsWith("DEMONSTRATION");
    $("aiNote").textContent = h.ai ? "AI checks that the photo matches the report." : "AI photo checks are off on this server. Your photo is still saved and shown.";
    $("labAI").hidden = !h.ai;
    const opts = arr => arr.map(a => `<option>${esc(a)}</option>`).join("");
    $("rArea").innerHTML = `<option value="">Pick on the map instead</option>` + opts(m.areas);
    $("oArea").innerHTML = opts(m.areas); $("qArea").innerHTML = opts(m.areas);
    $("rCat").innerHTML = Object.entries(m.report_categories).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("fCat").innerHTML = `<option value="">All categories</option>` + Object.entries(m.report_categories).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("fStatus").innerHTML = `<option value="">All statuses</option>` + m.report_statuses.map(s => `<option value="${s}">${esc(statusLabel(s))}</option>`).join("");
    $("qPurpose").innerHTML = Object.entries(m.reuse_categories).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("oCats").innerHTML = Object.entries(m.reuse_categories).map(([k, v]) => `<label class="cb chip"><input type="checkbox" value="${k}"> ${esc(v)}</label>`).join("");
  } catch (e) { $("srvBadge").textContent = "Server unreachable"; $("srvBadge").style.color = "var(--crit)"; toast(e.msg); }
  loadOverview(); loadHotspots(); loadRiskHistory(); loadReports(); renderExchangeForms(); initQuality().catch(e => toast(e.msg)); loadLakes(); runRwh();
  show(store.get("jalsetu.tab") || "overview");
}
start();
