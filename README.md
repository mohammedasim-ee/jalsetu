# JalSetu (ಜಲಸೇತು): water security for Bengaluru

Live: https://jalsetu-smoky.vercel.app · Admin: `/admin` · API: `/api` (offline list) and `/docs` (interactive)

## 1. Overview

JalSetu is a working prototype of a data-driven urban water-security and early-warning platform for Bengaluru. It answers four questions: what is happening to the city's water, what could happen next, why the risk is changing, and what practical action can be taken. Every figure shows its source, date and status. **Nothing is presented as a live government feed**: official figures are entered from published bulletins, and the pipeline validates their provenance.

## 2. Problem

Bengaluru is short of water on several fronts at once, and the facts that show it are spread across different sources:

- **Groundwater.** The official CGWB 2024 assessment puts Bengaluru Urban's groundwater extraction at **186.7%** of recharge, which makes it over-exploited. In 2024, 6,900 of 13,900 city borewells dried up.
- **Rain.** This monsoon, Bengaluru Urban received **48% less rain than normal** (IMD, 1 Jun – 28 Sep 2026).
- **Supply.** Piped supply (~1,935 MLD) is below demand (~2,600 MLD).
- **Lakes.** None of 149 monitored lakes met KSPCB class A–C.

These facts sit in IMD, CGWB, KSPCB and BWSSB documents and in news reports. Citizens can't turn them into a decision, and community knowledge such as dry borewells and tanker prices isn't recorded anywhere.

## 3. Solution

One system: **real data → validation → processing → analytics → explainable risk engine → ML (with honest evaluation) → GIS → early warnings → actions.** Communities add verified reports, and a matcher connects surplus treated sewage water with non-drinking uses.

## 4. Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) (diagram and request flow).

- **Server:** FastAPI (Python), with PostgreSQL on Neon in production and SQLite locally.
- **Pipeline:** a reproducible data pipeline over real datasets.
- **ML:** models trained offline and exported to JSON for pure-Python inference.
- **Frontend:** vanilla JS with a locally bundled Leaflet map.
- **Hosting:** Vercel.

## 5. Features

| Module | What works | Data status |
| --- | --- | --- |
| Overview | Risk score 0–100 with six weighted, explained components; data freshness; early warnings with triggers and actions; 8 indicator cards with source, period, dates, status; risk history | Official/published (historical) + live DB |
| Rainfall analytics | 115-year monsoon chart, anomalies (mm and %), IMD categories, 10-year moving average, OLS trend with CI, Mann-Kendall test, monthly anomaly chart per year | IMD 1901–2015 (historical, regional) |
| ML | Deficient-monsoon classifier with per-prediction explanation; forecaster (climatology won); Isolation Forest unusual-month detector; full metrics shown in the app | Trained on IMD data; see MODEL_REPORT.md |
| Map (GIS) | 243 BBMP wards, lakes, reports, treated-water offers and requests; layer toggles, category and status filters, ward click panel, ward shading by report count | KGIS/DataMeet, Wikipedia. Ward risk is shown as **unavailable**, not faked |
| Reservoirs | Latest per reservoir, % full, trend when two or more readings exist, admin ingestion with source | News report of official figures |
| Groundwater | Official extraction stage (real) shown separately from the modelled city water balance (estimate) | CGWB 2024 / WELL Labs |
| Lakes | List, ward, location source, city quality summary, admin-added observations | KSPCB summary; per-lake series unavailable |
| Community reports | 7 categories, area or exact map point or GPS, photo, status workflow SUBMITTED → UNDER_REVIEW → VERIFIED → RESOLVED / REJECTED, history | Live DB |
| Treated-water exchange | Organization offers (quantity, treatment level, BOD/TSS, dates, approved uses); requests (quantity, dates, purpose, minimum treatment); ranked matching; savings; unmet demand | Live DB; ₹10/kL BWSSB price |
| Water quality | 18 IS 10500:2012 parameters → Safe / High / Unsafe with explanation | BIS standard |
| Rainwater harvesting | BWSSB mandatory rule, storage, monthly and annual harvest (rainfall × area × runoff × efficiency), penalty avoided, choice of rainfall series | BWSSB rules; rainfall options labelled |
| Accounts and admin | Citizen / organization / admin; admin dashboard: reports review, warnings, data freshness, API health, ML info, predictions, audit log, reservoir ingestion | – |
| Demo mode | `JALSETU_DEMO=1` adds invented rows marked DEMO, shows a "DATA MODE: DEMONSTRATION" banner, and never counts them in the score | Demonstration |

## 6. Tech stack

| Area | Technology | Why |
| --- | --- | --- |
| Server | Python 3.12, FastAPI, Pydantic | Validation built in, OpenAPI docs |
| Database | psycopg 3 (Postgres) / sqlite3 | Same SQL on both; managed Postgres on Vercel |
| Images | Pillow | Re-encodes uploads safely |
| ML (offline) | scikit-learn 1.5.2, numpy | Training only; not needed at runtime |
| Map | Leaflet 1.9.4 | Open-source; bundled locally |
| Optional AI | Anthropic API | Photo checks; everything works without it |
| Tests | pytest, Playwright, node:test | Unit, integration, browser |
| Quality | ruff (incl. security rules), mypy | Lint and type checking |

## 7. Data sources

[DATA_SOURCES.md](DATA_SOURCES.md) lists every dataset with source, URL, period, retrieval date, status, processing and limitations.

## 8. Data pipeline

