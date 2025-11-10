from __future__ import annotations

import os
import sys
import ssl
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlparse

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from dotenv import load_dotenv

# ── ЛОГИ АЛЕМБИКА ─────────────────────────────────────────────────────────────
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# ── ПУТЬ К ПРОЕКТУ (чтобы `import backend.models` работал при запуске alembic) ──
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../backend/alembic → <root>
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── ENV ───────────────────────────────────────────────────────────────────────
# Подхватываем переменные окружения из корня проекта (.env рядом с alembic.ini)
load_dotenv(PROJECT_ROOT / ".env")

# ── МОДЕЛИ (metadata) ─────────────────────────────────────────────────────────
from backend.models import Base  # noqa: E402

target_metadata = Base.metadata

# ── URL БД ────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL не найден. Добавь его в .env, пример: "
        "postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
    )
if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise RuntimeError(
        "Для Alembic в async-режиме используй драйвер asyncpg: "
        "DATABASE_URL должен начинаться с 'postgresql+asyncpg://'"
    )

# Чтобы alembic в логах знал URL (не обязательно, но удобно)
context.config.set_main_option("sqlalchemy.url", DATABASE_URL)

# ── НАСТРОЙКИ ВЕРСИОНИРОВАНИЯ/СРАВНЕНИЯ ───────────────────────────────────────
VERSION_TABLE = os.getenv("ALEMBIC_VERSION_TABLE", "alembic_version")
VERSION_TABLE_SCHEMA = os.getenv("ALEMBIC_VERSION_SCHEMA", None)  # например, 'public'

COMPARE_TYPES = True
COMPARE_SERVER_DEFAULTS = True
RENDER_AS_BATCH = False  # для SQLite обычно True, для Postgres не нужно

def include_object(object, name, type_, reflected, compare_to):
    """Фильтрация объектов при автогенерации (оставим всё по умолчанию)."""
    return True

# ── SSL (Вариант A) ──────────────────────────────────────────────────────────
# В облаке нужен SSL, локально обычно нет. Логика:
#  - Если DB_SSL задан: "1/true/yes/require" → включить, "0/false/no/off" → выключить
#  - Иначе: включаем SSL, если хост не localhost/127.0.0.1
parsed = urlparse(DATABASE_URL)
host = (parsed.hostname or "").lower()

_db_ssl_env = os.getenv("DB_SSL", "").strip().lower()
if _db_ssl_env:
    ENABLE_SSL = _db_ssl_env not in {"0", "false", "no", "off"}
else:
    ENABLE_SSL = host not in {"localhost", "127.0.0.1"}

_connect_args = {}
if ENABLE_SSL:
    _ssl_ctx = ssl.create_default_context()
    _connect_args = {"ssl": _ssl_ctx}

# ── OFFLINE режим (генерация SQL без подключения) ─────────────────────────────
def run_migrations_offline() -> None:
    """
    Запуск миграций в 'offline' режиме: без реального подключения к БД.
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
        include_schemas=False,
        include_object=include_object,
        render_as_batch=RENDER_AS_BATCH,
        compare_type=COMPARE_TYPES,
        compare_server_default=COMPARE_SERVER_DEFAULTS,
    )

    with context.begin_transaction():
        context.run_migrations()

# ── ONLINE режим (реальное подключение к БД) ──────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
        include_schemas=False,
        include_object=include_object,
        render_as_batch=RENDER_AS_BATCH,
        compare_type=COMPARE_TYPES,
        compare_server_default=COMPARE_SERVER_DEFAULTS,
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    connectable: AsyncEngine = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        connect_args=_connect_args,   # <<< ВАЖНО: SSL для asyncpg тут
        pool_pre_ping=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

# ── ТОЧКА ВХОДА ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_migrations_online())
