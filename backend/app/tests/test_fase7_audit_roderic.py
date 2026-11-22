"""Auditoria independiente de integracion y regresion — Fase 7, hasta el commit 3.

Autor: Roderic Gallardo (Roderick_1rg).
Alcance aprobado por Diomar 2026-11-21: auditar lo implementado en los
commits 1, 2 y 3 de `feature/fase-7` (537e6b6), sin modificar codigo de
produccion, pruebas existentes ni el plan tecnico.

Metodo: los cambios de estado (pausar, cancelar, completar, desactivar
un medicamento, retirar el vinculo de un tratamiento) se ejecutan por
los endpoints REALES de la API, y la verificacion se hace por los
endpoints REALES de historial (RF13) y cumplimiento (RF14). La siembra
de recordatorios es solo preparacion determinista; el objeto auditado
son los flujos reales y sus efectos en el historial y el cumplimiento.

Operaciones controladas de base de datos (autorizadas por Diomar y
documentadas aqui):
- A-07: el paso PERDIDA de la reconciliacion se invoca directamente
  (`reminder_repository.mark_perdida`), porque el planificador no
  corre en las pruebas. Es el mismo paso que ejecuta el Reconciler.
- A-09: llamada directa a `cancel_pending_for_treatment` sin motivo
  (debe dar ValueError) y un INSERT directo de CANCELADA sin motivo
  dentro de un SAVEPOINT (debe rechazarlo el trigger, sin ensuciar
  la sesion). Es la unica forma de probar el cumplimiento del
  trigger sin desactivarlo.
- A-12: siembra de una CANCELADA historica (cancel_reason NULL) con
  el trigger desactivado temporalmente y reactivado de inmediato en
  un try/finally, para verificar el tratamiento de `unknown` (D-11,
  Alt 3). Es el procedimiento documentado por Diomar para S-71.

Pruebas: A-01 a A-13. Si alguna revela un defecto de produccion, se
documenta como hallazgo y NO se corrige el codigo.
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
            "name": "Auditoria Roderic",
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

    Operacion controlada (A-12): el trigger de D-11 impide crear
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
# A-01: cancelar un tratamiento por la API
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a01_cancel_treatment_via_api(client, session) -> None:
    """A-01: POST /treatments/{id}/cancel -> CANCELADA / TREATMENT_CANCELLED.

    Las 3 PENDIENTE futuras se cancelan; el cumplimiento las excluye
    del denominador (denominador 0 -> porcentaje null, D-1 + D-11).
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    for delta in (1, 2, 3):
        await _seed_reminder(session, chain, now + timedelta(hours=delta), "PENDIENTE")

    body = await _cancel(client, h, chain["treatment_id"])
    assert body["status"] == "CANCELADO"

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 3
    assert {row["status"] for row in page["items"]} == {"CANCELADA"}
    assert {row["cancel_reason"] for row in page["items"]} == {
        "TREATMENT_CANCELLED"
    }

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["scheduled"] == 3
    assert s["cancelled"] == 3
    assert s["cancelled_by_reason"]["treatment_cancelled"] == 3
    assert s["compliance_percentage"] is None  # denominador 0


