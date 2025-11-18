# backend/main.py
from __future__ import annotations

import os
import ssl
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# ────────────────────────────────────────────────────────────────────────────────
# App
# ────────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="TG WebApp Backend", version="1.2.0")

# ────────────────────────────────────────────────────────────────────────────────
# Static (favicon, assets)
# ────────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ────────────────────────────────────────────────────────────────────────────────
# CORS — максимально либеральный, чтобы ничего не блокировало WebApp
# ────────────────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",  # разрешаем любые http/https origin'ы
    allow_credentials=False,            # куки не используем
    allow_methods=["*"],                # GET, POST, PATCH, DELETE, OPTIONS и т.д.
    allow_headers=["*"],                # любые заголовки, включая X-Telegram-Id
)

# ────────────────────────────────────────────────────────────────────────────────
# Database (asyncpg + TLS)
# ────────────────────────────────────────────────────────────────────────────────
# В .env у тебя, например:
# DATABASE_URL=postgresql+asyncpg://user:pass@host:port/dbname?
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

engine: create_async_engine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None

if DATABASE_URL:
    connect_args: dict = {}

    # Для asyncpg нужен ssl-объект, а не sslmode в URL
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        connect_args["ssl"] = ssl.create_default_context()

    engine = create_async_engine(
        DATABASE_URL,
        connect_args=connect_args or None,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
    )
    SessionLocal = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    # кладём фабрику сессий в state — backend/api.py её использует
    app.state.sessionmaker = SessionLocal


# ────────────────────────────────────────────────────────────────────────────────
# API router
# ────────────────────────────────────────────────────────────────────────────────
from backend import api as api_module  # noqa: E402

app.include_router(api_module.router, prefix="/api")


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
    # совместимость со старым фронтом: и status, и database
    return {"status": "ok", "database": "ok"}


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
