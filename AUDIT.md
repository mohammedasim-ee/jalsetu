# JalSetu audit (before the v2 upgrade)

Audited version: commit `de6d910` (tagged `v1-presentation`), deployed at https://jalsetu-smoky.vercel.app.
Method: read every source file, ran the 38 backend tests and 42 browser checks, and checked the live deployment's `/api/health` and `/api/signals`.

## 1. Current architecture

| Layer | What exists |
| --- | --- |
| Frontend | One file, `static/index.html` (~560 lines, vanilla HTML/CSS/JS). Five tabs: Now, Report, Share, Quality, Recharge. No framework, no build step. |
| Backend | One FastAPI app, `app/main.py` (~460 lines) plus `app/rules.py` (rules) and `app/ai.py` (optional Anthropic calls). |
| Database | Raw SQL through a small adapter: SQLite locally, PostgreSQL (Neon) when `DATABASE_URL` is set. Two tables: `reports`, `listings`. Tables are created with `CREATE TABLE IF NOT EXISTS`; there are no migrations. |
| Data | `app/data/signals.json`: 3 hand-entered snapshots (IMD rain to 28 Sep 2026, reservoirs on 5 Sep 2026, groundwater balance 2024). Eight facts are hard-coded in the HTML with source links. |
| AI | Claude Haiku reads report photos and lab-report photos, only when `ANTHROPIC_API_KEY` is set. It is not machine learning trained on project data. |
| Deployment | Vercel (`vercel.json` routes every request to `api/index.py`), Neon Postgres, GitHub `mohammedasim-ee/jalsetu`. |
| Tests | `tests/test_api.py` (38 pytest tests), `tests/browser_checks.py` (42 Playwright checks, run manually). |

## 2. Working features (verified by tests)

- Early warning from 3 official figures: rain departure −48% and −20%, reservoirs at 63.7%, pumping 9.3× recharge.
- Citizen reports with 5 types, a photo (resized server-side) and a tanker price. The average price per 1,000 L is computed.
- Hotspots: count of problem reports per area over the last 30 days.
- Treated-water listings with nearest-first greedy matching (haversine distance), unmet demand and daily saving.
- IS 10500:2012 check for 18 parameters (Safe / High / Unsafe).
- BWSSB rainwater-harvesting rule, tank size and penalty.
- Owner-only delete through a hashed edit token; moderator deletes through `ADMIN_TOKEN`.
- Validation on every route, rate limit, photo type and size checks, and JSON error handling.

## 3. Partially working

| Feature | Limitation |
| --- | --- |
| Early warning | Single snapshot, no history, no trend. Thresholds are fixed in code. |
| Hotspots | Area centre points only; no map. |
| Matching | Uses distance and quantity only. It ignores availability dates, reuse purpose and quality. |
| Reports | No status workflow (submitted, verified, resolved) and no admin screen. The only moderation is a header token with `curl`. |
| AI features | Need a paid key; they are off on the live site. |
| Rate limit | In memory, so each Vercel instance counts separately. |

## 4. Missing (asked for in the v2 brief)

- Combined water-risk score with an explanation.
- Rainfall history, anomaly, trend and moving averages.
- Reservoir history.
- Groundwater module.
- Lake module.
- Map (GIS).
- A real ML pipeline with metrics.
- Accounts and roles; admin dashboard.
- Data pipeline scripts.
- Migrations.
- Structured logs.
- Architecture, API, security and testing documentation.

## 5. Static, manual or approximate data (not fake, but should be labelled)

| Item | Status |
| --- | --- |
| `signals.json` | Real figures, entered by hand. Not live. Updated by editing the file. |
| 8 fact cards in the HTML | Real figures with links. The sources are news or NGO articles, not official datasets. |
| 28 locality coordinates in `rules.py` | Hand-entered approximate area centres, not surveyed points. |
| Monthly rainfall used by the rainwater planner | From climate-data.org, a modelled climate site, not IMD. **Replace with IMD data.** |
| Tanker size list, ₹10/kL price | From news reports (The Hindu, 2024). |

No fabricated numbers were found. Every figure on screen has a source link or is computed from sourced figures.

## 6. Technical debt

