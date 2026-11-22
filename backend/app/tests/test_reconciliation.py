"""Pruebas del reconciliador (Fase 5, Etapa 5, plan corregido).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que las Etapas 2-4. La base de desarrollo (`dosisalerta`) no
recibe filas de prueba: la siembra se hace con sesiones que
confirman (para que las sesiones propias del reconciliador, en
conexiones distintas, vean las filas) y cada prueba borra sus
filas al final (por usuario unico).

Criterios que se verifican (aceptacion de la Etapa 5):
- PERDIDA por estado (PENDIENTE, ENVIADA, ENVIANDO) y por
  `scheduled_at` propio (hijo pospuesto); nunca TOMADA,
  POSPUESTA, CANCELADA ni FALLIDA; nunca se crean tomas.
- Un reintento pendiente cuya gracia paso se cancela (PERDIDA).
- Caidos: ENVIANDO reclamado hace > 5 min sin log -> PENDIENTE
  dentro de gracia (con los tres campos limpios y `attempt_count`
  intacto); fuera de gracia -> PERDIDA; reclamado hace 1 min no
  se toca; un `next_attempt_at` viejo no impide la liberacion;
  con log para el intento no se libera.
- Limite de lote 500 por pasada (PERDIDA y liberacion), verificado
  en el resultado del UPDATE.
- Modo simulado: no libera caidos; PERDIDA si aplica.
- Concurrencia: dos reconciladores marcan cada fila una sola
  vez; confirmar contra PERDIDA gana exactamente una; confirmar
  contra una liberacion deja una sola toma.
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
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.logs import NotificationLog
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.telegram import TelegramAccount
from app.models.users import User
from app.scheduler.reconciliation import Reconciler
from app.services import intake_service

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
    """Fabrica de sesiones del reconciliador, contra la base de pruebas."""

    def _factory():
        return AsyncSession(test_engine, expire_on_commit=False)

    return _factory


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "recon") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_chain(test_engine, *, linked: bool = True) -> dict:
    """Usuario + medicamento + tratamiento + vinculo + horario."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Reconciliacion",
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
    """Crea recordatorios con los campos que indique cada spec.

    Cada spec admite: ``scheduled_at`` y ``status`` (obligatorios)
    y ``claimed_at``, ``current_attempt_id``, ``next_attempt_at``,
    ``attempt_count``, ``parent_reminder_id``, ``postponed_count``
    y ``cancel_reason``. Una fila CANCELADA sembrada debe llevar
    un motivo valido (el trigger de D-11 rechaza CANCELADA sin
    motivo); el motivo no es lo que estas pruebas verifican.
    """
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        ids = []
        for spec in specs:
            row = MedicationReminder(
                schedule_id=chain["schedule_id"],
                treatment_medication_id=chain["link_id"],
                user_id=chain["user_id"],
                scheduled_at=spec["scheduled_at"],
                status=spec["status"],
                cancel_reason=spec.get("cancel_reason"),
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


async def _seed_log(
    test_engine,
    *,
    reminder_id: int,
    user_id: int,
    attempt_id,
    status: str,
) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        s.add(
            NotificationLog(
                reminder_id=reminder_id,
                user_id=user_id,
                attempt_id=attempt_id,
                status=status,
            )
        )
        await s.commit()


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


async def _reminder_row(test_engine, reminder_id: int) -> dict | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(
                MedicationReminder.status,
                MedicationReminder.next_attempt_at,
                MedicationReminder.attempt_count,
                MedicationReminder.current_attempt_id,
                MedicationReminder.claimed_at,
                MedicationReminder.version,
            ).where(MedicationReminder.id == reminder_id)
        )
        found = row.one_or_none()
        if found is None:
            return None
        return {
            "status": found[0],
            "next_attempt_at": found[1],
            "attempt_count": found[2],
            "current_attempt_id": found[3],
            "claimed_at": found[4],
            "version": found[5],
        }


