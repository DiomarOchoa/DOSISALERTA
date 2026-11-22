"""Pruebas de integracion de la proteccion de tratamientos
terminales (I-4).

Un tratamiento CANCELADO o COMPLETADO bloquea la edicion del
tratamiento y de sus vinculos con medicamentos (400 con
`_TERMINAL_STATE_ERROR`). ACTIVO y PAUSADO mantienen su
comportamiento actual. Las transiciones de estado no cambian.

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3 y que `test_treatments.py`.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = ZoneInfo("America/Bogota")
TERMINAL_ERROR = "El tratamiento ya está cancelado/completado"


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
    """Sesion por prueba, dentro de una transaccion que se revierte.

    `join_transaction_mode="create_savepoint"`: la sesion se une
    a la transaccion exterior mediante un savepoint, asi que los
    `commit` de los servicios solo liberan el savepoint y la
    transaccion exterior sigue pudiendo revertirse al final.
    """
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


def _today_bogota() -> date:
    """Hoy en la zona del usuario (la de generacion)."""
    return datetime.now(BOGOTA).date()


async def _register_ok(client, email, password=PASSWORD):
    """Registra un usuario y devuelve su perfil con sus tokens."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Prueba",
            "email": email,
            "password": password,
            "timezone": "America/Bogota",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_medication_ok(client, token, payload):
    """Crea un medicamento y devuelve su cuerpo (201)."""
    response = await client.post(
        "/api/v1/medications", json=payload, headers=_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _schedule_payload(times=("08:00",), frequency="DIARIO", start=None, end=None):
    """Horario valido: DIARIO a las horas dadas, desde hoy."""
    payload = {
        "frequency": frequency,
        "times": list(times),
        "start_date": (start or _today_bogota()).isoformat(),
    }
    if end is not None:
        payload["end_date"] = end.isoformat()
    return payload


def _med_item(medication_id, schedules, dose_amount=1, dose_unit="capsula"):
    return {
        "medication_id": medication_id,
        "dose_amount": dose_amount,
        "dose_unit": dose_unit,
        "schedules": schedules,
    }


def _treatment_payload(medications, title="Tratamiento", start=None, end=None):
    payload = {
        "title": title,
        "start_date": (start or _today_bogota()).isoformat(),
        "medications": medications,
    }
    if end is not None:
        payload["end_date"] = end.isoformat()
    return payload


async def _create_treatment_ok(client, token, payload, patient_id=None):
    """Crea un tratamiento y devuelve su cuerpo (201)."""
    url = "/api/v1/treatments"
    if patient_id is not None:
        url += f"?patient_id={patient_id}"
    response = await client.post(url, json=payload, headers=_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _create_treatment_with_link(client, token):
    """Tratamiento ACTIVO con un medicamento; devuelve (tratamiento,
    link_id)."""
    med = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(med["id"], [_schedule_payload()])]),
    )
    return created, created["medications"][0]["id"]


async def _change_status(client, token, treatment_id, action, expected_status):
    """POST /treatments/{id}/{action} y devuelve el cuerpo (200)."""
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/{action}", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status
    return response.json()


async def _get_treatment(client, token, treatment_id):
    """GET /treatments/{id} y devuelve el cuerpo (200)."""
    response = await client.get(
        f"/api/v1/treatments/{treatment_id}", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------
# 1. Editar el tratamiento
# ------------------------------------------------------------------


async def test_update_treatment_cancelled_400(client):
    """PATCH a un tratamiento CANCELADO -> 400; no cambia nada."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, _ = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "cancel", "CANCELADO")
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}",
        json={"title": "Cambiado"},
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == TERMINAL_ERROR
    data = await _get_treatment(client, token, created["id"])
    assert data["title"] == "Tratamiento"
    assert data["status"] == "CANCELADO"


async def test_update_treatment_completed_400(client):
    """PATCH a un tratamiento COMPLETADO -> 400; no cambia nada."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, _ = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "complete", "COMPLETADO")
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}",
        json={"title": "Cambiado"},
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == TERMINAL_ERROR
    data = await _get_treatment(client, token, created["id"])
    assert data["title"] == "Tratamiento"
    assert data["status"] == "COMPLETADO"


async def test_update_treatment_paused_ok(client):
    """PATCH a un tratamiento PAUSADO -> 200 (no es terminal)."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, _ = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "pause", "PAUSADO")
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}",
        json={"title": "Pausado y editado"},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Pausado y editado"
    assert response.json()["status"] == "PAUSADO"


# ------------------------------------------------------------------
# 2. Editar el vinculo
# ------------------------------------------------------------------


async def test_update_link_cancelled_400(client):
    """PATCH del vinculo en un tratamiento CANCELADO -> 400."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, link_id = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "cancel", "CANCELADO")
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        json={"dose_amount": 2.5},
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == TERMINAL_ERROR
    data = await _get_treatment(client, token, created["id"])
    assert data["medications"][0]["dose_amount"] == 1
    assert data["medications"][0]["is_active"] is True


async def test_update_link_completed_400(client):
    """PATCH del vinculo en un tratamiento COMPLETADO -> 400."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, link_id = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "complete", "COMPLETADO")
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        json={"dose_amount": 2.5},
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == TERMINAL_ERROR
    data = await _get_treatment(client, token, created["id"])
    assert data["medications"][0]["dose_amount"] == 1


async def test_update_link_paused_ok(client):
    """PATCH del vinculo en un tratamiento PAUSADO -> 200."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, link_id = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "pause", "PAUSADO")
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        json={"dose_amount": 2.5, "dose_unit": "comprimido"},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["dose_amount"] == 2.5
    assert response.json()["dose_unit"] == "comprimido"


# ------------------------------------------------------------------
# 3. Eliminar el vinculo
# ------------------------------------------------------------------


async def test_delete_link_cancelled_400(client):
    """DELETE del vinculo en un tratamiento CANCELADO -> 400; el
    vinculo sigue activo."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, link_id = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "cancel", "CANCELADO")
    response = await client.delete(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == TERMINAL_ERROR
    data = await _get_treatment(client, token, created["id"])
    assert data["medications"][0]["is_active"] is True


async def test_delete_link_completed_400(client):
    """DELETE del vinculo en un tratamiento COMPLETADO -> 400."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, link_id = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "complete", "COMPLETADO")
    response = await client.delete(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == TERMINAL_ERROR
    data = await _get_treatment(client, token, created["id"])
    assert data["medications"][0]["is_active"] is True


async def test_delete_link_paused_ok(client):
    """DELETE del vinculo en un tratamiento PAUSADO -> 200."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created, link_id = await _create_treatment_with_link(client, token)
    await _change_status(client, token, created["id"], "pause", "PAUSADO")
    response = await client.delete(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
