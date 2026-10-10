"""The application: creates the FastAPI app, plugs in every router and serves the frontend.

Run it from the backend folder:

    uvicorn main:app --reload

then open http://127.0.0.1:8000 in your browser. One process serves both the
API (everything under /api/) and the pages in ../frontend, so there is nothing
else to start and no CORS to configure.

This is a single-user app with no login. It listens on 127.0.0.1 only, which
means only this computer can reach it. Do not expose it to a network as it is.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware

import config
from errors import AppError
from migrations_runner import run_migrations
from routes.ai_routes import router as ai_router
from routes.analytics_routes import router as analytics_router
from routes.dashboard_routes import router as dashboard_router
from routes.data_routes import router as data_router
from routes.lookup_routes import router as lookup_router
from routes.match_routes import router as match_router
from routes.meta_routes import router as meta_router
from routes.notebook_routes import router as notebook_router
from routes.observation_routes import router as observation_router
from routes.player_routes import router as player_router
from routes.reference_routes import router as reference_router

logger = logging.getLogger("football")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_data_dirs()
    run_migrations()  # create or upgrade the tables before the first request
    yield


app = FastAPI(title="Football Analyst & Coach", lifespan=lifespan)

# Only answer requests addressed to this machine's own name (see config.ALLOWED_HOSTS).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)

# What the pages are allowed to load. Scripts and styles only from this app, so
# text you import or paste can never run as code. Images and videos may come
# from elsewhere because player photos and match videos can be web links.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data: blob: https: http:",
    "media-src 'self' blob: https: http:",
    "frame-src https://www.youtube.com https://www.youtube-nocookie.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    # API answers are your live data: never reuse an old copy. Pages and scripts
    # may be cached but must be re-checked, so an edit shows up on the next reload.
    is_api = request.url.path.startswith("/api/")
    response.headers.setdefault("Cache-Control", "no-store" if is_api else "no-cache")
    return response


# ── Errors: always JSON, never a stack trace ─────────────────────────────────
@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    """Errors the app raised on purpose; their message is written for the user."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, **exc.extra})


@app.exception_handler(IntegrityError)
async def handle_integrity_error(request: Request, exc: IntegrityError):
    """The database refused a change (a rule in models/). Nothing was saved."""
    logger.warning("Database rule refused %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=409,
        content={"detail": "The database refused this change because it would break a rule "
                           "(for example a duplicate entry, or removing something still in use). Nothing was saved."},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    """Anything nobody planned for. The details go to the server log, not to the browser."""
    logger.exception("Unexpected error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on the server and nothing was saved. "
                           "The details are in the terminal where the server is running."},
    )


# ── API routes ───────────────────────────────────────────────────────────────
app.include_router(meta_router)
app.include_router(reference_router)
app.include_router(player_router)
app.include_router(match_router)
app.include_router(observation_router)
app.include_router(dashboard_router)
app.include_router(analytics_router)
app.include_router(notebook_router)
app.include_router(data_router)
app.include_router(lookup_router)
app.include_router(ai_router)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def unknown_api_route(path: str):
    """Keeps mistyped API addresses from falling through to the page server below."""
    return JSONResponse(status_code=404, content={"detail": f"There is no API endpoint at /api/{path}"})


# ── Frontend ─────────────────────────────────────────────────────────────────
# Mounted last: anything that is not an API route is looked up in ../frontend.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
