"""Pruebas formales de RF13 (historial) y RF14 (estadísticas) — Fase 7.

Matriz H/S del plan técnico (PLAN_TECNICO_FASE_7.md, §8): 34 pruebas
de historial (H-01–H-34) y 88 de estadísticas (S-01–S-88). Este
archivo contiene 116 pruebas (115 HTTP/API + 1 de unidad, S-81); las
6 de migración (S-29, S-30, S-78, S-79, S-80 y S-88) viven en
`test_stats_migrations.py` porque requieren controlar la versión del
esquema.

Casos cubiertos por la auditoría independiente de Roderic
(`test_fase7_audit_roderic.py`, rama `feature/roderic-auditoria-fase7`)
y NO duplicados aquí: H-05, H-06, H-07, H-13, H-16, H-19, S-01, S-16,
S-18, S-24, S-43, S-44, S-71 y S-87 (ver la matriz de cobertura en el
informe del commit 5). La siembra es directa (recordatorios + tomas),
salvo donde se indica el flujo real por HTTP.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.database import get_session
from app.main import create_app
from app.models.caregivers import CaregiverAuditLog, CaregiverLink
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.models.schedules import MedicationSchedule
from app.repositories import reminder_repository

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
PASSWORD = "Prueba1234"
BOGOTA = "America/Bogota"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _test_url() -> str:
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
    return create_async_engine(_test_url(), poolclass=NullPool)


@pytest_asyncio.fixture
async def session(test_engine):
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
# Ayudantes
# ------------------------------------------------------------------


def _unique_email(prefix: str = "audit") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _register_ok(client, email) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Prueba Fase 7",
            "email": email,
            "password": PASSWORD,
            "timezone": BOGOTA,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_chain(session, user_id: int) -> dict:
    """Medicamento + tratamiento ACTIVO + vinculo + horario DIARIO 08:00."""
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
        "medication_id": med.id,
    }


async def _seed_reminder(
    session,
    chain: dict,
    when: datetime,
    status: str,
    cancel_reason: str | None = None,
) -> int:
    row = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=chain["user_id"],
        scheduled_at=when,
        status=status,
        cancel_reason=cancel_reason,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return row.id


async def _seed_taken(
    session, chain: dict, when: datetime, taken_at: datetime, source: str = "WEB"
) -> int:
    rid = await _seed_reminder(session, chain, when, "TOMADA")
    session.add(
        MedicationIntake(
            reminder_id=rid,
            user_id=chain["user_id"],
            taken_at=taken_at,
            source=source,
        )
    )
    await session.commit()
    return rid


async def _seed_unknown_cancelled(session, chain: dict, when: datetime) -> int:
    """Una CANCELADA historica con motivo NULL (categoria `unknown`).

    Operacion controlada (S-71): el trigger de D-11 impide crear
    cancelaciones nuevas sin motivo, asi que se desactiva solo para
    sembrar la fila historica y se reactiva de inmediato en un
    try/finally. Es el procedimiento documentado por Diomar para
    S-71 (commit 5).
    """
    await session.execute(
        text(
            "ALTER TABLE medication_reminders "
            "DISABLE TRIGGER trg_reminders_cancel_reason"
        )
    )
    try:
        row = MedicationReminder(
            schedule_id=chain["schedule_id"],
            treatment_medication_id=chain["link_id"],
            user_id=chain["user_id"],
            scheduled_at=when,
            status="CANCELADA",
            cancel_reason=None,
        )
        session.add(row)
        await session.flush()
    finally:
        await session.execute(
            text(
                "ALTER TABLE medication_reminders "
                "ENABLE TRIGGER trg_reminders_cancel_reason"
            )
        )
    await session.commit()
    return row.id


async def _audit_ok_count(session, *, caregiver_id: int, patient_id: int) -> int:
    stmt = select(CaregiverAuditLog).where(
        CaregiverAuditLog.caregiver_user_id == caregiver_id,
        CaregiverAuditLog.patient_user_id == patient_id,
        CaregiverAuditLog.action == "VIEW_HISTORY",
        CaregiverAuditLog.result == "OK",
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


def _history_window(now: datetime) -> tuple[datetime, datetime]:
    """Ventana amplia (datetimes UTC) que cubre siembras y regenerados."""
    return now - timedelta(days=1), now + timedelta(days=4)


def _compliance_window(today: date) -> tuple[date, date]:
    """Ventana amplia (fechas locales Bogota) que cubre lo mismo."""
    return today - timedelta(days=2), today + timedelta(days=4)


async def _history(client, headers, from_dt, to_dt, **params):
    q = {"from": from_dt.isoformat(), "to": to_dt.isoformat(), **params}
    r = await client.get("/api/v1/reminders/history", headers=headers, params=q)
    assert r.status_code == 200, r.text
    return r.json()


async def _compliance(client, headers, from_d=None, to_d=None, **params):
    q = {**params}
    if from_d is not None:
        q["from"] = from_d.isoformat()
    if to_d is not None:
        q["to"] = to_d.isoformat()
    r = await client.get("/api/v1/stats/compliance", headers=headers, params=q)
    assert r.status_code == 200, r.text
    return r.json()


# --- Acciones reales por la API (el objeto auditado) ----------------


async def _pause(client, headers, treatment_id: int):
    r = await client.post(
        f"/api/v1/treatments/{treatment_id}/pause", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _resume(client, headers, treatment_id: int):
    r = await client.post(
        f"/api/v1/treatments/{treatment_id}/resume", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _cancel(client, headers, treatment_id: int):
    r = await client.post(
        f"/api/v1/treatments/{treatment_id}/cancel", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _complete(client, headers, treatment_id: int):
    r = await client.post(
        f"/api/v1/treatments/{treatment_id}/complete", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _deactivate_medication(client, headers, medication_id: int):
    r = await client.delete(
        f"/api/v1/medications/{medication_id}", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _remove_link(client, headers, treatment_id: int, link_id: int):
    r = await client.delete(
        f"/api/v1/treatments/{treatment_id}/medications/{link_id}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _confirm(client, headers, reminder_id: int):
    r = await client.post(
        f"/api/v1/reminders/{reminder_id}/confirm", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------
# Ayudantes nuevos del plan (§8)
# ------------------------------------------------------------------

_BOGOTA_TZ = ZoneInfo(BOGOTA)


def _local(day: date, hour: int = 8, minute: int = 0) -> datetime:
    """Un instante UTC que es `hour:minute` en Bogotá el día `day`."""
    return datetime.combine(day, time(hour, minute), tzinfo=_BOGOTA_TZ).astimezone(
        timezone.utc
    )


def _future_within_today() -> datetime:
    """Un instante futuro dentro de hoy (Bogota), sin cruzar a mañana.

    La mitad del tiempo que queda hasta la medianoche: siempre es
    futuro y siempre cae dentro del periodo por defecto de 30 dias
    (que termina mañana a las 00:00 Bogota), a cualquier hora del
    dia. Lo usan S-25 y S-26 para que el PENDIENTE futuro no quede
    fuera del periodo cuando la prueba corre despues de las 22:00
    (entonces `ahora + 2 h` cae pasada la medianoche).
    """
    now = _utcnow()
    tomorrow = datetime.now(_BOGOTA_TZ).date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, time(0, 0), tzinfo=_BOGOTA_TZ).astimezone(
        timezone.utc
    )
    return now + (midnight - now) / 2


async def _seed_intake(
    session, reminder_id: int, user_id: int, taken_at: datetime, source: str = "WEB"
) -> int:
    """Crea la toma de un recordatorio TOMADA (plan §8)."""
    session.add(
        MedicationIntake(
            reminder_id=reminder_id,
            user_id=user_id,
            taken_at=taken_at,
            source=source,
        )
    )
    await session.commit()
    return reminder_id


async def _seed_caregiver_link(
    session,
    patient_id: int,
    caregiver_id: int,
    perm_view_history: bool = True,
    when: datetime | None = None,
) -> None:
    """Vínculo ACTIVO con los permisos indicados (plan §8)."""
    session.add(
        CaregiverLink(
            patient_user_id=patient_id,
            caregiver_user_id=caregiver_id,
            status="ACTIVO",
            invited_by=patient_id,
            accepted_at=when or _utcnow(),
            perm_view_history=perm_view_history,
        )
    )
    await session.commit()


async def _seed_chain_named(session, user_id: int, name: str) -> dict:
    """Como `_seed_chain` pero con el nombre de medicamento dado."""
    med = Medication(user_id=user_id, name=name)
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
        "medication_id": med.id,
    }


async def _setup(client, session):
    """Un usuario nuevo con su cadena de prueba."""
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    return uid, h, chain


def _groups_by_start(comp) -> dict:
    """Mapa period_start -> bucket (día/semana/mes)."""
    return {g["period_start"]: g for g in comp["groups"]}


async def _audit_rows(session, *, caregiver_id: int, patient_id: int, action: str, result: str) -> int:
    """Filas de auditoría de cuidador con esa acción y resultado."""
    stmt = select(CaregiverAuditLog).where(
        CaregiverAuditLog.caregiver_user_id == caregiver_id,
        CaregiverAuditLog.patient_user_id == patient_id,
        CaregiverAuditLog.action == action,
        CaregiverAuditLog.result == result,
    )
    res = await session.execute(stmt)
    return len(res.scalars().all())


# ==================================================================
# RF13 — Historial (H-01–H-34)
# ==================================================================

@pytest.mark.asyncio
async def test_h01_history_all_states(client, session) -> None:
    """H-01: historial básico con todos los estados."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    await _seed_taken(session, chain, _local(day, 8), _local(day, 8, 5))
    await _seed_reminder(session, chain, _local(day, 9), "PERDIDA")
    orig = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(day, 10),
        status="POSPUESTA",
        postponed_count=1,
    )
    session.add(orig)
    await session.flush()
    await _seed_reminder(
        session, chain, _local(day, 11), "CANCELADA", "TREATMENT_CANCELLED"
    )
    await _seed_reminder(session, chain, _local(day, 12), "PENDIENTE")
    await _seed_reminder(session, chain, _local(day, 13), "ENVIADA")
    child = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(day, 14),
        status="PENDIENTE",
        parent_reminder_id=orig.id,
    )
    session.add(child)
    await session.commit()
    page = await _history(
        client, h, _local(day, 0, 0), _local(day + timedelta(days=1), 0, 0)
    )
    assert page["total"] == 7
    assert len(page["items"]) == 7
    items = page["items"]
    # Orden scheduled_at DESC.
    scheduled = [item["scheduled_at"] for item in items]
    assert scheduled == sorted(scheduled, reverse=True)
    assert {item["status"] for item in items} == {
        "TOMADA",
        "PERDIDA",
        "POSPUESTA",
        "CANCELADA",
        "PENDIENTE",
        "ENVIADA",
    }
    tomada = [i for i in items if i["status"] == "TOMADA"][0]
    assert tomada["taken_at"] is not None
    assert tomada["source"] == "WEB"
    assert all(i["taken_at"] is None for i in items if i["status"] != "TOMADA")
    child_item = [i for i in items if i.get("parent_reminder_id") == orig.id]
    assert len(child_item) == 1
    assert child_item[0]["status"] == "PENDIENTE"
    # Los 7 con sus campos.
    for item in items:
        assert item["medication_id"] == chain["medication_id"]
        assert item["medication_name"] == "Paracetamol"
        assert item["treatment_id"] == chain["treatment_id"]
        assert item["dose_amount"] == "500.000"
        assert item["dose_unit"] == "mg"