async def _reminder_status(test_engine, reminder_id: int) -> str | None:
    row = await _reminder_row(test_engine, reminder_id)
    return row["status"] if row is not None else None


async def _count_status(test_engine, user_id: int, status: str) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(func.count())
            .select_from(MedicationReminder)
            .where(
                MedicationReminder.user_id == user_id,
                MedicationReminder.status == status,
            )
        )
        return row.scalar_one()


async def _intake_count(test_engine, reminder_id: int) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(func.count())
            .select_from(MedicationIntake)
            .where(MedicationIntake.reminder_id == reminder_id)
        )
        return row.scalar_one()


async def _actor(session_factory, user_id: int) -> User:
    async with session_factory() as s:
        user = await s.get(User, user_id)
        assert user is not None
        return user


@pytest_asyncio.fixture
async def _chain(test_engine):
    chain = await _seed_chain(test_engine)
    try:
        yield chain
    finally:
        await _cleanup_user(test_engine, chain["user_id"])


# ------------------------------------------------------------------
# Marcar PERDIDA
# ------------------------------------------------------------------


async def test_mark_perdida_by_state(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    pending_id, sent_id, sending_id = await _seed_rows(
        test_engine,
        _chain,
        [
            {"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"},
            {"scheduled_at": now - timedelta(hours=2, minutes=1), "status": "ENVIADA"},
            {
                "scheduled_at": now - timedelta(hours=2, minutes=2),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=1),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            },
        ],
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.marked_perdida == 3
    assert set(result.perdida_ids) == {pending_id, sent_id, sending_id}
    for rid in (pending_id, sent_id, sending_id):
        row = await _reminder_row(test_engine, rid)
        assert row["status"] == "PERDIDA"
        assert row["version"] == 2
    assert await _intake_count(test_engine, pending_id) == 0


async def test_mark_perdida_postponed_child_by_own_time(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (parent_id,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(hours=3), "status": "POSPUESTA"}],
    )
    (child_id,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(hours=2),
                "status": "PENDIENTE",
                "parent_reminder_id": parent_id,
                "postponed_count": 1,
            }
        ],
    )
    await Reconciler(session_factory).reconcile(now)
    assert await _reminder_status(test_engine, parent_id) == "POSPUESTA"
    assert await _reminder_status(test_engine, child_id) == "PERDIDA"


async def test_mark_perdida_unlinked_pending(
    test_engine, session_factory
) -> None:
    chain = await _seed_chain(test_engine, linked=False)
    try:
        now = _utcnow()
        (rid,) = await _seed_rows(
            test_engine,
            chain,
            [{"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"}],
        )
        await Reconciler(session_factory).reconcile(now)
        assert await _reminder_status(test_engine, rid) == "PERDIDA"
    finally:
        await _cleanup_user(test_engine, chain["user_id"])


async def test_mark_perdida_cancels_pending_retry(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(hours=2),
                "status": "PENDIENTE",
                "next_attempt_at": now - timedelta(hours=1),
                "attempt_count": 1,
            }
        ],
    )
    await Reconciler(session_factory).reconcile(now)
    assert await _reminder_status(test_engine, rid) == "PERDIDA"


