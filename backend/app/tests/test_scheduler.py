"""Pruebas del scheduler y la reclamacion atomica (Fase 5, Etapa 2).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: la siembra se hace con sesiones que confirman
(para que las sesiones propias del scheduler, en conexiones
distintas, vean las filas) y cada prueba borra sus filas al final
(por usuario unico). Los recordatorios se siembran directamente
con el ORM para controlar el instante exacto (`scheduled_at`).

Criterios que se verifican (aceptacion de la Etapa 2):
- Dos reclamaciones concurrentes del mismo recordatorio:
  exactamente una gana.
- Los PENDIENTE se recuperan despues de reiniciar el scheduler.
- Los ENVIADA no vuelven a la cola.
- El scheduler no procesa los cancelados.
- El envio simulado solo ocurre despues de una reclamacion exitosa.
- El scheduler se puede desactivar (lifespan) y arranca/parar limpio.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.main import create_app
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.users import User
from app.repositories.reminder_repository import (
    claim_reminder,
    mark_sent,
)
from app.scheduler import ReminderScheduler, SimulatedSender

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
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


@pytest.fixture(scope="session")
def session_factory(test_engine):
    """Fabrica de sesiones del scheduler, contra la base de pruebas."""

    def _factory():
        return AsyncSession(test_engine, expire_on_commit=False)

    return _factory


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "sched") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_chain(test_engine) -> dict:
    """Usuario + medicamento + tratamiento + vinculo + horario.

    Devuelve los ids de la cadena. Se confirma para que las
    sesiones del scheduler (otras conexiones) vean las filas.
    """
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Scheduler",
            email=_unique_email(),
            password_hash="x" * 60,
            timezone=BOGOTA,
        )
        s.add(user)
        await s.flush()
        med = Medication(user_id=user.id, name="Paracetamol")
        s.add(med)
        await s.flush()
        treatment = Treatment(
            user_id=user.id, title="Prueba", start_date=date.today()
        )
        s.add(treatment)
        await s.flush()
        link = TreatmentMedication(
            user_id=user.id,
            treatment_id=treatment.id,
            medication_id=med.id,
            dose_amount=Decimal("500"),
            dose_unit="mg",
        )
        s.add(link)
        await s.flush()
        schedule = MedicationSchedule(
            user_id=user.id,
            treatment_medication_id=link.id,
            frequency="DIARIO",
            times=[time(8, 0)],
            start_date=date.today(),
        )
        s.add(schedule)
        await s.flush()
        await s.commit()
        return {
            "user_id": user.id,
            "schedule_id": schedule.id,
            "link_id": link.id,
        }


async def _seed_reminders(
    test_engine, chain: dict, specs: list[tuple[datetime, str]]
) -> list[int]:
    """Crea recordatorios con (scheduled_at, status) dados; devuelve ids."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        ids = []
        for when, status in specs:
            row = MedicationReminder(
                schedule_id=chain["schedule_id"],
                treatment_medication_id=chain["link_id"],
                user_id=chain["user_id"],
                scheduled_at=when,
                status=status,
            )
            s.add(row)
            await s.flush()
            ids.append(row.id)
        await s.commit()
        return ids


async def _cleanup_user(test_engine, user_id: int) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        await s.execute(
            delete(MedicationReminder).where(
                MedicationReminder.user_id == user_id
            )
        )
        await s.execute(
            delete(MedicationSchedule).where(
                MedicationSchedule.user_id == user_id
            )
        )
        await s.execute(
            delete(TreatmentMedication).where(
                TreatmentMedication.user_id == user_id
            )
        )
        await s.execute(delete(Treatment).where(Treatment.user_id == user_id))
        await s.execute(delete(Medication).where(Medication.user_id == user_id))
        await s.execute(delete(User).where(User.id == user_id))
        await s.commit()


async def _reminder_status(test_engine, reminder_id: int) -> str | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(MedicationReminder.status).where(
                MedicationReminder.id == reminder_id
            )
        )
        return row.scalar_one_or_none()


async def _set_status(test_engine, reminder_id: int, status: str) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.get(MedicationReminder, reminder_id)
        assert row is not None
        row.status = status
        await s.commit()


# ------------------------------------------------------------------
# Reclamacion atomica (repositorio)
# ------------------------------------------------------------------


@pytest_asyncio.fixture
async def _chain(test_engine):
    chain = await _seed_chain(test_engine)
    try:
        yield chain
    finally:
        await _cleanup_user(test_engine, chain["user_id"])


