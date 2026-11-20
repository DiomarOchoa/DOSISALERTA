"""Pruebas de integracion de tratamientos y vinculos (Fase 4,
RF05/RF06/RF08).

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

Sobre las horas: la generacion usa la ventana [ahora,
ahora+72h) en tiempo absoluto, con las horas de pared en la
zona del usuario (America/Bogota, la zona de registro en estas
pruebas). Los conteos exactos se comprueban en la BD (numero
de filas generadas en la ventana); las respuestas HTTP de
proximos recordatorios solo se comprueban por presencia y
rango, porque un recordatorio de hoy a una hora ya pasada no
se genera.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
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
    CaregiverLink,
    MedicationIntake,
    MedicationReminder,
    MedicationSchedule,
    Treatment,
    TreatmentMedication,
    User,
)
from app.services.schedule_service import generate_reminders_for_schedule

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "clave-segura-123"
BOGOTA = ZoneInfo("America/Bogota")

# Ventana de generacion vigente: [ahora, ahora+72h) en tiempo absoluto.
HORIZON_HOURS = 72


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


def _wall_utc(day: date, wall: time) -> datetime:
    """Hora de pared en Bogota convertida a UTC."""
    return datetime.combine(day, wall, tzinfo=BOGOTA).astimezone(timezone.utc)


def _expected_occurrences(
    now_utc: datetime,
    *,
    times: tuple[str, ...],
    frequency: str = "DIARIO",
    days_of_week: tuple[int, ...] | None = None,
    interval_days: int | None = None,
    start_date: date,
    end_date: date | None = None,
) -> list[datetime]:
    """Instantes que debe generar la ventana [ahora, ahora+72h).

    Es la misma regla del servicio (`schedule_service`): por cada
    fecha en la ventana que coincida con la frecuencia y cada hora
    de `times`, el instante de pared en Bogota convertido a UTC,
    solo si cae en [ahora, ahora+72h).
    """
    limit = now_utc + timedelta(hours=HORIZON_HOURS)
    last_day = limit.astimezone(BOGOTA).date()
    expected: list[datetime] = []
    day = max(start_date, now_utc.astimezone(BOGOTA).date())
    while day <= last_day:
        if end_date is not None and day > end_date:
            break
        if frequency == "DIARIO":
            matches = True
        elif frequency == "DIAS_SEMANA":
            matches = day.weekday() in (days_of_week or ())
        elif frequency == "INTERVALO_DIAS":
            matches = (
                interval_days is not None
                and (day - start_date).days % interval_days == 0
            )
        else:
            raise ValueError(f"frecuencia desconocida: {frequency}")
        if matches:
            for wall in times:
                hour, minute = (int(part) for part in wall.split(":"))
                candidate = _wall_utc(day, time(hour, minute))
                if now_utc <= candidate < limit:
                    expected.append(candidate)
        day += timedelta(days=1)
    return sorted(expected)


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


def _schedule_payload(
    times=("08:00",),
    frequency="DIARIO",
    start=None,
    end=None,
    **extra,
):
    """Horario valido: DIARIO a las horas dadas, desde hoy."""
    payload = {
        "frequency": frequency,
        "times": list(times),
        "start_date": (start or _today_bogota()).isoformat(),
    }
    if end is not None:
        payload["end_date"] = end.isoformat()
    payload.update(extra)
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


async def _make_link(session, patient_id, caregiver_id, status="ACTIVO", **perms):
    """Crea un vinculo paciente-cuidador con los permisos dados."""
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
    """Paciente + cuidador registrados, con vinculo ACTIVO."""
    patient = await _register_ok(client, _unique_email("paciente"))
    caregiver = await _register_ok(client, _unique_email("cuidador"))
    await _make_link(
        session,
        patient["user"]["id"],
        caregiver["user"]["id"],
        **perms,
    )
    return patient, caregiver


async def _two_medications(client, token):
    """Dos medicamentos del usuario, devuelve sus cuerpos."""
    first = await _create_medication_ok(client, token, {"name": "Amoxicilina"})
    second = await _create_medication_ok(client, token, {"name": "Paracetamol"})
    return first, second


async def _reminders_of_schedule(session, schedule_id):
    """Recordatorios de un horario, ordenados por fecha."""
    result = await session.execute(
        select(MedicationReminder)
        .where(MedicationReminder.schedule_id == schedule_id)
        .order_by(MedicationReminder.scheduled_at)
    )
    return list(result.scalars().all())


async def _make_taken_reminder(session, schedule_id, link_id, user_id, day):
    """Recordatorio TOMADA de ayer + su toma confirmada (historial)."""
    reminder = MedicationReminder(
        schedule_id=schedule_id,
        treatment_medication_id=link_id,
        user_id=user_id,
        scheduled_at=_wall_utc(day, time(8, 0)),
        status="TOMADA",
    )
    session.add(reminder)
    await session.flush()
    intake = MedicationIntake(
        reminder_id=reminder.id,
        user_id=user_id,
        taken_at=_wall_utc(day, time(8, 5)),
        source="WEB",
    )
    session.add(intake)
    await session.flush()
    return reminder


# ------------------------------------------------------------------
# 1. Crear
# ------------------------------------------------------------------


async def test_create_treatment_ok(client, session):
    """Crear con 2 medicamentos y horarios distintos (aceptacion):
    201, ACTIVO, medicamentos con dosis y horarios, y
    `upcoming_reminders` con los generados (ventana 72 horas)."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    today = _today_bogota()
    before = datetime.now(timezone.utc)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload(
            [
                _med_item(first["id"], [_schedule_payload()]),
                _med_item(
                    second["id"],
                    [
                        _schedule_payload(
                            ("09:00", "21:00"),
                            frequency="DIAS_SEMANA",
                            days_of_week=[0, 2, 4],
                        )
                    ],
                    dose_amount=2,
                    dose_unit="comprimido",
                ),
            ]
        ),
    )
    after = datetime.now(timezone.utc)
    assert created["status"] == "ACTIVO"
    assert created["title"] == "Tratamiento"
    assert len(created["medications"]) == 2
    assert created["medications"][0]["dose_amount"] == 1
    assert created["medications"][1]["dose_amount"] == 2
    assert created["medications"][1]["dose_unit"] == "comprimido"
    assert len(created["medications"][0]["schedules"]) == 1
    assert created["medications"][0]["schedules"][0]["frequency"] == "DIARIO"
    assert "upcoming_reminders" in created
    # Ventana [ahora, ahora+72h): el total en BD debe ser exacto
    # (DIARIO 1 hora = 3 instantes; DIAS_SEMANA 2 horas en los dias
    # de la ventana que caen en lunes/miercoles/viernes).
    first_schedule_id = created["medications"][0]["schedules"][0]["id"]
    second_schedule_id = created["medications"][1]["schedules"][0]["id"]
    expected_first = _expected_occurrences(
        before, times=("08:00",), start_date=today
    )
    expected_second = _expected_occurrences(
        before,
        times=("09:00", "21:00"),
        frequency="DIAS_SEMANA",
        days_of_week=(0, 2, 4),
        start_date=today,
    )
    first_rows = await _reminders_of_schedule(session, first_schedule_id)
    second_rows = await _reminders_of_schedule(session, second_schedule_id)
    assert [row.scheduled_at for row in first_rows] == expected_first
    assert [row.scheduled_at for row in second_rows] == expected_second
    for reminder in created["upcoming_reminders"]:
        scheduled_at = datetime.fromisoformat(
            reminder["scheduled_at"].replace("Z", "+00:00")
        )
        assert before <= scheduled_at < after + timedelta(hours=HORIZON_HOURS)


