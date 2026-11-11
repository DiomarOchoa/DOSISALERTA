"""Conexion a PostgreSQL con SQLAlchemy async (Fase 2).

El motor y la fabrica de sesiones se construyen desde la
configuracion central (`app.core.config`, URL
``postgresql+asyncpg``). La aplicacion sigue arrancando y
respondiendo /health sin base de datos: nada de este modulo se
usa en el arranque de FastAPI en la Fase 2; es la base para los
servicios de las fases siguientes y para las pruebas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def create_engine():
    """Crea el motor asincrono desde la configuracion."""
    return create_async_engine(get_settings().database_url, echo=False)


engine = create_engine()

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia FastAPI: una sesion por peticion (Fases 3+)."""
    async with AsyncSessionLocal() as session:
        yield session
