"""Pruebas del scheduler, el envio real y los reintentos (Fase 5, Etapas 2-3).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: la siembra se hace con sesiones que confirman
(para que las sesiones propias del scheduler, en conexiones
distintas, vean las filas) y cada prueba borra sus filas al final
(por usuario unico). Los recordatorios se siembran directamente
con el ORM para controlar el instante exacto (`scheduled_at`).

Criterios que se verifican (aceptacion de las Etapas 2 y 3):
- Dos reclamaciones concurrentes del mismo recordatorio:
  exactamente una gana.
- Los PENDIENTE se recuperan despues de reiniciar el scheduler.
- Los ENVIADA no vuelven a la cola.
- El scheduler no procesa los cancelados.
- El envio simulado solo ocurre despues de una reclamacion exitosa
  y nunca marca ENVIADA (aislamiento aprobado 2026-11-20).
- El envio real marca ENVIADA con una fila de log ENVIADA.
- Fallo claro: reintento con backoff y FALLIDA terminal al tercero.
- Ambiguo: reintento a +10 min y FALLIDA terminal al tercero.
- 429: se respeta el retry_after exacto, sin tope.
- Sin cuenta vinculada: no se reclama, no se envia, no se registra.
- Un reintento pendiente sobrevive a un reinicio.
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
from telegram.error import BadRequest, RetryAfter, TimedOut

from app.core.config import get_settings
from app.main import create_app
from app.models.logs import NotificationLog
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.telegram import TelegramAccount
from app.models.users import User
from app.repositories.reminder_repository import (
    claim_reminder,
    mark_sent,
)
from app.scheduler import ReminderScheduler, SimulatedSender, TelegramSender

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
BOGOTA = "America/Bogota"
CHAT_ID = 123456789


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


class FakeBot:
    """Doble de telegram.Bot para las pruebas de integracion."""

    def __init__(self, behavior: str = "ok", message_id: int = 101, retry_after: int = 120):
        self.calls: list[dict] = []
        self.behavior = behavior
        self.message_id = message_id
        self.retry_after = retry_after

    async def send_message(self, *, chat_id, text, **kwargs):
        self.calls.append({"chat_id": chat_id, "text": text})
        if self.behavior == "ok":
            return _FakeMessage(self.message_id)
        if self.behavior == "bad_request":
            raise BadRequest("Bad Request: chat not found")
        if self.behavior == "timeout":
            raise TimedOut("Timed out")
        if self.behavior == "retry_after":
            raise RetryAfter(self.retry_after)
        raise AssertionError(f"comportamiento desconocido: {self.behavior}")


class _FakeMessage:
    def __init__(self, message_id: int | None):
        self.message_id = message_id


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "sched") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_chain(test_engine, *, linked: bool = True) -> dict:
    """Usuario + medicamento + tratamiento + vinculo + horario.

    Devuelve los ids de la cadena. Se confirma para que las
    sesiones del scheduler (otras conexiones) vean las filas.
    Con ``linked=True`` (por defecto) el usuario tiene una cuenta
    de Telegram VINCULADA con ``chat_id``.
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
        if linked:
            account = TelegramAccount(
                user_id=user.id,
                telegram_user_id=987654321,
                chat_id=CHAT_ID,
                status="VINCULADA",
            )
            s.add(account)
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
    test_engine, chain: dict, specs: list[tuple]
) -> list[int]:
    """Crea recordatorios; devuelve ids.

    Cada spec es ``(scheduled_at, status)`` o ``(scheduled_at,
    status, next_attempt_at, attempt_count)``.
    """
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        ids = []
        for spec in specs:
            when, status = spec[0], spec[1]
            next_attempt_at = spec[2] if len(spec) > 2 else None
            attempt_count = spec[3] if len(spec) > 3 else 0
            row = MedicationReminder(
                schedule_id=chain["schedule_id"],
                treatment_medication_id=chain["link_id"],
                user_id=chain["user_id"],
                scheduled_at=when,
                status=status,
                next_attempt_at=next_attempt_at,
                attempt_count=attempt_count,
            )
            s.add(row)
            await s.flush()
            ids.append(row.id)
        await s.commit()
        return ids