# ------------------------------------------------------------------
# A-02: pausar y reanudar por la API
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a02_pause_and_resume_via_api(client, session) -> None:
    """A-02: POST /treatments/{id}/pause -> TREATMENT_PAUSED; resume no revive.

    Tras la pausa, las PENDIENTE futuras son CANCELADA con el motivo
    TREATMENT_PAUSED. Tras reanudar, esas filas siguen CANCELADA (el
    historial se conserva, Decision B) y aparecen PENDIENTE nuevas
    regeneradas para la ventana futura.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    for delta in (2, 5):
        await _seed_reminder(session, chain, now + timedelta(hours=delta), "PENDIENTE")

    body = await _pause(client, h, chain["treatment_id"])
    assert body["status"] == "PAUSADO"

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 2
    assert {row["cancel_reason"] for row in page["items"]} == {
        "TREATMENT_PAUSED"
    }

    body = await _resume(client, h, chain["treatment_id"])
    assert body["status"] == "ACTIVO"

    page = await _history(client, h, f, t)
    cancelled = [r for r in page["items"] if r["status"] == "CANCELADA"]
    assert len(cancelled) == 2
    assert {r["cancel_reason"] for r in cancelled} == {"TREATMENT_PAUSED"}
    pending = [r for r in page["items"] if r["status"] == "PENDIENTE"]
    assert len(pending) >= 1  # regeneradas por la reanudacion


# ------------------------------------------------------------------
# A-03: completar un tratamiento por la API
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a03_complete_treatment_via_api(client, session) -> None:
    """A-03: POST /treatments/{id}/complete -> CANCELADA / TREATMENT_COMPLETED."""
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    for delta in (1, 4):
        await _seed_reminder(session, chain, now + timedelta(hours=delta), "PENDIENTE")

    body = await _complete(client, h, chain["treatment_id"])
    assert body["status"] == "COMPLETADO"

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 2
    assert {row["cancel_reason"] for row in page["items"]} == {
        "TREATMENT_COMPLETED"
    }

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["scheduled"] == 2 and s["cancelled"] == 2
    assert s["cancelled_by_reason"]["treatment_completed"] == 2
    assert s["compliance_percentage"] is None


# ------------------------------------------------------------------
# A-04: desactivar un medicamento por la API (I-3)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a04_deactivate_medication_via_api(client, session) -> None:
    """A-04: DELETE /medications/{id} -> CANCELADA / MEDICATION_DEACTIVATED."""
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    for delta in (1, 3):
        await _seed_reminder(session, chain, now + timedelta(hours=delta), "PENDIENTE")

    body = await _deactivate_medication(client, h, chain["medication_id"])
    assert body["is_active"] is False

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 2
    assert {row["cancel_reason"] for row in page["items"]} == {
        "MEDICATION_DEACTIVATED"
    }

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["cancelled_by_reason"]["medication_deactivated"] == 2
    assert s["compliance_percentage"] is None


# ------------------------------------------------------------------
# A-05: retirar un medicamento del tratamiento por la API
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a05_remove_link_via_api(client, session) -> None:
    """A-05: DELETE /treatments/{id}/medications/{link_id} -> LINK_REMOVED.

    La retirada es una desactivacion logica (is_active=False), asi
    que el historial sigue mostrando las filas canceladas.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    for delta in (1, 3):
        await _seed_reminder(session, chain, now + timedelta(hours=delta), "PENDIENTE")

    body = await _remove_link(client, h, chain["treatment_id"], chain["link_id"])
    assert body["is_active"] is False

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 2
    assert {row["cancel_reason"] for row in page["items"]} == {"LINK_REMOVED"}

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["cancelled_by_reason"]["link_removed"] == 2
    assert s["compliance_percentage"] is None


# ------------------------------------------------------------------
# A-06: confirmar por la API y luego cancelar (ejemplo de aceptacion)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a06_confirm_then_cancel_acceptance_77_8(client, session) -> None:
    """A-06: 7 confirmadas a tiempo + 2 perdidas + 1 cancelada = 77,8 %.

    El ejemplo de aceptacion de D-1, recorrido end-to-end: las 7
    confirmaciones van por POST /reminders/{id}/confirm y la
    cancelacion por POST /treatments/{id}/cancel.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    # 7 PENDIENTE recientes (dentro de la gracia de 30 min al confirmar).
    # Horas distintas: el indice parcial uq_reminders_schedule_time
    # prohibe dos recordatorios activos con el mismo (horario, hora).
    confirm_ids = [
        await _seed_reminder(
            session, chain, now - timedelta(minutes=5 + i), "PENDIENTE"
        )
        for i in range(7)
    ]
    # 2 PERDIDA.
    for _ in range(2):
        await _seed_reminder(session, chain, now - timedelta(hours=2), "PERDIDA")
    # 1 PENDIENTE futura, que la cancelacion convertira en CANCELADA.
    await _seed_reminder(session, chain, now + timedelta(hours=3), "PENDIENTE")

    for rid in confirm_ids:
        await _confirm(client, h, rid)
    await _cancel(client, h, chain["treatment_id"])

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 10
    by_status = {}
    for row in page["items"]:
        by_status.setdefault(row["status"], []).append(row)
    assert len(by_status["TOMADA"]) == 7
    assert len(by_status["PERDIDA"]) == 2
    assert len(by_status["CANCELADA"]) == 1
    assert by_status["CANCELADA"][0]["cancel_reason"] == "TREATMENT_CANCELLED"

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["scheduled"] == 10
    assert s["taken_on_time"] == 7
    assert s["lost"] == 2
    assert s["cancelled"] == 1
    assert s["compliance_percentage"] == 77.8


# ------------------------------------------------------------------
# A-07: PENDIENTE vencida + cancelar (observacion §12.11 punto 8)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a07_overdue_pending_not_cancelled_then_perdida(
    client, session
) -> None:
    """A-07: una PENDIENTE vencida NO se cancela al cancelar el tratamiento.

    Solo se cancelan las PENDIENTE/ENVIANDO con scheduled_at >= now.
    La vencida sigue PENDIENTE hasta que la reconciliacion la marca
    PERDIDA, y entonces cuenta como perdida (en el denominador).
    El paso PERDIDA se invoca directamente (mark_perdida, el mismo
    paso del Reconciler) porque el planificador no corre en pruebas.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    overdue_id = await _seed_reminder(
        session, chain, now - timedelta(minutes=45), "PENDIENTE"
    )
    await _seed_reminder(session, chain, now + timedelta(hours=3), "PENDIENTE")

    await _cancel(client, h, chain["treatment_id"])

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[overdue_id]["status"] == "PENDIENTE"  # NO cancelada
    assert {r["status"] for r in page["items"]} == {"PENDIENTE", "CANCELADA"}

    # Paso PERDIDA de la reconciliacion (directo, documentado arriba).
    marked = await reminder_repository.mark_perdida(
        session, cutoff=now - timedelta(minutes=30)
    )
    assert overdue_id in marked
    await session.commit()

    page = await _history(client, h, f, t)
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[overdue_id]["status"] == "PERDIDA"

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["lost"] == 1
    assert s["cancelled"] == 1
    assert s["compliance_percentage"] == 0.0  # 0 a tiempo de 1 en denominador


