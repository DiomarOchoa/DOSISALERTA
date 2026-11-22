"""Pruebas de integracion de la reactivacion de medicamentos (I-7).

`POST /api/v1/medications/{id}/reactivate` (200, `is_active=True`).
Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3 y que `test_medications.py`.

Cubre: reactivar un inactivo, idempotencia en un activo, 404,
403 de otro usuario, 401 sin token, que las filas CANCELADA no se
reviven ni pierden su motivo (decision B, D-11) y que los
recordatorios futuros nuevos nacen por el mecanismo normal de
generacion (que solo genera para medicamentos activos, Fase A,
I-3), y los permisos y la auditoria del cuidador (mismos que la
desactivacion).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
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
from app.models import (
    CaregiverAuditLog,
    CaregiverLink,
    Medication,
    MedicationReminder,
    MedicationSchedule,
    Treatment,
    TreatmentMedication,
    User,
)
from app.services.schedule_service import generate_reminders_for_schedule

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = ZoneInfo("America/Bogota")


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
            "timezone": "America/Bogota",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_medication_ok(client, token, payload, patient_id=None):
    """Crea un medicamento y devuelve su cuerpo (201)."""
    url = "/api/v1/medications"
    if patient_id is not None:
        url += f"?patient_id={patient_id}"
    response = await client.post(url, json=payload, headers=_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _deactivate_ok(client, token, medication_id, patient_id=None):
    """Desactiva un medicamento y devuelve su cuerpo (200)."""
    url = f"/api/v1/medications/{medication_id}"
    if patient_id is not None:
        url += f"?patient_id={patient_id}"
    response = await client.delete(url, headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


async def _reactivate(client, token, medication_id, patient_id=None):
    """POST reactivate; devuelve la respuesta sin afirmar el estado."""
    url = f"/api/v1/medications/{medication_id}/reactivate"
    if patient_id is not None:
        url += f"?patient_id={patient_id}"
    return await client.post(url, headers=_headers(token))


def _today_bogota() -> date:
    """Hoy en la zona del usuario (la de generacion)."""
    return datetime.now(BOGOTA).date()


async def _seed_treatment_chain(session, user_id, medication_id):
    """Tratamiento ACTIVO + vinculo + horario DIARIO 08:00, desde hoy.

    Devuelve (treatment, link, schedule) como objetos ORM.
    """
    today = _today_bogota()
    treatment = Treatment(
        user_id=user_id,
        title="Prueba",
        start_date=today,
        status="ACTIVO",
    )
    session.add(treatment)
    await session.flush()
    link = TreatmentMedication(
        user_id=user_id,
        treatment_id=treatment.id,
        medication_id=medication_id,
        dose_amount=Decimal("500"),
        dose_unit="mg",
        is_active=True,
    )
    session.add(link)
    await session.flush()
    schedule = MedicationSchedule(
        user_id=user_id,
        treatment_medication_id=link.id,
        frequency="DIARIO",
        days_of_week=None,
        interval_days=None,
        times=[time(8, 0)],
        start_date=today,
        end_date=None,
        is_active=True,
    )
    session.add(schedule)
    await session.flush()
    return treatment, link, schedule


async def _reminder_rows(session, user_id):
    """(id, scheduled_at, status, cancel_reason) de los recordatorios."""
    result = await session.execute(
        select(
            MedicationReminder.id,
            MedicationReminder.scheduled_at,
            MedicationReminder.status,
            MedicationReminder.cancel_reason,
        )
        .where(MedicationReminder.user_id == user_id)
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
    )
    return list(result.all())


async def _make_link(session, patient_id, caregiver_id, status="ACTIVO", **perms):
    """Crea un vinculo paciente-cuidador con los permisos dados.

    ACTIVO exige `accepted_at` (CHECK) y `caregiver_user_id`
    no nulo. Gestionar exige ver (CHECK): `perm_manage_medications`
    solo con `perm_view_medications` en True.
    """
    now = datetime.now(timezone.utc)
    link = CaregiverLink(
        patient_user_id=patient_id,
        caregiver_user_id=caregiver_id,
        status=status,
        invited_by=patient_id,
        accepted_at=now if status == "ACTIVO" else None,
        revoked_at=now if status == "REVOCADO" else None,
        **perms,
    )
    session.add(link)
    await session.flush()
    return link


async def _patient_and_caregiver(client, session, **perms):
    """Paciente + cuidador registrados, con vinculo ACTIVO.

    Devuelve (paciente, cuidador). `perms` son los permisos del
    vinculo (`perm_view_medications=True`, ...).
    """
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    await _make_link(
        session,
        patient["user"]["id"],
        caregiver["user"]["id"],
        **perms,
    )
    return patient, caregiver


async def _audit_rows(session, caregiver_id, patient_id):
    """Filas de auditoria de un cuidador sobre un paciente."""
    result = await session.execute(
        select(CaregiverAuditLog)
        .where(
            CaregiverAuditLog.caregiver_user_id == caregiver_id,
            CaregiverAuditLog.patient_user_id == patient_id,
        )
        .order_by(CaregiverAuditLog.id)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------
# 1. Reactivar
# ------------------------------------------------------------------


async def test_reactivate_medication_ok(client):
    """Desactivar y reactivar: 200, is_active=True, vuelve al listado."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    deactivated = await _deactivate_ok(client, token, created["id"])
    assert deactivated["is_active"] is False
    response = await _reactivate(client, token, created["id"])
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == created["id"]
    assert data["name"] == "Amoxicilina"
    assert data["is_active"] is True
    # Vuelve a salir en el listado por defecto.
    response = await client.get("/api/v1/medications", headers=_headers(token))
    assert [item["name"] for item in response.json()] == ["Amoxicilina"]


