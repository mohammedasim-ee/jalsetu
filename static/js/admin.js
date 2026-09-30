/* JalSetu admin dashboard. Uses the same API; admin role is enforced on the server, not here. */
"use strict";
const { esc, nf, fdate, ago, levelClass, statusLabel, statusClass } = window.JL;
const $ = id => document.getElementById(id);
let TOKEN = null; try { TOKEN = localStorage.getItem("jalsetu.token"); } catch (e) {}
let FLOW = {};
function toast(m) { const t = $("toast"); t.textContent = m; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => t.hidden = true, 3500); }
async function api(p, o = {}) {
  const h = { authorization: "Bearer " + (TOKEN || "") }; let b = o.body;
  if (b && typeof b !== "string") { b = JSON.stringify(b); h["content-type"] = "application/json"; }
  const r = await fetch("/api" + p, { method: o.method || "GET", headers: h, body: b });
  const j = await r.json().catch(() => null);
  if (!r.ok) throw { msg: (j && j.error) || "Error " + r.status, status: r.status };
  return j;
}
function showLogin(msg) { $("loginPanel").hidden = false; $("dash").hidden = true; if (msg) $("loginErr").textContent = msg; }
$("loginForm").addEventListener("submit", async e => {
  e.preventDefault(); $("loginErr").textContent = "";
  try {
    const j = await api("/auth/login", { method: "POST", body: { email: $("email").value, password: $("pass").value } });
    if (j.user.role !== "admin") { $("loginErr").textContent = "This account is not an admin."; return; }
    TOKEN = j.token; try { localStorage.setItem("jalsetu.token", TOKEN); } catch (e) {}
    load();
  } catch (err) {
    $("loginErr").textContent = err.msg;
    if (err.status === 401) {   // explain exactly what doesn't match the server's ADMIN_* settings
      try { const c = await api("/auth/admin-check", { method: "POST", body: { email: $("email").value, password: $("pass").value } }); $("loginErr").textContent = c.message; }
      catch (e2) { /* keep the original message */ }
    }
  }
});
async function load() {
  if (!TOKEN) { showLogin(); return; }
  let o;
  try { o = await api("/admin/overview"); } catch (e) { showLogin(e.status === 403 ? "Log in with the admin account." : ""); return; }
  $("loginPanel").hidden = true; $("dash").hidden = false;
  const rs = o.reports.by_status;
  $("summary").innerHTML = [
    ["Water risk", `${nf(o.risk.score, 1)} <span class="pill ${levelClass(o.risk.level)}">${esc(o.risk.level)}</span>`],
    ["Active reports", nf(o.reports.unresolved)], ["Awaiting review", nf((rs.SUBMITTED || 0) + (rs.UNDER_REVIEW || 0))], ["Verified", nf(rs.VERIFIED || 0)],
    ["Resolved", nf(rs.RESOLVED || 0)], ["Warnings", nf(o.warnings.length)], ["Open offers / requests", `${o.exchange.open_offers} / ${o.exchange.open_requests}`],
    ["Users", Object.entries(o.users).map(([k, v]) => `${v} ${k}`).join(", ") || "0"],
  ].map(([k, v]) => `<div class="card"><span class="label">${esc(k)}</span><span class="v" style="font-size:22px">${v}</span></div>`).join("");
  $("warns").innerHTML = o.warnings.map(w => `<div class="warn ${esc(w.level)}"><div class="row between"><b>${esc(w.title)}</b><span class="pill ${levelClass(w.level)}">${esc(w.level)}</span></div><span class="src">${esc(w.trigger)}</span></div>`).join("") || `<div class="empty">None.</div>`;
  $("fresh").innerHTML = o.data_freshness.map(d => `<tr><td>${esc(d.dataset)}</td><td>${esc(fdate(d.as_of))}</td><td class="num">${d.days_old ?? "–"} days</td><td><span class="st ${d.stale ? "stale" : esc(d.status)}">${d.stale ? "stale" : esc(d.status)}</span></td></tr>`).join("");
  $("pipe").textContent = `Pipeline v${o.pipeline.pipeline_version}, last run ${o.pipeline.generated_at}. Update data/raw and run python pipeline/run_pipeline.py.`;
  const h = o.api_health;
  $("health").innerHTML = `<dt>Database</dt><dd>${h.database ? "reachable" : "DOWN"} (${esc(h.dialect)}, schema v${h.schema_version})</dd><dt>AI</dt><dd>${h.ai_enabled ? "on" : "off (no API key)"}</dd>`;
  $("models").innerHTML = `<dt>Version</dt><dd>${esc(o.ml.version)}</dd><dt>Trained</dt><dd>${esc(o.ml.trained_at)}</dd><dt>Classifier</dt><dd>${esc(o.ml.classifier)}</dd><dt>Forecaster</dt><dd>${esc(o.ml.forecaster)}</dd><dt>Predictions logged</dt><dd>${o.ml.predictions_logged}</dd>`;
  $("preds").innerHTML = o.ml.recent_predictions.map(p => `<div class="src">${esc(p.model)} v${esc(p.version)} → ${esc(p.output)} · ${esc(ago(p.created_at))}</div>`).join("");
  $("audit").innerHTML = o.activity.map(a => `<tr><td>${esc(ago(a.created_at))}</td><td>${esc(a.email || "–")}</td><td>${esc(a.action)}</td><td>${esc(a.target || "")}</td><td>${esc(a.detail || "")}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">No activity yet.</td></tr>`;
  loadReports(); loadUsers();
}
async function loadUsers() {
  const j = await api("/admin/users");
  $("userRows").innerHTML = j.users.map(u => `<tr><td>${esc(u.email)}</td><td>${esc(u.name)}${u.organization ? `<br><small class="muted">${esc(u.organization)}</small>` : ""}</td>
    <td><select data-role="${u.id}" aria-label="Role for ${esc(u.email)}" style="width:auto;padding:4px 6px">${["citizen", "organization", "admin"].map(r => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select></td>
    <td>${u.last_login_at ? esc(ago(u.last_login_at)) : "never"}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">No accounts yet.</td></tr>`;
}
document.addEventListener("change", async e => {
  const s = e.target.closest("select[data-role]"); if (!s) return;
  if (!confirm(`Change this account's role to "${s.value}"?`)) { loadUsers(); return; }
  try { const r = await api("/admin/users/" + s.dataset.role, { method: "PATCH", body: { role: s.value } }); toast(r.changed ? `Role changed to ${r.role}.` : "No change."); load(); }
  catch (err) { toast(err.msg); loadUsers(); }
});
async function loadReports() {
  const st = $("stFilter").value;
  const j = await api("/admin/reports" + (st ? "?status=" + st : ""));
  FLOW = j.allowed_transitions;
  $("repRows").innerHTML = j.reports.map(r => `<tr><td class="num">${r.id}</td><td><b>${esc(r.category_label)}</b> · ${esc(r.area)}${r.ward ? ` (ward ${r.ward.ward_no})` : ""}${r.is_demo ? ` <span class="st demo">demo</span>` : ""}<br><small class="muted">${esc(r.description || "")} · ${esc(ago(r.created_at))}</small>${r.photo_url ? `<br><a href="${esc(r.photo_url)}" target="_blank" rel="noopener">photo</a> · <button class="plain" type="button" data-rmphoto="${r.id}" style="color:var(--crit);padding:0">Remove photo</button>` : ""}</td>
    <td><span class="pill ${statusClass(r.status)}">${esc(statusLabel(r.status))}</span></td>
    <td>${(FLOW[r.status] || []).length ? `<div class="row" style="gap:4px"><input id="n-${r.id}" placeholder="note (optional)" maxlength="300" style="width:140px;padding:5px 8px">${FLOW[r.status].map(s => `<button class="small ${s === "REJECTED" ? "ghost" : ""}" type="button" data-id="${r.id}" data-to="${s}">${esc(statusLabel(s))}</button>`).join("")}</div>` : `<span class="muted">final</span>`}</td><td><button class="small ghost" type="button" data-del="${r.id}" data-label="${esc(r.category_label)} · ${esc(r.area)}" aria-label="Delete report ${r.id}" style="color:var(--crit);border-color:var(--crit)">Delete</button></td></tr>`).join("") || `<tr><td colspan="5" class="empty">No reports.</td></tr>`;
}
$("stFilter").onchange = loadReports;
document.addEventListener("click", async e => {
  const p = e.target.closest("button[data-rmphoto]");
  if (p) {
    if (!confirm(`Remove the photo from report #${p.dataset.rmphoto}? The report itself stays. This can't be undone.`)) return;
    p.disabled = true;
    try { await api(`/admin/reports/${p.dataset.rmphoto}/photo`, { method: "DELETE" }); toast("Photo removed."); load(); }
    catch (err) { toast(err.msg); p.disabled = false; }
    return;
  }
  const d = e.target.closest("button[data-del]");
  if (d) {
    if (!confirm(`Permanently delete report #${d.dataset.del} (${d.dataset.label})?\n\nIts photo and status history are deleted too. This can't be undone.`)) return;
    d.disabled = true;
    try { await api("/admin/reports/" + d.dataset.del, { method: "DELETE" }); toast(`Report ${d.dataset.del} deleted.`); load(); }
    catch (err) { toast(err.msg); d.disabled = false; }
    return;
  }
  const b = e.target.closest("button[data-to]"); if (!b) return;
  b.disabled = true;
  try { await api("/admin/reports/" + b.dataset.id, { method: "PATCH", body: { status: b.dataset.to, note: ($("n-" + b.dataset.id) || {}).value || "" } }); toast(`Report ${b.dataset.id}: ${statusLabel(b.dataset.to)}`); load(); }
  catch (err) { toast(err.msg); b.disabled = false; }
});
$("resForm").addEventListener("submit", async e => {
  e.preventDefault(); $("resErr").textContent = "";
  const [id, name] = $("resId").value.split("|"), num = v => v === "" ? null : +v;
  try {
    await api("/admin/reservoir-readings", { method: "POST", body: { reservoir_id: id, reservoir: name, date: $("resDate").value, pct_full: num($("resPct").value), storage_tmc: num($("resSto").value), capacity_tmc: num($("resCap").value), source: $("resSrc").value, url: $("resUrl").value } });
    toast("Reading added. The risk score and warnings use it now."); $("resForm").reset(); load();
  } catch (err) { $("resErr").textContent = err.msg; }
});
load();
