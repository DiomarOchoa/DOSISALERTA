"""Pruebas de integracion del limite de posposiciones (I-5).

Maximo 3 posposiciones por cadena: las tres primeras funcionan
normalmente y la cuarta devuelve HTTP 409. El hijo hereda el
contador de la cadena (`postponed_count` +1) y el limite se aplica
tambien al posponer un hijo. El rechazo no crea hijos ni modifica
el recordatorio original.

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3 y que `test_medications.py`. Las posposiciones se
ejercen por la API (`POST /api/v1/reminders/{id}/postpone`).
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models import MedicationReminder

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = ZoneInfo("America/Bogota")
LIMIT_ERROR = "Límite de posposiciones alcanzado (máximo 3 por cadena)"


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


async def _create_treatment_ok(client, token, payload):
    """Crea un tratamiento y devuelve su cuerpo (201)."""
    response = await client.post(
        "/api/v1/treatments", json=payload, headers=_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _setup_chain(client, token):
    """Tratamiento ACTIVO con un medicamento; devuelve
    (schedule_id, link_id)."""
    med = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(med["id"], [_schedule_payload()])]),
    )
    link = created["medications"][0]
    return link["schedules"][0]["id"], link["id"]


async def _seed_reminder(session, user_id, schedule_id, link_id, when, status,
                         postponed_count=0, parent_id=None):
    """Siembra un recordatorio y devuelve su id."""
    row = MedicationReminder(
        schedule_id=schedule_id,
        treatment_medication_id=link_id,
        user_id=user_id,
        scheduled_at=when,
        status=status,
        parent_reminder_id=parent_id,
        postponed_count=postponed_count,
    )
    session.add(row)
    await session.flush()
    return row.id


async def _postpone(client, token, reminder_id, delay_minutes=15):
    """POST /reminders/{id}/postpone; devuelve la respuesta."""
    return await client.post(
        f"/api/v1/reminders/{reminder_id}/postpone",
        json={"delay_minutes": delay_minutes},
        headers=_headers(token),
    )


async def _reminder_row(session, reminder_id):
    """(status, postponed_count, parent_reminder_id) de un recordatorio."""
    result = await session.execute(
        select(
            MedicationReminder.status,
            MedicationReminder.postponed_count,
            MedicationReminder.parent_reminder_id,
        ).where(MedicationReminder.id == reminder_id)
    )
    row = result.one_or_none()
    assert row is not None
    return row[0], row[1], row[2]


async def _children_count(session, parent_id):
    """Cuantos hijos tiene un recordatorio."""
    result = await session.execute(
        select(MedicationReminder.id).where(
            MedicationReminder.parent_reminder_id == parent_id
        )
    )
    return len(list(result.all()))


# ------------------------------------------------------------------
# 1. La cadena: 3 posposiciones OK, la 4a es 409
# ------------------------------------------------------------------


async def test_postpone_three_times_ok_fourth_is_409(client, session):
    """Posponer 3 veces funciona (contador 1, 2, 3); la 4a es 409
    y no crea hijo ni cambia el recordatorio."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    user_id = body["user"]["id"]
    schedule_id, link_id = await _setup_chain(client, token)
    now = datetime.now(timezone.utc)
    rid = await _seed_reminder(
        session, user_id, schedule_id, link_id,
        now + timedelta(hours=1), "PENDIENTE",
    )

    # 1a posposicion: hijo con contador 1.
    response = await _postpone(client, token, rid)
    assert response.status_code == 200, response.text
    child1 = response.json()["child"]
    assert child1["postponed_count"] == 1
    assert child1["status"] == "PENDIENTE"
    assert response.json()["original"]["status"] == "POSPUESTA"

    # 2a posposicion (al hijo): nieto con contador 2.
    response = await _postpone(client, token, child1["id"])
    assert response.status_code == 200, response.text
    child2 = response.json()["child"]
    assert child2["postponed_count"] == 2
    assert child2["parent_reminder_id"] == child1["id"]

    # 3a posposicion (al nieto): bisnieto con contador 3.
    response = await _postpone(client, token, child2["id"])
    assert response.status_code == 200, response.text
    child3 = response.json()["child"]
    assert child3["postponed_count"] == 3
    assert child3["parent_reminder_id"] == child2["id"]

    # 4a posposicion (al bisnieto, contador 3): 409.
    response = await _postpone(client, token, child3["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == LIMIT_ERROR
    # No crea hijo ni cambia el bisnieto.
    assert await _children_count(session, child3["id"]) == 0
    status, count, _ = await _reminder_row(session, child3["id"])
    assert status == "PENDIENTE"
    assert count == 3


# ------------------------------------------------------------------
# 2. El limite se aplica tambien a un hijo sembrado
# ------------------------------------------------------------------


async def test_postpone_child_at_limit_is_409(client, session):
    """Un hijo con postponed_count=3 no se puede posponer: 409,
    sin hijo nuevo y sin cambios."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    user_id = body["user"]["id"]
    schedule_id, link_id = await _setup_chain(client, token)
    now = datetime.now(timezone.utc)
    rid = await _seed_reminder(
        session, user_id, schedule_id, link_id,
        now + timedelta(hours=1), "PENDIENTE", postponed_count=3,
    )
    response = await _postpone(client, token, rid)
    assert response.status_code == 409
    assert response.json()["detail"] == LIMIT_ERROR
    assert await _children_count(session, rid) == 0
    status, count, _ = await _reminder_row(session, rid)
    assert status == "PENDIENTE"
    assert count == 3


async def test_postpone_child_below_limit_ok(client, session):
    """Un hijo con postponed_count=2 si se puede posponer: el
    nuevo hijo lleva contador 3."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    user_id = body["user"]["id"]
    schedule_id, link_id = await _setup_chain(client, token)
    now = datetime.now(timezone.utc)
    rid = await _seed_reminder(
        session, user_id, schedule_id, link_id,
        now + timedelta(hours=1), "PENDIENTE", postponed_count=2,
    )
    response = await _postpone(client, token, rid)
    assert response.status_code == 200, response.text
    child = response.json()["child"]
    assert child["postponed_count"] == 3
    assert child["parent_reminder_id"] == rid
    assert response.json()["original"]["status"] == "POSPUESTA"