```
python pipeline/run_pipeline.py
```

`data/raw` → validation (missing, negative, duplicate, sum checks; provenance required) → cleaning → normalisation → features (climatology, anomalies, categories, moving averages, trends; ward simplification and point-in-polygon) → `data/processed` plus `manifest.json` (SHA-256 of every input and output). The run is deterministic: the same inputs always give byte-identical outputs, and this is tested.

## 9. ML pipeline

```
pip install -r requirements-ml.txt
python ml/train.py
```

Preprocessing and features (`ml/features.py`, training-period baselines only, so there is no leakage) → time-series validation → metrics → export to JSON (`ml/export.py`) → pure-Python inference (`app/ml_runtime.py`, tested equal to scikit-learn) → predictions logged with model version. Results: [MODEL_REPORT.md](MODEL_REPORT.md). Card: [ML_MODEL_CARD.md](ML_MODEL_CARD.md).

## 10. API

52 endpoints. [API.md](API.md) is generated from the OpenAPI schema by `python scripts/gen_api_docs.py`.

## 11. Database schema

Versioned migrations are in `app/db.py`; the applied version is recorded in `schema_migrations` (currently 2).

| Table | Purpose |
| --- | --- |
| `users` | Email, name, role, organization, scrypt hash |
| `sessions` | SHA-256 of token, expiry |
| `reports` | Category, area, lat/lng, ward, description, tanker price/size, photo, AI check, status, demo flag |
| `report_events` | Status history with actor and note |
| `offers` / `requests` | Treated-water exchange |
| `risk_scores` | Snapshots with component points and input hash |
| `warnings` | Active/inactive with first and last seen |
| `model_predictions` | Model, version, inputs, output, time |
| `reservoir_readings` / `lake_observations` | Admin-ingested data with source URL |
| `audit_logs` | Actor, action, target, detail, IP, time |
| `listings` | v1 table, kept for compatibility |

## 12. Installation

Needs Python 3.10+.

```
pip install -r requirements.txt            # to run
pip install -r requirements-dev.txt        # to test, lint, retrain
```

## 13. Environment variables

See [.env.example](.env.example).

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres; empty = SQLite |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Creates the admin account (password 8+ characters) |
| `ANTHROPIC_API_KEY` | Optional AI |
| `JALSETU_DEMO=1` | Demo rows |
| `CORS_ORIGINS` | Other sites allowed to call the API |
| `JALSETU_WRITE_LIMIT`, `JALSETU_LOGIN_LIMIT` | Rate limits |

## 14. Running locally

```
ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='a-long-password' uvicorn app.main:app --reload
```

Open http://localhost:8000, and http://localhost:8000/admin for the admin dashboard.

## 15. Testing

See [TESTING.md](TESTING.md).

```
pytest
node --test static/js/lib.test.js
ruff check .
python -m mypy
```

Latest run (30 Sep 2026):
- **pytest:** 108 passed (backend, pipeline, ML, and 6 browser end-to-end tests), on both SQLite and PostgreSQL 16 for the non-browser suites.
- **node:** 9 passed.
- **ruff and mypy:** clean.

## 16. Deployment (Vercel + Neon)

1. Push to GitHub. Vercel builds `api/index.py` (`vercel.json`); the bundle contains no ML libraries (~2 MB of app files).
2. Storage → Neon Postgres → connect. This sets `DATABASE_URL`, and migrations run automatically on first start, including upgrading a v1 database.
3. Settings → Environment Variables: set `ADMIN_EMAIL` and `ADMIN_PASSWORD`; optionally `ANTHROPIC_API_KEY`.
4. Redeploy.

Also works on Render (`render.yaml`) or Docker (`Dockerfile`).

## 17. Limitations (honest)

- **No live feeds.** Official figures are entered by hand; there are no live government feeds and no IoT sensors.
- **Secondary sources.** Some official figures come from news reports of them: reservoir levels, the CGWB stage, the KSPCB summary.
- **Historical rainfall.** It is regional (South Interior Karnataka) and ends in 2015; the models cannot see 2016–2026.
- **ML value.** The classifier doesn't beat a simple rule on F1, and its probabilities are uncalibrated; next-month forecasting has no skill over the average. Both are stated in the app.
- **No ward risk.** No ward-level risk, rainfall or groundwater data is public, so none is shown.
- **Limited lake data.** Only 7 lakes have locations, and none has a per-lake quality series yet.
- **Mixed dates.** Inputs to the risk score come from different dates; each component's age is displayed.
- **Unverified organizations.** Organizations are self-declared. There is no email verification or password reset.
- **Per-instance rate limits.** On serverless, each instance counts separately.
- **Map tiles need internet.** OpenStreetMap tiles need a connection; the ward outlines don't.
- **Arsenic limit to recheck.** Confirm the arsenic permissible limit against the latest BIS amendment.

## 18. Future work

- **Better data:** KSNDMC reservoir bulletins and IMD daily district rainfall, ingested automatically where their terms allow; CGWB observation wells mapped to wards (which would make a ward risk layer possible); KSPCB monthly lake reports per lake.
- **Better models:** retrain on data after 2015 and probability calibration.
- **Accounts:** httpOnly cookie sessions, organization verification, and Kannada language support.

---

Also in this repository: [AUDIT.md](AUDIT.md) (before and after), [SECURITY.md](SECURITY.md), [DEMO_SCRIPT.md](DEMO_SCRIPT.md), `docs/` (risk, water-quality and rainwater methodologies).