async def test_no_mark_within_grace_or_terminal(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    ids = await _seed_rows(
        test_engine,
        _chain,
        [
            {"scheduled_at": now - timedelta(minutes=29), "status": "PENDIENTE"},
            {"scheduled_at": now - timedelta(hours=2), "status": "TOMADA"},
            {"scheduled_at": now - timedelta(hours=2, minutes=1), "status": "POSPUESTA"},
            {"scheduled_at": now - timedelta(hours=2, minutes=2), "status": "CANCELADA", "cancel_reason": "TREATMENT_CANCELLED"},
            {"scheduled_at": now - timedelta(hours=2, minutes=3), "status": "FALLIDA"},
            {"scheduled_at": now + timedelta(hours=1), "status": "PENDIENTE"},
        ],
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.marked_perdida == 0
    expected = ["PENDIENTE", "TOMADA", "POSPUESTA", "CANCELADA", "FALLIDA", "PENDIENTE"]
    for rid, status in zip(ids, expected):
        assert await _reminder_status(test_engine, rid) == status


async def test_perdida_creates_no_intakes(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    ids = await _seed_rows(
        test_engine,
        _chain,
        [
            {"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"},
            {"scheduled_at": now - timedelta(hours=2, minutes=1), "status": "ENVIADA"},
        ],
    )
    await Reconciler(session_factory).reconcile(now)
    for rid in ids:
        assert await _intake_count(test_engine, rid) == 0


# ------------------------------------------------------------------
# Liberar caídos
# ------------------------------------------------------------------


async def test_release_stale_sending(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    attempt_id = uuid4()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(minutes=10),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": attempt_id,
                "attempt_count": 1,
            }
        ],
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.released_stale == 1
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "PENDIENTE"
    assert row["current_attempt_id"] is None
    assert row["claimed_at"] is None
    assert row["next_attempt_at"] is None
    assert row["attempt_count"] == 1
    assert row["version"] == 2


async def test_release_stale_sending_past_grace_is_perdida(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(hours=2),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            }
        ],
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.marked_perdida == 1
    assert result.released_stale == 0
    assert await _reminder_status(test_engine, rid) == "PERDIDA"


async def test_release_stale_sending_recent_claim_untouched(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(minutes=10),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=1),
                "current_attempt_id": uuid4(),
                "attempt_count": 1,
            }
        ],
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.released_stale == 0
    assert await _reminder_status(test_engine, rid) == "ENVIANDO"


async def test_release_stale_sending_with_old_next_attempt(
    test_engine, session_factory, _chain
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
                # Valor viejo de un ciclo anterior: la reclamación
                # no lo limpia y no debe impedir la liberación.
                "next_attempt_at": now - timedelta(hours=1),
                "attempt_count": 2,
            }
        ],
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.released_stale == 1
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "PENDIENTE"
    assert row["next_attempt_at"] is None
    assert row["attempt_count"] == 2


async def test_release_stale_sending_with_log_not_released(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    attempt_id = uuid4()
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [
            {
                "scheduled_at": now - timedelta(minutes=10),
                "status": "ENVIANDO",
                "claimed_at": now - timedelta(minutes=6),
                "current_attempt_id": attempt_id,
                "attempt_count": 1,
            }
        ],
    )
    # El intento sí quedó registrado: no es un caído.
    await _seed_log(
        test_engine,
        reminder_id=rid,
        user_id=_chain["user_id"],
        attempt_id=attempt_id,
        status="AMBIGUA",
    )
    result = await Reconciler(session_factory).reconcile(now)
    assert result.released_stale == 0
    assert await _reminder_status(test_engine, rid) == "ENVIANDO"


# ------------------------------------------------------------------
# Límite de lote (precisión B)
# ------------------------------------------------------------------


