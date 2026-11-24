"""Pruebas del estado persistente de los flujos del bot.

El flujo guardado sobrevive a reinicios: guardar, cargar, actualizar
y borrar; un flujo por usuario; flujos distintos y usuarios distintos
no se mezclan. Misma base de pruebas aislada que los demas modulos
con base de datos: cada prueba corre dentro de una transaccion que
se revierte al final (con ``join_transaction_mode="create_savepoint"``,
porque el servicio hace ``commit`` y sin savepoint el commit
confirmaria la transaccion exterior).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models.bot_flow_states import BotFlowState
from app.models.users import User
from app.services import bot_flow_state_service

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
BOGOTA = "America/Bogota"


def _test_url() -> str:
    """URL de la base de pruebas, derivada de la configuracion."""
    url = get_settings().database_url
    assert url.endswith("/dosisalerta"), f"URL inesperada: {url.rsplit('@', 1)[-1]}"
    return url[: -len("dosisalerta")] + TEST_DB


async def _create_test_db() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


async def _drop_test_db() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_test_db():
    """Crea la base de pruebas vacia y aplica las migraciones."""
    import asyncio

    asyncio.run(_create_test_db())
    os.environ["ALEMBIC_DATABASE_URL"] = _test_url()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield
    asyncio.run(_drop_test_db())
    os.environ.pop("ALEMBIC_DATABASE_URL", None)


@pytest.fixture(scope="session")
def test_engine(_migrated_test_db):
    # NullPool: cada conexion se crea en el bucle del test que la
    # usa y se cierra al devolverla.
    return create_async_engine(_test_url(), poolclass=NullPool)


@pytest_asyncio.fixture
async def session(test_engine):
    """Sesion por prueba, dentro de una transaccion que se revierte."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        sess = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield sess
        finally:
            await sess.close()
            await trans.rollback()


@pytest_asyncio.fixture
async def client(session):
    """Cliente HTTP contra la app, con la sesion de la prueba."""
    get_settings.cache_clear()
    app = create_app()

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------


def _unique_email(prefix: str = "usuario") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _make_user(client, session) -> int:
    """Registra un usuario por HTTP y devuelve su id."""
    email = _unique_email()
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Prueba",
            "email": email,
            "password": "Prueba-2026-11-24",
            "timezone": BOGOTA,
        },
    )
    assert response.status_code == 201, response.text
    result = await session.execute(select(User.id).where(User.email == email))
    return result.scalar_one()


async def _count_states(session, user_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(BotFlowState)
        .where(BotFlowState.user_id == user_id)
    )
    return result.scalar_one()


# ------------------------------------------------------------------
# Guardar y cargar
# ------------------------------------------------------------------


async def test_guardar_y_cargar_flujo(client, session):
    """Guardar un paso y cargarlo devuelve el mismo paso y los mismos datos."""
    user_id = await _make_user(client, session)
    saved = await bot_flow_state_service.save_flow(
        session, user_id, "med_create", "name", {}
    )
    assert saved == {"step": "name", "data": {}}
    loaded = await bot_flow_state_service.load_flow(session, user_id, "med_create")
    assert loaded == {"step": "name", "data": {}}


async def test_actualizar_paso_sobrescribe_sin_duplicar(client, session):
    """Guardar de nuevo el mismo flujo actualiza el paso y los datos, sin crear otra fila."""
    user_id = await _make_user(client, session)
    await bot_flow_state_service.save_flow(session, user_id, "med_create", "name", {})
    updated = await bot_flow_state_service.save_flow(
        session,
        user_id,
        "med_create",
        "presentation",
        {"name": "Ibuprofeno", "presentation": None},
    )
    assert updated == {
        "step": "presentation",
        "data": {"name": "Ibuprofeno", "presentation": None},
    }
    loaded = await bot_flow_state_service.load_flow(session, user_id, "med_create")
    assert loaded == {
        "step": "presentation",
        "data": {"name": "Ibuprofeno", "presentation": None},
    }
    assert await _count_states(session, user_id) == 1


async def test_cargar_sin_flujo_devuelve_none(client, session):
    """Un usuario sin flujo guardado carga None."""
    user_id = await _make_user(client, session)
    assert (
        await bot_flow_state_service.load_flow(session, user_id, "med_create") is None
    )


async def test_borrar_flujo(client, session):
    """Borrar elimina el flujo; borrar de nuevo devuelve False."""
    user_id = await _make_user(client, session)
    await bot_flow_state_service.save_flow(
        session, user_id, "med_create", "name", {"name": "Paracetamol"}
    )
    assert (
        await bot_flow_state_service.clear_flow(session, user_id, "med_create") is True
    )
    assert (
        await bot_flow_state_service.load_flow(session, user_id, "med_create") is None
    )
    assert (
        await bot_flow_state_service.clear_flow(session, user_id, "med_create")
        is False
    )


async def test_flujos_distintos_no_se_mezclan(client, session):
    """Dos flujos del mismo usuario se guardan y cargan por separado."""
    user_id = await _make_user(client, session)
    await bot_flow_state_service.save_flow(
        session, user_id, "med_create", "name", {"name": "Ibuprofeno"}
    )
    await bot_flow_state_service.save_flow(
        session, user_id, "otro_flujo", "paso_1", {"clave": "valor"}
    )
    assert await bot_flow_state_service.load_flow(
        session, user_id, "med_create"
    ) == {"step": "name", "data": {"name": "Ibuprofeno"}}
    assert await bot_flow_state_service.load_flow(
        session, user_id, "otro_flujo"
    ) == {"step": "paso_1", "data": {"clave": "valor"}}
    assert await _count_states(session, user_id) == 2


async def test_usuarios_distintos_no_se_mezclan(client, session):
    """El mismo flujo de dos usuarios guarda datos distintos."""
    user_a = await _make_user(client, session)
    user_b = await _make_user(client, session)
    await bot_flow_state_service.save_flow(
        session, user_a, "med_create", "name", {"name": "Ibuprofeno"}
    )
    await bot_flow_state_service.save_flow(
        session, user_b, "med_create", "notes", {"name": "Amoxicilina"}
    )
    assert await bot_flow_state_service.load_flow(
        session, user_a, "med_create"
    ) == {"step": "name", "data": {"name": "Ibuprofeno"}}
    assert await bot_flow_state_service.load_flow(
        session, user_b, "med_create"
    ) == {"step": "notes", "data": {"name": "Amoxicilina"}}