@pytest.mark.asyncio
async def test_h02_filter_by_date_range(client, session) -> None:
    """H-02: filtro por fecha from/to."""
    uid, h, chain = await _setup(client, session)
    await _seed_reminder(session, chain, _local(date(2026, 11, 10), 8), "PENDIENTE")
    await _seed_reminder(session, chain, _local(date(2026, 11, 15), 8), "PENDIENTE")
    await _seed_reminder(session, chain, _local(date(2026, 11, 20), 8), "PENDIENTE")
    page = await _history(
        client,
        h,
        datetime(2026, 11, 12, tzinfo=timezone.utc),
        datetime(2026, 11, 18, tzinfo=timezone.utc),
    )
    assert page["total"] == 1
    assert len(page["items"]) == 1
    item = page["items"][0]
    sched = datetime.fromisoformat(item["scheduled_at"].replace("Z", "+00:00"))
    assert sched.astimezone(_BOGOTA_TZ).date() == date(2026, 11, 15)


@pytest.mark.asyncio
async def test_h03_filter_by_medication(client, session) -> None:
    """H-03: filtro por medicamento."""
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    day = date(2026, 11, 10)
    for hour in (8, 9):
        await _seed_reminder(session, chain_a, _local(day, hour), "PENDIENTE")
    for hour in (10, 11):
        await _seed_reminder(session, chain_b, _local(day, hour), "PENDIENTE")
    page = await _history(
        client,
        h,
        _local(day, 0, 0),
        _local(day + timedelta(days=1), 0, 0),
        medication_id=chain_a["medication_id"],
    )
    assert page["total"] == 2
    assert len(page["items"]) == 2
    assert all(
        item["medication_id"] == chain_a["medication_id"] for item in page["items"]
    )
    assert all(item["medication_name"] == "Paracetamol" for item in page["items"])


@pytest.mark.asyncio
async def test_h04_filter_by_treatment(client, session) -> None:
    """H-04: filtro por tratamiento."""
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    day = date(2026, 11, 10)
    for hour in (8, 9):
        await _seed_reminder(session, chain_a, _local(day, hour), "PENDIENTE")
    for hour in (10, 11):
        await _seed_reminder(session, chain_b, _local(day, hour), "PENDIENTE")
    page = await _history(
        client,
        h,
        _local(day, 0, 0),
        _local(day + timedelta(days=1), 0, 0),
        treatment_id=chain_a["treatment_id"],
    )
    assert page["total"] == 2
    assert len(page["items"]) == 2
    assert all(
        item["treatment_id"] == chain_a["treatment_id"] for item in page["items"]
    )


@pytest.mark.asyncio
async def test_h08_pagination_limit_offset_total(client, session) -> None:
    """H-08: paginación (limit/offset/total)."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    ids = []
    for hour in (8, 9, 10, 11, 12):
        ids.append(await _seed_reminder(session, chain, _local(day, hour), "PENDIENTE"))
    desc_ids = list(reversed(ids))
    start = _local(day, 0, 0)
    end = _local(day + timedelta(days=1), 0, 0)
    p0 = await _history(client, h, start, end, limit=2, offset=0)
    p2 = await _history(client, h, start, end, limit=2, offset=2)
    p4 = await _history(client, h, start, end, limit=2, offset=4)
    assert p0["total"] == 5 and p2["total"] == 5 and p4["total"] == 5
    assert len(p0["items"]) == 2
    assert len(p2["items"]) == 2
    assert len(p4["items"]) == 1
    # Sin repetidos ni faltantes entre páginas; orden estable.
    all_ids = [r["id"] for r in p0["items"] + p2["items"] + p4["items"]]
    assert all_ids == desc_ids
    assert sorted(all_ids) == sorted(ids)


@pytest.mark.asyncio
async def test_h09_invalid_limits(client, session) -> None:
    """H-09: límites inválidos."""
    uid, h, chain = await _setup(client, session)
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        r = await client.get("/api/v1/reminders/history", headers=h, params=params)
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_h10_no_authentication(client, session) -> None:
    """H-10: sin autenticación."""
    uid, h, chain = await _setup(client, session)
    await _seed_reminder(session, chain, _local(date(2026, 11, 10), 8), "PENDIENTE")
    r = await client.get("/api/v1/reminders/history")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_h11_isolation_between_users(client, session) -> None:
    """H-11: aislamiento entre usuarios."""
    uid_a, h_a, chain_a = await _setup(client, session)
    user_b = await _register_ok(client, _unique_email("b"))
    uid_b, token_b = user_b["user"]["id"], user_b["access_token"]
    h_b = _headers(token_b)
    chain_b = await _seed_chain(session, uid_b)
    day = date(2026, 11, 10)
    ids_a = []
    for hour in (8, 9, 10):
        ids_a.append(await _seed_reminder(session, chain_a, _local(day, hour), "PENDIENTE"))
    ids_b = []
    for hour in (8, 9):
        ids_b.append(await _seed_reminder(session, chain_b, _local(day, hour), "PENDIENTE"))
    page = await _history(
        client, h_b, _local(day, 0, 0), _local(day + timedelta(days=1), 0, 0)
    )
    assert page["total"] == 2
    assert sorted(r["id"] for r in page["items"]) == sorted(ids_b)
    assert not set(ids_a) & {r["id"] for r in page["items"]}


@pytest.mark.asyncio
async def test_h12_other_user_by_patient_id_no_link(client, session) -> None:
    """H-12: otro usuario por patient_id sin vínculo."""
    uid_a, h_a, chain_a = await _setup(client, session)
    day = date(2026, 11, 10)
    await _seed_reminder(session, chain_a, _local(day, 8), "PENDIENTE")
    user_b = await _register_ok(client, _unique_email("b"))
    uid_b, token_b = user_b["user"]["id"], user_b["access_token"]
    h_b = _headers(token_b)
    r = await client.get(
        "/api/v1/reminders/history", headers=h_b, params={"patient_id": uid_a}
    )
    assert r.status_code == 403, r.text
    assert (
        await _audit_rows(
            session,
            caregiver_id=uid_b,
            patient_id=uid_a,
            action="ACCESS_DENIED",
            result="DENEGADO",
        )
        == 1
    )


@pytest.mark.asyncio
async def test_h14_caregiver_without_perm_view_history(client, session) -> None:
    """H-14: cuidador sin perm_view_history."""
    uid_a, h_a, chain_a = await _setup(client, session)
    day = date(2026, 11, 10)
    await _seed_reminder(session, chain_a, _local(day, 8), "PENDIENTE")
    user_b = await _register_ok(client, _unique_email("b"))
    uid_b, token_b = user_b["user"]["id"], user_b["access_token"]
    h_b = _headers(token_b)
    await _seed_caregiver_link(
        session, patient_id=uid_a, caregiver_id=uid_b, perm_view_history=False
    )
    r = await client.get(
        "/api/v1/reminders/history", headers=h_b, params={"patient_id": uid_a}
    )
    assert r.status_code == 403, r.text
    assert (
        await _audit_rows(
            session,
            caregiver_id=uid_b,
            patient_id=uid_a,
            action="ACCESS_DENIED",
            result="DENEGADO",
        )
        == 1
    )


@pytest.mark.asyncio
async def test_h15_history_survives_treatment_cancel(client, session) -> None:
    """H-15: el historial sobrevive a cancelar el tratamiento."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_taken(
        session, chain, now - timedelta(hours=2), now - timedelta(hours=2) + timedelta(minutes=5)
    )
    await _seed_reminder(session, chain, now + timedelta(hours=1), "PENDIENTE")
    await _seed_reminder(session, chain, now + timedelta(hours=2), "PENDIENTE")
    body = await _cancel(client, h, chain["treatment_id"])
    assert body["status"] == "CANCELADO"
    page = await _history(client, h, now - timedelta(days=1), now + timedelta(days=1))
    assert page["total"] == 3
    assert len(page["items"]) == 3
    by_status = {}
    for item in page["items"]:
        by_status.setdefault(item["status"], []).append(item)
    assert len(by_status.get("TOMADA", [])) == 1
    assert by_status["TOMADA"][0]["taken_at"] is not None
    assert len(by_status.get("CANCELADA", [])) == 2
    assert all(
        item["cancel_reason"] == "TREATMENT_CANCELLED"
        for item in by_status["CANCELADA"]
    )


@pytest.mark.asyncio
async def test_h17_postponed_and_child_related(client, session) -> None:
    """H-17: la pospuesta y su hijo aparecen relacionados."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    orig = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(day, 8),
        status="POSPUESTA",
        postponed_count=1,
    )
    session.add(orig)
    await session.flush()
    child = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(day, 9),
        status="PENDIENTE",
        parent_reminder_id=orig.id,
    )
    session.add(child)
    await session.commit()
    page = await _history(
        client, h, _local(day, 0, 0), _local(day + timedelta(days=1), 0, 0)
    )
    assert page["total"] == 2
    assert len(page["items"]) == 2
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[orig.id]["status"] == "POSPUESTA"
    assert by_id[orig.id]["postponed_count"] >= 1
    assert by_id[child.id]["status"] == "PENDIENTE"
    assert by_id[child.id]["parent_reminder_id"] == orig.id


@pytest.mark.asyncio
async def test_h18_other_user_medication_as_filter(client, session) -> None:
    """H-18: medicamento de otro usuario como filtro."""
    uid_a, h_a, chain_a = await _setup(client, session)
    day = date(2026, 11, 10)
    await _seed_reminder(session, chain_a, _local(day, 8), "PENDIENTE")
    user_b = await _register_ok(client, _unique_email("b"))
    uid_b, token_b = user_b["user"]["id"], user_b["access_token"]
    h_b = _headers(token_b)
    page = await _history(
        client,
        h_b,
        _local(day, 0, 0),
        _local(day + timedelta(days=1), 0, 0),
        medication_id=chain_a["medication_id"],
    )
    assert page["total"] == 0
    assert page["items"] == []


@pytest.mark.asyncio
async def test_h20_default_pagination_values(client, session) -> None:
    """H-20: valores predeterminados de paginación."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    for hour in (8, 9, 10):
        await _seed_reminder(session, chain, _local(day, hour), "PENDIENTE")
    page = await _history(
        client, h, _local(day, 0, 0), _local(day + timedelta(days=1), 0, 0)
    )
    assert page["total"] == 3
    assert len(page["items"]) == 3
    assert page["limit"] == 50
    assert page["offset"] == 0