async def test_concurrent_claims_exactly_one_wins(
    test_engine, session_factory, _chain
) -> None:
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(_utcnow() + timedelta(hours=1), "PENDIENTE")]
    )

    async def _claim_once():
        async with session_factory() as s:
            row = await claim_reminder(
                s, rid, attempt_id=uuid4(), now=_utcnow()
            )
            await s.commit()
            return row

    first, second = await asyncio.gather(_claim_once(), _claim_once())
    winners = [r for r in (first, second) if r is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert winner.status == "ENVIANDO"
    assert winner.attempt_count == 1
    assert winner.current_attempt_id is not None
    assert winner.claimed_at is not None

    # Un tercer intento ya no puede reclamar.
    async with session_factory() as s:
        assert (
            await claim_reminder(s, rid, attempt_id=uuid4(), now=_utcnow())
            is None
        )
        await s.commit()
    assert await _reminder_status(test_engine, rid) == "ENVIANDO"


async def test_claim_rejected_for_non_pending(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    cancelled_id, sent_id = await _seed_reminders(
        test_engine,
        _chain,
        [
            (now + timedelta(hours=1), "CANCELADA"),
            (now + timedelta(hours=2), "ENVIADA"),
        ],
    )
    async with session_factory() as s:
        assert (
            await claim_reminder(s, cancelled_id, attempt_id=uuid4(), now=now)
            is None
        )
        assert (
            await claim_reminder(s, sent_id, attempt_id=uuid4(), now=now)
            is None
        )
        await s.commit()


async def test_mark_sent_only_for_the_claimer(
    test_engine, session_factory, _chain
) -> None:
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(_utcnow() + timedelta(hours=1), "PENDIENTE")]
    )
    async with session_factory() as s:
        claimed = await claim_reminder(s, rid, attempt_id=uuid4(), now=_utcnow())
        await s.commit()
    assert claimed is not None

    # Otro intento no puede marcar: el intento no coincide.
    async with session_factory() as s:
        assert (
            await mark_sent(s, rid, attempt_id=uuid4()) is None
        )
        await s.commit()
    assert await _reminder_status(test_engine, rid) == "ENVIANDO"

    # El reclamante si puede.
    async with session_factory() as s:
        marked = await mark_sent(
            s, rid, attempt_id=claimed.current_attempt_id
        )
        await s.commit()
    assert marked is not None
    assert marked.status == "ENVIADA"
    assert await _reminder_status(test_engine, rid) == "ENVIADA"


# ------------------------------------------------------------------
# Scheduler: carga, reinicio y proceso
# ------------------------------------------------------------------


