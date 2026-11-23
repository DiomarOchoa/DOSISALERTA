"""Pruebas HTTP de `PATCH /api/v1/auth/me` (RF03, Etapa 5).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: cada prueba corre dentro de una transaccion
que se revierte al final (con
`join_transaction_mode="create_savepoint"`, porque los
servicios hacen `commit` y sin savepoint el commit confirmaria
la transaccion exterior).

Las llamadas HTTP usan `httpx.AsyncClient` + `ASGITransport`
(en el mismo bucle de eventos que la prueba), para que la
sesion de la prueba —ligada a ese bucle— funcione dentro de
cada peticion.

RF03: el perfil tiene zona horaria configurable (por defecto
`America/Bogota`, cambiable por el usuario). RNF04: un cambio
de zona recalcula unicamente los recordatorios PENDIENTE
futuros.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

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
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationReminder
from app.models.schedules import MedicationSchedule
from app.repositories import (
    schedule_repository,
    treatment_repository,
    user_repository,
)
from app.services import schedule_service

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = "America/Bogota"
MEXICO = "America/Mexico_City"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


async def _register_ok(client, email, password=PASSWORD):
    """Registra un usuario y devuelve su perfil con sus tokens."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Prueba",
            "email": email,
            "password": password,
            "timezone": BOGOTA,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_chain(session, user_id: int) -> dict:
    """Medicamento + tratamiento + vinculo + horario de un usuario."""
    med = Medication(user_id=user_id, name="Paracetamol")
    session.add(med)
    await session.flush()
    treatment = Treatment(
        user_id=user_id, title="Prueba", start_date=date.today()
    )
    session.add(treatment)
    await session.flush()
    link = TreatmentMedication(
        user_id=user_id,
        treatment_id=treatment.id,
        medication_id=med.id,
        dose_amount=Decimal("500"),
        dose_unit="mg",
    )
    session.add(link)
    await session.flush()
    schedule = MedicationSchedule(
        user_id=user_id,
        treatment_medication_id=link.id,
        frequency="DIARIO",
        times=[time(8, 0)],
        start_date=date.today(),
    )
    session.add(schedule)
    await session.flush()
    await session.commit()
    return {
        "user_id": user_id,
        "schedule_id": schedule.id,
        "link_id": link.id,
        "treatment_id": treatment.id,
    }


async def _future_pending(session, user_id: int) -> list[MedicationReminder]:
    """PENDIENTE futuros del usuario, ordenados por hora."""
    now = _utcnow()
    result = await session.execute(
        select(MedicationReminder)
        .where(
            MedicationReminder.user_id == user_id,
            MedicationReminder.status == "PENDIENTE",
            MedicationReminder.scheduled_at >= now,
        )
        .order_by(MedicationReminder.scheduled_at)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------
# PATCH /me
# ------------------------------------------------------------------


async def test_patch_me_changes_timezone(client, session):
    """Cambia la zona horaria y la devuelve en el perfil (200)."""
    reg = await _register_ok(client, _unique_email())
    token = reg["access_token"]
    assert reg["user"]["timezone"] == BOGOTA

    response = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": MEXICO},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == MEXICO
    assert body["id"] == reg["user"]["id"]
    assert body["name"] == reg["user"]["name"]
    assert body["email"] == reg["user"]["email"]

    me = await client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["timezone"] == MEXICO


async def test_patch_me_invalid_timezone_422(client):
    """Una zona IANA invalida se rechaza con 422."""
    reg = await _register_ok(client, _unique_email())
    response = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": "No/Existe"},
        headers=_headers(reg["access_token"]),
    )
    assert response.status_code == 422, response.text


async def test_patch_me_no_auth_401(client):
    """Sin sesion, PATCH /me es 401."""
    response = await client.patch(
        "/api/v1/auth/me", json={"timezone": MEXICO}
    )
    assert response.status_code == 401, response.text