async def test_create_treatment_atomic_rollback(client, session):
    """Creacion atomica: si un horario del segundo medicamento
    falla (fin antes de inicio -> 400), no queda ningun
    tratamiento, vinculo, horario ni recordatorio en la BD."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    today = _today_bogota()
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [
                _med_item(first["id"], [_schedule_payload()]),
                _med_item(
                    second["id"],
                    [
                        _schedule_payload(
                            start=today,
                            end=today - timedelta(days=1),
                        )
                    ],
                ),
            ]
        ),
        headers=_headers(token),
    )
    assert response.status_code == 400, response.text
    treatments = list((await session.execute(select(Treatment))).scalars().all())
    assert treatments == []
    assert list((await session.execute(select(TreatmentMedication))).scalars().all()) == []
    assert list((await session.execute(select(MedicationSchedule))).scalars().all()) == []
    assert list((await session.execute(select(MedicationReminder))).scalars().all()) == []


async def test_create_treatment_end_before_start_400(client):
    """`end_date < start_date` del tratamiento -> 400."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    today = _today_bogota()
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [_med_item(first["id"], [_schedule_payload()])],
            start=today,
            end=today - timedelta(days=1),
        ),
        headers=_headers(token),
    )
    assert response.status_code == 400


async def test_create_treatment_deactivated_medication_409(client, session):
    """Medicamento desactivado en la creacion -> 409 y no se crea
    el tratamiento."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    response = await client.delete(
        f"/api/v1/medications/{second['id']}", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [
                _med_item(first["id"], [_schedule_payload()]),
                _med_item(second["id"], [_schedule_payload()]),
            ]
        ),
        headers=_headers(token),
    )
    assert response.status_code == 409
    treatments = list((await session.execute(select(Treatment))).scalars().all())
    assert treatments == []


async def test_create_treatment_duplicate_medication_409(client):
    """El mismo medicamento dos veces en el payload -> 409."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [
                _med_item(first["id"], [_schedule_payload()]),
                _med_item(first["id"], [_schedule_payload(("10:00",))]),
            ]
        ),
        headers=_headers(token),
    )
    assert response.status_code == 409


