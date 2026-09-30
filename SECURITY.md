# Security

## Checks performed (v2.0.0)

| Area | What JalSetu does | How it was checked |
| --- | --- | --- |
| Secrets | No keys or passwords in code. The admin account comes from `ADMIN_EMAIL` / `ADMIN_PASSWORD` environment variables; the AI key from `ANTHROPIC_API_KEY`. `.env` is git-ignored; `.env.example` is blank | Searched source and the full git history for `sk-ant` and assigned keys: none. The browser only ever calls `/api/*` on the same origin |
| Passwords | scrypt (N=2¹⁴, r=8, p=1, 16-byte random salt); compared in constant time; never logged | `test_password_hashing_never_plaintext`, `test_register_login_me_logout` (stored hash starts `scrypt$`) |
| Sessions | 32-byte random token returned once; only its SHA-256 is stored; 7-day expiry; logout deletes it | Tests check the raw token is not in the DB, and that expired and forged tokens get 401 |
| Account enumeration | Wrong password and unknown email return the identical 401 message; unknown emails are still checked against a dummy hash to even out timing | `test_login_wrong_password_and_unknown_user_same_message` |
| Authorization | Roles enforced on the server: offers need organization or admin; `/api/admin/*` needs admin; closing an offer or request needs its owner or admin. Admin accounts can't self-register | `test_admin_routes_need_admin`, `test_roles_and_validation`, ownership checks in `test_ranked_matching_ownership_and_unmet` |
| Workflow integrity | Report status changes follow a state machine (no skipping, no leaving final states); every change goes to `report_events` and `audit_logs` | `test_report_review_workflow_and_audit` |
| Injection | Every SQL value is a bound parameter. The few f-strings join only constant column lists or allow-listed table names, each marked in code | ruff `S608` reviewed line by line |
| XSS | All user text is escaped before insertion (`JL.esc`). A strict Content-Security-Policy on pages: `script-src 'self'` (no inline scripts, no eval), `frame-ancestors 'none'` | lib tests for escaping; E2E runs with the CSP and fails on any CSP violation |
| Uploads | 8 MB limit; must decode as an image; re-encoded to JPEG with Pillow (strips other content); served as `image/jpeg` | `test_report_rejects_non_image_and_huge_file` |
| Validation | Pydantic models with bounds on every write; location must be inside Bengaluru; dates must be ISO and ordered; source URLs must be https | Parametrised validation tests |
| Abuse limits | 30 writes and 10 login attempts per IP per 10 minutes; 5,000-row cap on reports | `test_rate_limit` |
| Errors | JSON errors with plain messages. Unexpected errors return a reference ID; details go only to the server log | `test_unknown_route_and_server_error_is_json` (no stack trace in the response) |
| Headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP, `X-Request-ID` | `test_security_headers_and_request_id` |
| CORS | Same-origin only by default; other origins only if listed in `CORS_ORIGINS` | Config |
| Data exposure | Public endpoints never return emails, password hashes or tokens. Reports show no reporter identity | Reviewed response models |

## Known limitations (accepted for a student project)

- **Session token in the browser.** It is kept in `localStorage`. An XSS bug could read it; escaping and CSP make that unlikely, but an httpOnly cookie with CSRF protection would be stronger.
- **Per-instance rate limits.** They are in-memory, so each serverless instance counts separately. A shared store such as Redis would be needed for strict limits.
- **Self-declared organizations.** The organization role is not verified; an admin should check organizations before trusting their offers.
- **Email existence.** Registration reveals whether an email is already registered (409).
- **No email verification or password reset.**
- **Admin changes to shared data.** Admins can add reservoir readings that change the public risk score. Every change is audit-logged with its source URL.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository, or contact the maintainer. Please don't open a public issue.