async def test_patch_me_empty_body_no_change(client):
    """Sin `timezone`, no se cambia nada y se devuelve el perfil."""
    reg = await _register_ok(client, _unique_email())
    response = await client.patch(
        "/api/v1/auth/me",
        json={},
        headers=_headers(reg["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == BOGOTA


async def test_patch_me_same_timezone_no_regeneration(client, session):
    """Misma zona: no se regenera nada (mismos ids)."""
    reg = await _register_ok(client, _unique_email())
    user_id = reg["user"]["id"]
    chain = await _seed_chain(session, user_id)
    schedule = await schedule_repository.get_by_id(
        session, chain["schedule_id"], user_id=user_id
    )
    treatment = await treatment_repository.get_by_id(
        session, chain["treatment_id"], user_id=user_id
    )
    user = await user_repository.get_by_id(session, user_id)
    assert schedule is not None and treatment is not None and user is not None
    created = await schedule_service.generate_reminders_for_schedule(
        session, schedule, treatment, user
    )
    assert created > 0
    await session.commit()
    before = await _future_pending(session, user_id)
    assert len(before) == created
    before_ids = [row.id for row in before]

    response = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": BOGOTA},
        headers=_headers(reg["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == BOGOTA

    after = await _future_pending(session, user_id)
    assert [row.id for row in after] == before_ids


async def test_patch_me_regenerates_future_pending(client, session):
    """Cambio de zona: los PENDIENTE futuros se regeneran con la
    zona nueva (RNF04); los no-PENDIENTE no se tocan.

    Horario diario 08:00. En Bogota (UTC-5) es 13:00 UTC; en
    Ciudad de Mexico (UTC-6) es 14:00 UTC. Tras el cambio, los
    PENDIENTE futuros deben estar a las 14:00 UTC y no debe
    quedar ninguno a las 13:00 UTC. Una TOMADA futura sembrada
    a otra hora queda intacta.
    """
    reg = await _register_ok(client, _unique_email())
    user_id = reg["user"]["id"]
    chain = await _seed_chain(session, user_id)
    schedule = await schedule_repository.get_by_id(
        session, chain["schedule_id"], user_id=user_id
    )
    treatment = await treatment_repository.get_by_id(
        session, chain["treatment_id"], user_id=user_id
    )
    user = await user_repository.get_by_id(session, user_id)
    assert schedule is not None and treatment is not None and user is not None
    created = await schedule_service.generate_reminders_for_schedule(
        session, schedule, treatment, user
    )
    assert created > 0
    before = await _future_pending(session, user_id)
    assert len(before) == created
    # Todos a las 08:00 de Bogota = 13:00 UTC.
    assert all(
        row.scheduled_at.hour == 13 and row.scheduled_at.minute == 0
        for row in before
    )

    # TOMADA futura a otra hora (15:00 UTC de manana): no se toca.
    # (taken_at/source viven en la tabla de tomas, no en el
    # recordatorio: aqui basta el estado TOMADA.)
    taken_at = _utcnow() + timedelta(days=1)
    taken_at = taken_at.replace(hour=15, minute=0, second=0, microsecond=0)
    taken = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=user_id,
        scheduled_at=taken_at,
        status="TOMADA",
    )
    session.add(taken)
    await session.commit()
    taken_id = taken.id

    response = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": MEXICO},
        headers=_headers(reg["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == MEXICO

    after = await _future_pending(session, user_id)
    assert len(after) == created
    # Todos a las 08:00 de Mexico = 14:00 UTC; ninguno a las 13:00.
    assert all(
        row.scheduled_at.hour == 14 and row.scheduled_at.minute == 0
        for row in after
    )
    assert all(row.scheduled_at.hour != 13 for row in after)
    # Son filas nuevas (los viejos PENDIENTE se borraron).
    assert [row.id for row in after] != [row.id for row in before]

    kept = await session.get(MedicationReminder, taken_id)
    assert kept is not None
    assert kept.status == "TOMADA"
    assert kept.scheduled_at == taken_at
