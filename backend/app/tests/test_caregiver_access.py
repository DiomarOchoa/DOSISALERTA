"""Pruebas de acceso del cuidador (Fase 4, diseno §4.6 y §4.12).

Reglas probadas aqui (modulos de medicamentos y de
tratamientos/vinculos; los casos de horarios y recordatorios
llegan con sus modulos): el cuidador con permiso ve y gestiona
medicamentos del paciente; sin vinculo ACTIVO o sin el
permiso concreto -> 403; editar `concentration`/`unit` ->
403 siempre; desactivar un medicamento en tratamiento activo
-> 403; el cuidador nunca crea/edita tratamientos, cambia su
estado ni escribe dosis (403 directo, auditado); la lectura
de tratamientos filtra secciones por D-1; cada accion
(concedida o denegada) queda en `caregiver_audit_log` (RF22),
con `details` minimizado (RELACIONES §5.3: nunca nombres de
medicamentos).

Misma infraestructura de pruebas que `test_auth.py` y
`test_medications.py` (base `dosisalerta_test`, transaccion
por prueba con savepoint, cliente HTTP con ASGITransport).
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
from app.models import (
    CaregiverAuditLog,
    CaregiverLink,
    Treatment,
    TreatmentMedication,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "clave-segura-123"


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


async def _make_link(session, patient_id, caregiver_id, status="ACTIVO", **perms):
    """Crea un vinculo paciente-cuidador con los permisos dados.

    ACTIVO exige `accepted_at` (CHECK) y `caregiver_user_id`
    no nulo; REVOCADO exige `revoked_at`. Gestionar exige ver
    (CHECK): `perm_manage_medications` solo con
    `perm_view_medications` en True.
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


async def _make_active_treatment_with_medication(
    session, patient_id, medication_id
):
    """Tratamiento ACTIVO con el medicamento en vinculo activo."""
    treatment = Treatment(
        user_id=patient_id, title="Infeccion", start_date=date(2026, 11, 11)
    )
    session.add(treatment)
    await session.flush()
    link = TreatmentMedication(
        user_id=patient_id,
        treatment_id=treatment.id,
        medication_id=medication_id,
        dose_amount=1,
        dose_unit="capsula",
    )
    session.add(link)
    await session.flush()
    return treatment, link


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


BOGOTA = ZoneInfo("America/Bogota")


def _today_bogota() -> date:
    """Hoy en la zona del usuario (la de generacion)."""
    return datetime.now(BOGOTA).date()


def _schedule_payload(times=("08:00",)):
    """Horario valido: DIARIO a las horas dadas, desde hoy."""
    return {
        "frequency": "DIARIO",
        "times": list(times),
        "start_date": _today_bogota().isoformat(),
    }


def _treatment_payload(medication_id, title="Tratamiento"):
    """Tratamiento con un medicamento y un horario DIARIO."""
    return {
        "title": title,
        "start_date": _today_bogota().isoformat(),
        "medications": [
            {
                "medication_id": medication_id,
                "dose_amount": 1,
                "dose_unit": "capsula",
                "schedules": [_schedule_payload()],
            }
        ],
    }


