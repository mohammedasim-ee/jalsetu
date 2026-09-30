# Testing

```
pip install -r requirements-dev.txt
python -m playwright install chromium        # once, for the browser tests
pytest                                      # backend + ML + end-to-end browser tests
node --test static/js/lib.test.js           # frontend unit tests
ruff check .                                # lint (includes security rules)
python -m mypy                              # type check
python pipeline/run_pipeline.py             # rebuild data (deterministic)
python ml/train.py                          # retrain + re-evaluate models
```

Run against PostgreSQL by setting `DATABASE_URL` to an empty database first; the same suite runs there.

## What is covered

| Suite | File | Tests | Covers |
| --- | --- | --- | --- |
| API | `tests/test_api.py` | 52 | Health, headers, site stays up if the database is down at start, provenance on every data endpoint, rainfall analysis, reservoirs, groundwater, lakes, GIS, all 18 IS 10500 parameters at their boundaries, RWH formula and units, report creation, photos (JPEG/PNG/WebP re-encoded; empty, corrupt, oversize and decompression-bomb images rejected), map points, validation, XSS-as-text, ML and forecast APIs, anomaly API, rate limit, 404 and 500 handling, AI on/off/failure, every endpoint documented |
| Accounts and admin | `tests/test_auth_admin.py` | 25 | Hashing, sessions, expiry, forged tokens, registration validation, same message for wrong password and unknown user, role checks, report state machine, audit log, rejected reports hidden, verified reports raise the risk score, reservoir ingestion validation and trend, lake observations, admin bootstrap |
| Exchange | `tests/test_exchange.py` | 4 | Hard filters (use, treatment, dates), score formula, overlap days, roles, validation, ranking (nearest first, blocked excluded), savings, unmet demand, owner-only close |
| Risk engine | `tests/test_risk.py` | 18 | Weights sum to 1, normalisation (both directions, clamping, bad input), hand-calculated score, LOW and CRITICAL cases, out-of-range inputs rejected, explanation text, every warning rule including trend and one-reading cases, data age |
| Pipeline | `tests/test_pipeline.py` | 7 | Bad rows dropped (missing, negative, duplicate, sum mismatch), missing columns rejected, statistics (moving average, OLS, Mann-Kendall, IMD categories), anomaly definition, point-in-polygon and simplification, indicator provenance validation, byte-identical reruns, ward-area sanity check |
| Migrations | `tests/test_migrations.py` | 2 | A v1 database upgrades to v2 with categories mapped; migrate is idempotent |
| ML | `ml/tests/test_ml.py` | 10 | Loading and validation, training-only climatology, feature definitions, artifact metadata, internally consistent metrics, **JSON inference equals scikit-learn** (classifier and Isolation Forest), explanations add up, forecast uses the selected model |
| End-to-end | `tests/e2e/test_e2e.py` | 9 | Real Chromium, own server: open → dashboard → risk explanation → map (243 wards, ward click) → report with photo → quality Safe/High/Unsafe → RWH ₹8,400 → org registers, offers, requests, match ranked #1 at 5.5 km → ML prediction with explanation → admin reviews the report → citizen sees "Verified". No JS errors, no API errors ≥ 400, no CSP violations; no sideways scroll on any tab at 320/390/768/1366 px in light and dark; keyboard Tab reaches all 7 tabs with visible focus, Enter works |
| Frontend units | `static/js/lib.test.js` | 9 | Escaping, Indian number format and minus sign, dates, relative time, season features match the server's, status and level classes, quality explanations, chart scaling, provenance text |

Counts are tests as collected by pytest (parametrised cases counted separately): 127 Python tests + 9 JavaScript tests.

`scripts/qa_audit.py` is a separate black-box check (64 checks) that talks HTTP to a running **local** server: accounts, sessions, admin authorization, report review and deletion, photo upload/view/removal, security headers and persistence across a server restart. It refuses to run against a non-local URL, and every record it creates is marked `QA-TEST-DO-NOT-KEEP` and deleted at the end.

## Failing cases the system handles (good demo material)

| Action | Result |
| --- | --- |
| Photo that isn't an image | 415 "That file isn't a photo…" |
| Report location in Mumbai | 422 "outside Bengaluru" |
| Tanker size of 7,000 L | 422 with the allowed sizes |
| Admin tries SUBMITTED → RESOLVED | 409, with the allowed next steps |
| Reservoir reading with `http://` source | 422 |
| Reservoir reading with storage > capacity | 422 |
| Reservoir reading dated in the future | 422 |
| Citizen opens `/api/admin/overview` | 403 |
| AI key invalid | Report saves, marked "not checked"; lab reader shows a clear message |
| Pipeline given a record without a source | Pipeline stops with the list of problems |