@pytest.mark.asyncio
async def test_h21_tiebreak_by_id_same_scheduled_at(client, session) -> None:
    """H-21: desempate por id con mismo scheduled_at."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    when = _local(day, 8)
    ids = []
    for name in ("MedA", "MedB", "MedC", "MedD", "MedE"):
        named = await _seed_chain_named(session, uid, name)
        ids.append(await _seed_reminder(session, named, when, "PENDIENTE"))
    start = _local(day, 0, 0)
    end = _local(day + timedelta(days=1), 0, 0)
    p0 = await _history(client, h, start, end, limit=2, offset=0)
    p2 = await _history(client, h, start, end, limit=2, offset=2)
    p4 = await _history(client, h, start, end, limit=2, offset=4)
    assert p0["total"] == 5 and p2["total"] == 5 and p4["total"] == 5
    assert len(p0["items"]) == 2
    assert len(p2["items"]) == 2
    assert len(p4["items"]) == 1
    # Sin repetidos ni faltantes entre páginas.
    all_ids = [r["id"] for r in p0["items"] + p2["items"] + p4["items"]]
    assert sorted(all_ids) == sorted(ids)
    # Dos peticiones idénticas devuelven el mismo orden.
    p0b = await _history(client, h, start, end, limit=2, offset=0)
    assert [r["id"] for r in p0b["items"]] == [r["id"] for r in p0["items"]]


@pytest.mark.asyncio
async def test_h22_pagination_with_filters(client, session) -> None:
    """H-22: paginación combinada con filtros."""
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    day = date(2026, 11, 10)
    for hour in (8, 9, 10, 11, 12):
        await _seed_reminder(session, chain_a, _local(day, hour), "PENDIENTE")
    for hour in (8, 9, 10):
        await _seed_reminder(session, chain_b, _local(day, hour), "PENDIENTE")
    start = _local(day, 0, 0)
    end = _local(day + timedelta(days=1), 0, 0)
    p0 = await _history(
        client, h, start, end, medication_id=chain_a["medication_id"], limit=2, offset=0
    )
    p2 = await _history(
        client, h, start, end, medication_id=chain_a["medication_id"], limit=2, offset=2
    )
    p4 = await _history(
        client, h, start, end, medication_id=chain_a["medication_id"], limit=2, offset=4
    )
    assert p0["total"] == 5 and p2["total"] == 5 and p4["total"] == 5
    all_items = p0["items"] + p2["items"] + p4["items"]
    assert len(all_items) == 5
    # Las páginas solo traen A.
    assert all(
        item["medication_id"] == chain_a["medication_id"] for item in all_items
    )
    assert all(item["medication_name"] == "Paracetamol" for item in all_items)


@pytest.mark.asyncio
async def test_h23_limit_200_accepted(client, session) -> None:
    """H-23: límite 200 aceptado."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    await _seed_reminder(session, chain, _local(day, 8), "PENDIENTE")
    page = await _history(
        client, h, _local(day, 0, 0), _local(day + timedelta(days=1), 0, 0), limit=200
    )
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["limit"] == 200


@pytest.mark.asyncio
async def test_h24_offset_not_multiple_of_limit(client, session) -> None:
    """H-24: offset no múltiplo del límite."""
    uid, h, chain = await _setup(client, session)
    day = date(2026, 11, 10)
    ids = []
    for hour in (8, 9, 10, 11, 12):
        ids.append(await _seed_reminder(session, chain, _local(day, hour), "PENDIENTE"))
    desc_ids = list(reversed(ids))
    page = await _history(
        client,
        h,
        _local(day, 0, 0),
        _local(day + timedelta(days=1), 0, 0),
        limit=2,
        offset=3,
    )
    assert page["total"] == 5
    assert len(page["items"]) == 2
    # Posiciones 4 y 5 (en orden scheduled_at DESC): las 09:00 y 08:00.
    assert [r["id"] for r in page["items"]] == desc_ids[3:5]


@pytest.mark.asyncio
async def test_h25_empty_history(client, session) -> None:
    """H-25: historial vacío."""
    uid, h, chain = await _setup(client, session)
    r = await client.get("/api/v1/reminders/history", headers=h)
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["items"] == []
    assert page["total"] == 0
    assert page["limit"] == 50
    assert page["offset"] == 0


@pytest.mark.asyncio
async def test_h26_future_pending_appears(client, session) -> None:
    """H-26: PENDIENTE futuro aparece (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now + timedelta(days=1), "PENDIENTE")
    page = await _history(client, h, now, now + timedelta(days=2))
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["status"] == "PENDIENTE"
    assert page["items"][0]["taken_at"] is None


@pytest.mark.asyncio
async def test_h27_pending_in_grace_not_lost(client, session) -> None:
    """H-27: PENDIENTE en gracia no es PERDIDA (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(minutes=20), "PENDIENTE")
    page = await _history(client, h, now - timedelta(days=1), now + timedelta(days=1))
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["status"] == "PENDIENTE"


@pytest.mark.asyncio
async def test_h28_pending_past_grace_still_pending(client, session) -> None:
    """H-28: PENDIENTE pasada la gracia sin reconciliar sigue PENDIENTE (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(minutes=45), "PENDIENTE")
    page = await _history(client, h, now - timedelta(days=1), now + timedelta(days=1))
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["status"] == "PENDIENTE"


@pytest.mark.asyncio
async def test_h29_enviando_and_enviada_appear(client, session) -> None:
    """H-29: ENVIANDO y ENVIADA aparecen (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(hours=1), "ENVIANDO")
    await _seed_reminder(session, chain, now - timedelta(hours=2), "ENVIADA")
    page = await _history(client, h, now - timedelta(days=1), now + timedelta(days=1))
    assert page["total"] == 2
    assert len(page["items"]) == 2
    assert {item["status"] for item in page["items"]} == {"ENVIANDO", "ENVIADA"}


@pytest.mark.asyncio
async def test_h30_fallida_appears_without_intake(client, session) -> None:
    """H-30: FALLIDA aparece sin toma (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(hours=1), "FALLIDA")
    page = await _history(client, h, now - timedelta(days=1), now + timedelta(days=1))
    assert page["total"] == 1
    assert len(page["items"]) == 1
    item = page["items"][0]
    assert item["status"] == "FALLIDA"
    assert item["taken_at"] is None
    assert item["source"] is None


@pytest.mark.asyncio
async def test_h31_future_beyond_horizon_not_present(client, session) -> None:
    """H-31: futuro fuera del horizonte no existe (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now + timedelta(hours=24), "PENDIENTE")
    await _seed_reminder(session, chain, now + timedelta(hours=70), "PENDIENTE")
    page = await _history(client, h, now, now + timedelta(days=30))
    assert page["total"] == 2
    assert len(page["items"]) == 2
    assert all(item["status"] == "PENDIENTE" for item in page["items"])


@pytest.mark.asyncio
async def test_h32_status_filter_separates_resolved(client, session) -> None:
    """H-32: el filtro por estado separa resueltos de pendientes (D-10)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_taken(
        session, chain, now - timedelta(hours=3), now - timedelta(hours=3) + timedelta(minutes=5)
    )
    await _seed_reminder(session, chain, now - timedelta(hours=2), "PERDIDA")
    await _seed_reminder(session, chain, now + timedelta(hours=1), "PENDIENTE")
    await _seed_reminder(
        session, chain, now + timedelta(hours=2), "CANCELADA", "TREATMENT_CANCELLED"
    )
    start = now - timedelta(days=1)
    end = now + timedelta(days=1)
    page_p = await _history(client, h, start, end, status="PENDIENTE")
    assert page_p["total"] == 1
    assert all(item["status"] == "PENDIENTE" for item in page_p["items"])
    page_t = await _history(client, h, start, end, status="TOMADA")
    assert page_t["total"] == 1
    assert all(item["status"] == "TOMADA" for item in page_t["items"])


@pytest.mark.asyncio
async def test_h33_range_uses_scheduled_at_not_taken_at(client, session) -> None:
    """H-33: el rango usa scheduled_at, no taken_at (D-10)."""
    uid, h, chain = await _setup(client, session)
    day_x = date(2026, 11, 10)
    day_x1 = date(2026, 11, 11)
    sched = _local(day_x, 8)
    taken = sched + timedelta(hours=25)
    await _seed_taken(session, chain, sched, taken)
    page_x = await _history(
        client, h, _local(day_x, 0, 0), _local(day_x1, 0, 0)
    )
    assert page_x["total"] == 1
    assert len(page_x["items"]) == 1
    assert page_x["items"][0]["status"] == "TOMADA"
    page_x1 = await _history(
        client, h, _local(day_x1, 0, 0), _local(date(2026, 11, 12), 0, 0)
    )
    assert page_x1["total"] == 0
    assert page_x1["items"] == []


@pytest.mark.asyncio
async def test_h34_child_appears_in_own_range(client, session) -> None:
    """H-34: el hijo aparece en su propio rango (D-10)."""
    uid, h, chain = await _setup(client, session)
    day_x = date(2026, 11, 10)
    day_y = date(2026, 11, 11)
    orig = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(day_x, 8),
        status="POSPUESTA",
        postponed_count=1,
    )
    session.add(orig)
    await session.flush()
    child = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(day_y, 8),
        status="PENDIENTE",
        parent_reminder_id=orig.id,
    )
    session.add(child)
    await session.commit()
    page = await _history(
        client, h, _local(day_y, 0, 0), _local(date(2026, 11, 12), 0, 0)
    )
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["status"] == "PENDIENTE"
    assert page["items"][0]["parent_reminder_id"] == orig.id


# ==================================================================
# RF14 — Estadísticas, primera parte (S-02–S-48)
# ==================================================================

@pytest.mark.asyncio
async def test_s02_on_time_exact_30_minutes(client, session) -> None:
    """S-02: a tiempo en el borde (30:00 exactos)."""
    uid, h, chain = await _setup(client, session)
    when = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when, when + timedelta(minutes=30))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s03_late_just_after_30_minutes(client, session) -> None:
    """S-03: tardía justo después (30:01)."""
    uid, h, chain = await _setup(client, session)
    when = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when, when + timedelta(minutes=30, seconds=1))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 1
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s04_late_counts_in_denominator(client, session) -> None:
    """S-04: tardía cuenta en denominador (1 a tiempo + 1 tardía 60 min)."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_taken(session, chain, when2, when2 + timedelta(minutes=60))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 1
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 50.0


@pytest.mark.asyncio
async def test_s05_lost_is_not_compliance(client, session) -> None:
    """S-05: perdida no es cumplimiento (1 a tiempo + 1 perdida)."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "PERDIDA")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 1
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 50.0


@pytest.mark.asyncio
async def test_s06_cancelled_excluded_from_denominator(client, session) -> None:
    """S-06: cancelada excluida del denominador (D-1, opción 2)."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "CANCELADA", "TREATMENT_CANCELLED")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 1,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    # Denominador 1: la cancelada no baja el porcentaje.
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s07_postponed_original_does_not_count(client, session) -> None:
    """S-07: original POSPUESTA no cuenta; el hijo sí."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() - timedelta(hours=2)
    await _seed_reminder(session, chain, when1, "POSPUESTA")
    await _seed_taken(session, chain, when2, when2 + timedelta(minutes=10))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s08_postponed_child_still_pending_does_not_count(client, session) -> None:
    """S-08: hijo POSPUESTA aún pendiente no cuenta."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() + timedelta(hours=2)
    await _seed_reminder(session, chain, when1, "POSPUESTA")
    await _seed_reminder(session, chain, when2, "PENDIENTE")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 0
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] is None


@pytest.mark.asyncio
async def test_s09_unconfirmed_failed_does_not_count(client, session) -> None:
    """S-09: FALLIDA sin confirmar no cuenta."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "FALLIDA")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s10_future_pending_does_not_count(client, session) -> None:
    """S-10: PENDIENTE futuro no cuenta."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() + timedelta(hours=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "PENDIENTE")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s11_period_without_data(client, session) -> None:
    """S-11: periodo sin datos."""
    uid, h, chain = await _setup(client, session)
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 0
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] is None