async def test_create_treatment_foreign_medication_403(client):
    """Medicamento de otro usuario en la creacion -> 403."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    foreign, _ = await _two_medications(client, user_a["access_token"])
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [_med_item(foreign["id"], [_schedule_payload()])]
        ),
        headers=_headers(user_b["access_token"]),
    )
    assert response.status_code == 403


async def test_create_treatment_medication_not_found_404(client):
    """Medicamento inexistente en la creacion -> 404."""
    body = await _register_ok(client, _unique_email())
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [_med_item(999999, [_schedule_payload()])]
        ),
        headers=_headers(body["access_token"]),
    )
    assert response.status_code == 404


async def test_create_treatment_unauthenticated_401(client):
    """Sin token -> 401."""
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [_med_item(1, [_schedule_payload()])]
        ),
    )
    assert response.status_code == 401


async def test_create_treatment_schedule_without_times_422(client):
    """Horario sin horas (`times` vacio) -> 422."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [_med_item(first["id"], [_schedule_payload(times=[])])]
        ),
        headers=_headers(token),
    )
    assert response.status_code == 422


async def test_create_treatment_weekly_without_days_422(client):
    """DIAS_SEMANA sin `days_of_week` -> 422."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    response = await client.post(
        "/api/v1/treatments",
        json=_treatment_payload(
            [
                _med_item(
                    first["id"],
                    [_schedule_payload(frequency="DIAS_SEMANA")],
                )
            ]
        ),
        headers=_headers(token),
    )
    assert response.status_code == 422


# ------------------------------------------------------------------
# 2. Listar y ver
# ------------------------------------------------------------------


async def test_list_treatments_by_status(client):
    """Listar por estado: cada filtro trae solo los suyos."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    one = await _create_treatment_ok(
        client,
        token,
        _treatment_payload(
            [_med_item(first["id"], [_schedule_payload()])], title="Uno"
        ),
    )
    await _create_treatment_ok(
        client,
        token,
        _treatment_payload(
            [_med_item(first["id"], [_schedule_payload()])], title="Dos"
        ),
    )
    response = await client.post(
        f"/api/v1/treatments/{one['id']}/pause", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.get(
        "/api/v1/treatments?status=PAUSADO", headers=_headers(token)
    )
    assert [item["title"] for item in response.json()] == ["Uno"]
    response = await client.get(
        "/api/v1/treatments?status=ACTIVO", headers=_headers(token)
    )
    assert [item["title"] for item in response.json()] == ["Dos"]
    response = await client.get("/api/v1/treatments", headers=_headers(token))
    assert len(response.json()) == 2


async def test_get_treatment_nested(client):
    """Ver con anidado: el paciente ve medicamentos, horarios y
    proximos recordatorios."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.get(
        f"/api/v1/treatments/{created['id']}", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == created["id"]
    assert "medications" in data
    assert len(data["medications"]) == 1
    assert "schedules" in data["medications"][0]
    assert data["medications"][0]["medication"]["name"] == "Amoxicilina"
    assert "upcoming_reminders" in data


async def test_get_treatment_not_found_404(client):
    """Id inexistente -> 404."""
    body = await _register_ok(client, _unique_email())
    response = await client.get(
        "/api/v1/treatments/999999", headers=_headers(body["access_token"])
    )
    assert response.status_code == 404


async def test_get_treatment_other_user_403(client):
    """Tratamiento de otro usuario -> 403 (no 404: existe)."""
    user_a = await _register_ok(client, _unique_email("a"))
    user_b = await _register_ok(client, _unique_email("b"))
    first, _ = await _two_medications(client, user_a["access_token"])
    created = await _create_treatment_ok(
        client,
        user_a["access_token"],
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.get(
        f"/api/v1/treatments/{created['id']}",
        headers=_headers(user_b["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 3. Editar
# ------------------------------------------------------------------


async def test_update_treatment_ok(client):
    """PATCH parcial: cambia titulo y fin; el estado no cambia."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    today = _today_bogota()
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}",
        json={
            "title": "Infeccion tratada",
            "notes": "Con alimentos",
            "end_date": (today + timedelta(days=10)).isoformat(),
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "Infeccion tratada"
    assert data["notes"] == "Con alimentos"
    assert data["status"] == "ACTIVO"
    assert data["end_date"] == (today + timedelta(days=10)).isoformat()


async def test_update_treatment_end_before_start_400(client):
    """PATCH con `end_date < start_date` -> 400."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    today = _today_bogota()
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}",
        json={"end_date": (today - timedelta(days=1)).isoformat()},
        headers=_headers(token),
    )
    assert response.status_code == 400


# ------------------------------------------------------------------
# 4. Estados
# ------------------------------------------------------------------


async def test_pause_treatment_cancels_future_preserves_taken(client, session):
    """Pausar cancela los PENDIENTE futuros y conserva el
    historial (una toma TOMADA con su intake sigue intacta)."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    user_id = body["user"]["id"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    link_id = created["medications"][0]["id"]
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    today = _today_bogota()
    taken = await _make_taken_reminder(
        session, schedule_id, link_id, user_id, today - timedelta(days=1)
    )
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/pause", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PAUSADO"
    now = datetime.now(timezone.utc)
    future = [
        row
        for row in await _reminders_of_schedule(session, schedule_id)
        if row.scheduled_at >= now
    ]
    assert len(future) == 3
    assert all(row.status == "CANCELADA" for row in future)
    # El historial no se toca.
    result = await session.execute(
        select(MedicationReminder).where(MedicationReminder.id == taken.id)
    )
    assert result.scalar_one().status == "TOMADA"
    result = await session.execute(
        select(MedicationIntake).where(
            MedicationIntake.reminder_id == taken.id
        )
    )
    assert result.scalar_one() is not None


async def test_resume_treatment_regenerates(client, session):
    """Reanudar regenera sin borrar el historial (decision B):
    las CANCELADA quedan intactas y se crean PENDIENTE nuevas
    (con parent_reminder_id), sin duplicados activos."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    before = await _reminders_of_schedule(session, schedule_id)
    assert len(before) == 3
    assert all(row.status == "PENDIENTE" for row in before)
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/pause", headers=_headers(token)
    )
    assert response.status_code == 200
    cancelled = await _reminders_of_schedule(session, schedule_id)
    assert len(cancelled) == 3
    assert all(row.status == "CANCELADA" for row in cancelled)
    cancelled_ids = {row.id for row in cancelled}
    cancelled_by_time = {row.scheduled_at: row.id for row in cancelled}
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/resume", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVO"
    rows = await _reminders_of_schedule(session, schedule_id)
    assert len(rows) == 6
    old = [row for row in rows if row.id in cancelled_ids]
    new = [row for row in rows if row.id not in cancelled_ids]
    # El historial queda intacto: mismas filas, mismo estado.
    assert len(old) == 3
    assert all(row.status == "CANCELADA" for row in old)
    # Las nuevas son PENDIENTE, una por hueco, sin duplicados.
    assert len(new) == 3
    assert all(row.status == "PENDIENTE" for row in new)
    assert len({row.scheduled_at for row in new}) == 3
    assert {row.scheduled_at for row in new} == {
        row.scheduled_at for row in old
    }
    # Cada nueva apunta a la cancelada que reemplaza.
    assert all(
        row.parent_reminder_id == cancelled_by_time[row.scheduled_at]
        for row in new
    )


async def test_cancel_treatment_ok(client, session):
    """Cancelar: estado CANCELADO y futuros PENDIENTE cancelados."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/cancel", headers=_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELADO"
    now = datetime.now(timezone.utc)
    future = [
        row
        for row in await _reminders_of_schedule(session, schedule_id)
        if row.scheduled_at >= now
    ]
    assert all(row.status == "CANCELADA" for row in future)


async def test_complete_treatment_ok(client, session):
    """Completar: estado COMPLETADO y futuros PENDIENTE cancelados."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/complete",
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETADO"
    now = datetime.now(timezone.utc)
    future = [
        row
        for row in await _reminders_of_schedule(session, schedule_id)
        if row.scheduled_at >= now
    ]
    assert all(row.status == "CANCELADA" for row in future)


async def test_invalid_transitions_400(client):
    """Transiciones invalidas -> 400: pausar un PAUSADO, reanudar
    un ACTIVO, completar un PAUSADO, y cualquier transicion desde
    un estado terminal."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    treatment_id = created["id"]
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/resume", headers=_headers(token)
    )
    assert response.status_code == 400
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/pause", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/pause", headers=_headers(token)
    )
    assert response.status_code == 400
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/complete", headers=_headers(token)
    )
    assert response.status_code == 400
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/cancel", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/pause", headers=_headers(token)
    )
    assert response.status_code == 400
    response = await client.post(
        f"/api/v1/treatments/{treatment_id}/resume", headers=_headers(token)
    )
    assert response.status_code == 400


