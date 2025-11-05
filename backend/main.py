import os
import ssl
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# ────────────────────────────────────────────────────────────────────────────────
# App
# ────────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="TG WebApp Backend", version="1.1.0")

# ────────────────────────────────────────────────────────────────────────────────
# Static (favicon, assets)
# ────────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ────────────────────────────────────────────────────────────────────────────────
# CORS (env-driven)
# ────────────────────────────────────────────────────────────────────────────────
def split_env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]

ALLOWED_ORIGINS = split_env_list("ALLOWED_ORIGINS")
ALLOWED_ORIGIN_REGEX = os.getenv("ALLOWED_ORIGIN_REGEX", "").strip()

if ALLOWED_ORIGIN_REGEX:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=ALLOWED_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ────────────────────────────────────────────────────────────────────────────────
# Database (asyncpg + TLS)
# ────────────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

connect_args = {}
# Render Postgres требует TLS — включаем явно.
connect_args["ssl"] = ssl.create_default_context()

engine = create_async_engine(
    DATABASE_URL,
    connect_args=connect_args,   # работает и когда ?ssl=true, и когда параметров нет
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=0,
) if DATABASE_URL else None

# ────────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return """
    <!doctype html>
    <html lang="ru">
    <head><meta charset="utf-8"><title>TG WebApp Backend</title></head>
    <body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;padding:24px">
      <h1>✅ Backend работает</h1>
      <ul>
        <li><a href="/docs">/docs</a> — Swagger</li>
        <li><a href="/redoc">/redoc</a> — ReDoc</li>
        <li><a href="/health">/health</a> — Health</li>
        <li><a href="/health/db">/health/db</a> — Health DB</li>
      </ul>
    </body>
    </html>
    """

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

@app.get("/health/db")
async def health_db() -> dict:
    if engine is None:
        return {"db": "skipped", "detail": "DATABASE_URL is not set"}
    try:
        async with engine.connect() as conn:
            r = await conn.execute(text("SELECT 1"))
            _ = r.scalar_one()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "detail": str(e)}

@app.get("/favicon.ico")
async def favicon() -> Response:
    ico = STATIC_DIR / "favicon.ico"
    if ico.exists():
        return FileResponse(ico, media_type="image/x-icon")
    return Response(status_code=204)

# ────────────────────────────────────────────────────────────────────────────────
# Minimal API stub (чтобы фронт не падал)
# ────────────────────────────────────────────────────────────────────────────────
@app.get("/api/categories")
async def list_categories() -> list[dict]:
    return []