@pytest.mark.asyncio
async def test_s12_group_by_medication(client, session) -> None:
    """S-12: agrupar por medicamento (A: 4, 3 a tiempo + 1 perdida;
    B: 2, 1 a tiempo + 1 cancelada por cancelación del tratamiento)."""
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    d = date(2026, 11, 10)
    await _seed_taken(session, chain_a, _local(d, 8, 0), _local(d, 8, 5))
    await _seed_taken(session, chain_a, _local(d, 8, 30), _local(d, 8, 35))
    await _seed_taken(session, chain_a, _local(d, 9, 0), _local(d, 9, 5))
    await _seed_reminder(session, chain_a, _local(d, 10, 0), "PERDIDA")
    await _seed_taken(session, chain_b, _local(d, 11, 0), _local(d, 11, 5))
    await _seed_reminder(
        session, chain_b, _local(d, 12, 0), "CANCELADA", "TREATMENT_CANCELLED"
    )
    comp = await _compliance(
        client, h, d, d + timedelta(days=1), group_by="medication"
    )
    assert len(comp["groups"]) == 2
    # Ordenados por medication_name ascendente.
    assert [g["medication_name"] for g in comp["groups"]] == [
        "Amoxicilina",
        "Paracetamol",
    ]
    by_name = {g["medication_name"]: g for g in comp["groups"]}
    a = by_name["Paracetamol"]
    b = by_name["Amoxicilina"]
    assert a["scheduled"] == 4
    assert a["taken_on_time"] == 3
    assert a["taken_late"] == 0
    assert a["lost"] == 1
    assert a["cancelled"] == 0
    assert a["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert a["compliance_percentage"] == 75.0
    assert b["scheduled"] == 2
    assert b["taken_on_time"] == 1
    assert b["taken_late"] == 0
    assert b["lost"] == 0
    assert b["cancelled"] == 1
    assert b["cancelled_by_reason"] == {
        "treatment_cancelled": 1,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert b["compliance_percentage"] == 100.0
    # La suma de grupos es el resumen.
    s = comp["summary"]
    assert s["scheduled"] == 6
    assert s["taken_on_time"] == 4
    assert s["taken_late"] == 0
    assert s["lost"] == 1
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 1,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 80.0


@pytest.mark.asyncio
async def test_s13_group_by_day(client, session) -> None:
    """S-13: agrupar por día (dosis en 2 días distintos)."""
    uid, h, chain = await _setup(client, session)
    d1, d2 = date(2026, 11, 10), date(2026, 11, 11)
    await _seed_taken(session, chain, _local(d1, 8, 0), _local(d1, 8, 5))
    await _seed_taken(session, chain, _local(d1, 9, 0), _local(d1, 9, 5))
    await _seed_taken(session, chain, _local(d2, 8, 0), _local(d2, 8, 5))
    await _seed_reminder(session, chain, _local(d2, 9, 0), "PERDIDA")
    comp = await _compliance(client, h, d1, d2 + timedelta(days=1), group_by="day")
    assert len(comp["groups"]) == 2
    by_start = _groups_by_start(comp)
    g1, g2 = by_start["2026-11-10"], by_start["2026-11-11"]
    assert g1["period_label"] == "2026-11-10"
    assert g1["scheduled"] == 2
    assert g1["taken_on_time"] == 2
    assert g1["compliance_percentage"] == 100.0
    assert g2["period_label"] == "2026-11-11"
    assert g2["scheduled"] == 2
    assert g2["taken_on_time"] == 1
    assert g2["lost"] == 1
    assert g2["compliance_percentage"] == 50.0
    # La suma de grupos es el resumen.
    s = comp["summary"]
    assert s["scheduled"] == 4
    assert s["taken_on_time"] == 3
    assert s["lost"] == 1
    assert s["compliance_percentage"] == 75.0


@pytest.mark.asyncio
async def test_s14_group_by_day_crosses_midnight_utc(client, session) -> None:
    """S-14: agrupar por día cruza la medianoche UTC (23:30 Bogotá)."""
    uid, h, chain = await _setup(client, session)
    d1, d2 = date(2026, 11, 10), date(2026, 11, 11)
    await _seed_taken(session, chain, _local(d1, 23, 30), _local(d1, 23, 35))
    comp = await _compliance(client, h, d1, d2 + timedelta(days=1), group_by="day")
    by_start = _groups_by_start(comp)
    # La dosis cae en el día local (Bogotá), no en el día UTC.
    assert by_start["2026-11-10"]["scheduled"] == 1
    assert by_start["2026-11-10"]["taken_on_time"] == 1
    assert by_start["2026-11-11"]["scheduled"] == 0
    assert comp["summary"]["scheduled"] == 1
    assert comp["summary"]["taken_on_time"] == 1
    assert comp["summary"]["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s15_filter_by_medication(client, session) -> None:
    """S-15: filtro por medicamento en estadísticas (solo las cifras de A)."""
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    d = date(2026, 11, 10)
    await _seed_taken(session, chain_a, _local(d, 8, 0), _local(d, 8, 5))
    await _seed_taken(session, chain_a, _local(d, 9, 0), _local(d, 9, 5))
    await _seed_taken(session, chain_b, _local(d, 10, 0), _local(d, 10, 5))
    await _seed_reminder(session, chain_b, _local(d, 11, 0), "PERDIDA")
    comp = await _compliance(
        client,
        h,
        d,
        d + timedelta(days=1),
        medication_id=chain_a["medication_id"],
    )
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 2
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s17_isolation_between_users(client, session) -> None:
    """S-17: aislamiento entre usuarios (A: 5, 4 a tiempo; B: 2, 0)."""
    uid_a, h_a, chain_a = await _setup(client, session)
    d = date(2026, 11, 10)
    for hour in (8, 9, 10, 11):
        await _seed_taken(session, chain_a, _local(d, hour, 0), _local(d, hour, 5))
    await _seed_reminder(session, chain_a, _local(d, 12, 0), "PERDIDA")
    user_b = await _register_ok(client, _unique_email())
    uid_b, token_b = user_b["user"]["id"], user_b["access_token"]
    h_b = _headers(token_b)
    chain_b = await _seed_chain(session, uid_b)
    await _seed_reminder(session, chain_b, _local(d, 8, 0), "PERDIDA")
    await _seed_reminder(session, chain_b, _local(d, 9, 0), "PERDIDA")
    comp = await _compliance(client, h_b, d, d + timedelta(days=1))
    s = comp["summary"]
    # Solo las cifras de B.
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 0
    assert s["lost"] == 2
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s19_caregiver_without_permission(client, session) -> None:
    """S-19: cuidador sin permiso / extraño (403 + ACCESS_DENIED)."""
    uid_a, h_a, chain_a = await _setup(client, session)
    user_b = await _register_ok(client, _unique_email())
    uid_b, token_b = user_b["user"]["id"], user_b["access_token"]
    h_b = _headers(token_b)
    await _seed_caregiver_link(
        session, patient_id=uid_a, caregiver_id=uid_b, perm_view_history=False
    )
    r = await client.get(
        "/api/v1/stats/compliance", headers=h_b, params={"patient_id": uid_a}
    )
    assert r.status_code == 403, r.text
    assert (
        await _audit_rows(
            session,
            caregiver_id=uid_b,
            patient_id=uid_a,
            action="ACCESS_DENIED",
            result="DENEGADO",
        )
        == 1
    )


@pytest.mark.asyncio
async def test_s20_without_authentication(client, session) -> None:
    """S-20: sin autenticación (401)."""
    r = await client.get("/api/v1/stats/compliance")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_s21_default_period_30_days(client, session) -> None:
    """S-21: periodo por defecto (30 días): fuera hace 40, dentro hace 5."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    when_old = now - timedelta(days=40)
    when_new = now - timedelta(days=5)
    await _seed_taken(session, chain, when_old, when_old + timedelta(minutes=10))
    await _seed_taken(session, chain, when_new, when_new + timedelta(minutes=10))
    comp = await _compliance(client, h)
    s = comp["summary"]
    # Solo cuenta la de hace 5 días (la de hace 40 queda fuera).
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s22_invalid_group_by(client, session) -> None:
    """S-22: group_by inválido (422)."""
    uid, h, chain = await _setup(client, session)
    r = await client.get(
        "/api/v1/stats/compliance", headers=h, params={"group_by": "hora"}
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_s23_confirm_then_measure(client, session) -> None:
    """S-23: flujo real: confirmar y luego medir (ENVIADA -> a tiempo)."""
    uid, h, chain = await _setup(client, session)
    when = _utcnow() - timedelta(minutes=10)
    rid = await _seed_reminder(session, chain, when, "ENVIADA")
    await _confirm(client, h, rid)
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s25_cancelled_by_medication_deactivation(client, session) -> None:
    """S-25: cancelada por desactivación del medicamento (I-3)."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=2)
    when2 = _future_within_today()
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "PENDIENTE")
    await _deactivate_medication(client, h, chain["medication_id"])
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 1,
        "link_removed": 0,
        "unknown": 0,
    }
    # Denominador 1 (D-11 Alt 3).
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s26_cancelled_by_treatment_pause(client, session) -> None:
    """S-26: cancelada por pausa del tratamiento."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=2)
    when2 = _future_within_today()
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "PENDIENTE")
    await _pause(client, h, chain["treatment_id"])
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 1,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    # Denominador 1 (D-11 Alt 3).
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s27_taken_without_intake_counts_late(client, session) -> None:
    """S-27: TOMADA sin toma cuenta como tardía (D-9)."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=3)
    when2 = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_reminder(session, chain, when2, "TOMADA")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 1
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 50.0


@pytest.mark.asyncio
async def test_s28_history_shows_cancel_reason(client, session) -> None:
    """S-28: el historial muestra el motivo de cancelación."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    when1 = now - timedelta(hours=3)
    when2 = now - timedelta(hours=2)
    await _seed_reminder(session, chain, when1, "CANCELADA", "MEDICATION_DEACTIVATED")
    await _seed_unknown_cancelled(session, chain, when2)
    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 2
    assert {row["status"] for row in page["items"]} == {"CANCELADA"}
    assert {row["cancel_reason"] for row in page["items"]} == {
        "MEDICATION_DEACTIVATED",
        None,
    }


@pytest.mark.asyncio
async def test_s31_chain_of_two_postponements(client, session) -> None:
    """S-31: cadena de dos posposiciones (solo el nieto cuenta)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(hours=3), "POSPUESTA")
    await _seed_reminder(session, chain, now - timedelta(hours=2), "POSPUESTA")
    when3 = now - timedelta(hours=1)
    await _seed_taken(session, chain, when3, when3 + timedelta(minutes=10))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s32_postponed_then_lost(client, session) -> None:
    """S-32: pospuesta y luego perdida (el hijo perdido sí cuenta)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(hours=2), "POSPUESTA")
    await _seed_reminder(session, chain, now - timedelta(hours=1), "PERDIDA")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 0
    assert s["lost"] == 1
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s33_child_late_against_own_time(client, session) -> None:
    """S-33: hijo tomado tarde contra su propia hora (+45 min)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(hours=2), "POSPUESTA")
    when_child = now - timedelta(hours=1)
    await _seed_taken(session, chain, when_child, when_child + timedelta(minutes=45))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 1
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s34_distinguishes_a_from_c(client, session) -> None:
    """S-34: el caso que distingue A de C (D-2).

    Original 08:00, hijo 08:35 (demora 30 min), tomado 08:40: a
    tiempo contra la hora del hijo (contra la del original sería
    tardía).
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_reminder(session, chain, _local(d, 8, 0), "POSPUESTA")
    await _seed_taken(session, chain, _local(d, 8, 35), _local(d, 8, 40))
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s35_history_stats_coherence_with_postponement(client, session) -> None:
    """S-35: coherencia historial ↔ estadísticas con posposición."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_reminder(session, chain, _local(d, 8, 0), "POSPUESTA")
    await _seed_reminder(session, chain, _local(d, 9, 0), "POSPUESTA")
    await _seed_taken(session, chain, _local(d, 10, 0), _local(d, 10, 5))
    page = await _history(
        client, h, _local(d, 0, 0), _local(d + timedelta(days=1), 0, 0)
    )
    assert page["total"] == 3
    # Conteo manual sobre el historial, excluyendo las POSPUESTA.
    items = [row for row in page["items"] if row["status"] != "POSPUESTA"]
    assert len(items) == 1
    on_time = 0
    for row in items:
        if row["status"] == "TOMADA" and row["taken_at"] is not None:
            taken = datetime.fromisoformat(row["taken_at"])
            sched = datetime.fromisoformat(row["scheduled_at"])
            if taken <= sched + timedelta(minutes=30):
                on_time += 1
    assert on_time == 1
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s36_failed_confirmed_on_time(client, session) -> None:
    """S-36: FALLIDA confirmada a tiempo (+10 min)."""
    uid, h, chain = await _setup(client, session)
    when = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when, when + timedelta(minutes=10))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s37_failed_confirmed_late(client, session) -> None:
    """S-37: FALLIDA confirmada tarde (+45 min)."""
    uid, h, chain = await _setup(client, session)
    when = _utcnow() - timedelta(hours=2)
    await _seed_taken(session, chain, when, when + timedelta(minutes=45))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 1
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s38_failed_postponed(client, session) -> None:
    """S-38: FALLIDA pospuesta (original POSPUESTA + hijo a tiempo)."""
    uid, h, chain = await _setup(client, session)
    when1 = _utcnow() - timedelta(hours=2)
    when2 = _utcnow() - timedelta(hours=1)
    await _seed_reminder(session, chain, when1, "POSPUESTA")
    await _seed_taken(session, chain, when2, when2 + timedelta(minutes=10))
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s39_only_failed_in_period(client, session) -> None:
    """S-39: solo FALLIDA en el periodo (sin datos de adherencia)."""
    uid, h, chain = await _setup(client, session)
    when = _utcnow() - timedelta(hours=2)
    await _seed_reminder(session, chain, when, "FALLIDA")
    comp = await _compliance(client, h)
    s = comp["summary"]
    assert s["scheduled"] == 0
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] is None


