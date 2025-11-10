from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from dotenv import load_dotenv

# ── ЛОГИ АЛЕМБИКА ─────────────────────────────────────────────────────────────
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# ── ПУТЬ К ПРОЕКТУ (чтобы import backend.models работал при запуске alembic) ──
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../backend/alembic → root
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── МОДЕЛИ (metadata) ─────────────────────────────────────────────────────────
load_dotenv()  # читаем .env из корня
from backend.models import Base  # noqa: E402

target_metadata = Base.metadata

# ── URL БД ────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL не найден. Добавь его в .env, пример: "
        "postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/tg_shop"
    )

# Можно настроить версионную таблицу/схему (при желании)
VERSION_TABLE = os.getenv("ALEMBIC_VERSION_TABLE", "alembic_version")
VERSION_TABLE_SCHEMA = os.getenv("ALEMBIC_VERSION_SCHEMA", None)  # например, 'public'

# Сравнение типов/имен колонок при автогенерации
COMPARE_TYPES = True
COMPARE_SERVER_DEFAULTS = True
RENDER_AS_BATCH = False  # для SQLite можно включить True


def include_object(object, name, type_, reflected, compare_to):
    """
    Фильтрация объектов при автогенерации (оставим всё по умолчанию).
    """
    return True


# ── OFFLINE режим (генерация SQL без подключения) ─────────────────────────────
def run_migrations_offline() -> None:
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


# ── ONLINE режим (подключение к БД) ───────────────────────────────────────────
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
        future=True,
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