# ------------------------------------------------------------------
# 5. Vinculos: anadir, editar dosis, quitar
# ------------------------------------------------------------------


async def test_add_medication_to_treatment_ok(client, session):
    """Anadir un medicamento a un tratamiento ACTIVO -> 201, con
    sus horarios y sus recordatorios generados."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/medications",
        json=_med_item(
            second["id"],
            [_schedule_payload(("12:00",))],
            dose_amount=2,
            dose_unit="comprimido",
        ),
        headers=_headers(token),
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["medication_id"] == second["id"]
    assert data["dose_amount"] == 2
    assert data["dose_unit"] == "comprimido"
    assert data["is_active"] is True
    assert len(data["schedules"]) == 1
    schedule_id = data["schedules"][0]["id"]
    assert len(await _reminders_of_schedule(session, schedule_id)) == 3


async def test_add_medication_treatment_not_active_400(client):
    """Anadir a un tratamiento PAUSADO -> 400."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/pause", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/medications",
        json=_med_item(second["id"], [_schedule_payload()]),
        headers=_headers(token),
    )
    assert response.status_code == 400


async def test_add_medication_deactivated_409(client):
    """Anadir un medicamento desactivado -> 409."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.delete(
        f"/api/v1/medications/{second['id']}", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/medications",
        json=_med_item(second["id"], [_schedule_payload()]),
        headers=_headers(token),
    )
    assert response.status_code == 409


async def test_add_medication_duplicate_409(client):
    """Anadir un medicamento que ya esta activo -> 409."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, second = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/medications",
        json=_med_item(first["id"], [_schedule_payload(("10:00",))]),
        headers=_headers(token),
    )
    assert response.status_code == 409