async def _cleanup_user(test_engine, user_id: int) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        await s.execute(
            delete(NotificationLog).where(NotificationLog.user_id == user_id)
        )
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
        await s.execute(
            delete(TelegramAccount).where(TelegramAccount.user_id == user_id)
        )
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


async def _reminder_row(test_engine, reminder_id: int) -> dict | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(
                MedicationReminder.status,
                MedicationReminder.next_attempt_at,
                MedicationReminder.attempt_count,
            ).where(MedicationReminder.id == reminder_id)
        )
        found = row.one_or_none()
        if found is None:
            return None
        return {
            "status": found[0],
            "next_attempt_at": found[1],
            "attempt_count": found[2],
        }


async def _log_rows(test_engine, reminder_id: int) -> list[dict]:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        rows = await s.execute(
            select(
                NotificationLog.status,
                NotificationLog.telegram_message_id,
                NotificationLog.sent_at,
                NotificationLog.error,
            )
            .where(NotificationLog.reminder_id == reminder_id)
            .order_by(NotificationLog.attempted_at, NotificationLog.id)
        )
        return [
            {
                "status": r[0],
                "telegram_message_id": r[1],
                "sent_at": r[2],
                "error": r[3],
            }
            for r in rows.all()
        ]


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
    # El simulado no es una entrega real: no hay ids enviados,
    # pero la entrega simulada solo ocurre tras la reclamacion.
    assert sent == []
    assert [d["reminder_id"] for d in sender.deliveries] == [second_id]
    assert await _reminder_status(test_engine, first_id) == "ENVIANDO"
    # El segundo queda ENVIANDO (reclamado), no ENVIADA: el
    # simulado nunca marca una entrega que no ocurrio.
    assert await _reminder_status(test_engine, second_id) == "ENVIANDO"
    assert await _log_rows(test_engine, first_id) == []
    assert await _log_rows(test_engine, second_id) == []


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
        # Con el sender simulado quedan ENVIANDO (reclamados),
        # nunca ENVIADA.
        for _ in range(20):
            if await _reminder_status(test_engine, due_ids[0]) == "ENVIANDO" and await _reminder_status(
                test_engine, due_ids[1]
            ) == "ENVIANDO":
                break
            await asyncio.sleep(0.5)
        assert await _reminder_status(test_engine, due_ids[0]) == "ENVIANDO"
        assert await _reminder_status(test_engine, due_ids[1]) == "ENVIANDO"
        assert await _reminder_status(test_engine, future_id) == "PENDIENTE"
        assert {d["reminder_id"] for d in sender.deliveries} == set(due_ids[:2])
        assert await _log_rows(test_engine, due_ids[0]) == []
        assert scheduler.job_for_id(future_id) is not None
    finally:
        await scheduler.stop()
    assert not scheduler.running


# ------------------------------------------------------------------
# Envio real y reintentos (Etapa 3)
# ------------------------------------------------------------------


def _telegram_scheduler(session_factory, bot, **kwargs):
    return ReminderScheduler(
        session_factory,
        TelegramSender(bot),
        clear_delays=(timedelta(seconds=2), timedelta(seconds=3)),
        ambiguous_delay=timedelta(seconds=2),
        **kwargs,
    )


async def test_telegram_send_end_to_end(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(now - timedelta(seconds=5), "PENDIENTE")]
    )
    bot = FakeBot("ok", message_id=101)
    scheduler = _telegram_scheduler(session_factory, bot)
    await scheduler.load_pending(now)
    assert len(scheduler) == 1

    sent = await scheduler.process_due(_utcnow())
    assert sent == [rid]
    assert await _reminder_status(test_engine, rid) == "ENVIADA"
    assert len(bot.calls) == 1
    assert bot.calls[0]["chat_id"] == CHAT_ID
    text = bot.calls[0]["text"]
    assert "Paracetamol 500 mg" in text
    assert "Prueba" in text
    assert "YA LO TOMÉ" not in text
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 1
    assert logs[0]["status"] == "ENVIADA"
    assert logs[0]["telegram_message_id"] == 101
    assert logs[0]["sent_at"] is not None
    assert logs[0]["error"] is None