@pytest.mark.asyncio
async def test_s40_history_stats_coherence_with_failed(client, session) -> None:
    """S-40: coherencia historial ↔ estadísticas con FALLIDA."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_taken(session, chain, _local(d, 8, 0), _local(d, 8, 5))
    await _seed_reminder(session, chain, _local(d, 9, 0), "FALLIDA")
    page = await _history(
        client, h, _local(d, 0, 0), _local(d + timedelta(days=1), 0, 0)
    )
    assert page["total"] == 2
    # Conteo manual sobre el historial, excluyendo la FALLIDA.
    items = [row for row in page["items"] if row["status"] != "FALLIDA"]
    assert len(items) == 1
    on_time = 0
    for row in items:
        if row["status"] == "TOMADA" and row["taken_at"] is not None:
            taken = datetime.fromisoformat(row["taken_at"])
            sched = datetime.fromisoformat(row["scheduled_at"])
            if taken <= sched + timedelta(minutes=30):
                on_time += 1
    assert on_time == 1
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s41_only_from(client, session) -> None:
    """S-41: solo from=2026-11-01 (to efectivo = hoy + 1 día)."""
    uid, h, chain = await _setup(client, session)
    d1 = date(2026, 11, 1)
    d2 = date(2026, 11, 15)
    await _seed_taken(session, chain, _local(d1, 8, 0), _local(d1, 8, 5))
    await _seed_taken(session, chain, _local(d2, 8, 0), _local(d2, 8, 5))
    comp = await _compliance(client, h, d1)
    s = comp["summary"]
    today = datetime.now(ZoneInfo(BOGOTA)).date()
    assert s["from"] == "2026-11-01"
    assert s["to"] == (today + timedelta(days=1)).isoformat()
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 2
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s42_only_to(client, session) -> None:
    """S-42: solo to=2026-11-21 (from efectivo = to - 30 días)."""
    uid, h, chain = await _setup(client, session)
    d1 = date(2026, 10, 15)
    d2 = date(2026, 11, 1)
    await _seed_taken(session, chain, _local(d1, 8, 0), _local(d1, 8, 5))
    await _seed_taken(session, chain, _local(d2, 8, 0), _local(d2, 8, 5))
    comp = await _compliance(client, h, None, date(2026, 11, 21))
    s = comp["summary"]
    assert s["from"] == "2026-10-22"
    assert s["to"] == "2026-11-21"
    # Solo cuenta la del 1 de noviembre (la del 15 de octubre queda fuera).
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s45_fully_future_period(client, session) -> None:
    """S-45: periodo totalmente futuro (sin dosis)."""
    uid, h, chain = await _setup(client, session)
    comp = await _compliance(client, h, date(2027, 1, 1), date(2027, 2, 1))
    s = comp["summary"]
    assert s["scheduled"] == 0
    assert s["taken_on_time"] == 0
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] is None


@pytest.mark.asyncio
async def test_s46_default_period_group_by_day(client, session) -> None:
    """S-46: defecto con group_by=day (exactamente 30 buckets)."""
    uid, h, chain = await _setup(client, session)
    now = _utcnow()
    when1 = now - timedelta(days=5)
    when2 = now - timedelta(days=2)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=10))
    await _seed_taken(session, chain, when2, when2 + timedelta(minutes=10))
    comp = await _compliance(client, h, group_by="day")
    assert len(comp["groups"]) == 30
    today = datetime.now(ZoneInfo(BOGOTA)).date()
    assert comp["groups"][0]["period_start"] == (
        today - timedelta(days=29)
    ).isoformat()
    assert comp["groups"][-1]["period_start"] == today.isoformat()
    assert comp["summary"]["scheduled"] == 2
    assert comp["summary"]["taken_on_time"] == 2
    assert comp["summary"]["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s47_period_boundary_in_user_timezone(client, session) -> None:
    """S-47: frontera de periodo en zona del usuario (23:30 local)."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 20)
    await _seed_taken(session, chain, _local(d, 23, 30), _local(d, 23, 35))
    comp = await _compliance(client, h, date(2026, 11, 10), date(2026, 11, 21))
    s = comp["summary"]
    # La dosis cuenta (en UTC caería fuera del rango).
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s48_default_period_boundary(client, session) -> None:
    """S-48: frontera del defecto (hace 30 días fuera, hace 29 dentro)."""
    uid, h, chain = await _setup(client, session)
    today = datetime.now(ZoneInfo(BOGOTA)).date()
    d30 = today - timedelta(days=30)
    d29 = today - timedelta(days=29)
    await _seed_taken(session, chain, _local(d30, 8, 0), _local(d30, 8, 5))
    await _seed_taken(session, chain, _local(d29, 8, 0), _local(d29, 8, 5))
    comp = await _compliance(client, h)
    s = comp["summary"]
    # Solo cuenta la de hace 29 días.
    assert s["scheduled"] == 1
    assert s["taken_on_time"] == 1
    assert s["taken_late"] == 0
    assert s["lost"] == 0
    assert s["cancelled"] == 0
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


# ==================================================================
# RF14 — Estadísticas, segunda parte (S-49–S-86)
# ==================================================================

@pytest.mark.asyncio
async def test_s49_week_partial_start(client, session) -> None:
    """S-49 (D-7): semana parcial al inicio.

    from = miércoles 2026-11-11, dosis en la semana 46 y 47: el
    primer bucket tiene period_start lunes 2026-11-09 y etiqueta
    "2026-W46", y solo cuenta las filas desde el 11 (la del lunes
    9 queda fuera del periodo).
    """
    uid, h, chain = await _setup(client, session)
    await _seed_taken(session, chain, _local(date(2026, 11, 9)), _local(date(2026, 11, 9), 8, 5))
    await _seed_taken(session, chain, _local(date(2026, 11, 11)), _local(date(2026, 11, 11), 8, 5))
    await _seed_taken(session, chain, _local(date(2026, 11, 15)), _local(date(2026, 11, 15), 8, 5))
    await _seed_taken(session, chain, _local(date(2026, 11, 16)), _local(date(2026, 11, 16), 8, 5))
    comp = await _compliance(
        client, h, date(2026, 11, 11), date(2026, 11, 18), group_by="week"
    )
    assert len(comp["groups"]) == 2
    by_start = _groups_by_start(comp)
    w46, w47 = by_start["2026-11-09"], by_start["2026-11-16"]
    assert w46["period_label"] == "2026-W46"
    assert w46["scheduled"] == 2  # 11 y 15; la del 9 queda fuera del periodo
    assert w46["compliance_percentage"] == 100.0
    assert w47["period_label"] == "2026-W47"
    assert w47["scheduled"] == 1
    assert comp["summary"]["scheduled"] == 3


@pytest.mark.asyncio
async def test_s50_month_partial(client, session) -> None:
    """S-50 (D-7): mes parcial, periodo del 2026-10-20 al 2026-11-21."""
    uid, h, chain = await _setup(client, session)
    await _seed_taken(session, chain, _local(date(2026, 10, 1)), _local(date(2026, 10, 1), 8, 5))
    await _seed_taken(session, chain, _local(date(2026, 10, 20)), _local(date(2026, 10, 20), 8, 5))
    await _seed_taken(session, chain, _local(date(2026, 11, 10)), _local(date(2026, 11, 10), 8, 5))
    comp = await _compliance(
        client, h, date(2026, 10, 20), date(2026, 11, 21), group_by="month"
    )
    assert len(comp["groups"]) == 2
    by_start = _groups_by_start(comp)
    octb, novb = by_start["2026-10-01"], by_start["2026-11-01"]
    assert octb["period_label"] == "2026-10"
    assert octb["scheduled"] == 1  # solo el 20; el 1 queda fuera del periodo
    assert novb["period_label"] == "2026-11"
    assert novb["scheduled"] == 1
    assert comp["summary"]["scheduled"] == 2