async def test_update_link_dose_ok(client):
    """PATCH del vinculo: cambia dosis, unidad e instrucciones."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    link_id = created["medications"][0]["id"]
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        json={
            "dose_amount": 2.5,
            "dose_unit": "comprimido",
            "instructions": "Cada 8 horas",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["dose_amount"] == 2.5
    assert data["dose_unit"] == "comprimido"
    assert data["instructions"] == "Cada 8 horas"
    assert data["is_active"] is True


async def test_delete_link_ok_and_readd_allowed(client, session):
    """DELETE del vinculo: `is_active=false`, cancela sus
    recordatorios PENDIENTE futuros, y el indice parcial permite
    volver a anadir el mismo medicamento despues."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    link_id = created["medications"][0]["id"]
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    response = await client.delete(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}",
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    now = datetime.now(timezone.utc)
    future = [
        row
        for row in await _reminders_of_schedule(session, schedule_id)
        if row.scheduled_at >= now
    ]
    assert all(row.status == "CANCELADA" for row in future)
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/medications",
        json=_med_item(first["id"], [_schedule_payload(("10:00",))]),
        headers=_headers(token),
    )
    assert response.status_code == 201, response.text


# ------------------------------------------------------------------
# 6. Cuidador: 403 en mutaciones de tratamientos/vinculos
# ------------------------------------------------------------------