- The frontend is one large HTML file; its JS helper functions have no unit tests.
- SQL strings are spread across route handlers, and there is no schema version.
- Rules (thresholds, weights) are code constants, not configuration.
- The browser checks need two manually started servers.

## 7. Security findings

| Finding | Severity | Note |
| --- | --- | --- |
| No accounts; anyone can post | Medium | Acceptable for public reporting; there is no way to attribute or moderate in the UI. |
| Moderator key is a static header token | Medium | No audit log of moderator actions. |
| `CORS_ORIGINS` defaults to `*` | Low | The API is public and read-mostly; tighten it for production. |
| In-memory rate limit | Low | Not shared across serverless instances. |
| Secrets | OK | No keys committed; `.env` is ignored; `.env.example` is blank. |
| Uploads | OK | Re-encoded through Pillow to JPEG; type and size checked. |
| XSS | OK | All user text is escaped in the frontend. |
| SQL injection | OK | Parameterised queries everywhere. |

## 8. Accessibility and mobile

The v1 audit passed keyboard, focus-outline, 320–1366 px and dark-mode checks (42/42). No open issues.

## 9. Recommended architecture (v2)

Keep the same stack (FastAPI, Postgres/SQLite, vanilla JS, Vercel), because it works and every addition can be tested. Add:

1. `data/raw → pipeline/ → data/processed`: a reproducible pipeline over real datasets (IMD subdivision rainfall 1901–2015, BBMP ward boundaries, Wikipedia-sourced lake locations, the existing signals).
2. `ml/`: training with scikit-learn offline. Models are exported to JSON, so the server runs inference in pure Python with no scikit-learn at runtime, which keeps the Vercel bundle small.
3. `app/risk.py`: an explainable, configurable risk engine (`config/risk_weights.json`) plus early-warning rules.
4. Versioned SQL migrations; tables for users, sessions, reports (with status), offers, requests, risk snapshots, warnings, predictions, reservoir readings and audit logs.
5. Accounts with scrypt password hashing and random session tokens stored hashed. Roles: citizen, organization, admin.
6. Frontend: add Overview (risk), Rainfall and ML, Map (Leaflet, bundled locally), Exchange, Admin.

## 10. Implementation roadmap

1. Audit (this file).
2. Pipeline and real datasets.
3. Migrations and accounts.
4. Risk engine and warnings.
5. ML and evaluation.
6. APIs.
7. Frontend.
8. Tests and security.
9. Docs and deployment.

Each step is followed by running the full test suite.

---

## 11. Status after the v2 upgrade (30 Sep 2026)

| v1 gap | v2 status |
| --- | --- |
| No combined risk score | Done: explainable, configurable score (`app/risk.py`, `config/risk_config.json`, docs/water-risk-methodology.md) |
| Single-snapshot warning | Done: 8 warning rules with triggers and actions, persisted with first and last seen; risk snapshots in `risk_scores` |
| No rainfall analytics | Done: IMD 1901–2015 pipeline (anomalies, categories, moving average, OLS trend, Mann-Kendall) |
| No ML | Done: 3 models, time-series validation, real metrics (MODEL_REPORT.md). The honest finding is that the ML does not beat a simple rule / the monthly average, and the app says so |
| No map | Done: Leaflet with 243 BBMP wards, lakes, reports, exchange; filters, layers, ward panel. Ward risk is marked unavailable |
| No accounts / admin UI | Done: scrypt, hashed sessions, 3 roles; admin dashboard with review workflow, freshness, health, ML, audit log |
| No report workflow | Done: 7 categories, map point or GPS, 5-state workflow with history |
| Matching on distance only | Done: hard filters (use, treatment, dates) + ranked score + reasons |
| No migrations | Done: versioned, idempotent, SQLite and Postgres; v1 databases upgrade in place (tested) |
| No pipeline | Done: `pipeline/run_pipeline.py`, deterministic with a manifest |
| Hard-coded facts in HTML | Moved to `data/raw/official_indicators.json`; the pipeline refuses records without provenance |
| climate-data.org rainfall used silently | Now labelled "modelled" in the planner, with the official IMD regional series as an alternative |
| Tests: 38 backend | Now 108 Python tests (incl. 6 browser end-to-end) + 9 JS; ruff and mypy clean |

Remaining limitations are listed in README §17.