@pytest.mark.asyncio
async def test_s51_empty_days_included(client, session) -> None:
    """S-51 (D-7): días vacíos incluidos; 30 días con dosis en solo 3."""
    uid, h, chain = await _setup(client, session)
    base = date(2026, 11, 1)
    for day in (date(2026, 11, 2), date(2026, 11, 10), date(2026, 11, 29)):
        await _seed_taken(session, chain, _local(day), _local(day, 8, 5))
    comp = await _compliance(
        client, h, base, base + timedelta(days=30), group_by="day"
    )
    assert len(comp["groups"]) == 30
    empty = [g for g in comp["groups"] if g["scheduled"] == 0]
    assert len(empty) == 27
    assert all(g["compliance_percentage"] is None for g in empty)
    assert all(g["taken_on_time"] == 0 and g["cancelled"] == 0 for g in empty)
    assert comp["groups"][0]["period_start"] == "2026-11-01"
    assert comp["groups"][-1]["period_start"] == "2026-11-30"
    assert comp["summary"]["scheduled"] == 3
    assert comp["summary"]["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s52_empty_week_included(client, session) -> None:
    """S-52 (D-7): semana vacía incluida en medio del rango."""
    uid, h, chain = await _setup(client, session)
    await _seed_taken(session, chain, _local(date(2026, 11, 10)), _local(date(2026, 11, 10), 8, 5))
    await _seed_taken(session, chain, _local(date(2026, 11, 24)), _local(date(2026, 11, 24), 8, 5))
    comp = await _compliance(
        client, h, date(2026, 11, 9), date(2026, 11, 30), group_by="week"
    )
    assert len(comp["groups"]) == 3
    by_start = _groups_by_start(comp)
    w47 = by_start["2026-11-16"]
    assert w47["scheduled"] == 0
    assert w47["compliance_percentage"] is None
    assert w47["period_label"] == "2026-W47"
    assert comp["summary"]["scheduled"] == 2


@pytest.mark.asyncio
async def test_s53_medication_order_and_sum(client, session) -> None:
    """S-53 (D-7): agrupar por medicamento, orden y suma (3 medicamentos).

    Amoxicilina: 2 programadas (1 a tiempo + 1 cancelada por
    cancelación del tratamiento) -> 100.0 (denominador 1).
    Ibuprofeno: 1 programada (1 a tiempo) -> 100.0.
    Paracetamol: 4 programadas (3 a tiempo + 1 perdida) -> 75.0.
    Resumen: 7 programadas, 5 a tiempo, 83.3 (denominador 6).
    """
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    chain_c = await _seed_chain_named(session, uid, "Ibuprofeno")
    d = date(2026, 11, 10)
    for minute in (5, 10, 15):
        await _seed_taken(session, chain_a, _local(d, 8, minute), _local(d, 8, minute + 1))
    await _seed_reminder(session, chain_a, _local(d, 9), "PERDIDA")
    await _seed_taken(session, chain_b, _local(d, 10), _local(d, 10, 5))
    await _seed_reminder(
        session, chain_b, _local(d, 11), "CANCELADA", "TREATMENT_CANCELLED"
    )
    await _seed_taken(session, chain_c, _local(d, 12), _local(d, 12, 5))
    comp = await _compliance(
        client, h, d, d + timedelta(days=1), group_by="medication"
    )
    assert len(comp["groups"]) == 3
    assert [g["medication_name"] for g in comp["groups"]] == [
        "Amoxicilina",
        "Ibuprofeno",
        "Paracetamol",
    ]
    b, c, a = comp["groups"]
    assert a["scheduled"] == 4 and a["taken_on_time"] == 3
    assert a["lost"] == 1 and a["compliance_percentage"] == 75.0
    assert b["scheduled"] == 2 and b["taken_on_time"] == 1
    assert b["cancelled"] == 1
    assert b["cancelled_by_reason"]["treatment_cancelled"] == 1
    assert b["compliance_percentage"] == 100.0
    assert c["scheduled"] == 1 and c["taken_on_time"] == 1
    assert c["compliance_percentage"] == 100.0
    # La suma de los grupos es el resumen.
    s = comp["summary"]
    assert s["scheduled"] == 7 and s["taken_on_time"] == 5
    assert s["lost"] == 1 and s["cancelled"] == 1
    assert s["cancelled_by_reason"]["treatment_cancelled"] == 1
    assert s["compliance_percentage"] == 83.3
    assert (
        sum(g["scheduled"] for g in comp["groups"]) == s["scheduled"]
        and sum(g["taken_on_time"] for g in comp["groups"]) == s["taken_on_time"]
        and sum(g["cancelled"] for g in comp["groups"]) == s["cancelled"]
    )


@pytest.mark.asyncio
async def test_s54_postpone_moves_bucket(client, session) -> None:
    """S-54 (D-2, D-7): la posposición mueve el bucket.

    Original POSPUESTA el día X (no cuenta) e hijo TOMADA el día Y
    (cuenta): el día X no cuenta esa dosis, el día Y sí.
    """
    uid, h, chain = await _setup(client, session)
    d1, d2 = date(2026, 11, 10), date(2026, 11, 11)
    orig_id = await _seed_reminder(session, chain, _local(d1, 8), "POSPUESTA")
    child = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=uid,
        scheduled_at=_local(d2, 8),
        status="TOMADA",
        parent_reminder_id=orig_id,
    )
    session.add(child)
    await session.flush()
    session.add(
        MedicationIntake(
            reminder_id=child.id,
            user_id=uid,
            taken_at=_local(d2, 8, 5),
            source="WEB",
        )
    )
    await session.commit()
    comp = await _compliance(client, h, d1, d2 + timedelta(days=1), group_by="day")
    by_start = _groups_by_start(comp)
    assert by_start["2026-11-10"]["scheduled"] == 0
    assert by_start["2026-11-11"]["scheduled"] == 1
    assert by_start["2026-11-11"]["compliance_percentage"] == 100.0
    assert comp["summary"]["scheduled"] == 1


@pytest.mark.asyncio
async def test_s55_fallida_excluded_from_groups(client, session) -> None:
    """S-55 (D-3, D-7): FALLIDA excluida de todos los grupos.

    1 TOMADA a tiempo + 1 FALLIDA el mismo día: ese día tiene
    scheduled=1 y 100.0 %.
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_taken(session, chain, _local(d, 8), _local(d, 8, 5))
    await _seed_reminder(session, chain, _local(d, 9), "FALLIDA")
    comp = await _compliance(client, h, d, d + timedelta(days=1), group_by="day")
    assert len(comp["groups"]) == 1
    g = comp["groups"][0]
    assert g["period_start"] == "2026-11-10"
    assert g["scheduled"] == 1
    assert g["taken_on_time"] == 1
    assert g["compliance_percentage"] == 100.0
    assert comp["summary"]["scheduled"] == 1


@pytest.mark.asyncio
async def test_s56_iso_week_label(client, session) -> None:
    """S-56 (D-7): etiqueta de semana ISO.

    Dosis en la semana del 9 al 15 de noviembre de 2026:
    period_start es el lunes 2026-11-09 y period_label "2026-W46".
    """
    uid, h, chain = await _setup(client, session)
    await _seed_taken(
        session, chain, _local(date(2026, 11, 12)), _local(date(2026, 11, 12), 8, 5)
    )
    comp = await _compliance(
        client, h, date(2026, 11, 9), date(2026, 11, 16), group_by="week"
    )
    assert len(comp["groups"]) == 1
    g = comp["groups"][0]
    assert g["period_start"] == "2026-11-09"
    assert g["period_label"] == "2026-W46"
    assert g["scheduled"] == 1
    assert g["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s57_medication_with_filter(client, session) -> None:
    """S-57 (D-7): medicamento + filtro por medicamento A."""
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    d = date(2026, 11, 10)
    await _seed_taken(session, chain_a, _local(d, 8), _local(d, 8, 5))
    await _seed_taken(session, chain_b, _local(d, 10), _local(d, 10, 5))
    comp = await _compliance(
        client,
        h,
        d,
        d + timedelta(days=1),
        group_by="medication",
        medication_id=chain_a["medication_id"],
    )
    assert len(comp["groups"]) == 1
    assert comp["groups"][0]["medication_name"] == "Paracetamol"
    assert comp["groups"][0]["scheduled"] == 1
    assert comp["summary"]["scheduled"] == 1


@pytest.mark.asyncio
async def test_s58_summary_not_average(client, session) -> None:
    """S-58 (D-7): el resumen no es el promedio de los grupos.

    Día 1 con 2/2 a tiempo (100 %), día 2 con 0/1 (0 %): resumen
    66.7 % (2/3), no 50 %.
    """
    uid, h, chain = await _setup(client, session)
    d1, d2 = date(2026, 11, 10), date(2026, 11, 11)
    await _seed_taken(session, chain, _local(d1), _local(d1, 8, 5))
    await _seed_taken(session, chain, _local(d1, 8, 30), _local(d1, 8, 35))
    await _seed_reminder(session, chain, _local(d2, 9), "PERDIDA")
    comp = await _compliance(client, h, d1, d2 + timedelta(days=1), group_by="day")
    by_start = _groups_by_start(comp)
    assert by_start["2026-11-10"]["compliance_percentage"] == 100.0
    assert by_start["2026-11-11"]["compliance_percentage"] == 0.0
    assert comp["summary"]["compliance_percentage"] == 66.7


@pytest.mark.asyncio
async def test_s59_on_time_just_before_grace(client, session) -> None:
    """S-59 (D-8): a tiempo justo antes; taken_at = scheduled_at + 29:59."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(
        session, chain, when, when + timedelta(minutes=29, seconds=59)
    )
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s60_late_one_microsecond_after_grace(client, session) -> None:
    """S-60 (D-8): tardía un microsegundo después de la gracia."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(
        session, chain, when, when + timedelta(minutes=30, microseconds=1)
    )
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_late"] == 1
    assert s["taken_on_time"] == 0
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s61_early_confirmation_on_time(client, session) -> None:
    """S-61 (D-8): confirmación anticipada; taken_at = scheduled_at - 5:00."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(session, chain, when, when - timedelta(minutes=5))
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s62_mixed_grace_boundary(client, session) -> None:
    """S-62 (D-8): borde mixto en una sola consulta.

    Una dosis con taken_at = scheduled_at + 29:59 (a tiempo) y otra
    con taken_at = scheduled_at + 30:01 (tardía).
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when1 = _local(d, 8)
    when2 = _local(d, 9)
    await _seed_taken(
        session, chain, when1, when1 + timedelta(minutes=29, seconds=59)
    )
    await _seed_taken(
        session, chain, when2, when2 + timedelta(minutes=30, seconds=1)
    )
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1 and s["taken_late"] == 1
    assert s["compliance_percentage"] == 50.0


@pytest.mark.asyncio
async def test_s63_taken_on_time_control(client, session) -> None:
    """S-63 (D-9, control): TOMADA con toma a tiempo (+10 min)."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=10))
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s64_taken_late_control(client, session) -> None:
    """S-64 (D-9, control): TOMADA con toma tardía (+45 min)."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=45))
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_late"] == 1
    assert s["taken_on_time"] == 0
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s65_taken_without_intake_alone(client, session) -> None:
    """S-65 (D-9): TOMADA sin toma, sola (sin fila en medication_intakes)."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_reminder(session, chain, _local(d, 8), "TOMADA")
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_late"] == 1
    assert s["taken_on_time"] == 0
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s66_other_states_without_intake(client, session) -> None:
    """S-66 (D-9): otros estados sin registro no cuentan.

    1 PENDIENTE + 1 ENVIADA + 1 FALLIDA, ninguna con toma.
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_reminder(session, chain, _local(d, 8), "PENDIENTE")
    await _seed_reminder(session, chain, _local(d, 9), "ENVIADA")
    await _seed_reminder(session, chain, _local(d, 10), "FALLIDA")
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 0
    assert s["taken_on_time"] == 0 and s["taken_late"] == 0
    assert s["lost"] == 0 and s["cancelled"] == 0
    assert s["compliance_percentage"] is None


@pytest.mark.asyncio
async def test_s67_history_stats_coherence_no_intake(client, session) -> None:
    """S-67 (D-9): coherencia historial ↔ estadísticas con TOMADA sin toma.

    1 TOMADA con toma a tiempo + 1 TOMADA sin toma: el historial
    trae 2 filas (una con taken_at y source, otra con ambos null);
    las estadísticas dan scheduled=2, on_time=1, late=1.
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=10))
    await _seed_reminder(session, chain, _local(d, 9), "TOMADA")
    page = await _history(client, h, _local(d, 0), _local(d + timedelta(days=1), 0))
    assert page["total"] == 2
    with_intake = [r for r in page["items"] if r["taken_at"] is not None]
    without_intake = [r for r in page["items"] if r["taken_at"] is None]
    assert len(with_intake) == 1 and len(without_intake) == 1
    assert with_intake[0]["source"] is not None
    assert without_intake[0]["source"] is None
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1 and s["taken_late"] == 1
    assert s["compliance_percentage"] == 50.0


