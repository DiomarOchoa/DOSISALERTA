"""Pruebas del top-up periódico (Fase 5, Etapa 6).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacía y migrada con Alembic, igual
que las Etapas 2-5. La base de desarrollo (`dosisalerta`) no
recibe filas de prueba: la siembra se hace con sesiones que
confirman (para que las sesiones propias del top-up, en
conexiones distintas, vean las filas) y cada prueba borra sus
filas al final (por usuario único).

Criterios que se verifican (aceptación de la Etapa 6):
- La ventana de 72 h se mantiene llena al avanzar el tiempo
  (24 h y 72 h): solo se crean las filas del tramo nuevo.
- Idempotencia: dos pasadas con el mismo `now` crean 0 filas
  la segunda vez; el total no cambia.
- No se generan filas para tratamientos no ACTIVO, vínculos u
  horarios inactivos, ni fuera de las fechas de inicio/fin.
- Se respetan las zonas horarias y las reglas DST (salto
  adelante: hora inexistente; salto atrás: una sola fila).
- Un horario con zona inválida se salta sin abortar la pasada.
- Los huecos CANCELADA admiten un PENDIENTE nuevo (decisión B)
  sin tocar el historial; los estados existentes no cambian.
- La enumeración solo devuelve horarios activos.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.users import User
from app.repositories import reminder_repository, schedule_repository
from app.scheduler.topup import run_topup

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
BOGOTA = "America/Bogota"
NEW_YORK = "America/New_York"

# Instante de referencia fijo (sábado 21 de noviembre de 2026,
# 12:00 UTC). Con DIARIO 08:00 en Bogotá (UTC-5), las
# ocurrencias son a las 13:00 UTC: 21, 22 y 23 de noviembre
# (el 24 a las 13:00 queda fuera de [T0, T0+72h)).
T0 = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


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
    """Fábrica de sesiones del top-up, contra la base de pruebas."""

    def _factory():
        return AsyncSession(test_engine, expire_on_commit=False)

    return _factory


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "topup") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_chain(
    test_engine,
    *,
    timezone: str = BOGOTA,
    treatment_status: str = "ACTIVO",
    link_active: bool = True,
    schedule_active: bool = True,
    frequency: str = "DIARIO",
    times: tuple[time, ...] = (time(8, 0),),
    days_of_week: list[int] | None = None,
    interval_days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    treatment_start: date | None = None,
    treatment_end: date | None = None,
) -> dict:
    """Usuario + medicamento + tratamiento + vínculo + horario.

    Las fechas por defecto son el día de T0, para que los
    instantes de las pruebas sean deterministas.
    """
    start = start_date or T0.date()
    t_start = treatment_start or T0.date()
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Top-up",
            email=_unique_email(),
            password_hash="x" * 60,
            timezone=timezone,
        )
        s.add(user)
        await s.flush()
        med = Medication(user_id=user.id, name="Paracetamol")
        s.add(med)
        await s.flush()
        treatment = Treatment(
            user_id=user.id,
            title="Prueba",
            start_date=t_start,
            end_date=treatment_end,
            status=treatment_status,
        )
        s.add(treatment)
        await s.flush()
        link = TreatmentMedication(
            user_id=user.id,
            treatment_id=treatment.id,
            medication_id=med.id,
            dose_amount=Decimal("500"),
            dose_unit="mg",
            is_active=link_active,
        )
        s.add(link)
        await s.flush()
        schedule = MedicationSchedule(
            user_id=user.id,
            treatment_medication_id=link.id,
            frequency=frequency,
            days_of_week=days_of_week,
            interval_days=interval_days,
            times=list(times),
            start_date=start,
            end_date=end_date,
            is_active=schedule_active,
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


async def _reminder_rows(test_engine, user_id: int) -> list[tuple]:
    """(scheduled_at, status) de los recordatorios, en orden."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        result = await s.execute(
            select(MedicationReminder.scheduled_at, MedicationReminder.status)
            .where(MedicationReminder.user_id == user_id)
            .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
        )
        return list(result.all())


