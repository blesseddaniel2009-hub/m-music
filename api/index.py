"""Vercel entrypoint under the standard `api/` folder convention.

Vercel auto-detects Python entrypoints in the repo root OR inside a `src/`,
`app/`, or `api/` folder, provided the file has one of the recognized names:
`app.py`, `index.py`, `server.py`, `main.py`, `wsgi.py`, or `asgi.py`.

This repo already ships the primary entrypoint at the repo root
(`app.py`, exposing the top-level `app` Flask object). This file is an
**alternative** entrypoint that Vercel can also find at `api/index.py`: it simply
re-exports the same Flask app, so there is no duplicate application logic and no
risk of two serverless functions conflicting.

Use whichever convention you prefer:
  - Root convention  -> https://<project>.vercel.app/  served by app.py
  - api/ convention  -> https://<project>.vercel.app/  served by api/index.py

The `vercel.json` rewrites all non-static traffic to `app.py` by default. If you
would rather deploy under the `api/` convention, change that rewrite's
`destination` from `app.py` to `api/index.py` (both expose the same `app`).
"""

# Re-use the single source of truth: the Flask app defined in /app.py.
# `app.py` is on the Python path because the repo root is the working directory
# for the Vercel build step.
import os
import sys

# Make the repo root importable when this file is the entrypoint.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app import app  # noqa: E402  (re-export below)

# `app` is the top-level variable Vercel mounts as the WSGI handler.
__all__ = ["app"]