async def test_caregiver_pause_treatment_403(client, session):
    """Cuidador cambia el estado de un tratamiento -> 403."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_treatments=True
    )
    first, _ = await _two_medications(client, patient["access_token"])
    created = await _create_treatment_ok(
        client,
        patient["access_token"],
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/pause"
        f"?patient_id={patient['user']['id']}",
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


async def test_caregiver_update_link_dose_403(client, session):
    """Cuidador cambia la dosis de un vinculo -> 403."""
    patient, caregiver = await _patient_and_caregiver(
        client, session, perm_view_treatments=True
    )
    first, _ = await _two_medications(client, patient["access_token"])
    created = await _create_treatment_ok(
        client,
        patient["access_token"],
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    link_id = created["medications"][0]["id"]
    response = await client.patch(
        f"/api/v1/treatments/{created['id']}/medications/{link_id}"
        f"?patient_id={patient['user']['id']}",
        json={"dose_amount": 5},
        headers=_headers(caregiver["access_token"]),
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# 7. Generacion de recordatorios: ventana de 72 horas e idempotencia
# ------------------------------------------------------------------


async def test_generation_72h_idempotent(client, session):
    """Generacion 72 horas e idempotencia: crear genera 3
    recordatorios (DIARIO 1 hora, [ahora, ahora+72h)); pausar y
    reanudar regenera sin duplicar activos y sin borrar el
    historial: quedan 3 CANCELADA intactas y 3 PENDIENTE nuevas."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    today = _today_bogota()
    before = datetime.now(timezone.utc)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    expected = _expected_occurrences(
        before, times=("08:00",), start_date=today
    )
    rows = await _reminders_of_schedule(session, schedule_id)
    assert [row.scheduled_at for row in rows] == expected
    assert all(row.status == "PENDIENTE" for row in rows)
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/pause", headers=_headers(token)
    )
    assert response.status_code == 200
    response = await client.post(
        f"/api/v1/treatments/{created['id']}/resume", headers=_headers(token)
    )
    assert response.status_code == 200
    rows = await _reminders_of_schedule(session, schedule_id)
    assert len(rows) == 6
    old = [row for row in rows if row.status == "CANCELADA"]
    new = [row for row in rows if row.status == "PENDIENTE"]
    assert len(old) == 3
    assert len(new) == 3
    assert [row.scheduled_at for row in new] == expected
    assert len({row.scheduled_at for row in new}) == 3


