"""Package Buddy Redux server: FastAPI app factory."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import __version__, config, db, tracking
from .api import admin, auth, misc, packages
from .models import User
from .security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines would be noisy
log = logging.getLogger("packagebuddy")

DESCRIPTION = """
Self-hosted tracking server for Package Buddy Redux.

**Getting started:** call `POST /api/v1/auth/login` with the admin username and
password (or click **Authorize** above after logging in and paste the token).
For apps or Mira, create a long-lived token with `POST /api/v1/tokens`.

All tracking goes through 17TRACK with one shared key, so a number tracked by
several people is registered (and counted against the quota) only once.
"""


class NoCacheIndexStatic(StaticFiles):
    """Static files; index/bootstrap files are revalidated so updates show up after a rebuild."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        name = os.path.basename(path)
        if name in ("", ".", "index.html", "flutter_bootstrap.js", "flutter_service_worker.js",
                    "version.json", "manifest.json", "main.dart.js"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def bootstrap_admin() -> None:
    s = config.settings
    with db.session_scope() as d:
        if d.scalar(select(func.count(User.id))):
            return
        if not (s.admin_username and s.admin_password):
            log.warning("No users yet. Set ADMIN_USERNAME and ADMIN_PASSWORD and restart to create the admin.")
            return
        d.add(User(username=s.admin_username, password_hash=hash_password(s.admin_password), is_admin=True))
        log.info("Created admin user '%s'", s.admin_username)


def create_app(start_poller: bool | None = None) -> FastAPI:
    s = config.settings
    poller: tracking.Poller | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal poller
        db.init_engine(s.db_path)
        bootstrap_admin()
        if not tracking.get_client().configured:
            log.warning("TRACK17_API_KEY is not set: tracking is disabled until you add it.")
        if (s.enable_poller if start_poller is None else start_poller):
            poller = tracking.Poller(s.poll_interval_minutes)
            poller.start()
        yield
        if poller:
            poller.stop()

    app = FastAPI(title="Package Buddy Redux Server", version=__version__, description=DESCRIPTION,
                  lifespan=lifespan, docs_url="/docs", redoc_url="/redoc",
                  openapi_url="/api/v1/openapi.json")
    for r in (auth.router, packages.router, admin.router, misc.router):
        app.include_router(r, prefix="/api/v1")

    web_dir = s.web_dir
    index = os.path.join(web_dir, "index.html")
    if os.path.isfile(index):
        # The Flutter web app, same origin as the API (no CORS needed).
        @app.get("/", include_in_schema=False)
        def home_app():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        app.mount("/", NoCacheIndexStatic(directory=web_dir, html=True), name="web")
        log.info("Serving the web app from %s", web_dir)
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def home():
            return HOME_HTML

    return app


HOME_HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Package Buddy Redux Server</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font-family: system-ui, sans-serif; margin: 0; background: #0f131a; color: #e8e8e8; }}
 main {{ max-width: 640px; margin: 10vh auto; padding: 2rem; background: #181e28; border-radius: 12px;
        border-left: 10px solid #1565c0; }}
 h1 {{ margin-top: 0; }} a {{ color: #6ab0ff; }} code {{ background:#33373d; padding: 2px 6px; border-radius: 4px; }}
</style></head>
<body><main>
<h1>Package Buddy Redux Server</h1>
<p>The server is running (version {__version__}), but the web app files were not found in this image. Rebuild the image from the full folder (it includes <code>app/web</code>).</p>
<p>Until then you can explore and use everything from the interactive API page:
<a href="/docs">open the API docs</a>.</p>
<p>Health check: <a href="/api/v1/health"><code>/api/v1/health</code></a></p>
</main></body></html>"""

app = create_app()