# ------------------------------------------------------------------
# A-08: ENVIADA sobrevive a la cancelacion (observacion §12.11 punto 7)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a08_enviada_survives_cancel_and_confirms(client, session) -> None:
    """A-08: una ENVIADA no se cancela y aun se puede confirmar.

    Solo se cancelan PENDIENTE/ENVIANDO. La ENVIADA sigue ENVIADA
    tras cancelar el tratamiento, se confirma por la API y cuenta
    como TOMADA (a tiempo).
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    sent_id = await _seed_reminder(session, chain, now + timedelta(hours=1), "ENVIADA")
    await _seed_reminder(session, chain, now + timedelta(hours=3), "PENDIENTE")

    await _cancel(client, h, chain["treatment_id"])

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[sent_id]["status"] == "ENVIADA"  # NO cancelada
    assert {r["status"] for r in page["items"]} == {"ENVIADA", "CANCELADA"}

    await _confirm(client, h, sent_id)

    page = await _history(client, h, f, t)
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[sent_id]["status"] == "TOMADA"

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["cancelled"] == 1
    assert s["compliance_percentage"] == 100.0


# ------------------------------------------------------------------
# A-09: motivo obligatorio y trigger (commit 1 + commit 2)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a09_reason_required_and_trigger_enforced(client, session) -> None:
    """A-09: sin motivo no se puede cancelar ni insertar una CANCELADA.

    (1) `cancel_pending_for_treatment` sin motivo, con motivo
    invalido o sin el argumento da ValueError/TypeError y no cambia
    ninguna fila. (2) Un INSERT directo de CANCELADA sin motivo es
    rechazado por el trigger (en un SAVEPOINT, sin ensuciar la
    sesion). (3) Control: con un motivo valido la insercion se acepta.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    for delta in (1, 2):
        await _seed_reminder(session, chain, now + timedelta(hours=delta), "PENDIENTE")

    # (1) El parametro `reason` es obligatorio y validado.
    with pytest.raises(ValueError):
        await reminder_repository.cancel_pending_for_treatment(
            session, chain["treatment_id"], now, None
        )
    with pytest.raises(ValueError):
        await reminder_repository.cancel_pending_for_treatment(
            session, chain["treatment_id"], now, "INVALIDO"
        )
    with pytest.raises(TypeError):
        await reminder_repository.cancel_pending_for_treatment(
            session, chain["treatment_id"], now
        )
    # Ninguna fila cambio.
    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    assert page["total"] == 2
    assert {row["status"] for row in page["items"]} == {"PENDIENTE"}

    # (2) El trigger rechaza un INSERT de CANCELADA sin motivo.
    with pytest.raises(Exception):
        async with session.begin_nested():
            row = MedicationReminder(
                schedule_id=chain["schedule_id"],
                treatment_medication_id=chain["link_id"],
                user_id=chain["user_id"],
                scheduled_at=now + timedelta(hours=1),
                status="CANCELADA",
                cancel_reason=None,
            )
            session.add(row)
            await session.flush()
    stmt = select(MedicationReminder).where(
        MedicationReminder.user_id == uid,
        MedicationReminder.status == "CANCELADA",
    )
    result = await session.execute(stmt)
    assert result.scalars().all() == []

    # (3) Control: con un motivo valido la insercion se acepta.
    cid = await _seed_reminder(
        session,
        chain,
        now + timedelta(hours=4),
        "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    page = await _history(client, h, f, t)
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[cid]["status"] == "CANCELADA"
    assert by_id[cid]["cancel_reason"] == "TREATMENT_CANCELLED"


# ------------------------------------------------------------------
# A-10: historial — paginacion, filtros y validaciones (D-6, D-10)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a10_history_pagination_and_filters(client, session) -> None:
    """A-10: paginacion D-6, filtros, orden y validaciones 422 del historial."""
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    # 6 filas con estados y horas distintos (orden total por scheduled_at).
    await _seed_reminder(
        session, chain, now + timedelta(hours=2), "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    await _seed_reminder(session, chain, now + timedelta(hours=1), "PENDIENTE")
    await _seed_taken(
        session, chain, now - timedelta(minutes=30), now - timedelta(minutes=20)
    )
    await _seed_reminder(session, chain, now - timedelta(hours=1), "FALLIDA")
    await _seed_reminder(session, chain, now - timedelta(hours=2), "PERDIDA")
    await _seed_reminder(session, chain, now - timedelta(hours=3), "POSPUESTA")

    f, t = _history_window(now)
    # Orden: scheduled_at DESC.
    page = await _history(client, h, f, t)
    assert page["total"] == 6
    assert [r["status"] for r in page["items"]] == [
        "CANCELADA",
        "PENDIENTE",
        "TOMADA",
        "FALLIDA",
        "PERDIDA",
        "POSPUESTA",
    ]
    # Contrato de dose_amount como cadena ("500.000").
    assert page["items"][0]["dose_amount"] == "500.000"

    # Paginacion: limit/offset/total, offset mayor que el total.
    p1 = await _history(client, h, f, t, limit=2, offset=0)
    assert len(p1["items"]) == 2 and p1["total"] == 6
    assert p1["limit"] == 2 and p1["offset"] == 0
    p2 = await _history(client, h, f, t, limit=2, offset=2)
    assert [r["status"] for r in p2["items"]] == ["TOMADA", "FALLIDA"]
    p3 = await _history(client, h, f, t, limit=2, offset=100)
    assert p3["items"] == [] and p3["total"] == 6

    # Filtros.
    only_lost = await _history(client, h, f, t, status="PERDIDA")
    assert only_lost["total"] == 1
    assert only_lost["items"][0]["status"] == "PERDIDA"
    by_med = await _history(client, h, f, t, medication_id=chain["medication_id"])
    assert by_med["total"] == 6
    by_med_none = await _history(client, h, f, t, medication_id=999999)
    assert by_med_none["total"] == 0
    by_trt = await _history(client, h, f, t, treatment_id=chain["treatment_id"])
    assert by_trt["total"] == 6

    # Validaciones 422.
    r = await client.get(
        "/api/v1/reminders/history",
        headers=h,
        params={"from": f.isoformat(), "to": t.isoformat(), "status": "INVALIDO"},
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "literal_error"
    r = await client.get(
        "/api/v1/reminders/history",
        headers=h,
        params={"from": t.isoformat(), "to": f.isoformat()},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------
# A-11: cumplimiento — periodo por defecto y validaciones (D-4)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a11_compliance_default_period_and_422(client, session) -> None:
    """A-11: sin from/to, ultimos 30 dias en la zona del paciente (D-4).

    Y las validaciones 422: from >= to y fecha invalida.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    # Horas distintas: el indice parcial uq_reminders_schedule_time
    # prohibe dos TOMADA con el mismo (horario, hora).
    await _seed_taken(
        session, chain, now - timedelta(hours=1), now - timedelta(minutes=50)
    )
    await _seed_taken(
        session,
        chain,
        now - timedelta(hours=1, minutes=10),
        now - timedelta(minutes=55),
    )
    await _seed_reminder(session, chain, now - timedelta(hours=2), "PERDIDA")

    # Sin from/to: periodo por defecto.
    comp = await _compliance(client, h)
    today = datetime.now(ZoneInfo(BOGOTA)).date()
    s = comp["summary"]
    assert s["from"] == (today - timedelta(days=29)).isoformat()
    assert s["to"] == (today + timedelta(days=1)).isoformat()
    assert s["scheduled"] == 3
    assert s["taken_on_time"] == 2
    assert s["lost"] == 1
    assert s["compliance_percentage"] == 66.7
    assert comp["groups"] is None  # sin group_by (commit 4)

    # Validaciones 422.
    r = await client.get(
        "/api/v1/stats/compliance",
        headers=h,
        params={"from": "2026-11-20", "to": "2026-11-20"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "from debe ser anterior a to"
    r = await client.get(
        "/api/v1/stats/compliance",
        headers=h,
        params={"from": "2026-13-01", "to": "2026-11-20"},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------
# A-12: CANCELADA historica (unknown) en el denominador (D-11, Alt 3)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a12_unknown_cancelled_counts_in_denominator(client, session) -> None:
    """A-12: 1 TOMADA a tiempo + 1 CANCELADA NULL -> 50,0 % (Alt 3).

    La fila historica (cancel_reason NULL) se siembra con el trigger
    desactivado temporalmente (procedimiento documentado en
    `_seed_unknown_cancelled`); entra en el denominador, a diferencia
    de los 5 motivos conocidos, que se excluyen.
    """
    user = await _register_ok(client, _unique_email())
    uid, token = user["user"]["id"], user["access_token"]
    h = _headers(token)
    chain = await _seed_chain(session, uid)
    now = _utcnow()
    await _seed_taken(
        session, chain, now - timedelta(hours=1), now - timedelta(minutes=50)
    )
    unknown_id = await _seed_unknown_cancelled(
        session, chain, now - timedelta(hours=2)
    )

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, h, fd, td)
    s = comp["summary"]
    assert s["scheduled"] == 2
    assert s["taken_on_time"] == 1
    assert s["cancelled"] == 1
    assert s["cancelled_by_reason"]["unknown"] == 1
    assert s["cancelled_by_reason"]["treatment_cancelled"] == 0
    assert s["compliance_percentage"] == 50.0

    f, t = _history_window(now)
    page = await _history(client, h, f, t)
    by_id = {row["id"]: row for row in page["items"]}
    assert by_id[unknown_id]["status"] == "CANCELADA"
    assert by_id[unknown_id]["cancel_reason"] is None


# ------------------------------------------------------------------
# A-13: cuidador — historial y cumplimiento (RF13/RF14)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a13_caregiver_history_and_compliance(client, session) -> None:
    """A-13: cuidador con perm_view_history lee (200 + auditoria); sin el
    permiso, 403. Sin patient_id, el cuidador solo ve sus propios datos.
    """
    patient = await _register_ok(client, _unique_email("paciente"))
    pid, ptoken = patient["user"]["id"], patient["access_token"]
    pchain = await _seed_chain(session, pid)
    now = _utcnow()
    await _seed_reminder(session, pchain, now + timedelta(hours=1), "PENDIENTE")
    await _seed_taken(
        session, pchain, now - timedelta(hours=1), now - timedelta(minutes=50)
    )

    caregiver = await _register_ok(client, _unique_email("cuidador"))
    cid, ctoken = caregiver["user"]["id"], caregiver["access_token"]
    ch = _headers(ctoken)
    session.add(
        CaregiverLink(
            patient_user_id=pid,
            caregiver_user_id=cid,
            status="ACTIVO",
            invited_by=pid,
            accepted_at=now,
            perm_view_history=True,
        )
    )
    await session.commit()

    # Con permiso: historial y cumplimiento del paciente (200).
    f, t = _history_window(now)
    page = await _history(client, ch, f, t, patient_id=pid)
    assert page["total"] == 2
    assert await _audit_ok_count(session, caregiver_id=cid, patient_id=pid) >= 1

    today = datetime.now(ZoneInfo(BOGOTA)).date()
    fd, td = _compliance_window(today)
    comp = await _compliance(client, ch, fd, td, patient_id=pid)
    # Solo la TOMADA cuenta en `scheduled`; la PENDIENTE no cuenta.
    assert comp["summary"]["scheduled"] == 1
    assert comp["summary"]["taken_on_time"] == 1

    # Sin patient_id: solo sus propios datos (vacios).
    page = await _history(client, ch, f, t)
    assert page["total"] == 0

    # Sin el permiso: 403.
    other = await _register_ok(client, _unique_email("cuidador2"))
    oid, otoken = other["user"]["id"], other["access_token"]
    session.add(
        CaregiverLink(
            patient_user_id=pid,
            caregiver_user_id=oid,
            status="ACTIVO",
            invited_by=pid,
            accepted_at=now,
            perm_view_history=False,
        )
    )
    await session.commit()
    r = await client.get(
        "/api/v1/reminders/history",
        headers=_headers(otoken),
        params={"from": f.isoformat(), "to": t.isoformat(), "patient_id": pid},
    )
    assert r.status_code == 403
    r = await client.get(
        "/api/v1/stats/compliance",
        headers=_headers(otoken),
        params={
            "from": fd.isoformat(),
            "to": td.isoformat(),
            "patient_id": pid,
        },
    )
    assert r.status_code == 403
