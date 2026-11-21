"""Pruebas HTTP de los endpoints de tomas (Fase 5, Etapa 4).

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
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models.caregivers import CaregiverAuditLog, CaregiverLink
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationReminder
from app.models.schedules import MedicationSchedule

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = "America/Bogota"


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
    }


async def _seed_reminder(session, chain: dict, when: datetime, status: str) -> int:
    row = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=chain["user_id"],
        scheduled_at=when,
        status=status,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return row.id


async def _audit_denied_count(session, *, caregiver_id: int, patient_id: int) -> int:
    row = await session.execute(
        select(func.count())
        .select_from(CaregiverAuditLog)
        .where(
            CaregiverAuditLog.caregiver_user_id == caregiver_id,
            CaregiverAuditLog.patient_user_id == patient_id,
            CaregiverAuditLog.action == "ACCESS_DENIED",
            CaregiverAuditLog.result == "DENEGADO",
        )
    )
    return row.scalar_one()


# ------------------------------------------------------------------
# POST /confirm
# ------------------------------------------------------------------


async def test_confirm_ok_and_idempotent(client, session) -> None:
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    chain = await _seed_chain(session, body["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )

    first = await client.post(
        f"/api/v1/reminders/{rid}/confirm", headers=_headers(token)
    )
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["reminder_id"] == rid
    assert data["user_id"] == body["user"]["id"]
    assert data["source"] == "WEB"
    assert data["reminder_status"] == "TOMADA"
    assert data["taken_at"]
    assert data["id"]

    second = await client.post(
        f"/api/v1/reminders/{rid}/confirm", headers=_headers(token)
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == data["id"]
    assert second.json()["taken_at"] == data["taken_at"]


async def test_confirm_requires_auth(client, session) -> None:
    body = await _register_ok(client, _unique_email())
    chain = await _seed_chain(session, body["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )
    response = await client.post(f"/api/v1/reminders/{rid}/confirm")
    assert response.status_code == 401


async def test_confirm_missing_is_404(client) -> None:
    body = await _register_ok(client, _unique_email())
    response = await client.post(
        "/api/v1/reminders/999999999/confirm",
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 404


async def test_confirm_other_users_reminder_is_403(client, session) -> None:
    owner = await _register_ok(client, _unique_email("dueno"))
    other = await _register_ok(client, _unique_email("otro"))
    chain = await _seed_chain(session, owner["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )
    response = await client.post(
        f"/api/v1/reminders/{rid}/confirm",
        headers=_headers(other["access_token"]),
    )
    assert response.status_code == 403


async def test_confirm_perdida_is_409(client, session) -> None:
    body = await _register_ok(client, _unique_email())
    chain = await _seed_chain(session, body["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(minutes=40), "PERDIDA"
    )
    response = await client.post(
        f"/api/v1/reminders/{rid}/confirm",
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 409


async def test_caregiver_confirm_is_403_with_audit(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    chain = await _seed_chain(session, patient["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )
    session.add(
        CaregiverLink(
            patient_user_id=patient["user"]["id"],
            caregiver_user_id=caregiver["user"]["id"],
            status="ACTIVO",
            invited_by=patient["user"]["id"],
            # El CHECK de ACTIVO exige accepted_at no nulo.
            accepted_at=_utcnow(),
        )
    )
    await session.commit()

    response = await client.post(
        f"/api/v1/reminders/{rid}/confirm",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    assert (
        await _audit_denied_count(
            session,
            caregiver_id=caregiver["user"]["id"],
            patient_id=patient["user"]["id"],
        )
        == 1
    )


# ------------------------------------------------------------------
# POST /postpone
# ------------------------------------------------------------------


async def test_postpone_ok_15_30_60(client, session) -> None:
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    chain = await _seed_chain(session, body["user"]["id"])
    for i, delay in enumerate((15, 30, 60)):
        rid = await _seed_reminder(
            session,
            chain,
            _utcnow() - timedelta(seconds=10 + i),
            "ENVIADA",
        )
        response = await client.post(
            f"/api/v1/reminders/{rid}/postpone",
            json={"delay_minutes": delay},
            headers=_headers(token),
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["original"]["id"] == rid
        assert data["original"]["status"] == "POSPUESTA"
        assert data["child"]["parent_reminder_id"] == rid
        assert data["child"]["status"] == "PENDIENTE"
        assert data["child"]["postponed_count"] == 1
        scheduled = datetime.fromisoformat(
            data["child"]["scheduled_at"].replace("Z", "+00:00")
        )
        assert _utcnow() + timedelta(minutes=delay - 1) <= scheduled <= (
            _utcnow() + timedelta(minutes=delay + 1)
        )


async def test_postpone_invalid_delay_is_422(client, session) -> None:
    body = await _register_ok(client, _unique_email())
    chain = await _seed_chain(session, body["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )
    for payload in ({"delay_minutes": 20}, {"delay_minutes": 5}, {}):
        response = await client.post(
            f"/api/v1/reminders/{rid}/postpone",
            json=payload,
            headers=_headers(body["access_token"]),
        )
        assert response.status_code == 422, response.text


async def test_postpone_taken_is_409(client, session) -> None:
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    chain = await _seed_chain(session, body["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )
    confirmed = await client.post(
        f"/api/v1/reminders/{rid}/confirm", headers=_headers(token)
    )
    assert confirmed.status_code == 200
    response = await client.post(
        f"/api/v1/reminders/{rid}/postpone",
        json={"delay_minutes": 15},
        headers=_headers(token),
    )
    assert response.status_code == 409


async def test_caregiver_postpone_is_403_with_audit(client, session) -> None:
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    chain = await _seed_chain(session, patient["user"]["id"])
    rid = await _seed_reminder(
        session, chain, _utcnow() - timedelta(seconds=10), "ENVIADA"
    )
    session.add(
        CaregiverLink(
            patient_user_id=patient["user"]["id"],
            caregiver_user_id=caregiver["user"]["id"],
            status="ACTIVO",
            invited_by=patient["user"]["id"],
            # El CHECK de ACTIVO exige accepted_at no nulo.
            accepted_at=_utcnow(),
        )
    )
    await session.commit()

    response = await client.post(
        f"/api/v1/reminders/{rid}/postpone",
        json={"delay_minutes": 15},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    assert (
        await _audit_denied_count(
            session,
            caregiver_id=caregiver["user"]["id"],
            patient_id=patient["user"]["id"],
        )
        == 1
    )
