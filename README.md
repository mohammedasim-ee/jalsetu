# JalSetu: water security for Bengaluru

A full-stack web app: a **Python (FastAPI) backend with a database** (PostgreSQL when deployed, SQLite on a laptop) plus a mobile-first website.

| Module | What it does | Where the data comes from |
| --- | --- | --- |
| Early warning | Rain deficit + reservoir storage + groundwater balance → Alert / Watch | IMD, reservoir reports, WELL Labs (`app/data/signals.json`) |
| Citizen reports | Dry borewells, sewage, tanker prices, with photos, shared by everyone | Users, stored in the database |
| Treated-water exchange | Apartments with surplus STP water matched to nearby buyers | Users; BWSSB ₹10/kL price |
| Water quality | Lab values checked against IS 10500:2012 | BIS standard (`app/rules.py`) |
| Rainwater planner | BWSSB rules: mandatory or not, tank size, yearly harvest | BWSSB rules, rainfall averages |
| AI (optional) | Checks report photos; reads lab-report photos | Needs `ANTHROPIC_API_KEY` |

The AI only reads photos. Every decision (safe/unsafe, mandatory, counted in hotspots) is made by the official rules in `app/rules.py`.

## Project structure

```
app/main.py         API routes, database (Postgres or SQLite), validation, rate limiting
api/index.py        Vercel entry point (vercel.json sends every request here)
app/rules.py        IS 10500 limits, BWSSB rainwater rules, matching algorithm
app/ai.py           optional AI photo checks (switched off without an API key)
app/data/signals.json  official figures for the early warning (edit to update)
static/index.html   the website (served at /)
tests/test_api.py   38 automated tests
```

## Run it on a laptop (5 minutes)

1. Install Python 3.10 or newer from python.org.
2. In a terminal, inside this folder:
   ```
   pip install -r requirements.txt
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
3. Open **http://localhost:8000**. The API list is at **http://localhost:8000/api** (works offline); interactive docs are at **/docs** (needs internet).

**Classroom demo:** connect the laptop and phones to the same Wi-Fi or hotspot. Find the laptop's IP address (Windows: `ipconfig`, Mac: System Settings → Wi-Fi → Details). Classmates open `http://<laptop-ip>:8000` on their phones, and everyone's reports appear for everyone.

## Run the tests

```
pip install -r requirements-dev.txt
pytest -q
```

## Put it online with Vercel (free)

1. Sign in at **vercel.com** with your GitHub account → **Add New… → Project** → import this repository → **Deploy**. `vercel.json` sets everything up.
2. **Add a database so reports are kept and shared:** in the Vercel project open **Storage → Create Database → Neon (Postgres)** → connect it to the project. Vercel adds `DATABASE_URL` automatically.
3. **Deployments → ⋯ → Redeploy** so the app picks up the database. The site is at `https://<project-name>.vercel.app`.
4. Optional: **Settings → Environment Variables** → add `ANTHROPIC_API_KEY` (AI photo checks) and `ADMIN_TOKEN` (moderator key), then redeploy.

Without step 2 the site still works, but it stores data in temporary server storage, so reports can disappear when Vercel restarts the function.
Photos are shrunk in the browser before upload because Vercel limits a request to about 4.5 MB.

## Put it online with Render (alternative)

1. Create a GitHub account and a new repository; upload this folder's files (the "Add file → Upload files" button works from a phone browser).
2. Create a free account at render.com → **New → Blueprint** → pick the repository. `render.yaml` sets everything up.
3. Render gives you a public link like `https://jalsetu.onrender.com`.

Limits of the free plan to know about:
- The server sleeps after about 15 minutes without visitors; the first visit after that takes up to a minute to wake it.
- The free plan's disk is not permanent: **reports and listings are wiped when the server restarts or redeploys.** For data that must last, add a persistent disk (paid) or move to a hosted database.

## Settings (environment variables)

| Name | Purpose |
| --- | --- |
| `ADMIN_TOKEN` | Moderator key. Send it as the `x-admin-token` header to delete any report or listing. |
| `ANTHROPIC_API_KEY` | Optional. Switches on AI photo checks and lab-report reading (paid per use). |
| `JALSETU_AI_MODEL` | Optional. Defaults to `claude-haiku-4-5-20251001`. |
| `DATABASE_URL` | PostgreSQL connection string (set automatically by Vercel's Neon integration). If empty, SQLite is used. |
| `JALSETU_DB` | Path of the SQLite file. Defaults to `jalsetu.db` in this folder. |

## API summary

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server status, AI on/off, counts |
| GET | `/api/signals` | Early-warning figures and computed alert levels |
| GET / POST | `/api/reports` | List / create a report (multipart form; optional photo up to 8 MB) |
| GET | `/api/reports/{id}/photo` | Report photo (resized JPEG) |
| DELETE | `/api/reports/{id}` | Moderator only |
| GET | `/api/hotspots` | Areas with most reports in the last 30 days; average tanker price |
| GET / POST | `/api/listings` | List / add a treated-water listing (returns an `edit_token` once) |
| DELETE | `/api/listings/{id}` | Owner (`x-edit-token`) or moderator |
| GET | `/api/match` | Nearest-first matching of supply and demand, with savings |
| POST | `/api/quality/check` | IS 10500 check of lab values |
| POST | `/api/rwh` | BWSSB rainwater harvesting plan |
| POST | `/api/ai/lab-report` | AI reads a lab-report photo (needs API key) |

Safety built in: input validation on every route, photo type and size checks, 30 writes per device per 10 minutes, owner-only deletes, HTML shown as text (no script injection), clear error messages instead of server crashes.

## Updating the early warning

Edit `app/data/signals.json` with the newest IMD rainfall and reservoir figures (keep the `as_of` date and source). The alert levels are recalculated automatically.
