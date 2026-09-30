# JalSetu

Water-security and early-warning platform for Bengaluru: FastAPI + PostgreSQL (Neon) on Vercel, vanilla JS frontend. Live at https://jalsetu-smoky.vercel.app. The project report is `docs/PROJECT_REPORT.md`; data provenance is `DATA_SOURCES.md`; ML results are `MODEL_REPORT.md`.

## Commands

```
pip install -r requirements-dev.txt
uvicorn app.main:app --reload                   # local server (SQLite); set ADMIN_EMAIL/ADMIN_PASSWORD for /admin
pytest                                          # all Python tests incl. Playwright end-to-end (127)
DATABASE_URL=<empty local Postgres> pytest --ignore=tests/e2e   # same suite on PostgreSQL
node --test static/js/lib.test.js               # frontend unit tests (9)
ruff check . && python -m mypy                  # must stay clean
python pipeline/run_pipeline.py                 # rebuild data/processed (deterministic)
python ml/train.py                              # retrain + re-evaluate (needs requirements-ml.txt)
python scripts/gen_api_docs.py                  # regenerate API.md after changing endpoints
QA_BASE=http://127.0.0.1:8850 QA_ADMIN_EMAIL=... QA_ADMIN_PASSWORD=... python scripts/qa_audit.py   # local only
```

## Non-negotiable rules

1. **No fabricated data or metrics.** Every figure needs a source, URL, date and status (`historical`, `modelled`, `live`, `demonstration`, `manually uploaded`, `unavailable`). If data doesn't exist, show "unavailable"; never invent it. Demo rows exist only with `JALSETU_DEMO=1`, are marked DEMO and never count toward the score.
2. **ML numbers come only from `ml/train.py`** (`ml/artifacts/metrics.json`). Report results honestly, including where a model loses to a baseline.
3. **Database:** keep PostgreSQL in production and SQLite locally through `app/db.py`; the same SQL must run on both. Schema changes are new, append-only entries in `MIGRATIONS`; never edit an applied migration. Every value is a bound parameter.
4. **Security:** authorization is enforced on the server (`auth.require(...)`), never only in the UI. Never log or return passwords, tokens, hashes or connection strings. Don't weaken the CSP (`script-src 'self'`: no inline scripts, no `eval`). Uploads go through `common.to_jpeg` (8 MB, 60 MP, re-encode).
5. **Photos live in `reports.photo`** (database), not on disk: Vercel's filesystem is temporary.
6. **Never delete or change production data** to test something. Use local servers and records marked `QA-TEST-DO-NOT-KEEP`.
7. **Risk weights and anchors** live in `config/risk_config.json`; document any change in `docs/water-risk-methodology.md`.
8. **Keep the existing UI and features.** Fix in place; no rewrites or new frameworks without asking.
9. **Diagnose → test → fix → verify.** Add a regression test that fails without the fix. Run the full suite before committing, and update the counts in README.md, TESTING.md and DEMO_SCRIPT.md if they change.

## Deploying

Vercel deploys every push to `main`, but only for commits authored with the owner's GitHub noreply email (`226057725+mohammedasim-ee@users.noreply.github.com`). Environment-variable changes need a redeploy. After deploying, check `/api/health` (`"database":"postgres"`, `schema_version`) and `/api/admin-setup-status`.