async def _create_treatment_ok(client, token, payload, patient_id=None):
    """Crea un tratamiento y devuelve su cuerpo (201)."""
    url = "/api/v1/treatments"
    if patient_id is not None:
        url += f"?patient_id={patient_id}"
    response = await client.post(url, json=payload, headers=_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _patient_with_treatment(client, session, **perms):
    """Paciente + cuidador con vinculo, y un tratamiento del
    paciente con un medicamento y recordatorios generados.

    Devuelve (paciente, cuidador, tratamiento).
    """
    patient, caregiver = await _patient_and_caregiver(client, session, **perms)
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    treatment = await _create_treatment_ok(
        client,
        patient["access_token"],
        _treatment_payload(created["id"]),
    )
    return patient, caregiver, treatment


# ------------------------------------------------------------------
# 1. Lectura con permiso
# ------------------------------------------------------------------


async def test_caregiver_views_medications_with_permission(client, session):
    """Cuidador con `perm_view_medications` -> 200, solo los
    medicamentos del paciente (no los suyos propios)."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_medications=True
    )
    await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    await _create_medication_ok(
        client, caregiver["access_token"], {"name": "Paracetamol"}
    )
    response = await client.get(
        f"/api/v1/medications?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert [item["name"] for item in response.json()] == ["Amoxicilina"]


async def test_caregiver_views_one_medication_with_permission(client, session):
    """Cuidador con `perm_view_medications` -> 200 en el detalle."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_medications=True
    )
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.get(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Amoxicilina"


# ------------------------------------------------------------------
# 2. Lectura sin permiso o sin vinculo
# ------------------------------------------------------------------


async def test_caregiver_views_medications_without_permission(client, session):
    """Vinculo ACTIVO sin `perm_view_medications` -> 403."""
    patient, caregiver = await _patient_and_caregiver(client, session)
    response = await client.get(
        f"/api/v1/medications?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


async def test_caregiver_views_medications_without_link(client, session):
    """Sin vinculo con el paciente -> 403."""
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    response = await client.get(
        f"/api/v1/medications?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


async def test_caregiver_views_medications_revoked_link(client, session):
    """Vinculo REVOCADO -> 403 aunque el permiso estuviera dado."""
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    await _make_link(
        session,
        patient["user"]["id"],
        caregiver["user"]["id"],
        status="REVOCADO",
        perm_view_medications=True,
    )
    response = await client.get(
        f"/api/v1/medications?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 3. Crear con permiso
# ------------------------------------------------------------------


async def test_caregiver_creates_medication_with_permission(client, session):
    """Cuidador con `perm_manage_medications` crea medicamentos
    del paciente -> 201, el medicamento queda a nombre del
    paciente (no del cuidador)."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client,
        caregiver["access_token"],
        {"name": "Amoxicilina"},
        patient_id=patient["user"]["id"],
    )
    assert created["name"] == "Amoxicilina"
    assert created["is_active"] is True
    # El paciente lo ve en su propio listado.
    response = await client.get(
        "/api/v1/medications", headers=_headers(patient["access_token"])
    )
    assert [item["name"] for item in response.json()] == ["Amoxicilina"]


async def test_caregiver_creates_medication_without_permission(client, session):
    """Cuidador sin `perm_manage_medications` -> 403."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_medications=True
    )
    response = await client.post(
        f"/api/v1/medications?patient_id={patient['user']['id']}",
        json={"name": "Amoxicilina"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 4. Editar: campos permitidos y prohibidos (C3)
# ------------------------------------------------------------------


async def test_caregiver_updates_allowed_fields(client, session):
    """Cuidador con permiso edita solo `name`/`presentation`/
    `notes` -> 200."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        json={"name": "Amoxicilina forte", "notes": "Con alimentos"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Amoxicilina forte"
    assert response.json()["notes"] == "Con alimentos"


async def test_caregiver_updates_concentration_403(client, session):
    """Cuidador edita `concentration` -> 403 (C3: la
    concentracion es lo que se muestra como dosis)."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client,
        patient["access_token"],
        {"name": "Amoxicilina", "concentration": "500 mg"},
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        json={"concentration": "250 mg"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    # Nada cambio: la concentracion sigue siendo la original.
    response = await client.get(
        f"/api/v1/medications/{created['id']}",
        headers=_headers(patient["access_token"]),
    )
    assert response.json()["concentration"] == "500 mg"


async def test_caregiver_updates_unit_403(client, session):
    """Cuidador edita `unit` -> 403 (C3)."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client,
        patient["access_token"],
        {"name": "Amoxicilina", "unit": "capsula"},
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        json={"unit": "comprimido"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 5. Desactivar (C3)
# ------------------------------------------------------------------


async def test_caregiver_deactivates_medication_not_in_treatment(client, session):
    """Cuidador con permiso desactiva un medicamento sin
    tratamiento activo -> 200."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.delete(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False


async def test_caregiver_deactivates_medication_in_active_treatment_403(
    client, session
):
    """Cuidador desactiva un medicamento en tratamiento ACTIVO
    -> 403 (desactivarlo silenciaria sus recordatorios)."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    await _make_active_treatment_with_medication(
        session, patient["user"]["id"], created["id"]
    )
    response = await client.delete(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    # El medicamento sigue activo.
    response = await client.get(
        f"/api/v1/medications/{created['id']}",
        headers=_headers(patient["access_token"]),
    )
    assert response.json()["is_active"] is True


# ------------------------------------------------------------------
# 6. Auditoria (RF22)
# ------------------------------------------------------------------


async def test_caregiver_action_audited_ok(client, session):
    """Una accion concedida queda en `caregiver_audit_log` con
    resultado OK y la accion que fue."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client,
        caregiver["access_token"],
        {"name": "Amoxicilina"},
        patient_id=patient["user"]["id"],
    )
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "MANAGE_MEDICATION_CREATE"
    assert rows[0].result == "OK"
    assert rows[0].target_type == "medication"
    assert rows[0].target_id == created["id"]


async def test_caregiver_denial_audited_access_denied(client, session):
    """Una denegacion queda en `caregiver_audit_log` como
    ACCESS_DENIED, con la operacion intentada en `details`."""
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    response = await client.get(
        f"/api/v1/medications?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].result == "DENEGADO"
    assert rows[0].details["attempted_action"] == "VIEW_MEDICATIONS"


async def test_caregiver_audit_details_minimized(client, session):
    """`details` solo lleva el nombre del campo que cambio
    (§5.3): nunca el nombre del medicamento ni su valor."""
    patient, caregiver = await _patient_and_caregiver(
        client,
        session,
        perm_view_medications=True,
        perm_manage_medications=True,
    )
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.patch(
        f"/api/v1/medications/{created['id']}?patient_id={patient['user']['id']}",
        json={"name": "Amoxicilina forte"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "MANAGE_MEDICATION_UPDATE"
    assert rows[0].result == "OK"
    assert rows[0].details == {"field": "name"}
    assert "Amoxicilina" not in str(rows[0].details)


# ------------------------------------------------------------------
# 7. Tratamientos: filtrado por seccion D-1
# ------------------------------------------------------------------


async def test_caregiver_treatment_detail_only_general_data(client, session):
    """Cuidador con solo `perm_view_treatments` -> 200 con solo
    datos generales: `medications` y `upcoming_reminders`
    AUSENTES del JSON (ni null ni lista vacia)."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    response = await client.get(
        f"/api/v1/treatments/{treatment['id']}"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "Tratamiento"
    assert data["status"] == "ACTIVO"
    assert "medications" not in data
    assert "upcoming_reminders" not in data


async def test_caregiver_treatment_detail_with_medications_no_schedules(
    client, session
):
    """Cuidador con `perm_view_treatments` + `perm_view_medications`
    -> 200 con medicamentos, pero sin horarios en cada vinculo y
    sin proximos recordatorios."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client,
        session,
        perm_view_treatments=True,
        perm_view_medications=True,
    )
    response = await client.get(
        f"/api/v1/treatments/{treatment['id']}"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "medications" in data
    assert len(data["medications"]) == 1
    assert "schedules" not in data["medications"][0]
    assert "upcoming_reminders" not in data


async def test_caregiver_treatment_detail_schedules_without_medications(
    client, session
):
    """Cuidador con `perm_view_treatments` + `perm_view_schedules`
    (sin `perm_view_medications`) -> 200 con solo datos generales:
    sin seccion de medicamentos no hay donde mostrar horarios."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client,
        session,
        perm_view_treatments=True,
        perm_view_schedules=True,
    )
    response = await client.get(
        f"/api/v1/treatments/{treatment['id']}"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "medications" not in data
    assert "upcoming_reminders" not in data


async def test_caregiver_treatment_detail_all_permissions(client, session):
    """Cuidador con los 4 permisos -> 200 con todo: medicamentos
    con horarios y proximos recordatorios."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client,
        session,
        perm_view_treatments=True,
        perm_view_medications=True,
        perm_view_schedules=True,
        perm_view_upcoming=True,
    )
    response = await client.get(
        f"/api/v1/treatments/{treatment['id']}"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "medications" in data
    assert "schedules" in data["medications"][0]
    assert "upcoming_reminders" in data


async def test_caregiver_treatment_detail_without_view_treatments_403(
    client, session
):
    """Cuidador sin `perm_view_treatments` -> 403 aunque tenga los
    otros 3 permisos."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client,
        session,
        perm_view_medications=True,
        perm_view_schedules=True,
        perm_view_upcoming=True,
    )
    response = await client.get(
        f"/api/v1/treatments/{treatment['id']}"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


async def test_patient_treatment_detail_full(client, session):
    """Paciente -> 200 con todo siempre (medicamentos, horarios y
    proximos recordatorios)."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    response = await client.get(
        f"/api/v1/treatments/{treatment['id']}",
        headers=_headers(patient["access_token"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "medications" in data
    assert "schedules" in data["medications"][0]
    assert "upcoming_reminders" in data


async def test_caregiver_treatment_list_only_general_data(client, session):
    """Listado `GET /treatments` con solo `perm_view_treatments`:
    cada elemento sin secciones anidadas (derivada de D-1)."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    response = await client.get(
        f"/api/v1/treatments?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    item = response.json()[0]
    assert item["id"] == treatment["id"]
    assert "medications" not in item
    assert "upcoming_reminders" not in item


# ------------------------------------------------------------------
# 8. Tratamientos/vinculos: 403 directo para el cuidador
# ------------------------------------------------------------------


async def test_caregiver_creates_treatment_403_and_audited(client, session):
    """Cuidador crea un tratamiento -> 403 directo + ACCESS_DENIED
    auditado (ningun permiso cubre crear tratamientos)."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_treatments=True
    )
    created = await _create_medication_ok(
        client, patient["access_token"], {"name": "Amoxicilina"}
    )
    response = await client.post(
        f"/api/v1/treatments?patient_id={patient['user']['id']}",
        json=_treatment_payload(created["id"]),
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].result == "DENEGADO"
    assert rows[0].details["attempted_action"] == "CREATE_TREATMENT"


async def test_caregiver_updates_treatment_403_and_audited(client, session):
    """Cuidador edita un tratamiento -> 403 directo + ACCESS_DENIED."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    response = await client.patch(
        f"/api/v1/treatments/{treatment['id']}"
        f"?patient_id={patient['user']['id']}",
        json={"title": "Otro titulo"},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].details["attempted_action"] == "UPDATE_TREATMENT"


async def test_caregiver_changes_treatment_state_403_and_audited(
    client, session
):
    """Cuidador cambia el estado de un tratamiento -> 403 directo
    + ACCESS_DENIED."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    response = await client.post(
        f"/api/v1/treatments/{treatment['id']}/pause"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].details["attempted_action"] == "PAUSE_TREATMENT"


async def test_caregiver_adds_medication_to_treatment_403_and_audited(
    client, session
):
    """Cuidador anade un medicamento a un tratamiento -> 403
    directo + ACCESS_DENIED."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    second = await _create_medication_ok(
        client, patient["access_token"], {"name": "Paracetamol"}
    )
    response = await client.post(
        f"/api/v1/treatments/{treatment['id']}/medications"
        f"?patient_id={patient['user']['id']}",
        json={
            "medication_id": second["id"],
            "dose_amount": 1,
            "dose_unit": "capsula",
            "schedules": [_schedule_payload()],
        },
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].details["attempted_action"] == "ADD_TREATMENT_MEDICATION"


async def test_caregiver_updates_link_dose_403_and_audited(client, session):
    """Cuidador cambia la dosis de un vinculo -> 403 directo +
    ACCESS_DENIED."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    link_id = treatment["medications"][0]["id"]
    response = await client.patch(
        f"/api/v1/treatments/{treatment['id']}/medications/{link_id}"
        f"?patient_id={patient['user']['id']}",
        json={"dose_amount": 5},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].details["attempted_action"] == "UPDATE_TREATMENT_MEDICATION"


async def test_caregiver_removes_medication_from_treatment_403_and_audited(
    client, session
):
    """Cuidador quita un medicamento de un tratamiento -> 403
    directo + ACCESS_DENIED."""
    patient, caregiver, treatment = await _patient_with_treatment(
        client, session, perm_view_treatments=True
    )
    link_id = treatment["medications"][0]["id"]
    response = await client.delete(
        f"/api/v1/treatments/{treatment['id']}/medications/{link_id}"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403
    rows = await _audit_rows(
        session, caregiver["user"]["id"], patient["user"]["id"]
    )
    assert len(rows) == 1
    assert rows[0].action == "ACCESS_DENIED"
    assert rows[0].details["attempted_action"] == "DELETE_TREATMENT_MEDICATION"
