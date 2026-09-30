# JalSetu API reference

Version 2.0.0. Generated from the OpenAPI schema by `python scripts/gen_api_docs.py`. Interactive docs: `/docs`; offline list: `/api`.

## Conventions

- JSON in and out. Errors are always `{"error": "plain-language message"}` (500 errors also include a `ref` that matches a server log line).
- Status codes: 200 OK · 201 created · 401 not logged in · 403 wrong role/owner · 404 not found · 409 conflict (duplicate email, invalid status change) · 413 file too large · 415 not an image · 422 validation · 429 rate limited · 502/503 AI unavailable · 507 store full.
- Auth: `Authorization: Bearer <token>` from `/api/auth/login` or `/api/auth/register`. Tokens last 7 days; only their SHA-256 is stored.
- Every data response includes provenance fields (`source`, `url`, `as_of`/`period`, `status`).

## admin

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/admin/overview` | admin | Admin dashboard data: reports by status, risk, warnings, freshness, health, ML, activity | – | – |
| `GET` | `/api/admin/reports` | admin | All reports with allowed status transitions | status, limit | – |
| `PATCH` | `/api/admin/reports/{rid}` | admin | Change a report's status (state machine enforced, audit-logged) | rid | JSON `StatusIn` |
| `DELETE` | `/api/admin/reports/{rid}` | admin | Permanently delete a report, its photo and status history (audit-logged) | rid | – |
| `DELETE` | `/api/admin/reports/{rid}/photo` | admin | Remove only a report's photo (admin, audit-logged) | rid | – |
| `POST` | `/api/admin/reservoir-readings` | admin | Add a reservoir reading with its source (ingestion interface) | – | JSON `ReservoirIn` |
| `POST` | `/api/admin/lake-observations` | admin | Add a lake quality observation with its source | – | JSON `LakeObsIn` |
| `GET` | `/api/admin/audit-logs` | admin | Audit log of admin and account actions | limit | – |
| `GET` | `/api/admin/users` | admin | Accounts (no password data) | – | – |
| `PATCH` | `/api/admin/users/{uid}` | admin | Change an account's role, e.g. make someone an admin (audit-logged) | uid | JSON `RoleIn` |
| `GET` | `/api/admin/predictions` | admin | Logged model predictions | limit | – |

## admin-setup-status

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/admin-setup-status` | admin | Diagnose admin login: whether ADMIN_* settings are present and match the account (no secrets) | – | – |

## ai

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/ai/lab-report` | – | AI reads values from a lab-report photo (only when an AI key is configured) | – | multipart form `Body_ai_lab_report_api_ai_lab_report_post` |

## areas

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/areas` | – | v1 compatibility: areas and categories | – | – |

## auth

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/auth/register` | – | Create a citizen or organization account (returns a session token) | – | JSON `RegisterIn` |
| `POST` | `/api/auth/login` | – | Log in (returns a session token) | – | JSON `LoginIn` |
| `POST` | `/api/auth/admin-check` | – | Explain a failed admin login: wrong email, wrong password, or admin not set up (rate-limited) | – | JSON `LoginIn` |
| `POST` | `/api/auth/logout` | logged in | End this session | – | – |
| `GET` | `/api/auth/me` | logged in | The logged-in account | – | – |

## forecast

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/forecast` | – | Next-month rainfall forecast with the evaluation behind the chosen model | month | – |
| `GET` | `/api/forecast/backtest` | – | Out-of-sample forecasts vs actual rainfall (test period 1996 onwards) | start | – |

## gis

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/gis/wards` | – | 243 BBMP ward polygons (GeoJSON, simplified) | – | – |
| `GET` | `/api/gis/layers` | – | Map layer sources, locality points, and what ward-level data is unavailable | – | – |

## groundwater

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/groundwater` | – | Official extraction stage (real) vs modelled city water balance, stress score | – | – |

## health

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/health` | – | Server status: database, schema version, data mode, pipeline and model versions, counts | – | – |

## hotspots

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/hotspots` | – | Report counts per area and per ward (last N days) and average tanker price | days, verified_only | – |

## lakes

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/lakes` | – | Lakes with location provenance, ward and number of quality observations; city lake summary | – | – |
| `GET` | `/api/lakes/{lake_id}` | – | One lake with its admin-added quality observations | lake_id | – |

## matches

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/matches` | – | Ranked offers for each open request, with filters, score parts, reasons and savings | request_id, fresh_rs_per_kl, include_blocked | – |

## meta

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/meta` | – | Areas, report categories and statuses, tanker sizes, reuse categories | – | – |

## ml

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/ml/predict` | – | Deficient-monsoon risk score from June/July departures, with per-feature explanation | – | JSON `SeasonIn` |
| `POST` | `/api/ml/anomaly` | – | Is this month's rainfall unusual? (Isolation Forest) | – | JSON `AnomalyIn` |
| `GET` | `/api/ml/models` | – | Model versions, training data hash, and all evaluation metrics | – | – |