@pytest.mark.asyncio
async def test_s68_taken_without_intake_grouped_by_day(client, session) -> None:
    """S-68 (D-7, D-9): TOMADA sin toma en agrupación por día.

    Día 1 con 1 TOMADA sin toma; día 2 con 1 TOMADA a tiempo.
    """
    uid, h, chain = await _setup(client, session)
    d1, d2 = date(2026, 11, 10), date(2026, 11, 11)
    await _seed_reminder(session, chain, _local(d1, 8), "TOMADA")
    when2 = _local(d2, 8)
    await _seed_taken(session, chain, when2, when2 + timedelta(minutes=10))
    comp = await _compliance(client, h, d1, d2 + timedelta(days=1), group_by="day")
    by_start = _groups_by_start(comp)
    day1, day2 = by_start["2026-11-10"], by_start["2026-11-11"]
    assert day1["scheduled"] == 1 and day1["taken_late"] == 1
    assert day1["compliance_percentage"] == 0.0
    assert day2["scheduled"] == 1 and day2["taken_on_time"] == 1
    assert day2["compliance_percentage"] == 100.0
    s = comp["summary"]
    assert s["scheduled"] == 2 and s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 50.0


@pytest.mark.asyncio
async def test_s69_history_stats_with_pending_and_future(client, session) -> None:
    """S-69 (D-10): coherencia historial ↔ estadísticas con pendientes.

    1 TOMADA a tiempo + 1 PENDIENTE futuro + 1 PENDIENTE en gracia:
    historial total=3; estadísticas scheduled=1, on_time=1, 100.0 %.
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    when = _local(d, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=10))
    now = _utcnow()
    await _seed_reminder(session, chain, now - timedelta(minutes=10), "PENDIENTE")
    await _seed_reminder(session, chain, now + timedelta(hours=2), "PENDIENTE")
    page = await _history(client, h, _local(d, 0), now + timedelta(days=1))
    assert page["total"] == 3
    comp = await _compliance(client, h, date(2026, 11, 1), date(2026, 12, 1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["taken_on_time"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s70_only_pending_and_future_null(client, session) -> None:
    """S-70 (D-10): solo pendientes y futuro → porcentaje null."""
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_reminder(session, chain, _local(d, 9), "PENDIENTE")
    await _seed_reminder(session, chain, _local(d, 10), "ENVIADA")
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 0
    assert s["compliance_percentage"] is None


@pytest.mark.asyncio
async def test_s72_breakdown_six_keys(client, session) -> None:
    """S-72 (D-11): desglose con las seis claves.

    1 CANCELADA por cada uno de los cinco motivos + 1 con
    cancel_reason=NULL: scheduled=6, cancelled=6, las seis claves
    en 1 cada una, denominador 1, 0.0 %.
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    reasons = [
        "TREATMENT_CANCELLED",
        "TREATMENT_PAUSED",
        "TREATMENT_COMPLETED",
        "MEDICATION_DEACTIVATED",
        "LINK_REMOVED",
    ]
    for i, reason in enumerate(reasons):
        await _seed_reminder(
            session, chain, _local(d, 8 + i), "CANCELADA", reason
        )
    await _seed_unknown_cancelled(session, chain, _local(d, 13))
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 6
    assert s["taken_on_time"] == 0 and s["taken_late"] == 0
    assert s["lost"] == 0 and s["cancelled"] == 6
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 1,
        "treatment_paused": 1,
        "treatment_completed": 1,
        "medication_deactivated": 1,
        "link_removed": 1,
        "unknown": 1,
    }
    assert sum(s["cancelled_by_reason"].values()) == 6 == s["cancelled"]
    assert s["compliance_percentage"] == 0.0


@pytest.mark.asyncio
async def test_s73_link_removed_excluded(client, session) -> None:
    """S-73 (D-11, vía API): LINK_REMOVED excluido del denominador.

    1 TOMADA a tiempo + 1 PENDIENTE futura; se retira el vínculo
    por HTTP (la PENDIENTE pasa a CANCELADA/LINK_REMOVED).
    """
    uid, h, chain = await _setup(client, session)
    today = datetime.now(_BOGOTA_TZ).date()
    past = today - timedelta(days=1)
    when = _local(past, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=10))
    await _seed_reminder(session, chain, _utcnow() + timedelta(hours=2), "PENDIENTE")
    await _remove_link(client, h, chain["treatment_id"], chain["link_id"])
    comp = await _compliance(
        client, h, today - timedelta(days=2), today + timedelta(days=2)
    )
    s = comp["summary"]
    assert s["scheduled"] == 2 and s["taken_on_time"] == 1
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"]["link_removed"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s74_treatment_completed_excluded(client, session) -> None:
    """S-74 (D-11, vía API): TREATMENT_COMPLETED excluido del denominador.

    1 TOMADA a tiempo + 1 PENDIENTE futura; se completa el
    tratamiento por HTTP (la PENDIENTE pasa a CANCELADA con ese motivo).
    """
    uid, h, chain = await _setup(client, session)
    today = datetime.now(_BOGOTA_TZ).date()
    past = today - timedelta(days=1)
    when = _local(past, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=10))
    await _seed_reminder(session, chain, _utcnow() + timedelta(hours=2), "PENDIENTE")
    await _complete(client, h, chain["treatment_id"])
    comp = await _compliance(
        client, h, today - timedelta(days=2), today + timedelta(days=2)
    )
    s = comp["summary"]
    assert s["scheduled"] == 2 and s["taken_on_time"] == 1
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"]["treatment_completed"] == 1
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s75_medication_grouped_by_reason(client, session) -> None:
    """S-75 (D-7, D-11): agrupación por medicamento con motivos distintos.

    Med A: 1 a tiempo + 1 cancelada unknown -> 50.0 %.
    Med B: 1 a tiempo + 1 cancelada treatment_cancelled -> 100.0 %.
    Resumen: 66.7 % (2/3), no el promedio (75 %).
    """
    uid, h, chain_a = await _setup(client, session)
    chain_b = await _seed_chain_named(session, uid, "Amoxicilina")
    d = date(2026, 11, 10)
    await _seed_taken(session, chain_a, _local(d, 8), _local(d, 8, 5))
    await _seed_unknown_cancelled(session, chain_a, _local(d, 9))
    await _seed_taken(session, chain_b, _local(d, 10), _local(d, 10, 5))
    await _seed_reminder(
        session, chain_b, _local(d, 11), "CANCELADA", "TREATMENT_CANCELLED"
    )
    comp = await _compliance(
        client, h, d, d + timedelta(days=1), group_by="medication"
    )
    assert len(comp["groups"]) == 2
    b, a = comp["groups"]
    assert a["scheduled"] == 2 and a["compliance_percentage"] == 50.0
    assert a["cancelled_by_reason"]["unknown"] == 1
    assert b["scheduled"] == 2 and b["compliance_percentage"] == 100.0
    assert b["cancelled_by_reason"]["treatment_cancelled"] == 1
    s = comp["summary"]
    assert s["scheduled"] == 4 and s["taken_on_time"] == 2
    assert s["compliance_percentage"] == 66.7


@pytest.mark.asyncio
async def test_s76_day_grouped_by_reason(client, session) -> None:
    """S-76 (D-7, D-11): agrupación por día con motivo excluido y unknown.

    Día 1: 1 a tiempo + 1 cancelada MEDICATION_DEACTIVATED -> 100.0 %.
    Día 2: 1 a tiempo + 1 cancelada unknown -> 50.0 %.
    Resumen: 66.7 % (2/3).
    """
    uid, h, chain = await _setup(client, session)
    d1, d2 = date(2026, 11, 10), date(2026, 11, 11)
    when1 = _local(d1, 8)
    await _seed_taken(session, chain, when1, when1 + timedelta(minutes=5))
    await _seed_reminder(
        session, chain, _local(d1, 9), "CANCELADA", "MEDICATION_DEACTIVATED"
    )
    when2 = _local(d2, 8)
    await _seed_taken(session, chain, when2, when2 + timedelta(minutes=5))
    await _seed_unknown_cancelled(session, chain, _local(d2, 9))
    comp = await _compliance(client, h, d1, d2 + timedelta(days=1), group_by="day")
    by_start = _groups_by_start(comp)
    day1, day2 = by_start["2026-11-10"], by_start["2026-11-11"]
    assert day1["scheduled"] == 2 and day1["compliance_percentage"] == 100.0
    assert day1["cancelled_by_reason"]["medication_deactivated"] == 1
    assert day2["scheduled"] == 2 and day2["compliance_percentage"] == 50.0
    assert day2["cancelled_by_reason"]["unknown"] == 1
    s = comp["summary"]
    assert s["scheduled"] == 4 and s["taken_on_time"] == 2
    assert s["compliance_percentage"] == 66.7


