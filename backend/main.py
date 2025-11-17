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
# CORS
# ────────────────────────────────────────────────────────────────────────────────
def split_env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


# Домены фронта/вебхуков по умолчанию
DEFAULT_ALLOWED_ORIGINS: list[str] = [
    # Vercel фронтенд WebApp
    "https://tgwebapp-chi.vercel.app",
    # Render-бэкенд как origin (если вдруг будешь открывать оттуда что-то в браузере)
    "https://tg-webapp-e4pr.onrender.com",
]

ALLOWED_ORIGINS = split_env_list("ALLOWED_ORIGINS") or DEFAULT_ALLOWED_ORIGINS

# Здесь без allow_origin_regex — он тебе не нужен сейчас
# И без credentials, чтобы можно было спокойно использовать любой набор доменов
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,   # либо из .env, либо DEFAULT_ALLOWED_ORIGINS
    allow_credentials=False,         # cookies/авторизацию не используем → отключаем
    allow_methods=["*"],             # разрешаем все методы: GET, POST, OPTIONS и т.д.
    allow_headers=["*"],             # разрешаем все заголовки, включая X-Telegram-Id
)


# ────────────────────────────────────────────────────────────────────────────────
# Database (asyncpg + TLS)
# ────────────────────────────────────────────────────────────────────────────────
# В .env у тебя:
# DATABASE_URL=postgresql+asyncpg://.../tg_shop_db_jerq?
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()  # postgresql+asyncpg://...

engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None

if DATABASE_URL:
    # Для asyncpg нужен объект ssl, а не sslmode в URL
    connect_args: dict = {}

    # На всякий случай включаем TLS только для asyncpg-схемы
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        connect_args["ssl"] = ssl.create_default_context()

    engine = create_async_engine(
        DATABASE_URL,
        connect_args=connect_args or None,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
    )
    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    # положим фабрику сессий в state — её подхватывает backend/api.py
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
    # совместимость со старым фронтом: возвращаем и status, и pseudo-database
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