async def test_pending_recovered_after_restart(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    user_id = _chain["user_id"]
    pending_ids = await _seed_reminders(
        test_engine,
        _chain,
        [
            (now + timedelta(hours=1), "PENDIENTE"),
            (now + timedelta(hours=2), "PENDIENTE"),
            (now + timedelta(hours=3), "PENDIENTE"),
            # Horas distintas: el indice unico parcial no permite dos
            # recordatorios activos con el mismo horario e instante.
            (now + timedelta(hours=1, minutes=30), "ENVIADA"),
            (now + timedelta(hours=1, minutes=45), "CANCELADA"),
        ],
    )
    pending = pending_ids[:3]

    first = ReminderScheduler(session_factory, SimulatedSender())
    await first.start()
    try:
        assert len(first) == 3
        assert {first.job_for_id(rid).reminder_id for rid in pending} == set(
            pending
        )
        assert first.jobs_for_user(user_id) == set(pending)
        assert first.running
    finally:
        await first.stop()
    assert not first.running

    # Segundo arranque: los mismos 3 PENDIENTE vuelven a la cola;
    # ENVIADA y CANCELADA no.
    second = ReminderScheduler(session_factory, SimulatedSender())
    await second.start()
    try:
        assert len(second) == 3
        assert second.jobs_for_user(user_id) == set(pending)
    finally:
        await second.stop()


async def test_enviada_and_cancelled_not_loaded(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    await _seed_reminders(
        test_engine,
        _chain,
        [
            (now + timedelta(hours=1), "ENVIADA"),
            (now + timedelta(hours=1), "CANCELADA"),
            (now + timedelta(hours=1), "TOMADA"),
            (now + timedelta(hours=1), "PERDIDA"),
        ],
    )
    scheduler = ReminderScheduler(session_factory, SimulatedSender())
    await scheduler.start()
    try:
        assert len(scheduler) == 0
    finally:
        await scheduler.stop()


async def test_overdue_beyond_grace_not_loaded(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    await _seed_reminders(
        test_engine,
        _chain,
        [(now - timedelta(hours=2), "PENDIENTE")],
    )
    scheduler = ReminderScheduler(session_factory, SimulatedSender())
    await scheduler.start()
    try:
        assert len(scheduler) == 0
    finally:
        await scheduler.stop()


async def test_cancelled_not_processed(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(now - timedelta(seconds=10), "PENDIENTE")]
    )
    sender = SimulatedSender()
    scheduler = ReminderScheduler(session_factory, sender)
    # Carga directa sin arrancar el bucle: el bucle procesaria el
    # vencido antes de cancelarlo y la prueba dejaria de ser
    # determinista.
    await scheduler.load_pending(now)
    assert len(scheduler) == 1
    # Se cancela en la BD despues de cargar: el proceso debe
    # fallar la reclamacion y no enviar nada.
    await _set_status(test_engine, rid, "CANCELADA")
    sent = await scheduler.process_due(_utcnow())
    assert sent == []
    assert sender.deliveries == []
    assert await _reminder_status(test_engine, rid) == "CANCELADA"


async def test_simulated_send_only_after_successful_claim(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    first_id, second_id = await _seed_reminders(
        test_engine,
        _chain,
        [
            (now - timedelta(seconds=10), "PENDIENTE"),
            (now - timedelta(seconds=5), "PENDIENTE"),
        ],
    )
    sender = SimulatedSender()
    scheduler = ReminderScheduler(session_factory, sender)
    # Carga directa sin arrancar el bucle: el bucle procesaria los
    # vencidos antes de la reclamacion previa y la prueba dejaria
    # de ser determinista.
    await scheduler.load_pending(now)
    assert len(scheduler) == 2
    # Otro proceso reclama el primero antes de procesar.
    async with session_factory() as s:
        claimed = await claim_reminder(
            s, first_id, attempt_id=uuid4(), now=_utcnow()
        )
        await s.commit()
    assert claimed is not None

    sent = await scheduler.process_due(_utcnow())
    assert sent == [second_id]
    assert [d["reminder_id"] for d in sender.deliveries] == [second_id]
    assert await _reminder_status(test_engine, first_id) == "ENVIANDO"
    assert await _reminder_status(test_engine, second_id) == "ENVIADA"


async def test_scheduler_processes_due_end_to_end(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    due_ids = await _seed_reminders(
        test_engine,
        _chain,
        [
            (now - timedelta(seconds=5), "PENDIENTE"),
            (now - timedelta(seconds=2), "PENDIENTE"),
            (now + timedelta(hours=1), "PENDIENTE"),
        ],
    )
    future_id = due_ids[2]
    sender = SimulatedSender()
    scheduler = ReminderScheduler(
        session_factory, sender, reload_interval_seconds=5.0
    )
    await scheduler.start()
    try:
        # El bucle procesa los vencidos sin que nadie lo llame.
        for _ in range(20):
            if await _reminder_status(test_engine, due_ids[0]) == "ENVIADA" and await _reminder_status(
                test_engine, due_ids[1]
            ) == "ENVIADA":
                break
            await asyncio.sleep(0.5)
        assert await _reminder_status(test_engine, due_ids[0]) == "ENVIADA"
        assert await _reminder_status(test_engine, due_ids[1]) == "ENVIADA"
        assert await _reminder_status(test_engine, future_id) == "PENDIENTE"
        assert {d["reminder_id"] for d in sender.deliveries} == set(due_ids[:2])
        assert scheduler.job_for_id(future_id) is not None
    finally:
        await scheduler.stop()
    assert not scheduler.running


# ------------------------------------------------------------------
# Lifespan: integrado y desactivable
# ------------------------------------------------------------------


async def test_lifespan_starts_and_stops_scheduler(session_factory) -> None:
    app = create_app(run_scheduler=True, session_factory=session_factory)
    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        assert scheduler is not None
        assert scheduler.running
    assert not scheduler.running
    assert app.state.scheduler is None


async def test_lifespan_disabled_by_default() -> None:
    app = create_app(run_scheduler=False)
    async with app.router.lifespan_context(app):
        assert app.state.scheduler is None


async def test_lifespan_follows_settings_default() -> None:
    # Sin parametro: sigue settings.scheduler_enabled, que es False
    # por defecto mientras el sender es simulado (Etapa 2).
    assert get_settings().scheduler_enabled is False
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.scheduler is None
