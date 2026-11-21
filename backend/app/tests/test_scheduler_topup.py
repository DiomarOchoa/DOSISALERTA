"""Pruebas de integración del top-up con el scheduler (Fase 5, Etapa 6).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacía y migrada con Alembic, igual
que las Etapas 2-5. La base de desarrollo (`dosisalerta`) no
recibe filas de prueba.

Criterios que se verifican (aceptación de la Etapa 6):
- Al arrancar, el top-up llena la ventana antes del primer
  `load_pending` (las filas nuevas están en la cola).
- En una pasada de recarga, reconciliar → top-up → cargar deja
  las filas nuevas en la cola en la misma pasada.
- El reconciliador corre antes que el top-up: una fila PERDIDA
  no se recrea.
- El top-up no envía nada a Telegram (cero llamadas al sender).
- Tras un reinicio, la ventana se rellena con tiempo controlado.
- El top-up no corre en cada recarga (60 s), solo cuando toca.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from telegram.error import BadRequest, RetryAfter, TimedOut

from app.models.logs import NotificationLog
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.telegram import TelegramAccount
from app.models.users import User
from app.scheduler import ReminderScheduler
from app.scheduler.scheduler import run_topup as _real_run_topup
from app.scheduler.telegram_sender import TelegramSender
from app.services import schedule_service

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
BOGOTA = "America/Bogota"
CHAT_ID = 123456789


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _test_url() -> str:
    from app.core.config import get_settings

    url = get_settings().database_url
    assert url.endswith("/dosisalerta"), f"URL inesperada: {url.rsplit('@', 1)[-1]}"
    return url[: -len("dosisalerta")] + TEST_DB


async def _create_test_db() -> None:
    from app.core.config import get_settings

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
    from app.core.config import get_settings

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
    """Crea la base de pruebas vacía y aplica las migraciones."""
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


@pytest.fixture(scope="session")
def session_factory(test_engine):
    """Fábrica de sesiones del scheduler, contra la base de pruebas."""

    def _factory():
        return AsyncSession(test_engine, expire_on_commit=False)

    return _factory


# ------------------------------------------------------------------
# Dobles y siembra
# ------------------------------------------------------------------


class FakeBot:
    """Doble de telegram.Bot para las pruebas de integración."""

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


def _unique_email(prefix: str = "sched-topup") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_chain(test_engine, *, times=(time(23, 0),)) -> dict:
    """Usuario + cuenta vinculada + medicamento + tratamiento + vínculo + horario."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Scheduler Top-up",
            email=_unique_email(),
            password_hash="x" * 60,
            timezone=BOGOTA,
        )
        s.add(user)
        await s.flush()
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
            times=list(times),
            start_date=date.today(),
        )
        s.add(schedule)
        await s.flush()
        await s.commit()
        return {
            "user_id": user.id,
            "schedule_id": schedule.id,
            "link_id": link.id,
            "treatment_id": treatment.id,
        }


async def _seed_reminders(test_engine, chain: dict, specs: list[tuple]) -> list[int]:
    """Crea recordatorios (scheduled_at, status) y devuelve sus ids."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        ids = []
        for scheduled_at, status in specs:
            row = MedicationReminder(
                schedule_id=chain["schedule_id"],
                treatment_medication_id=chain["link_id"],
                user_id=chain["user_id"],
                scheduled_at=scheduled_at,
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
            delete(NotificationLog).where(NotificationLog.user_id == user_id)
        )
        await s.execute(
            delete(MedicationIntake).where(MedicationIntake.user_id == user_id)
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


async def _pending_in_window(
    test_engine, user_id: int, start: datetime, end: datetime
) -> list[datetime]:
    """Instantes PENDIENTE del usuario dentro de [start, end)."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        result = await s.execute(
            select(MedicationReminder.scheduled_at)
            .where(
                MedicationReminder.user_id == user_id,
                MedicationReminder.status == "PENDIENTE",
                MedicationReminder.scheduled_at >= start,
                MedicationReminder.scheduled_at < end,
            )
            .order_by(MedicationReminder.scheduled_at)
        )
        return list(result.scalars().all())


def _expected_occurrences(
    start: datetime, end: datetime, wall: time, tz_name: str
) -> list[datetime]:
    """Ocurrencias diarias de `wall` en [start, end), con reglas DST."""
    tz = ZoneInfo(tz_name)
    out: list[datetime] = []
    day = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    while day <= last:
        instant = schedule_service._wall_to_utc(day, wall, tz)
        if start <= instant < end:
            out.append(instant)
        day += timedelta(days=1)
    return out


def _telegram_scheduler(session_factory, bot, **kwargs):
    return ReminderScheduler(
        session_factory,
        TelegramSender(bot),
        clear_delays=(timedelta(seconds=2), timedelta(seconds=3)),
        ambiguous_delay=timedelta(seconds=2),
        **kwargs,
    )


async def _generate_24h(test_engine, session_factory, chain: dict, now: datetime) -> int:
    """Genera solo las primeras 24 h de la ventana (ventana medio vacía)."""
    async with session_factory() as s:
        schedule = await s.get(MedicationSchedule, chain["schedule_id"])
        treatment = await s.get(Treatment, chain["treatment_id"])
        user = await s.get(User, chain["user_id"])
        assert schedule is not None and treatment is not None and user is not None
        created = await schedule_service.generate_reminders_for_schedule(
            s, schedule, treatment, user, horizon_hours=24, now=now
        )
        await s.commit()
        return created