@pytest.mark.asyncio
async def test_s77_reason_kept_after_resume_and_cancel(client, session) -> None:
    """S-77 (D-11): el motivo no cambia al reanudar y cancelar después.

    1 TOMADA a tiempo (pasada) + 2 PENDIENTE futuras (únicas dosis
    futuras del tratamiento en el periodo); pausar por HTTP (2 filas
    → TREATMENT_PAUSED), reanudar (2 nuevos PENDIENTE en los mismos
    huecos), cancelar por HTTP (2 filas → TREATMENT_CANCELLED).
    El periodo excluye el tercer hueco de 08:00 que la regeneración
    crea en la ventana de 72 h, para que las 2 PENDIENTE sean las
    únicas dosis futuras del tratamiento dentro del periodo.
    """
    uid, h, chain = await _setup(client, session)
    now_local = datetime.now(_BOGOTA_TZ)
    today = now_local.date()
    # Los 3 huecos de las 08:00 dentro de [ahora, ahora+72h): el
    # primero es hoy si aún no son las 08:00, si no mañana.
    first_day = today if now_local.time() < time(8, 0) else today + timedelta(days=1)
    slots = [first_day + timedelta(days=i) for i in range(3)]
    past = today - timedelta(days=1)
    when = _local(past, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=5))
    await _seed_reminder(session, chain, _local(slots[0], 8), "PENDIENTE")
    await _seed_reminder(session, chain, _local(slots[1], 8), "PENDIENTE")
    await _pause(client, h, chain["treatment_id"])
    await _resume(client, h, chain["treatment_id"])
    await _cancel(client, h, chain["treatment_id"])
    comp = await _compliance(client, h, past, slots[2])
    s = comp["summary"]
    assert s["scheduled"] == 5 and s["taken_on_time"] == 1
    assert s["taken_late"] == 0 and s["lost"] == 0
    assert s["cancelled"] == 4
    assert s["cancelled_by_reason"] == {
        "treatment_paused": 2,
        "treatment_cancelled": 2,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert sum(s["cancelled_by_reason"].values()) == 4 == s["cancelled"]
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s81_reason_parameter_validation(client, session) -> None:
    """S-81 (D-11): validación del parámetro reason — prueba de unidad.

    Llamada directa a `cancel_pending_for_treatment` (repositorio),
    no HTTP. Con reason=None → ValueError (la fila sigue PENDIENTE);
    con reason='INVALIDO' → ValueError; con reason='TREATMENT_PAUSED'
    → sin error y la fila pasa a CANCELADA con ese motivo.
    """
    uid, h, chain = await _setup(client, session)
    rid = await _seed_reminder(
        session, chain, _utcnow() + timedelta(hours=2), "PENDIENTE"
    )
    with pytest.raises(ValueError):
        await reminder_repository.cancel_pending_for_treatment(
            session, chain["treatment_id"], _utcnow(), None
        )
    with pytest.raises(ValueError):
        await reminder_repository.cancel_pending_for_treatment(
            session, chain["treatment_id"], _utcnow(), "INVALIDO"
        )
    # Tras los dos ValueError, la fila sigue PENDIENTE.
    f, t = _history_window(_utcnow())
    page = await _history(client, h, f, t)
    assert page["total"] == 1
    assert page["items"][0]["status"] == "PENDIENTE"
    cancelled = await reminder_repository.cancel_pending_for_treatment(
        session, chain["treatment_id"], _utcnow(), "TREATMENT_PAUSED"
    )
    assert cancelled == 1
    await session.commit()
    page = await _history(client, h, f, t)
    assert page["total"] == 1
    assert page["items"][0]["status"] == "CANCELADA"
    assert page["items"][0]["cancel_reason"] == "TREATMENT_PAUSED"


@pytest.mark.asyncio
async def test_s82_deactivate_then_cancel_first_event_wins(client, session) -> None:
    """S-82 (D-11): desactivar y luego cancelar; el primer evento gana.

    Tratamiento con 2 medicamentos (A y B), 2 PENDIENTE futuras por
    medicamento + 1 TOMADA a tiempo (pasada); desactivar A por HTTP,
    luego cancelar el tratamiento por HTTP: las 2 de A conservan
    MEDICATION_DEACTIVATED y solo las 2 de B llevan
    TREATMENT_CANCELLED.
    """
    uid, h, chain_a = await _setup(client, session)
    # Segundo medicamento B en el MISMO tratamiento.
    med_b = Medication(user_id=uid, name="Amoxicilina")
    session.add(med_b)
    await session.flush()
    link_b = TreatmentMedication(
        user_id=uid,
        treatment_id=chain_a["treatment_id"],
        medication_id=med_b.id,
        dose_amount=Decimal("500"),
        dose_unit="mg",
    )
    session.add(link_b)
    await session.flush()
    schedule_b = MedicationSchedule(
        user_id=uid,
        treatment_medication_id=link_b.id,
        frequency="DIARIO",
        times=[time(8, 0)],
        start_date=date.today(),
    )
    session.add(schedule_b)
    await session.flush()
    await session.commit()
    chain_b = {
        "user_id": uid,
        "schedule_id": schedule_b.id,
        "link_id": link_b.id,
        "treatment_id": chain_a["treatment_id"],
        "medication_id": med_b.id,
    }
    today = datetime.now(_BOGOTA_TZ).date()
    past = today - timedelta(days=1)
    when = _local(past, 8)
    await _seed_taken(session, chain_a, when, when + timedelta(minutes=5))
    now = _utcnow()
    await _seed_reminder(session, chain_a, now + timedelta(hours=2), "PENDIENTE")
    await _seed_reminder(session, chain_a, now + timedelta(hours=3), "PENDIENTE")
    await _seed_reminder(session, chain_b, now + timedelta(hours=4), "PENDIENTE")
    await _seed_reminder(session, chain_b, now + timedelta(hours=5), "PENDIENTE")
    await _deactivate_medication(client, h, chain_a["medication_id"])
    await _cancel(client, h, chain_a["treatment_id"])
    comp = await _compliance(
        client, h, today - timedelta(days=2), today + timedelta(days=2)
    )
    s = comp["summary"]
    assert s["scheduled"] == 5 and s["taken_on_time"] == 1
    assert s["cancelled"] == 4
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 2,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 2,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s83_pause_then_deactivate_reason_kept(client, session) -> None:
    """S-83 (D-11): pausar y luego desactivar; el motivo no cambia.

    1 medicamento, 2 PENDIENTE futuras + 1 TOMADA a tiempo (pasada);
    pausar el tratamiento por HTTP, luego desactivar el medicamento
    por HTTP sin reanudar: las 2 filas conservan TREATMENT_PAUSED y
    medication_deactivated queda en 0.
    """
    uid, h, chain = await _setup(client, session)
    today = datetime.now(_BOGOTA_TZ).date()
    past = today - timedelta(days=1)
    when = _local(past, 8)
    await _seed_taken(session, chain, when, when + timedelta(minutes=5))
    now = _utcnow()
    await _seed_reminder(session, chain, now + timedelta(hours=2), "PENDIENTE")
    await _seed_reminder(session, chain, now + timedelta(hours=3), "PENDIENTE")
    await _pause(client, h, chain["treatment_id"])
    await _deactivate_medication(client, h, chain["medication_id"])
    comp = await _compliance(
        client, h, today - timedelta(days=2), today + timedelta(days=2)
    )
    s = comp["summary"]
    assert s["scheduled"] == 3 and s["taken_on_time"] == 1
    assert s["cancelled"] == 2
    assert s["cancelled_by_reason"] == {
        "treatment_paused": 2,
        "treatment_cancelled": 0,
        "treatment_completed": 0,
        "medication_deactivated": 0,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] == 100.0


@pytest.mark.asyncio
async def test_s84_week_grouped_by_reason(client, session) -> None:
    """S-84 (D-7, D-11): agrupación por semana con motivos distintos.

    Semana 2026-W47: 1 a tiempo (2026-11-17) + 1 cancelada unknown
    (2026-11-18) -> 50.0 %. Semana 2026-W48: 1 a tiempo (2026-11-24)
    + 1 cancelada medication_deactivated (2026-11-25) -> 100.0 %.
    Resumen: 66.7 % (2/3), no el promedio (75 %); orden cronológico.
    """
    uid, h, chain = await _setup(client, session)
    await _seed_taken(session, chain, _local(date(2026, 11, 17)), _local(date(2026, 11, 17), 8, 5))
    await _seed_unknown_cancelled(session, chain, _local(date(2026, 11, 18)))
    await _seed_taken(session, chain, _local(date(2026, 11, 24)), _local(date(2026, 11, 24), 8, 5))
    await _seed_reminder(
        session, chain, _local(date(2026, 11, 25)), "CANCELADA", "MEDICATION_DEACTIVATED"
    )
    comp = await _compliance(
        client, h, date(2026, 11, 16), date(2026, 11, 30), group_by="week"
    )
    assert len(comp["groups"]) == 2
    by_start = _groups_by_start(comp)
    w47, w48 = by_start["2026-11-16"], by_start["2026-11-23"]
    assert w47["period_label"] == "2026-W47"
    assert w47["scheduled"] == 2 and w47["compliance_percentage"] == 50.0
    assert w47["cancelled_by_reason"]["unknown"] == 1
    assert w48["period_label"] == "2026-W48"
    assert w48["scheduled"] == 2 and w48["compliance_percentage"] == 100.0
    assert w48["cancelled_by_reason"]["medication_deactivated"] == 1
    assert comp["groups"][0]["period_start"] == "2026-11-16"
    assert comp["groups"][1]["period_start"] == "2026-11-23"
    s = comp["summary"]
    assert s["scheduled"] == 4 and s["taken_on_time"] == 2
    assert s["compliance_percentage"] == 66.7


@pytest.mark.asyncio
async def test_s85_month_grouped_by_reason(client, session) -> None:
    """S-85 (D-7, D-11): agrupación por mes con motivos distintos.

    Mes 2026-11: 1 a tiempo + 1 cancelada unknown -> 50.0 %.
    Mes 2026-12: 1 a tiempo + 1 cancelada treatment_completed
    -> 100.0 %. Resumen: 66.7 % (2/3), no el promedio (75 %);
    orden cronológico.
    """
    uid, h, chain = await _setup(client, session)
    await _seed_taken(session, chain, _local(date(2026, 11, 5)), _local(date(2026, 11, 5), 8, 5))
    await _seed_unknown_cancelled(session, chain, _local(date(2026, 11, 6)))
    await _seed_taken(session, chain, _local(date(2026, 12, 5)), _local(date(2026, 12, 5), 8, 5))
    await _seed_reminder(
        session, chain, _local(date(2026, 12, 6)), "CANCELADA", "TREATMENT_COMPLETED"
    )
    comp = await _compliance(
        client, h, date(2026, 11, 1), date(2027, 1, 1), group_by="month"
    )
    assert len(comp["groups"]) == 2
    by_start = _groups_by_start(comp)
    nov, dec = by_start["2026-11-01"], by_start["2026-12-01"]
    assert nov["period_label"] == "2026-11"
    assert nov["scheduled"] == 2 and nov["compliance_percentage"] == 50.0
    assert nov["cancelled_by_reason"]["unknown"] == 1
    assert dec["period_label"] == "2026-12"
    assert dec["scheduled"] == 2 and dec["compliance_percentage"] == 100.0
    assert dec["cancelled_by_reason"]["treatment_completed"] == 1
    assert comp["groups"][0]["period_start"] == "2026-11-01"
    assert comp["groups"][1]["period_start"] == "2026-12-01"
    s = comp["summary"]
    assert s["scheduled"] == 4 and s["taken_on_time"] == 2
    assert s["compliance_percentage"] == 66.7


@pytest.mark.asyncio
async def test_s86_only_cancelled_known_reason_null(client, session) -> None:
    """S-86 (D-11): solo canceladas con motivo conocido → porcentaje null.

    1 CANCELADA por MEDICATION_DEACTIVATED y ninguna otra:
    scheduled=1, cancelled=1, denominador 0, percentage null.
    """
    uid, h, chain = await _setup(client, session)
    d = date(2026, 11, 10)
    await _seed_reminder(
        session, chain, _local(d, 8), "CANCELADA", "MEDICATION_DEACTIVATED"
    )
    comp = await _compliance(client, h, d, d + timedelta(days=1))
    s = comp["summary"]
    assert s["scheduled"] == 1 and s["cancelled"] == 1
    assert s["cancelled_by_reason"] == {
        "treatment_cancelled": 0,
        "treatment_paused": 0,
        "treatment_completed": 0,
        "medication_deactivated": 1,
        "link_removed": 0,
        "unknown": 0,
    }
    assert s["compliance_percentage"] is None