async def test_reactivate_medication_already_active_idempotent(client):
    """Reactivar un medicamento ya activo: 200, sin modificarlo."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    created = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    response = await _reactivate(client, token, created["id"])
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True
    assert response.json()["name"] == "Amoxicilina"
    # Una segunda reactivacion tambien es 200.
    response = await _reactivate(client, token, created["id"])
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True


async def test_reactivate_medication_not_found_404(client):
    """POST reactivate a id inexistente -> 404."""
    body = await _register_ok(client, _unique_email())
    response = await _reactivate(client, body["access_token"], 999999)
    assert response.status_code == 404


async def test_reactivate_medication_other_user_403(client):
    """Reactivar un medicamento de otro usuario -> 403."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    created = await _create_medication_ok(
        client, user_a["access_token"], {"name": "Amoxicilina"}
    )
    await _deactivate_ok(client, user_a["access_token"], created["id"])
    response = await _reactivate(client, user_b["access_token"], created["id"])
    assert response.status_code == 403


async def test_reactivate_medication_unauthenticated_401(client):
    """Sin token -> 401."""
    response = await client.post("/api/v1/medications/1/reactivate")
    assert response.status_code == 401


# ------------------------------------------------------------------
# 2. Las CANCELADA no se reviven; los futuros nacen por generacion
# ------------------------------------------------------------------


async def test_reactivate_keeps_cancelled_and_regenerates(client, session):
    """Desactivar cancela los futuros (MEDICATION_DEACTIVATED);
    reactivar NO los revive y el mecanismo normal de generacion
    crea los PENDIENTE nuevos."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    user_id = body["user"]["id"]
    created = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    treatment, link, schedule = await _seed_treatment_chain(
        session, user_id, created["id"]
    )
    user = await session.get(User, user_id)
    now = datetime.now(timezone.utc)

    # Generacion normal: crea los PENDIENTE de la ventana 72 h.
    inserted = await generate_reminders_for_schedule(
        session, schedule, treatment, user, now=now
    )
    assert inserted >= 1
    rows = await _reminder_rows(session, user_id)
    assert len(rows) == inserted
    assert all(status == "PENDIENTE" for _, _, status, _ in rows)

    # Desactivar: los futuros pasan a CANCELADA con el motivo.
    await _deactivate_ok(client, token, created["id"])
    rows = await _reminder_rows(session, user_id)
    assert len(rows) == inserted
    assert all(status == "CANCELADA" for _, _, status, _ in rows)
    assert all(
        reason == "MEDICATION_DEACTIVATED" for _, _, _, reason in rows
    )

    # Mientras esta inactivo, la generacion no crea nada (I-3).
    assert (
        await generate_reminders_for_schedule(
            session, schedule, treatment, user, now=now
        )
        == 0
    )

    # Reactivar: 200, activo.
    response = await _reactivate(client, token, created["id"])
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True

    # Las CANCELADA siguen CANCELADA con su motivo: no se reviven.
    rows = await _reminder_rows(session, user_id)
    assert len(rows) == inserted
    assert all(status == "CANCELADA" for _, _, status, _ in rows)
    assert all(
        reason == "MEDICATION_DEACTIVATED" for _, _, _, reason in rows
    )

    # El mecanismo normal de generacion crea los PENDIENTE nuevos.
    inserted_again = await generate_reminders_for_schedule(
        session, schedule, treatment, user, now=now
    )
    assert inserted_again >= 1
    rows = await _reminder_rows(session, user_id)
    cancelled = [r for r in rows if r[2] == "CANCELADA"]
    pending = [r for r in rows if r[2] == "PENDIENTE"]
    assert len(cancelled) == inserted
    assert all(r[3] == "MEDICATION_DEACTIVATED" for r in cancelled)
    assert len(pending) == inserted_again


# ------------------------------------------------------------------
# 3. Cuidador: mismo permiso y auditoria que la desactivacion
# ------------------------------------------------------------------


async def test_reactivate_caregiver_with_permission_ok_and_audit(client, session):
    """Cuidador con `perm_manage_medications` reactiva -> 200 y
    queda la fila de auditoria MANAGE_MEDICATION_REACTIVATE/OK."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client,
        patient["access_token"],
        {"name": "Amoxicilina"},
    )
    await _deactivate_ok(client, patient["access_token"], created["id"])
    response = await _reactivate(
        client,
        caregiver["access_token"],
        created["id"],
        patient_id=patient["user"]["id"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "MANAGE_MEDICATION_REACTIVATE"
    assert rows[0].result == "OK"


async def test_reactivate_caregiver_without_permission_403_and_audit(client, session):
    """Cuidador sin `perm_manage_medications` -> 403 y registro
    ACCESS_DENIED; el medicamento sigue inactivo."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_medications=True
    )
    created = await _create_medication_ok(
        client,
        patient["access_token"],
        {"name": "Amoxicilina"},
    )
    await _deactivate_ok(client, patient["access_token"], created["id"])
    response = await _reactivate(
        client,
        caregiver["access_token"],
        created["id"],
        patient_id=patient["user"]["id"],
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].result == "DENEGADO"
    assert rows[0].details["attempted_action"] == "MANAGE_MEDICATION_REACTIVATE"
    # El medicamento sigue inactivo.
    result = await session.execute(
        select(Medication).where(Medication.id == created["id"])
    )
    assert result.scalar_one().is_active is False
