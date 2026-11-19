# Deploying M MUSICS to Vercel

This Flask app is configured for **zero-config deployment on Vercel**.

## How Vercel detects this project

Vercel's Python runtime looks for, and this repo provides, all four:

| Requirement | Where it lives | Notes |
| --- | --- | --- |
| **Dependencies list** | `requirements.txt` (repo root) | Vercel runs `pip install -r requirements.txt` at build time |
| **Standard entrypoint** | `app.py` (repo root) + `api/index.py` (alternative) | Both are recognized names in recognized locations; both expose the same `app`. `vercel.json` routes to `app.py` by default |
| **Exposed app variable** | `app = Flask(...)` at module top level | Vercel mounts this WSGI object; no `gunicorn` needed |
| **Static files on the CDN** | `public/` folder | Vercel serves every file under `public/` straight from the edge, no function invocation. Assets live in `public/static/` and are referenced as `/static/...` (e.g. `/static/style.css`, `/static/img/musicians.jpg`) |

## Required files & standard naming

Vercel's Python runtime scans specific folders for specific filenames. This is
the contract, and where this repo satisfies each part:

### Where Vercel looks (folder)

| Folder | Status in this repo |
| --- | --- |
| **Repo root** (`/`) | ✅ `app.py` lives here — the primary entrypoint |
| `api/` | ✅ `api/index.py` — alternative entrypoint (re-exports the same `app`) |
| `src/` | not used |
| `app/` | not used (would clash with the Flask `app` variable name) |

### What Vercel recognizes (filename)

Vercel only auto-detects these **exact** filenames. A custom name like
`bot.py` or `run.py` will **not** be found unless you add a custom path in
`vercel.json`.

| Recognized filename | Present in this repo? |
| --- | --- |
| `app.py` | ✅ `/app.py` (root) — **active entrypoint** |
| `index.py` | ✅ `/api/index.py` (api folder convention) |
| `main.py` | — |
| `server.py` | — |
| `wsgi.py` | — |
| `asgi.py` | — |
| `manage.py` | — (Django-only; Vercel also auto-detects this for Django) |

### Required files (the full set Vercel needs)

| File | Purpose | In this repo |
| --- | --- | --- |
| `requirements.txt` | Dependency list; Vercel runs `pip install -r requirements.txt` | ✅ root |
| `app.py` (or other recognized name) | Entrypoint exposing the top-level `app` (or `application`) variable | ✅ root |
| `vercel.json` | Build + routing config (optional but recommended) | ✅ root |
| `public/` | Static assets served from the CDN (optional) | ✅ `public/static/` |
| `.python-version` | Pins the Python runtime (optional) | ✅ root |
| `.vercelignore` | Excludes dev/test files from the deploy bundle (optional) | ✅ root |

### Common mistakes avoided here

- **Custom entrypoint name.** The file is `app.py`, not `run.py` / `bot.py` /
  `start.py` — Vercel finds it with zero config.
- **Entry point not in a scanned folder.** It sits in the repo root (and a
  second copy lives under `api/`), both of which Vercel scans.
- **No top-level `app` variable.** `app = Flask(...)` is defined at module
  top level, so Vercel mounts it directly.
- **Two functions fighting.** Both entrypoints import the *same* Flask `app`
  object — there is one application, not two. `vercel.json` rewrites traffic to
  `app.py`; switch the rewrite's `destination` to `api/index.py` if you prefer
  that convention.

## Routes (see `vercel.json`)

- Files under `public/` are served first by Vercel's CDN (highest priority).
- Everything else is rewritten to the `app.py` serverless function, where Flask handles the dynamic routes (`/`, `/hire/<cat>`, `/provider/<id>`, `/admin`, etc.).

## Deploy

```bash
npm i -g vercel        # one-time
cd m_musics_vercel
vercel                  # preview deploy
vercel --prod           # production
```

Or push the folder to a Git repo and import it at <https://vercel.com/new>.

## Required environment variables (set in Vercel → Project → Settings → Environment Variables)

| Var | Purpose |
| --- | --- |
| `SECRET_KEY` | **Required.** Flask session signing key. Generate with `python -c "import secrets;print(secrets.token_hex(32))"`. |
| `DATABASE_URL` | **Required for production.** A managed PostgreSQL URL, e.g. `postgresql://user:pass@host:5432/mmusics`. Without it the app falls back to SQLite in the ephemeral `/tmp` — data is lost on every cold start. Use Neon, Supabase, Vercel Postgres, etc. |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | First super-admin account, auto-created on first run. |
| `ADMIN_PASSWORD` | Password for the seeded `admin@mmusics.local` account. |
| `PAYMENT_MODE` | `demo` (default, payments always succeed) or `live` (implement `charge()` in `app.py`). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Enable email notifications (optional). |
| `UPLOAD_DIR` | Override the upload directory. Defaults to `/tmp/mmusics_uploads/uploads` on Vercel. For persistence across requests, point this at an object store mount (S3 via a fuse layer, Cloudinary, etc.). |

## ⚠️ Serverless constraints (read before going live)

Vercel functions are **read-only** except for `/tmp`, and the filesystem is **not shared between invocations**. This affects two parts of the app:

1. **Database.** If `DATABASE_URL` is unset, the app writes its SQLite file to `/tmp/mmusics.db`. That file exists only for the life of one warm instance and is rebuilt on each cold start — fine for a demo, useless for production. **Always set `DATABASE_URL` to a real Postgres in production.**
2. **Uploaded files (artist photos, audio, product images).** These are written to `/tmp/mmusics_uploads/uploads` and served from `/media/<name>`. On Vercel they disappear when the instance recycles and are not visible to other instances. For production, move uploads to S3/R2/Cloudinary and rewrite the `/media/<name>` route (and `save_upload()`) to fetch from there.

The module-level `init_db()` call that creates tables and seeds demo data is wrapped in a try/except, so a read-only or unavailable database never crashes a cold start — it logs a warning and continues.

## Run locally (unchanged from the original)

```bash
pip install -r requirements.txt
python app.py          # http://127.0.0.1:5000
python tests/smoke_test.py
```

Locally the SQLite file and uploads sit next to `app.py` (the original behavior); the `/tmp` redirection only activates when `VERCEL=1` is set at runtime, which Vercel does automatically.