async def test_batch_limit_perdida(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    base = now - timedelta(minutes=40)
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        for i in range(510):
            s.add(
                MedicationReminder(
                    schedule_id=_chain["schedule_id"],
                    treatment_medication_id=_chain["link_id"],
                    user_id=_chain["user_id"],
                    scheduled_at=base - timedelta(seconds=i),
                    status="PENDIENTE",
                )
            )
        await s.commit()
    reconciler = Reconciler(session_factory)
    first = await reconciler.reconcile(now)
    assert first.marked_perdida == 500
    assert await _count_status(test_engine, _chain["user_id"], "PERDIDA") == 500
    assert await _count_status(test_engine, _chain["user_id"], "PENDIENTE") == 10
    second = await reconciler.reconcile(now)
    assert second.marked_perdida == 10
    assert await _count_status(test_engine, _chain["user_id"], "PERDIDA") == 510


async def test_batch_limit_stale_release(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    base = now - timedelta(minutes=10)
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        for i in range(510):
            s.add(
                MedicationReminder(
                    schedule_id=_chain["schedule_id"],
                    treatment_medication_id=_chain["link_id"],
                    user_id=_chain["user_id"],
                    scheduled_at=base - timedelta(seconds=i),
                    status="ENVIANDO",
                    claimed_at=now - timedelta(minutes=6),
                    current_attempt_id=uuid4(),
                    attempt_count=1,
                )
            )
        await s.commit()
    reconciler = Reconciler(session_factory)
    first = await reconciler.reconcile(now)
    assert first.released_stale == 500
    assert await _count_status(test_engine, _chain["user_id"], "PENDIENTE") == 500
    assert await _count_status(test_engine, _chain["user_id"], "ENVIANDO") == 10
    second = await reconciler.reconcile(now)
    assert second.released_stale == 10
    assert await _count_status(test_engine, _chain["user_id"], "PENDIENTE") == 510


# ------------------------------------------------------------------
# Modo simulado
# ------------------------------------------------------------------


async def test_simulated_mode_skips_stale_release(
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
    result = await Reconciler(session_factory, simulated=True).reconcile(now)
    assert result.released_stale == 0
    assert result.skipped_simulated == 1
    assert result.marked_perdida == 1
    assert await _reminder_status(test_engine, stale_id) == "ENVIANDO"
    assert await _reminder_status(test_engine, overdue_id) == "PERDIDA"


# ------------------------------------------------------------------
# Concurrencia (precisión C)
# ------------------------------------------------------------------


async def test_two_reconcilers_mark_each_row_once(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    base = now - timedelta(hours=2)
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        for i in range(20):
            s.add(
                MedicationReminder(
                    schedule_id=_chain["schedule_id"],
                    treatment_medication_id=_chain["link_id"],
                    user_id=_chain["user_id"],
                    scheduled_at=base - timedelta(seconds=i),
                    status="PENDIENTE",
                )
            )
        await s.commit()
    first, second = await asyncio.gather(
        Reconciler(session_factory).reconcile(now),
        Reconciler(session_factory).reconcile(now),
    )
    assert first.marked_perdida + second.marked_perdida == 20
    assert await _count_status(test_engine, _chain["user_id"], "PERDIDA") == 20


async def test_confirm_vs_perdida_exactly_one_wins(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    user_id = _chain["user_id"]
    (rid,) = await _seed_rows(
        test_engine,
        _chain,
        [{"scheduled_at": now - timedelta(hours=2), "status": "PENDIENTE"}],
    )

    async def _confirm():
        actor = await _actor(session_factory, user_id)
        try:
            async with session_factory() as s:
                await intake_service.confirm(s, actor, rid, source="WEB")
            return "confirmed"
        except HTTPException as exc:
            return f"http_{exc.status_code}"

    async def _reconcile():
        await Reconciler(session_factory).reconcile(now)
        return "reconciled"

    outcome, _ = await asyncio.gather(_confirm(), _reconcile())
    if outcome == "confirmed":
        assert await _reminder_status(test_engine, rid) == "TOMADA"
        assert await _intake_count(test_engine, rid) == 1
    else:
        assert outcome == "http_409"
        assert await _reminder_status(test_engine, rid) == "PERDIDA"
        assert await _intake_count(test_engine, rid) == 0


async def test_confirm_vs_release_leaves_one_intake(
    test_engine, session_factory, _chain
) -> None:
    now = _utcnow()
    user_id = _chain["user_id"]
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

    async def _confirm():
        actor = await _actor(session_factory, user_id)
        async with session_factory() as s:
            await intake_service.confirm(s, actor, rid, source="WEB")
        return "confirmed"

    async def _reconcile():
        await Reconciler(session_factory).reconcile(now)
        return "reconciled"

    await asyncio.gather(_confirm(), _reconcile())
    # Gane quien gane, la dosis termina confirmada con una sola toma:
    # si confirma primero, la liberación salta la fila; si libera
    # primero, la confirmación parte del PENDIENTE liberado.
    assert await _reminder_status(test_engine, rid) == "TOMADA"
    assert await _intake_count(test_engine, rid) == 1
