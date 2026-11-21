"""Pruebas de integración del scheduler con la reconciliación
(Fase 5, Etapa 5, plan corregido) y del cargador con los reintentos.

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`), igual que las Etapas 2-4. La siembra y la
limpieza siguen el patrón de `test_scheduler.py`.

Criterios que se verifican (aceptacion de la Etapa 5):
- Arranque: el scheduler reconcilia antes de la primera carga
  (el caído se re-encola, el vencido no).
- Ciclo: el bucle marca PERDIDA un recordatorio que vence
  durante la ejecución; una liberación y la recarga ocurren en
  la misma pasada.
- La cola se limpia: un trabajo PERDIDA desaparece de
  `jobs_by_id` / `jobs_for_user`.
- Supervivencia: una regla que falla no mata el bucle ni impide
  la otra regla; el scheduler sigue enviando.
- Modo simulado: el scheduler simulado no libera caídos.
- El cargador recoge los reintentos por tipo (precisión A,
  reinterpretada): claro +1/+5, AMBIGUA +10 y 429 con su
  `retry_after` exacto, nunca antes de su hora.
- El ciclo completo por tipo, con el reconciliador en el bucle:
  claro y ambiguo hasta FALLIDA al tercer intento; 429 con
  `retry_after` exacto y éxito después.
- Recuperación tras reinicio: un ENVIANDO caído se re-encola y
  se envía; un PENDIENTE vencido pasa a PERDIDA.
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

from app.models.logs import NotificationLog
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.telegram import TelegramAccount
from app.models.users import User
from app.repositories import reminder_repository
from app.scheduler import ReminderScheduler, SimulatedSender, TelegramSender
from app.scheduler.reconciliation import Reconciler

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


class FlakyBot:
    """429 la primera vez, éxito después."""

    def __init__(self, retry_after: int = 2, message_id: int = 404):
        self.calls: list[dict] = []
        self.retry_after = retry_after
        self.message_id = message_id
        self._calls = 0

    async def send_message(self, *, chat_id, text, **kwargs):
        self.calls.append({"chat_id": chat_id, "text": text})
        self._calls += 1
        if self._calls == 1:
            raise RetryAfter(self.retry_after)
        return _FakeMessage(self.message_id)


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "schedrecon") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_chain(test_engine, *, linked: bool = True) -> dict:
    """Usuario + medicamento + tratamiento + vinculo + horario."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Scheduler Reconciliacion",
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