# ------------------------------------------------------------------
# Integración
# ------------------------------------------------------------------


async def test_startup_topup_fills_window(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    now = _utcnow()
    assert await _generate_24h(test_engine, session_factory, chain, now) == 1
    scheduler = _telegram_scheduler(session_factory, FakeBot("ok"))
    await scheduler.start()
    try:
        expected = _expected_occurrences(
            now, now + timedelta(hours=72), time(23, 0), BOGOTA
        )
        assert len(expected) == 3
        pending = await _pending_in_window(
            test_engine, chain["user_id"], now, now + timedelta(hours=72)
        )
        assert pending == expected
        assert len(scheduler) == 3
    finally:
        await scheduler.stop()
    await _cleanup_user(test_engine, chain["user_id"])


async def test_reload_topup_loads_new_rows_in_same_pass(
    test_engine, session_factory, monkeypatch
) -> None:
    chain = await _seed_chain(test_engine)
    now = _utcnow()
    assert await _generate_24h(test_engine, session_factory, chain, now) == 1
    calls: list[int] = []

    async def counting(*args, **kwargs):
        calls.append(1)
        return await _real_run_topup(*args, **kwargs)

    monkeypatch.setattr("app.scheduler.scheduler.run_topup", counting)
    scheduler = _telegram_scheduler(
        session_factory, FakeBot("ok"), topup_interval_seconds=3600
    )
    await scheduler._reconcile(now)
    await scheduler._topup_if_due(now)
    await scheduler.load_pending(now)
    assert calls == [1]
    assert len(scheduler) == 3
    # Con el mismo `now`, la segunda llamada no vuelve a correr.
    await scheduler._topup_if_due(now)
    assert calls == [1]
    assert len(scheduler) == 3
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_runs_after_reconcile(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    now = _utcnow()
    assert await _generate_24h(test_engine, session_factory, chain, now) == 1
    # La ocurrencia de anteayer (23:00 Bogotá) está vencida fuera
    # de la gracia: el reconciliador debe marcarla PERDIDA y el
    # top-up no debe recrearla.
    past = schedule_service._wall_to_utc(
        (now - timedelta(days=2)).astimezone(ZoneInfo(BOGOTA)).date(),
        time(23, 0),
        ZoneInfo(BOGOTA),
    )
    (rid,) = await _seed_reminders(test_engine, chain, [(past, "PENDIENTE")])
    scheduler = _telegram_scheduler(session_factory, FakeBot("ok"))
    await scheduler._reconcile(now)
    await scheduler._topup(now)
    await scheduler.load_pending(now)
    assert await _reminder_status(test_engine, rid) == "PERDIDA"
    pending = await _pending_in_window(
        test_engine, chain["user_id"], now, now + timedelta(hours=72)
    )
    assert past not in pending
    assert len(pending) == 3
    assert len(scheduler) == 3
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_makes_no_telegram_calls(
    test_engine, session_factory
) -> None:
    chain = await _seed_chain(test_engine)
    now = _utcnow()
    assert await _generate_24h(test_engine, session_factory, chain, now) == 1
    bot = FakeBot("ok")
    scheduler = _telegram_scheduler(session_factory, bot)
    await scheduler._topup(now)
    assert bot.calls == []
    # El envío normal sigue funcionando: un vencido se envía una vez.
    (rid,) = await _seed_reminders(
        test_engine, chain, [(now - timedelta(seconds=5), "PENDIENTE")]
    )
    await scheduler.load_pending(now)
    sent = await scheduler.process_due(now)
    assert sent == [rid]
    assert await _reminder_status(test_engine, rid) == "ENVIADA"
    assert len(bot.calls) == 1
    await _cleanup_user(test_engine, chain["user_id"])


async def test_restart_refills_window(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    start = _utcnow()
    assert await _generate_24h(test_engine, session_factory, chain, start) == 1
    first = _telegram_scheduler(session_factory, FakeBot("ok"))
    await first.start()
    try:
        assert len(first) == 3
    finally:
        await first.stop()
    # 48 h después, con una instancia nueva (reinicio): la pasada
    # rellena la ventana relativa al nuevo `now`.
    future = start + timedelta(hours=48)
    second = _telegram_scheduler(session_factory, FakeBot("ok"))
    await second._reconcile(future)
    await second._topup(future)
    await second.load_pending(future)
    expected = _expected_occurrences(
        future, future + timedelta(hours=72), time(23, 0), BOGOTA
    )
    assert len(expected) == 3
    pending = await _pending_in_window(
        test_engine, chain["user_id"], future, future + timedelta(hours=72)
    )
    assert pending == expected
    assert len(second) == 3
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_cadence_not_every_reload(
    test_engine, session_factory, monkeypatch
) -> None:
    chain = await _seed_chain(test_engine)
    calls: list[int] = []

    async def counting(*args, **kwargs):
        calls.append(1)
        return await _real_run_topup(*args, **kwargs)

    monkeypatch.setattr("app.scheduler.scheduler.run_topup", counting)
    scheduler = _telegram_scheduler(
        session_factory,
        FakeBot("ok"),
        reload_interval_seconds=0.5,
        topup_interval_seconds=3,
    )
    await scheduler.start()
    try:
        await asyncio.sleep(7)
    finally:
        await scheduler.stop()
    # Arranque + ~3 s + ~6 s: 3 pasadas; en cada recarga (0,5 s)
    # habrían sido ~14.
    assert 2 <= len(calls) <= 4
    assert len(calls) < 8
    await _cleanup_user(test_engine, chain["user_id"])