async def test_generation_interval_days(client, session):
    """INTERVALO_DIAS cada 2 dias: en la ventana [ahora, ahora+72h)
    caen los dias pares desde hoy cuya hora 08:00 no haya pasado
    (1 o 2 recordatorios segun la hora actual)."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    today = _today_bogota()
    before = datetime.now(timezone.utc)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload(
            [
                _med_item(
                    first["id"],
                    [
                        _schedule_payload(
                            frequency="INTERVALO_DIAS", interval_days=2
                        )
                    ],
                )
            ]
        ),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    expected = _expected_occurrences(
        before,
        times=("08:00",),
        frequency="INTERVALO_DIAS",
        interval_days=2,
        start_date=today,
    )
    rows = await _reminders_of_schedule(session, schedule_id)
    assert [row.scheduled_at for row in rows] == expected
    assert 1 <= len(rows) <= 2


async def test_generation_72h_two_times(client, session):
    """Ventana exacta: DIARIO con 2 horas genera 6 recordatorios,
    3 por hora, todos dentro de [ahora, ahora+72h) y ninguno fuera."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    today = _today_bogota()
    before = datetime.now(timezone.utc)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload(
            [_med_item(first["id"], [_schedule_payload(("08:00", "21:00"))])]
        ),
    )
    after = datetime.now(timezone.utc)
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    expected = _expected_occurrences(
        before, times=("08:00", "21:00"), start_date=today
    )
    assert len(expected) == 6
    rows = await _reminders_of_schedule(session, schedule_id)
    assert [row.scheduled_at for row in rows] == expected
    assert all(
        before <= row.scheduled_at < after + timedelta(hours=HORIZON_HOURS)
        for row in rows
    )


async def test_generation_excludes_past_times_today(client, session):
    """Una hora de hoy ya pasada no genera recordatorio: solo se
    crean los instantes en [ahora, ahora+72h)."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    today = _today_bogota()
    now_bogota = datetime.now(BOGOTA)
    past_wall = (now_bogota - timedelta(hours=1)).strftime("%H:%M")
    before = datetime.now(timezone.utc)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload(
            [_med_item(first["id"], [_schedule_payload((past_wall,))])]
        ),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    expected = _expected_occurrences(
        before, times=(past_wall,), start_date=today
    )
    rows = await _reminders_of_schedule(session, schedule_id)
    assert [row.scheduled_at for row in rows] == expected
    assert all(row.scheduled_at >= before for row in rows)
    assert len(rows) == 3


async def test_resume_twice_no_duplicate_active(client, session):
    """Dos ciclos pausa+resume: nunca hay dos activos en el mismo
    hueco; el historial acumula 3 CANCELADA por ciclo y las nuevas
    apuntan a la cancelada mas reciente."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    for _ in range(2):
        response = await client.post(
            f"/api/v1/treatments/{created['id']}/pause", headers=_headers(token)
        )
        assert response.status_code == 200
        response = await client.post(
            f"/api/v1/treatments/{created['id']}/resume", headers=_headers(token)
        )
        assert response.status_code == 200, response.text
    rows = await _reminders_of_schedule(session, schedule_id)
    assert len(rows) == 9
    active = [row for row in rows if row.status == "PENDIENTE"]
    cancelled = [row for row in rows if row.status == "CANCELADA"]
    assert len(active) == 3
    assert len(cancelled) == 6
    assert len({row.scheduled_at for row in active}) == 3
    latest_cancelled: dict = {}
    for row in cancelled:
        latest_cancelled[row.scheduled_at] = max(
            latest_cancelled.get(row.scheduled_at, 0), row.id
        )
    assert all(
        row.parent_reminder_id == latest_cancelled[row.scheduled_at]
        for row in active
    )


async def test_generate_idempotent_service(client, session):
    """Generar dos veces por el servicio no duplica: el segundo
    intento inserta 0 (ON CONFLICT DO NOTHING sobre el indice
    parcial)."""
    body = await _register_ok(client, _unique_email())
    token = body["access_token"]
    first, _ = await _two_medications(client, token)
    created = await _create_treatment_ok(
        client,
        token,
        _treatment_payload([_med_item(first["id"], [_schedule_payload()])]),
    )
    schedule_id = created["medications"][0]["schedules"][0]["id"]
    schedule = (
        await session.execute(
            select(MedicationSchedule).where(
                MedicationSchedule.id == schedule_id
            )
        )
    ).scalar_one()
    treatment = (
        await session.execute(
            select(Treatment).where(Treatment.id == created["id"])
        )
    ).scalar_one()
    user = (
        await session.execute(
            select(User).where(User.id == body["user"]["id"])
        )
    ).scalar_one()
    inserted = await generate_reminders_for_schedule(
        session, schedule, treatment, user
    )
    assert inserted == 0
    rows = await _reminders_of_schedule(session, schedule_id)
    assert len(rows) == 3
    assert all(row.status == "PENDIENTE" for row in rows)