async def _seed_rows(test_engine, chain: dict, specs: list[dict]) -> list[int]:
    """Crea recordatorios con los campos que indique cada spec."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        ids = []
        for spec in specs:
            row = MedicationReminder(
                schedule_id=chain["schedule_id"],
                treatment_medication_id=chain["link_id"],
                user_id=chain["user_id"],
                scheduled_at=spec["scheduled_at"],
                status=spec["status"],
                claimed_at=spec.get("claimed_at"),
                current_attempt_id=spec.get("current_attempt_id"),
                next_attempt_at=spec.get("next_attempt_at"),
                attempt_count=spec.get("attempt_count", 0),
                parent_reminder_id=spec.get("parent_reminder_id"),
                postponed_count=spec.get("postponed_count", 0),
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


async def _reminder_status(test_engine, reminder_id: int) -> str | None:
    row = await _reminder_row(test_engine, reminder_id)
    return row["status"] if row is not None else None


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


async def _wait_for_status(test_engine, reminder_id: int, status: str, timeout: float = 20.0) -> bool:
    """Espera hasta que el recordatorio tenga ese estado (bucle real)."""
    for _ in range(int(timeout / 0.5)):
        if await _reminder_status(test_engine, reminder_id) == status:
            return True
        await asyncio.sleep(0.5)
    return await _reminder_status(test_engine, reminder_id) == status


@pytest_asyncio.fixture
async def _chain(test_engine):
    chain = await _seed_chain(test_engine)
    try:
        yield chain
    finally:
        await _cleanup_user(test_engine, chain["user_id"])


def _telegram_scheduler(session_factory, bot, **kwargs):
    return ReminderScheduler(
        session_factory,
        TelegramSender(bot),
        clear_delays=(timedelta(seconds=2), timedelta(seconds=3)),
        ambiguous_delay=timedelta(seconds=2),
        **kwargs,
    )


# ------------------------------------------------------------------
# Arranque, ciclo y cola
# ------------------------------------------------------------------


async def test_startup_reconciles_before_first_load(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    # El caído tiene `scheduled_at` en el futuro: tras liberarlo
    # se encola pero el bucle no lo reclama todavía (no vencido),
    # así que las comprobaciones tras `start()` son deterministas.
    stale_id, overdue_id = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now + timedelta(hours=1),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            },
            {"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"},
        ],
    )
    # Con remitente real (FakeBot): en modo simulado el
    # reconciliador saltaría la liberación de caídos por diseño,
    # así que la prueba usa TelegramSender.
    scheduler = _telegram_scheduler(session_factory, FakeBot("ok"))
    await scheduler.start()
    try:
        # El caído se liberó y se cargó; el vencido no.
        assert scheduler.job_for_id(stale_id) is not None
        assert scheduler.job_for_id(overdue_id) is None
        assert await _reminder_status(test_engine, stale_id) == "PENDIENTE"
        assert await _reminder_status(test_engine, overdue_id) == "PERDIDA"
    finally:
        await scheduler.stop()


async def test_loop_marks_perdida_during_run(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(minutes=29, seconds=55), "status": "PENDIENTE"}],
    )
    scheduler = ReminderScheduler(
        session_factory, SimulatedSender(), reload_interval_seconds=1.0
    )
    await scheduler.start()
    try:
        assert await _wait_for_status(test_engine, rid, "PERDIDA", timeout=15.0)
    finally:
        await scheduler.stop()


async def test_release_and_reload_in_same_pass(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    # Con remitente real (FakeBot): en modo simulado el
    # reconciliador saltaría la liberación de caídos por diseño.
    scheduler = _telegram_scheduler(
        session_factory, FakeBot("ok"), reload_interval_seconds=1.0
    )
    await scheduler.start()
    try:
        (rid,) = await _seed_rows(
            test_engine,
            _chain,
            [
                {
                    "scheduled_at": now + timedelta(hours=1),
                    "status": "ENVIANDO",
                    "claimed_at": now - timedelta(minutes=6),
                    "current_attempt_id": uuid4(),
                    "attempt_count": 1,
                }
            ],
        )
        # La recarga periódica reconcilia y carga en la misma
        # pasada: el caído aparece en la cola sin esperar un ciclo más.
        for _ in range(10):
            if scheduler.job_for_id(rid) is not None:
                break
            await asyncio.sleep(0.5)
        assert scheduler.job_for_id(rid) is not None
        assert await _reminder_status(test_engine, rid) == "PENDIENTE"
    finally:
        await scheduler.stop()


async def test_queue_cleaned_on_perdida(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    user_id = _chain["user_id"]
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(minutes=10), "status": "PENDIENTE"}],
    )
    scheduler = ReminderScheduler(session_factory, SimulatedSender())
    await scheduler.load_pending(now)
    assert scheduler.job_for_id(rid) is not None
    assert rid in scheduler.jobs_for_user(user_id)
    await scheduler._reconcile(now + timedelta(minutes=31))
    assert scheduler.job_for_id(rid) is None
    assert rid not in scheduler.jobs_for_user(user_id)
    assert await _reminder_status(test_engine, rid) == "PERDIDA"


async def test_simulated_scheduler_skips_stale_release(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    stale_id, overdue_id = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now + timedelta(hours=1),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            },
            {"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"},
        ],
    )
    scheduler = ReminderScheduler(session_factory, SimulatedSender())
    await scheduler.start()
    try:
        assert scheduler.job_for_id(stale_id) is None
        assert scheduler.job_for_id(overdue_id) is None
        assert await _reminder_status(test_engine, stale_id) == "ENVIANDO"
        assert await _reminder_status(test_engine, overdue_id) == "PERDIDA"
    finally:
        await scheduler.stop()


# ------------------------------------------------------------------
# Supervivencia ante errores
# ------------------------------------------------------------------


async def test_failing_rule_does_not_block_other_rule(
    test_engine, session_factory, _chain, monkeypatch
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(minutes=10),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            }
        ],
    )

    async def _boom(*args, **kwargs):
        raise RuntimeError("BD caída en la pasada de PERDIDA")

    monkeypatch.setattr(reminder_repository, "mark_perdida", _boom)

    result = await Reconciler(session_factory).reconcile(now)
    assert result.marked_perdida == 0
    assert result.released_stale == 1
    assert await _reminder_status(test_engine, rid) == "PENDIENTE"


async def test_loop_survives_reconcile_failure(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(seconds=10), "status": "PENDIENTE"}],
    )
    scheduler = ReminderScheduler(
        session_factory, SimulatedSender(), reload_interval_seconds=1.0
    )

    async def _boom(now):
        raise RuntimeError("BD caída en la reconciliación")

    scheduler._reconciler.reconcile = _boom
    await scheduler.start()
    try:
        # El bucle sigue enviando aunque la reconciliación falle.
        assert await _wait_for_status(test_engine, rid, "ENVIANDO", timeout=10.0)
    finally:
        await scheduler.stop()


# ------------------------------------------------------------------
# El cargador recoge los reintentos, por tipo (precisión A)
# ------------------------------------------------------------------


async def test_loader_picks_up_retries_by_type(
    test_engine, session_factory, _chain
) -> None:
    base = _utcnow()
    clear1_id, retry429_id, clear2_id, ambiguous_id = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": base - timedelta(minutes=10),
                "status": "PENDIENTE",
                "next_attempt_at": base + timedelta(seconds=60),
                "attempt_count": 1,
            },
            {
                "scheduled_at": base - timedelta(minutes=9),
                "status": "PENDIENTE",
                "next_attempt_at": base + timedelta(seconds=120),
                "attempt_count": 1,
            },
            {
                "scheduled_at": base - timedelta(minutes=8),
                "status": "PENDIENTE",
                "next_attempt_at": base + timedelta(seconds=300),
                "attempt_count": 2,
            },
            {
                "scheduled_at": base - timedelta(minutes=7),
                "status": "PENDIENTE",
                "next_attempt_at": base + timedelta(seconds=600),
                "attempt_count": 1,
            },
        ],
    )
    scheduler = ReminderScheduler(session_factory, SimulatedSender())
    # Antes de su hora no se recoge ninguno.
    await scheduler.load_pending(base)
    assert len(scheduler) == 0
    # Fallo claro (+1 min): sí a los 61 s, no antes.
    await scheduler.load_pending(base + timedelta(seconds=61))
    assert scheduler.job_for_id(clear1_id) is not None
    assert scheduler.job_for_id(retry429_id) is None
    assert scheduler.job_for_id(clear2_id) is None
    assert scheduler.job_for_id(ambiguous_id) is None
    # 429 con retry_after de 120 s: no a los 60 s, sí a los 121 s.
    await scheduler.load_pending(base + timedelta(seconds=121))
    assert scheduler.job_for_id(retry429_id) is not None
    assert scheduler.job_for_id(clear2_id) is None
    assert scheduler.job_for_id(ambiguous_id) is None
    # Segundo fallo claro (+5 min).
    await scheduler.load_pending(base + timedelta(seconds=301))
    assert scheduler.job_for_id(clear2_id) is not None
    assert scheduler.job_for_id(ambiguous_id) is None
    # Ambiguo (+10 min).
    await scheduler.load_pending(base + timedelta(seconds=601))
    assert scheduler.job_for_id(ambiguous_id) is not None
    assert len(scheduler) == 4


# ------------------------------------------------------------------
# Ciclos completos por tipo, con el reconciliador en el bucle
# ------------------------------------------------------------------


async def test_cycle_clear_failure_with_reconciler(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(seconds=10), "status": "PENDIENTE"}],
    )
    bot = FakeBot("bad_request")
    scheduler = _telegram_scheduler(
        session_factory, bot, reload_interval_seconds=1.0
    )
    await scheduler.start()
    try:
        assert await _wait_for_status(test_engine, rid, "FALLIDA", timeout=20.0)
        row = await _reminder_row(test_engine, rid)
        assert row["attempt_count"] == 3
        logs = await _log_rows(test_engine, rid)
        assert len(logs) == 3
        assert all(log["status"] == "FALLIDA" for log in logs)
        assert len(bot.calls) == 3
    finally:
        await scheduler.stop()


async def test_cycle_ambiguous_with_reconciler(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(seconds=10), "status": "PENDIENTE"}],
    )
    bot = FakeBot("timeout")
    scheduler = _telegram_scheduler(
        session_factory, bot, reload_interval_seconds=1.0
    )
    await scheduler.start()
    try:
        assert await _wait_for_status(test_engine, rid, "FALLIDA", timeout=20.0)
        row = await _reminder_row(test_engine, rid)
        assert row["attempt_count"] == 3
        logs = await _log_rows(test_engine, rid)
        assert len(logs) == 3
        assert all(log["status"] == "AMBIGUA" for log in logs)
        assert len(bot.calls) == 3
    finally:
        await scheduler.stop()


async def test_cycle_retry_after_then_success_with_reconciler(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(seconds=10), "status": "PENDIENTE"}],
    )
    bot = FlakyBot(retry_after=2, message_id=404)
    scheduler = _telegram_scheduler(
        session_factory, bot, reload_interval_seconds=1.0
    )
    await scheduler.start()
    try:
        assert await _wait_for_status(test_engine, rid, "ENVIADA", timeout=15.0)
        row = await _reminder_row(test_engine, rid)
        assert row["attempt_count"] == 2
        logs = await _log_rows(test_engine, rid)
        assert len(logs) == 2
        assert logs[0]["status"] == "FALLIDA"
        assert "RetryAfter" in (logs[0]["error"] or "")
        assert logs[1]["status"] == "ENVIADA"
        assert logs[1]["telegram_message_id"] == 404
        assert len(bot.calls) == 2
    finally:
        await scheduler.stop()


# ------------------------------------------------------------------
# Recuperación tras reinicio
# ------------------------------------------------------------------


async def test_recovery_after_restart(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    stale_id, overdue_id = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(minutes=10),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            },
            {"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"},
        ],
    )
    bot = FakeBot("ok", message_id=505)
    scheduler = _telegram_scheduler(
        session_factory, bot, reload_interval_seconds=1.0
    )
    await scheduler.start()
    try:
        # El caído se libera, se re-encola y se envía; el vencido
        # pasa a PERDIDA sin enviarse.
        assert await _wait_for_status(test_engine, stale_id, "ENVIADA", timeout=15.0)
        assert await _reminder_status(test_engine, overdue_id) == "PERDIDA"
        assert len(bot.calls) == 1
        logs = await _log_rows(test_engine, stale_id)
        assert len(logs) == 1
        assert logs[0]["status"] == "ENVIADA"
        assert logs[0]["telegram_message_id"] == 505
    finally:
        await scheduler.stop()
