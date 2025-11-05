# backend/main.py
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse
from dotenv import load_dotenv

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker

# ── загрузим .env ПЕРЕД импортом роутера ──────────────────────────────────────
load_dotenv()

from backend.api import router as api_router  # теперь MODERATOR_IDS прочитается корректно

# ── env ───────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан в .env")

RAW_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: List[str] = [o.strip() for o in RAW_ALLOWED_ORIGINS.split(",") if o.strip()]
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
BACKEND_VERSION = "0.1.0"

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("tg_shop.backend")

# ── DB (без startup-хуков) ───────────────────────────────────────────────────
engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True, future=True)
SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(bind=engine, expire_on_commit=False)

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="TG Shop Backend")
app.state.sessionmaker = SessionFactory  # для backend/api.py

cors_origins = ALLOWED_ORIGINS or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── схемы ответов ─────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    time_utc: str
    database: str

class ConfigResponse(BaseModel):
    webapp_url: Optional[str] = None
    allowed_origins: List[str] = []
    backend_version: str
    now_utc: str

# ── маршруты ──────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "failed"

    return JSONResponse(
        HealthResponse(
            status="ok",
            time_utc=datetime.now(timezone.utc).isoformat(),
            database=db_status,
        ).model_dump()
    )

@app.get("/api/config", response_model=ConfigResponse, tags=["system"])
async def get_config() -> JSONResponse:
    return JSONResponse(
        ConfigResponse(
            webapp_url=WEBAPP_URL or None,
            allowed_origins=cors_origins,
            backend_version=BACKEND_VERSION,
            now_utc=datetime.now(timezone.utc).isoformat(),
        ).model_dump()
    )

@app.get("/", tags=["system"])
async def root():
    return {"ok": True, "msg": "TG Shop Backend is running"}

# CRUD роуты
app.include_router(api_router, prefix="/api")

# Запуск: uvicorn backend.main:app --reload --port 9010