async def test_clear_failure_retries_then_failed(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(now - timedelta(seconds=10), "PENDIENTE")]
    )
    bot = FakeBot("bad_request")
    scheduler = _telegram_scheduler(session_factory, bot)
    await scheduler.load_pending(now)

    # Intento 1: FALLIDA en el log, PENDIENTE con el reintento a +2 s.
    assert await scheduler.process_due(_utcnow()) == []
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "PENDIENTE"
    assert row["attempt_count"] == 1
    assert row["next_attempt_at"] is not None
    assert row["next_attempt_at"] > _utcnow()
    assert row["next_attempt_at"] <= _utcnow() + timedelta(seconds=5)
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 1
    assert logs[0]["status"] == "FALLIDA"
    assert logs[0]["telegram_message_id"] is None
    assert logs[0]["sent_at"] is None
    assert "BadRequest" in (logs[0]["error"] or "")
    assert len(bot.calls) == 1

    # La puerta de next_attempt_at: no se recoge antes de su hora.
    await scheduler.load_pending(_utcnow())
    assert len(scheduler) == 0

    # Intento 2, tras el backoff: reintento a +3 s.
    await asyncio.sleep(2.5)
    await scheduler.load_pending(_utcnow())
    assert len(scheduler) == 1
    assert await scheduler.process_due(_utcnow()) == []
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "PENDIENTE"
    assert row["attempt_count"] == 2
    assert len(await _log_rows(test_engine, rid)) == 2
    assert len(bot.calls) == 2

    # Intento 3: FALLIDA terminal, sin mas reintentos.
    await asyncio.sleep(3.5)
    await scheduler.load_pending(_utcnow())
    assert len(scheduler) == 1
    assert await scheduler.process_due(_utcnow()) == []
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "FALLIDA"
    assert row["attempt_count"] == 3
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 3
    assert all(log["status"] == "FALLIDA" for log in logs)
    assert len(bot.calls) == 3

    # Un FALLIDA no vuelve a la cola.
    await scheduler.load_pending(_utcnow())
    assert len(scheduler) == 0


async def test_ambiguous_retries_then_failed(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(now - timedelta(seconds=10), "PENDIENTE")]
    )
    bot = FakeBot("timeout")
    scheduler = _telegram_scheduler(session_factory, bot)
    await scheduler.load_pending(now)

    # Intento 1: AMBIGUA en el log, PENDIENTE con reintento a +2 s.
    assert await scheduler.process_due(_utcnow()) == []
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "PENDIENTE"
    assert row["attempt_count"] == 1
    assert row["next_attempt_at"] is not None
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 1
    assert logs[0]["status"] == "AMBIGUA"
    assert logs[0]["telegram_message_id"] is None
    assert logs[0]["sent_at"] is None

    # Intento 2, tras el backoff.
    await asyncio.sleep(2.5)
    await scheduler.load_pending(_utcnow())
    assert await scheduler.process_due(_utcnow()) == []
    assert (await _reminder_row(test_engine, rid))["attempt_count"] == 2
    assert len(await _log_rows(test_engine, rid)) == 2

    # Intento 3: FALLIDA terminal.
    await asyncio.sleep(2.5)
    await scheduler.load_pending(_utcnow())
    assert await scheduler.process_due(_utcnow()) == []
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "FALLIDA"
    assert row["attempt_count"] == 3
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 3
    assert all(log["status"] == "AMBIGUA" for log in logs)
    assert len(bot.calls) == 3


