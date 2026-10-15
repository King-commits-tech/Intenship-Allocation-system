# AI-Based Internship Allocation System (InternAlloc AI)

A complete Flask web application that helps a college placement cell, students and recruiters manage
internships. Students build a profile or upload a PDF resume; a **local, explainable matching engine**
scores every internship from 0–100 with reasons and missing skills; administrators run a **stable,
preference-aware allocation** within seat limits, preview it, and confirm it in a single transaction.

> Recommendations and scores **assist decision-making**. They do not guarantee selection or employment.
> No paid AI service or API key is needed — everything runs locally.

---

## Contents
1. [Features](#1-features)
2. [Technology stack](#2-technology-stack)
3. [Folder structure](#3-folder-structure)
4. [Prerequisites](#4-prerequisites)
5. [Installation — Method A: local (Windows / Linux / macOS)](#5-installation--method-a-local)
6. [Database configuration (SQLite or MySQL)](#6-database-configuration)
7. [Environment variables](#7-environment-variables)
8. [Demo accounts](#8-demo-accounts)
9. [Installation — Method B: Docker](#9-installation--method-b-docker)
10. [Running tests](#10-running-tests)
11. [How the AI matching works](#11-how-the-ai-matching-works)
12. [How allocation works](#12-how-allocation-works)
13. [REST API reference](#13-rest-api-reference)
14. [Troubleshooting](#14-troubleshooting)
15. [Verification status, limitations and future scope](#15-verification-status-limitations-and-future-scope)

---

## 1. Features

**Students**
- Register / log in; edit profile (degree, department, year, CGPA/percentage, skills, interests, projects, experience, certifications, preferred domain & location) with a profile-completion indicator.
- Upload a PDF resume → text extraction → skill detection; detected skills are added for review and can be removed or corrected (chip editor).
- Browse internships with search, domain / mode / paid / eligible-only filters, sorting (best match, newest, deadline, stipend) and pagination.
- Personalised recommendations with score breakdown, reasons, missing skills and "skills to improve".
- Apply with a preference rank; change preference; withdraw; track status on a timeline.
- See allocation results and submit feedback on allocated internships.

**College administrator**
- Dashboard with live charts (availability by domain, application status, allocation per internship, skill demand vs supply, score distribution, 14-day activity).
- Manage students (search, view, enable/disable), companies (create, edit, verify/revoke), internships (create/edit/publish/close for any company).
- View all applications with scores; review, change status, delete invalid entries.
- Allocation centre: generate preview → inspect proposals, seat usage and reasons for non-allocation → confirm or discard; cancel allocations; manual allocation / reassignment; conflict detection (over-capacity, over-limit).
- CSV reports (students, internships, applications, allocations, per-run report); announcements; system settings (matching weights, allocation policy); audit log.

**Company / recruiter**
- Self-register (must be verified by admin before publishing) or receive an account from the admin.
- Company profile; create/edit/publish/close internships with required & preferred skills, eligibility (min CGPA, departments, years), seats, duration, stipend, deadline.
- Ranked applicants with match scores and explanations; view resume (only for students who applied); shortlist / select / reject with notes.
- See candidates allocated to their internships.

**Platform**
- In-app notifications (application submitted, status changes, allocation confirmed/cancelled, internship updated, announcements); mark read / mark all read. The unread badge refreshes about every 60 s (polling, not push).
- Security: hashed passwords (Werkzeug scrypt), CSRF protection on every form and state-changing API call, server-side role checks on every route, login throttling/lock-out, session fixation protection, safe redirects, ORM-only queries, upload validation (extension + PDF magic bytes + size), random stored filenames, path-traversal protection, CSV formula-injection protection, security headers, rotating log file.

## 2. Technology stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, JavaScript, Bootstrap 5.3, Bootstrap Icons, Chart.js 4 (all **bundled locally** in `app/static/vendor`, works offline) |
| Backend | Python 3.11+ (tested on 3.13), Flask 3.1, Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, Flask-WTF (CSRF) |
| Database | MySQL 8 (primary) via PyMySQL, or SQLite (default for zero-setup development) |
| AI / NLP | scikit-learn (TF-IDF + cosine similarity), rule-based skill extraction with a configurable dictionary, pypdf for PDF text |
| Tests | pytest |
| Deployment | Docker + Docker Compose (MySQL 8 + gunicorn) |

## 3. Folder structure

```
internship-allocation-system/
├── app/
│   ├── __init__.py            # application factory, error handlers, security headers
│   ├── cli.py                 # flask init-db / seed-demo / create-admin / recompute-scores
│   ├── extensions.py          # db, migrate, login manager, CSRF
│   ├── data/skills.json       # configurable skill dictionary (canonical names + aliases)
│   ├── models/                # user, profile, internship, application (+allocation), misc
│   ├── routes/                # auth, main, student, company, admin, api (blueprints)
│   ├── services/              # matching, match_service, allocation, resume, skills,
│   │                          # applications, forms, notifications, settings, audit
│   ├── utils/                 # decorators (role_required), validators, template helpers, pdfgen
│   ├── templates/             # Jinja2 templates (public, student, company, admin, shared)
│   └── static/                # css, js, vendor (Bootstrap, Chart.js, icons)
├── migrations/                # Alembic migration scripts
├── scripts/                   # docker-entrypoint.sh, wait_for_db.py
├── tests/                     # pytest suite (71 tests)
├── instance/                  # runtime data: SQLite DB, uploads, logs (git-ignored)
├── config.py  run.py  requirements.txt  .env.example
├── Dockerfile  docker-compose.yml  .dockerignore  .gitignore
└── README.md
```

## 4. Prerequisites

- **Python 3.11, 3.12 or 3.13** (64-bit). Check with `python --version` (Windows) or `python3 --version`.
- Optional: **MySQL 8** (or MariaDB 10.6+) if you don't want SQLite.
- Optional: **Docker Desktop** (only for Method B — not required for Method A).
- No internet access is needed at runtime (the Google font falls back to system fonts when offline).

## 5. Installation — Method A: local

Unzip the project and open a terminal **inside the `internship-allocation-system` folder**.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env           # then edit .env and set SECRET_KEY
$env:FLASK_APP = "run.py"
flask init-db                         # creates all tables (SQLite: instance\internship.db)
flask seed-demo                       # optional: clearly labelled sample data + demo logins
python run.py                         # open http://127.0.0.1:5000
```

### Linux / macOS (bash / zsh)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env                  # then edit .env and set SECRET_KEY
export FLASK_APP=run.py
flask init-db
flask seed-demo                       # optional
python run.py                         # open http://127.0.0.1:5000
```

Generate a good secret key with: `python -c "import secrets; print(secrets.token_hex(32))"`.

Other useful commands (virtual environment active, `FLASK_APP=run.py`):

| Command | Purpose |
|---|---|
| `flask create-admin` | Create a real administrator account (prompts for email/password) |
| `flask recompute-scores` | Recompute cached match scores |
| `flask db upgrade` | Same as `init-db` (apply migrations) |
| `flask db migrate -m "msg"` | Generate a migration after changing models |
| `PORT=8000 python run.py` / `$env:PORT=8000; python run.py` | Use another port |

## 6. Database configuration

**SQLite (default)** — nothing to install. The database file is `instance/internship.db`.

**MySQL** — create a database and user, then set variables in `.env`:

```sql
CREATE DATABASE internship_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'internship'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON internship_db.* TO 'internship'@'localhost';
FLUSH PRIVILEGES;
```

```ini
DB_ENGINE=mysql
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=internship
MYSQL_PASSWORD=choose-a-strong-password
MYSQL_DATABASE=internship_db
```

Then run `flask init-db` (and `flask seed-demo`). Alternatively set a full `DATABASE_URL`
(e.g. `mysql+pymysql://user:pass@host:3306/internship_db?charset=utf8mb4`), which overrides the rest.
Special characters in `MYSQL_PASSWORD` are URL-encoded automatically.

## 7. Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | dev placeholder | **Required in production.** Signs sessions & CSRF tokens. |
| `FLASK_CONFIG` | `development` | `development` or `production` (production refuses to start without `SECRET_KEY`). |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Dev server bind address. |
| `DB_ENGINE` | `sqlite` | `sqlite` or `mysql`. |
| `SQLITE_PATH` | `instance/internship.db` | SQLite file location. |
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | — | MySQL connection. |
| `DATABASE_URL` | — | Full SQLAlchemy URL (overrides the above). |
| `UPLOAD_FOLDER` | `instance/uploads` | Where resumes are stored (outside `static`, never served directly). |
| `MAX_RESUME_MB` | `2` | Resume size limit. |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCK_MINUTES` | `5` / `10` | Account lock-out after failed logins. |
| `SESSION_COOKIE_SECURE` | `false` (dev) / `true` (prod) | Send session cookie only over HTTPS. |
| `SKILLS_FILE` | `app/data/skills.json` | Custom skill dictionary. |
| `PAGE_SIZE` | `9` | Internship cards per page. |
| `LOG_LEVEL` | `INFO` | Logs go to `instance/logs/app.log`. |

## 8. Demo accounts

Created by `flask seed-demo` (refuses to run if users already exist; never deletes data). All seeded
companies are suffixed **“(Sample)”** and sample internships/resumes are labelled as demo data.

| Role | Email | Password |
|---|---|---|
| Admin | `admin@demo.local` | `Admin@123` |
| Company | `company1@demo.local` … `company4@demo.local` (company4 is unverified) | `Company@123` |
| Student | `student1@demo.local` … `student12@demo.local` | `Student@123` |

⚠️ These credentials are for **local testing only**. Do not seed demo data on a deployed system; create a
real admin with `flask create-admin`.

**Suggested demo walkthrough:** log in as `student12` → Recommendations → apply → log in as `company2`
→ Internships → Applicants → shortlist → log in as `admin` → Allocation → *Generate preview* → *Confirm*
→ back as the student: Allocation & Feedback shows the result and a notification.

## 9. Installation — Method B: Docker

Requires Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 (Linux).

```bash
cp .env.example .env            # Windows: Copy-Item .env.example .env
# edit .env: set SECRET_KEY, MYSQL_PASSWORD and add MYSQL_ROOT_PASSWORD=<something>
docker compose up --build       # first start takes a few minutes
# open http://localhost:5000
```

- Services: `db` (MySQL 8 with a health check) and `web` (gunicorn). `web` waits until MySQL is healthy, then
  `scripts/wait_for_db.py` double-checks connectivity, runs migrations and (when `SEED_DEMO=1`, the default)
  seeds demo data once.
- Data persists in the `mysql_data` and `uploads` volumes. `docker compose down` keeps data;
  `docker compose down -v` deletes it.
- Set `SEED_DEMO=0` in `.env` for a clean installation, then `docker compose exec web flask create-admin`.
- Compose refuses to start if `SECRET_KEY`, `MYSQL_PASSWORD` or `MYSQL_ROOT_PASSWORD` are missing.

## 10. Running tests

```bash
pip install -r requirements.txt
python -m pytest -q               # Windows and Linux/macOS
```

Tests use a separate in-memory SQLite database and temporary upload folders — they never touch
`instance/` data. To run them against MySQL, point `TEST_DATABASE_URL` at an **empty, dedicated** test database
(the suite drops its tables after each test):

```bash
TEST_DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/internship_test?charset=utf8mb4" python -m pytest -q
```

Coverage of the 71 tests: registration/login/lock-out/logout, password hashing, open-redirect protection,
role permissions (pages and API), cross-company access, resume access control, profile creation &
validation, internship creation/editing/publishing rules, resume validation (type, magic bytes, size,
empty, corrupt, scanned), path traversal, skill normalisation & extraction, scoring formula & weights,
eligibility rules, empty profiles, recommendations & ranking, duplicate applications (route, API and DB
constraint), status transitions, notifications, announcements, feedback, allocation (seat limits,
preferences, non-greedy behaviour, fallback to second choice, per-student limits, min score, eligibility,
company priority, deterministic ties, preview vs confirm, re-validation, atomic rollback, cancel &
reassign, conflict detection), API errors, CSRF enforcement, migrations, and a seeded render of every page.

## 11. How the AI matching works

Implemented in `app/services/matching.py` (pure functions) and `app/services/match_service.py` (database layer
and caching in `match_scores`). There is **no trained predictive model** — no genuine historical outcome data
exists — so the engine is an explainable, content-based model:

```
total = 100 × (Ws·skills + Wp·projects + Wi·interests + Wa·academics) / (Ws + Wp + Wi + Wa)
```

| Component (0–1) | Calculation |
|---|---|
| **skills** (default 50%) | `0.75 × required coverage + 0.25 × preferred coverage` (if only one list exists it gets full weight; if the internship lists no skills, TF-IDF similarity of the whole profile is used) |
| **projects** (20%) | `0.5 × share of internship skills mentioned in projects/experience/certifications + 0.5 × min(1, 2.5 × TF-IDF cosine)` |
| **interests** (15%) | `0.5 × preferred-domain match + 0.4 × min(1, 2.5 × TF-IDF cosine of interests vs internship) + 0.1 × location fit` (remote always fits; no preference = 0.5) |
| **academics** (15%) | `CGPA / 10` (or `percentage / 100`; missing → neutral 0.5 and flagged) |

- TF-IDF (scikit-learn, English stop words, 1–2-grams, sublinear TF) is fitted over all documents in each batch.
  Short-text cosine values are small, so they are scaled by 2.5 and capped at 1.
- Weights are editable in **Admin → Settings** (stored in the `settings` table) and normalised automatically.
- **Hard eligibility** (min CGPA, departments, years) applies *only* when an internship sets it. Missing optional
  skills never make a student ineligible.
- **Skill normalisation**: `app/data/skills.json` maps aliases to canonical names (JS → JavaScript, ML → Machine
  Learning, k8s → Kubernetes …). Unknown skills are kept as typed. Ambiguous words (C, R, Go, Swift, Spring,
  Express …) are extracted from resumes only when written with a capital letter, and `C` never matches inside `C++`.
- Each result includes: component scores, eligibility reasons, matched / missing required / missing preferred
  skills, strengths, gaps, suggestions and a summary label.

## 12. How allocation works

Implemented in `app/services/allocation.py`. Policy: **student-proposing deferred acceptance**
(Gale–Shapley, many-to-many with capacities):

1. Candidates = applications with status submitted/shortlisted/selected (or only shortlisted/selected if the
   setting is on), to published or closed internships, where the student is eligible and the score ≥
   *minimum match score* (default 30).
2. Each student ranks applications by their **preference rank** (ties: higher score, then internship id).
3. Each internship ranks candidates by: company review tier (selected > shortlisted > submitted) → match score
   → CGPA → earlier application → lower student id (fully deterministic tie-breaking).
4. Capacity = seats − active allocations; each student can hold at most *max allocations per student*
   (default 1) minus what they already hold.
5. Students propose in order; internships keep the best candidates within capacity. The result is **stable**:
   no student/internship pair would both prefer each other to what they received. It is *not* greedy — a top
   scorer who prefers another internship does not block a seat they don't want.

**Preview → confirm.** A run first creates *proposed* rows only (no notifications, no seats taken). Confirming
re-validates every proposal (application still pending, seats left, limits, duplicates) inside one database
transaction; if anything raises, everything rolls back and the run is marked *failed*. Other open previews are
discarded on confirmation. Admins can cancel allocations (application returns to the pool) and manually
allocate/reassign with the same seat and limit checks. Every run records its parameters, summary, timestamps
and reasons for each unallocated student, and can be downloaded as CSV.

## 13. REST API reference

All endpoints are under `/api`, return JSON, and use the same session cookie as the web UI.
**State-changing requests (POST/PATCH) need an `X-CSRFToken` header** from `GET /api/csrf-token`.
Fetch a new token *after* logging in.

Error format (all errors, including unknown `/api/*` paths): `{"error": "message", "status": <code>}` with
`400` invalid input/CSRF, `401` not logged in, `403` wrong role, `404` not found / not visible to you,
`409` conflict (duplicate application, invalid status transition, run not in preview), `413` file too large,
`503` database unavailable.

Example session (Linux/macOS; cookies kept in `cj`):

```bash
T=$(curl -s -c cj -b cj http://127.0.0.1:5000/api/csrf-token | python3 -c "import sys,json;print(json.load(sys.stdin)['csrf_token'])")
curl -s -c cj -b cj -H "X-CSRFToken: $T" -H "Content-Type: application/json" \
     -d '{"email":"student1@demo.local","password":"Student@123"}' http://127.0.0.1:5000/api/auth/login
curl -s -b cj "http://127.0.0.1:5000/api/recommendations?limit=3"
T=$(curl -s -c cj -b cj http://127.0.0.1:5000/api/csrf-token | python3 -c "import sys,json;print(json.load(sys.stdin)['csrf_token'])")
curl -s -b cj -H "X-CSRFToken: $T" -H "Content-Type: application/json" \
     -d '{"internship_id": 2, "preference_rank": 2}' http://127.0.0.1:5000/api/applications
```

| Method & path | Roles | Description |
|---|---|---|
| `GET /api/health` | public | `{"status":"ok","database":"ok"}` or 503. |
| `GET /api/csrf-token` | public | `{"csrf_token": "..."}` |
| `POST /api/auth/login` | public | Body `{"email","password"}` → `{"user": {...}}`; 401 on bad credentials / locked / disabled. |
| `POST /api/auth/logout` | any | Ends the session. |
| `GET /api/me` | any | Current user, role profile, unread notification count. |
| `GET /api/internships` | any | Query: `q`, `domain`, `skill`, `status` (admin), `page`, `per_page` (≤50). Students see published only (with `match_score`, `eligible`); companies see their own. Returns `{items, page, pages, total}`. |
| `GET /api/internships/<id>` | any | Details (+ `match` explanation for students). Drafts hidden from students, other companies' internships hidden from companies. |
| `GET /api/internships/<id>/rankings` | admin, owning company | Ranked applicants with score, eligibility, components, matched/missing skills. |
| `GET /api/recommendations` | student | Query `limit` (≤50), `all=1` to include ineligible. `{items:[{internship, match}], disclaimer}` |
| `GET /api/match/<internship_id>` | student | Full match explanation for one internship. |
| `GET /api/applications` | any | Own (student), received (company), all (admin). Query `status`, `internship_id`. |
| `POST /api/applications` | student | Body `{"internship_id": int, "preference_rank"?: int, "cover_note"?: str}` → 201 `{application, match}`. 400 ineligible/closed, 404 unknown, 409 duplicate. |
| `PATCH /api/applications/<id>/status` | admin, owning company | Body `{"status": "shortlisted|selected|rejected|submitted|withdrawn", "note"?: str}`. Transition rules enforced (409 otherwise); `allocated` is reserved for allocation. |
| `GET /api/notifications` | any | Query `unread=1`. `{items, unread}` (latest 50). |
| `POST /api/notifications/<id>/read` | any | Mark one as read (own only). |
| `POST /api/notifications/read-all` | any | Mark all as read. |
| `POST /api/allocation/preview` | admin | Creates a preview run → 201 `{run_id, status, summary, proposals}`. |
| `GET /api/allocation/runs` | admin | Latest 50 runs with summaries and parameters. |
| `POST /api/allocation/runs/<id>/confirm` | admin | Confirm a preview → `{confirmed, skipped}`; 409 if not a preview. |
| `POST /api/allocation/runs/<id>/discard` | admin | Discard a preview. |
| `GET /api/allocations` | any | Active allocations visible to the caller. |
| `POST /api/allocations/<id>/cancel` | admin | Body `{"reason"?: str}`. |
| `GET /api/stats/admin` · `/api/stats/company` · `/api/stats/student` | matching role | Live chart data used by the dashboards. |
| `GET /api/students/<id>` | admin | Student profile summary. |

## 14. Troubleshooting

| Problem | Fix |
|---|---|
| `flask: command not found` / `'flask' is not recognized` | Activate the virtual environment, or use `python -m flask ...`. |
| `Error: Could not locate a Flask application` | Set `FLASK_APP=run.py` (`$env:FLASK_APP="run.py"` in PowerShell) or run from the project folder. |
| `ModuleNotFoundError: No module named ...` | `pip install -r requirements.txt` inside the activated venv. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again. |
| pip tries to compile numpy/scipy | Use 64-bit Python 3.11–3.13 and upgrade pip (`python -m pip install --upgrade pip`). |
| `no such table: users` | Run `flask init-db`. |
| `Access denied for user` / `Can't connect to MySQL server` | Check `MYSQL_*` values, that MySQL is running, the database exists and the user has privileges. |
| `RuntimeError: 'cryptography' package is required` | `pip install cryptography` (needed for MySQL 8 authentication; already in requirements). |
| `Address already in use` / port 5000 busy (macOS AirPlay uses 5000) | Start on another port: `PORT=5050 python run.py` (PowerShell: `$env:PORT=5050; python run.py`). For Docker set `PORT=5050` in `.env`. |
| "Your session form expired" after a long idle | Reload the page; CSRF tokens are tied to the session. |
| Resume uploaded but "No selectable text found" | The PDF is a scanned image; OCR is not supported. Export a text PDF or add skills manually. |
| Account locked | Wait `LOGIN_LOCK_MINUTES` (default 10). |
| Changes to `skills.json` not reflected in old scores | Admin → Settings → *Recompute scores* (or `flask recompute-scores`). |
| `seed-demo` refuses to run | The DB already has users; it never overwrites data. Use a fresh DB, or `--force` to add sample data anyway. |
| Docker: `required variable ... is missing` | Set `SECRET_KEY`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` in `.env`. |

## 15. Verification status, limitations and future scope

**What was actually verified** (Linux, Python 3.13):
- `flask init-db` + `flask seed-demo` on SQLite and on **MariaDB 10.11** (MySQL-compatible); all 71 tests pass
  on both SQLite and MariaDB.
- App served by the Flask dev server and by gunicorn in production mode; every page for every role rendered
  without errors; browser (headless Chromium) end-to-end flows: login for all roles, charts, skill editor,
  apply with confirmation dialog, allocation preview → confirm, company sees assigned candidates, mobile layout
  and menu.
- `docker compose config` validated and the container entrypoint was executed locally against MariaDB
  (including a second start that correctly skipped re-seeding).
- Dependency pins were checked to publish Python 3.11 wheels for Windows.

**Not verified here:** building/running the Docker image (no Docker daemon available), Oracle MySQL 8 itself
(MariaDB was used), Windows and macOS execution, and the PowerShell commands. They follow standard practice
but please report any issue.

**Known limitations**
- Matching is content-based (dictionary + TF-IDF); it does not understand synonyms beyond the dictionary or deep
  semantics. No trained model is used because there is no historical outcome data.
- Resume parsing supports text-based PDFs only (no OCR, no DOCX).
- Notifications are in-app only (no e-mail); the badge updates by polling every 60 s.
- Timestamps are stored and shown in UTC.
- Login throttling is per account (no IP-based rate limiting).
- Feedback is stored and shown to admins but not yet used to improve matching.

**Future scope** (architecture ready, not implemented): semantic matching with sentence embeddings, multilingual
profiles, interview scheduling, resume-improvement suggestions, e-mail/SMS notifications, mobile app via the REST
API, company system integrations, internship performance tracking, placement allocation, learning-to-rank using
genuine feedback once enough historical data exists.

**Assumptions:** no project synopsis PDF was provided, so the master prompt was followed as the specification.
CGPA is on a 10-point scale; stipends are monthly in INR; one active allocation per student by default.