async def _set_user_timezone(test_engine, user_id: int, timezone: str) -> None:
    """Cambia la zona horaria de un usuario (sin validación)."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = await s.get(User, user_id)
        assert user is not None
        user.timezone = timezone
        await s.commit()


# ------------------------------------------------------------------
# Generación y ventana
# ------------------------------------------------------------------


async def test_topup_creates_72h_window(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    result = await run_topup(session_factory, now=T0)
    assert result.schedules_checked == 1
    assert result.reminders_created == 3
    assert result.skipped == 0
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert [r[0] for r in rows] == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
    ]
    assert {r[1] for r in rows} == {"PENDIENTE"}
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_idempotent(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    first = await run_topup(session_factory, now=T0)
    assert first.reminders_created == 3
    second = await run_topup(session_factory, now=T0)
    assert second.schedules_checked == 1
    assert second.reminders_created == 0
    assert second.skipped == 0
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert len(rows) == 3
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_advance_24h(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    await run_topup(session_factory, now=T0)
    result = await run_topup(session_factory, now=T0 + timedelta(hours=24))
    assert result.reminders_created == 1
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert [r[0] for r in rows] == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 24, 13, 0, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_advance_72h(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine)
    await run_topup(session_factory, now=T0)
    result = await run_topup(session_factory, now=T0 + timedelta(hours=72))
    assert result.reminders_created == 3
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert len(rows) == 6
    assert [r[0] for r in rows][3:] == [
        datetime(2026, 11, 24, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc),
    ]
    # Las filas viejas siguen ahí (el top-up no borra nada).
    assert [r[1] for r in rows] == ["PENDIENTE"] * 6
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_skips_non_active_treatments(
    test_engine, session_factory
) -> None:
    chains = [
        await _seed_chain(test_engine, treatment_status=status)
        for status in ("PAUSADO", "CANCELADO", "COMPLETADO")
    ]
    result = await run_topup(session_factory, now=T0)
    assert result.schedules_checked == 0
    assert result.reminders_created == 0
    for chain in chains:
        assert await _reminder_rows(test_engine, chain["user_id"]) == []
        await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_skips_inactive_link_or_schedule(
    test_engine, session_factory
) -> None:
    chain_link = await _seed_chain(test_engine, link_active=False)
    chain_sched = await _seed_chain(test_engine, schedule_active=False)
    result = await run_topup(session_factory, now=T0)
    assert result.schedules_checked == 0
    assert result.reminders_created == 0
    for chain in (chain_link, chain_sched):
        assert await _reminder_rows(test_engine, chain["user_id"]) == []
        await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_respects_end_dates(test_engine, session_factory) -> None:
    chain_treatment = await _seed_chain(
        test_engine, treatment_end=date(2026, 11, 22)
    )
    chain_schedule = await _seed_chain(
        test_engine, end_date=date(2026, 11, 21)
    )
    await run_topup(session_factory, now=T0)
    rows_treatment = await _reminder_rows(test_engine, chain_treatment["user_id"])
    assert [r[0] for r in rows_treatment] == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc),
    ]
    rows_schedule = await _reminder_rows(test_engine, chain_schedule["user_id"])
    assert [r[0] for r in rows_schedule] == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain_treatment["user_id"])
    await _cleanup_user(test_engine, chain_schedule["user_id"])


async def test_topup_future_start_date(test_engine, session_factory) -> None:
    chain = await _seed_chain(test_engine, start_date=date(2026, 11, 25))
    result = await run_topup(session_factory, now=T0)
    assert result.schedules_checked == 1
    assert result.reminders_created == 0
    # Cuando la fecha entra en la ventana, aparecen solos.
    result = await run_topup(session_factory, now=T0 + timedelta(hours=72))
    assert result.reminders_created == 2
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert [r[0] for r in rows] == [
        datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain["user_id"])


# ------------------------------------------------------------------
# Zonas horarias y DST
# ------------------------------------------------------------------


async def test_topup_dst_spring_forward(test_engine, session_factory) -> None:
    """Salto adelante (EE. UU., 8 de marzo de 2026): 02:30 no existe.

    `_wall_to_utc` desplaza la hora inexistente sumando el salto
    (02:30 + 1 h = 03:30 EDT = 07:30 UTC), no a la primera hora
    válida (03:00 EDT = 07:00 UTC) como dice su docstring: es un
    comportamiento heredado de la Fase 4, no del top-up. La fila
    no se pierde ni se duplica (una por día, en el día correcto);
    la corrección a 03:00 queda como limitación conocida para una
    etapa posterior (ver informe de cierre).
    """
    now = datetime(2026, 3, 7, 6, 0, tzinfo=timezone.utc)
    chain = await _seed_chain(
        test_engine,
        timezone=NEW_YORK,
        times=(time(2, 30),),
        start_date=date(2026, 3, 7),
        treatment_start=date(2026, 3, 7),
    )
    result = await run_topup(session_factory, now=now)
    assert result.reminders_created == 3
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert [r[0] for r in rows] == [
        datetime(2026, 3, 7, 7, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 9, 6, 30, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_dst_fall_back(test_engine, session_factory) -> None:
    """Salto atrás (EE. UU., 1 de noviembre de 2026): 01:30 es ambigua.

    Se toma la primera ocurrencia (fold=0, EDT): una sola fila,
    sin duplicar el hueco.
    """
    now = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
    chain = await _seed_chain(
        test_engine,
        timezone=NEW_YORK,
        times=(time(1, 30),),
        start_date=date(2026, 10, 31),
        treatment_start=date(2026, 10, 31),
    )
    result = await run_topup(session_factory, now=now)
    assert result.reminders_created == 3
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert [r[0] for r in rows] == [
        datetime(2026, 10, 31, 5, 30, tzinfo=timezone.utc),
        datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc),
        datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_interval_and_weekdays(test_engine, session_factory) -> None:
    chain_interval = await _seed_chain(
        test_engine, frequency="INTERVALO_DIAS", interval_days=2
    )
    # 21 de noviembre de 2026 es sábado; [0, 2] = lunes y miércoles.
    chain_week = await _seed_chain(
        test_engine, frequency="DIAS_SEMANA", days_of_week=[0, 2]
    )
    await run_topup(session_factory, now=T0)
    rows_interval = await _reminder_rows(test_engine, chain_interval["user_id"])
    assert [r[0] for r in rows_interval] == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
    ]
    rows_week = await _reminder_rows(test_engine, chain_week["user_id"])
    assert [r[0] for r in rows_week] == [
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain_interval["user_id"])
    await _cleanup_user(test_engine, chain_week["user_id"])


async def test_topup_multiuser_timezones(test_engine, session_factory) -> None:
    """Misma hora de pared, instantes UTC distintos por zona.

    Julio: Nueva York está en EDT (UTC-4) y Bogotá en UTC-5.
    """
    now = datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc)
    chain_bogota = await _seed_chain(
        test_engine,
        timezone=BOGOTA,
        start_date=date(2026, 7, 1),
        treatment_start=date(2026, 7, 1),
    )
    chain_ny = await _seed_chain(
        test_engine,
        timezone=NEW_YORK,
        start_date=date(2026, 7, 1),
        treatment_start=date(2026, 7, 1),
    )
    await run_topup(session_factory, now=now)
    rows_bogota = await _reminder_rows(test_engine, chain_bogota["user_id"])
    rows_ny = await _reminder_rows(test_engine, chain_ny["user_id"])
    assert [r[0] for r in rows_bogota] == [
        datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 3, 13, 0, tzinfo=timezone.utc),
    ]
    assert [r[0] for r in rows_ny] == [
        datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain_bogota["user_id"])
    await _cleanup_user(test_engine, chain_ny["user_id"])


# ------------------------------------------------------------------
# Aislamiento de errores y estados existentes
# ------------------------------------------------------------------


async def test_topup_skips_invalid_timezone_without_aborting(
    test_engine, session_factory
) -> None:
    """Una zona inválida salta su horario; los demás siguen.

    El registro no acepta zonas inválidas (el esquema de auth las
    valida con ZoneInfo), pero el top-up no debe tumbarse si una
    llega por otra vía (dato viejo, edición directa en BD).
    """
    chain_bad = await _seed_chain(test_engine)
    await _set_user_timezone(test_engine, chain_bad["user_id"], "No/Existe")
    chain_ok = await _seed_chain(test_engine)
    result = await run_topup(session_factory, now=T0)
    assert result.schedules_checked == 2
    assert result.reminders_created == 3
    assert result.skipped == 1
    assert result.errors == (f"schedule_id={chain_bad['schedule_id']}",)
    assert await _reminder_rows(test_engine, chain_bad["user_id"]) == []
    assert len(await _reminder_rows(test_engine, chain_ok["user_id"])) == 3
    await _cleanup_user(test_engine, chain_bad["user_id"])
    await _cleanup_user(test_engine, chain_ok["user_id"])


async def test_topup_recreates_cancelled_slots_without_touching_history(
    test_engine, session_factory
) -> None:
    """Un hueco CANCELADA admite un PENDIENTE nuevo (decisión B)."""
    chain = await _seed_chain(test_engine)
    await run_topup(session_factory, now=T0)
    # Cancelar los 3 PENDIENTE futuros (como al pausar).
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        await reminder_repository.cancel_pending_for_treatment(
            s, chain["treatment_id"], T0
        )
        await s.commit()
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert len(rows) == 3 and {r[1] for r in rows} == {"CANCELADA"}
    result = await run_topup(session_factory, now=T0 + timedelta(hours=1))
    assert result.reminders_created == 3
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert len(rows) == 6
    # Ordenadas por (scheduled_at, id): en cada instante, primero
    # la CANCELADA (id menor) y luego la PENDIENTE nueva.
    assert sorted(r[1] for r in rows) == ["CANCELADA"] * 3 + ["PENDIENTE"] * 3
    assert sorted(r[0] for r in rows if r[1] == "CANCELADA") == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
    ]
    assert sorted(r[0] for r in rows if r[1] == "PENDIENTE") == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
    ]
    await _cleanup_user(test_engine, chain["user_id"])


async def test_topup_leaves_existing_states_intact(
    test_engine, session_factory
) -> None:
    """ENVIADA, TOMADA, POSPUESTA, PERDIDA, CANCELADA y FALLIDA no cambian."""
    chain = await _seed_chain(test_engine)
    await run_topup(session_factory, now=T0)
    other = [
        {"scheduled_at": datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc), "status": "ENVIADA"},
        {"scheduled_at": datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc), "status": "TOMADA"},
        {"scheduled_at": datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc), "status": "POSPUESTA"},
        {"scheduled_at": datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc), "status": "PERDIDA"},
        {"scheduled_at": datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc), "status": "CANCELADA"},
        {"scheduled_at": datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc), "status": "FALLIDA"},
    ]
    await _seed_rows(test_engine, chain, other)
    result = await run_topup(session_factory, now=T0)
    assert result.reminders_created == 0
    rows = await _reminder_rows(test_engine, chain["user_id"])
    assert len(rows) == 9
    by_status = {}
    for scheduled_at, status in rows:
        by_status.setdefault(status, []).append(scheduled_at)
    assert by_status["PENDIENTE"] == [
        datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc),
    ]
    assert by_status["ENVIADA"] == [datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)]
    assert by_status["TOMADA"] == [datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)]
    assert by_status["POSPUESTA"] == [datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)]
    assert by_status["PERDIDA"] == [datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)]
    assert by_status["CANCELADA"] == [datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)]
    assert by_status["FALLIDA"] == [datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)]
    await _cleanup_user(test_engine, chain["user_id"])


# ------------------------------------------------------------------
# Enumeración
# ------------------------------------------------------------------


async def test_list_active_for_topup_returns_only_active(
    test_engine, session_factory
) -> None:
    chain_ok = await _seed_chain(test_engine)
    chain_paused = await _seed_chain(test_engine, treatment_status="PAUSADO")
    chain_inactive = await _seed_chain(test_engine, schedule_active=False)
    async with session_factory() as s:
        ids = await schedule_repository.list_active_for_topup(s)
    # Pertenencia, no igualdad exacta: la enumeración es global y
    # otras pruebas del módulo pueden tener cadenas activas.
    assert chain_ok["schedule_id"] in ids
    assert chain_paused["schedule_id"] not in ids
    assert chain_inactive["schedule_id"] not in ids
    await _cleanup_user(test_engine, chain_ok["user_id"])
    await _cleanup_user(test_engine, chain_paused["user_id"])
    await _cleanup_user(test_engine, chain_inactive["user_id"])