async def test_retry_after_respected_exactly(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(now - timedelta(seconds=10), "PENDIENTE")]
    )
    bot = FakeBot("retry_after", retry_after=120)
    scheduler = _telegram_scheduler(session_factory, bot)
    await scheduler.load_pending(now)
    assert await scheduler.process_due(_utcnow()) == []
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "PENDIENTE"
    assert row["attempt_count"] == 1
    # El reintento es exactamente +120 s (sin tope).
    assert row["next_attempt_at"] is not None
    assert row["next_attempt_at"] > _utcnow() + timedelta(seconds=100)
    assert row["next_attempt_at"] <= _utcnow() + timedelta(seconds=125)
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 1
    assert logs[0]["status"] == "FALLIDA"
    assert "RetryAfter" in (logs[0]["error"] or "")
    assert len(bot.calls) == 1


async def test_no_linked_account_skips_without_claim_or_log(
    test_engine, session_factory
) -> None:
    chain = await _seed_chain(test_engine, linked=False)
    try:
        now = _utcnow()
        (rid,) = await _seed_reminders(
            test_engine, chain, [(now - timedelta(seconds=10), "PENDIENTE")]
        )
        bot = FakeBot("ok")
        scheduler = _telegram_scheduler(session_factory, bot)
        await scheduler.load_pending(now)
        assert len(scheduler) == 1
        assert await scheduler.process_due(_utcnow()) == []
        assert bot.calls == []
        row = await _reminder_row(test_engine, rid)
        assert row["status"] == "PENDIENTE"
        assert row["attempt_count"] == 0
        assert row["next_attempt_at"] is None
        assert await _log_rows(test_engine, rid) == []
    finally:
        await _cleanup_user(test_engine, chain["user_id"])


async def test_retry_survives_restart(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    # Un reintento pendiente: PENDIENTE, con next_attempt_at ya
    # vencido y un intento previo (como si el intento 1 hubiera
    # fallado antes de un reinicio).
    (rid,) = await _seed_reminders(
        test_engine,
        _chain,
        [(now - timedelta(minutes=20), "PENDIENTE", now - timedelta(seconds=5), 1)],
    )
    bot = FakeBot("ok", message_id=202)
    first = _telegram_scheduler(session_factory, bot)
    await first.start()
    try:
        for _ in range(20):
            if await _reminder_status(test_engine, rid) == "ENVIADA":
                break
            await asyncio.sleep(0.5)
        assert await _reminder_status(test_engine, rid) == "ENVIADA"
        logs = await _log_rows(test_engine, rid)
        assert len(logs) == 1
        assert logs[0]["telegram_message_id"] == 202
    finally:
        await first.stop()


async def test_concurrent_schedulers_one_real_send(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_reminders(
        test_engine, _chain, [(now - timedelta(seconds=10), "PENDIENTE")]
    )
    bot = FakeBot("ok", message_id=303)
    first = _telegram_scheduler(session_factory, bot)
    second = _telegram_scheduler(session_factory, bot)
    await first.load_pending(now)
    await second.load_pending(now)
    sent_first, sent_second = await asyncio.gather(
        first.process_due(_utcnow()), second.process_due(_utcnow())
    )
    assert sorted(sent_first + sent_second) == [rid]
    assert len(bot.calls) == 1
    assert await _reminder_status(test_engine, rid) == "ENVIADA"
    logs = await _log_rows(test_engine, rid)
    assert len(logs) == 1
    assert logs[0]["status"] == "ENVIADA"
    assert logs[0]["telegram_message_id"] == 303


# ------------------------------------------------------------------
# Lifespan: integrado y desactivable
# ------------------------------------------------------------------


async def test_lifespan_starts_and_stops_scheduler(session_factory) -> None:
    app = create_app(
        run_scheduler=True,
        session_factory=session_factory,
        sender=SimulatedSender(),
    )
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
    # por defecto (Etapa 3: el scheduler no se enciende solo).
    assert get_settings().scheduler_enabled is False
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.scheduler is None


async def test_lifespan_without_token_does_not_start_scheduler(
    session_factory, monkeypatch
) -> None:
    # Sin token no hay envio real: el scheduler no arranca y la
    # API sigue sirviendo. El simulado nunca se conecta aqui.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    app = create_app(run_scheduler=True, session_factory=session_factory)
    async with app.router.lifespan_context(app):
        assert app.state.scheduler is None
