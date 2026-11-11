"""Entorno de Alembic para DosisAlerta (Fase 2, motor asincrono).

La URL de conexion sale de la configuracion central
(`app.core.config`), que lee `.env` en la raiz del proyecto.
Nunca hay credenciales escritas en este archivo ni en
`alembic.ini`.

Se ejecuta desde la carpeta `backend/` con el entorno virtual
activado.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Carga .env: en la raiz del proyecto (../.env) o en backend/.env.
# `load_dotenv()` sin ruta ya busca hacia arriba desde el cwd, pero
# se dejan las dos rutas explicitas para no depender del cwd.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL de conexion para la migracion.

    Por defecto sale de la configuracion central (`.env`). Las
    pruebas de la Fase 2 pueden apuntar a otra base de datos
    (por ejemplo, `dosisalerta_test`) con la variable de entorno
    `ALEMBIC_DATABASE_URL`, sin tocar `.env`.
    """
    return os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    """Migraciones sin conexion: genera el SQL a partir de los metadatos."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Migraciones con motor asincrono (asyncpg)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