## overview

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/overview` | – | Dashboard in one call: risk score, warnings, all indicators with provenance | – | – |

## rainfall

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/rainfall` | – | Current season departures plus 1901–2017 IMD climatology, trend, Mann-Kendall test, driest seasons | – | – |
| `GET` | `/api/rainfall/history` | – | Season rows (and optionally monthly rows with anomalies) for a year range | start, end, monthly | – |

## reports

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/reports` | – | Community reports, newest first; filter by status or category | limit, status, category, include_rejected | – |
| `POST` | `/api/reports` | optional (anonymous allowed) | Submit a report (category, area or map point, description, optional photo) | – | multipart form `Body_create_report_api_reports_post` |
| `DELETE` | `/api/reports/{rid}` | – | Delete your own report (reports sent while logged in) | rid | – |
| `GET` | `/api/reports/{rid}` | – | One report with its status history | rid | – |
| `GET` | `/api/reports/{rid}/photo` | – | The report's resized photo | rid | – |

## reservoirs

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/reservoirs` | – | Latest reading per reservoir with trend and risk contribution | – | – |
| `GET` | `/api/reservoirs/history` | – | All reservoir readings (pipeline + admin uploads) | – | – |
| `GET` | `/api/reservoirs/{rid}` | – | One reservoir with its full history | rid | – |

## risk

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/risk/current` | – | Current water-risk score, level and weighted components (stores a snapshot when inputs change) | – | – |
| `GET` | `/api/risk/explanation` | – | Why the score is what it is: formula, weights, anchors, plain-language drivers | – | – |
| `GET` | `/api/risk/history` | – | Stored risk-score snapshots, newest first | limit | – |

## rwh

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/rwh` | – | Rainwater harvesting: BWSSB rule, storage, monthly and yearly harvest, penalty avoided | – | JSON `RwhIn` |

## signals

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/signals` | – | v1 compatibility: rain, reservoirs and groundwater in the old shape | – | – |

## treated-water

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/treated-water` | – | Open treated-water offers and requests | – | – |
| `POST` | `/api/treated-water/offers` | organization or admin | Offer treated water (organization or admin) | – | JSON `OfferIn` |
| `POST` | `/api/treated-water/requests` | logged in | Request treated water (any logged-in user) | – | JSON `RequestIn` |
| `DELETE` | `/api/treated-water/offers/{oid}` | owner or admin | Close an offer (owner or admin) | oid | – |
| `DELETE` | `/api/treated-water/requests/{rid}` | owner or admin | Close a request (owner or admin) | rid | – |

## warnings

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/warnings` | – | Early warnings from the rule engine: level, trigger, indicator, time, actions | – | – |

## water-quality

| Method | Path | Auth | Purpose | Params | Body |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/water-quality` | – | IS 10500:2012 limits for the 18 parameters | – | – |
| `POST` | `/api/water-quality/check` | – | Classify lab values as Safe / High / Unsafe against IS 10500:2012 | – | JSON `WaterIn` |

## Schemas

- **AnomalyIn**: `month`*, `rain_mm`*, `prev_month_mm`*, `prev2_month_mm`*  (* required)
- **LakeObsIn**: `lake_id`*, `date`*, `parameter`*, `value`, `class`, `source`*, `url`*  (* required)
- **LoginIn**: `email`*, `password`*  (* required)
- **OfferIn**: `area`, `lat`, `lng`, `organization`*, `qty_kl_per_day`*, `treatment_level`*, `quality_notes`, `bod_mg_l`, `tss_mg_l`, `available_from`*, `available_to`*, `reuse_categories`*  (* required)
- **RegisterIn**: `email`*, `password`*, `name`*, `role`, `organization`  (* required)
- **RequestIn**: `area`, `lat`, `lng`, `requester`*, `qty_kl_per_day`*, `needed_from`*, `needed_to`*, `purpose`*, `min_treatment`  (* required)
- **ReservoirIn**: `reservoir_id`*, `reservoir`*, `date`*, `storage_tmc`, `capacity_tmc`, `pct_full`, `inflow_cusecs`, `outflow_cusecs`, `source`*, `url`*, `status`  (* required)
- **RoleIn**: `role`*  (* required)
- **RwhIn**: `length_ft`*, `width_ft`*, `built`, `roof_sqm`, `paved_sqm`, `monthly_bill_rs`, `runoff_coefficient`, `collection_efficiency`, `rainfall_series`, `annual_rain_mm`  (* required)
- **SeasonIn**: `jun_dep_pct`*, `jul_dep_pct`*, `premonsoon_dep_pct`, `prev_ond_dep_pct`  (* required)
- **StatusIn**: `status`*, `note`  (* required)
- **WaterIn**: `values`  (* required)
