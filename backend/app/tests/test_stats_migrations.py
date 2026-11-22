"""Pruebas de migración de D-11 (Fase 7, Etapa 2, commit 5).

S-29, S-30, S-78, S-79, S-80 y S-88. Estas seis pruebas NO usan el
fixture habitual (que crea la base ya migrada hasta la cabeza), porque
necesitan controlar la versión del esquema. En su lugar usan una base
PostgreSQL aislada (`dosisalerta_test_migrations`):

1. Se crea la base vacía y se migra con Alembic hasta `fc387ec4f3db`
   (la cabeza anterior a D-11, sin la columna `cancel_reason`).
2. Se siembran los datos que representan el estado anterior a la
   migración (2 `CANCELADA` + 1 `TOMADA` con su toma, vía SQL directo
   para los recordatorios porque el modelo ORM ya incluye la columna
   que aún no existe).
3. Se ejecuta `alembic upgrade head` para aplicar la migración nueva.
4. Se verifica el resultado.

Garantías de aislamiento y limpieza (plan §8, obligatorias):
1. La base no debe existir antes de crearla. Si ya existe, la prueba
   se detiene con un error explícito; no se reutiliza ni se elimina.
2. La conexión nunca apunta a otra base. Se verifica explícitamente
   que la cadena apunta a la base aislada y nunca a `dosisalerta` ni
   a `dosisalerta_test`.
3. Solo se elimina lo que el propio módulo creó (la base aislada de
   esta ejecución).
4. Ante un fallo, se detiene el procedimiento y se reporta; nunca se
   eliminan otras bases ni se hacen limpiezas indiscriminadas.
5. La limpieza final actúa solo sobre la base aislada creada por el
   propio módulo en esa ejecución.
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
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.security import hash_password
from app.database import get_session
from app.main import create_app
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.users import User
from app.repositories import reminder_repository

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATION_DB = "dosisalerta_test_migrations"
PRE_D11 = "fc387ec4f3db"
BOGOTA = "America/Bogota"
PASSWORD = "Prueba1234"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local(day: date, hour: int = 8, minute: int = 0) -> datetime:
    """Un instante UTC que es `hour:minute` en Bogotá el día `day`."""
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(BOGOTA)).astimezone(
        timezone.utc
    )


def _migration_url() -> str:
    """URL de la base aislada; falla si la URL base no es la esperada."""
    url = get_settings().database_url
    assert url.endswith("/dosisalerta"), f"URL inesperada: {url.rsplit('@', 1)[-1]}"
    return url[: -len("dosisalerta")] + MIGRATION_DB


async def _db_exists(name: str) -> bool:
    """True si la base `name` existe en el servidor PostgreSQL."""
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        row = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", name
        )
        return row is not None
    finally:
        await conn.close()


async def _create_migration_db() -> None:
    """Crea la base aislada. Garantía 1: falla si ya existe."""
    if await _db_exists(MIGRATION_DB):
        raise RuntimeError(
            f"la base aislada {MIGRATION_DB} ya existe; no se reutiliza "
            "ni se elimina (garantía 1 del plan §8)"
        )
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await conn.execute(f'CREATE DATABASE "{MIGRATION_DB}"')
    finally:
        await conn.close()


async def _drop_migration_db() -> None:
    """Elimina SOLO la base aislada creada por este módulo."""
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
    finally:
        await conn.close()


def _alembic_cfg(url: str) -> Config:
    os.environ["ALEMBIC_DATABASE_URL"] = url
    return Config(str(BACKEND_DIR / "alembic.ini"))


async def _seed_pre_migration(engine) -> dict:
    """Siembra el estado anterior a la migración D-11.

    Un usuario con su cadena y 3 recordatorios el 2026-11-10 (2
    CANCELADA + 1 TOMADA con su toma). Los recordatorios se insertan
    con SQL directo porque el modelo ORM ya incluye `cancel_reason`,
    columna que aún no existe en esta revisión del esquema.
    """
    day = date(2026, 11, 10)
    email = f"migracion-{uuid.uuid4().hex[:12]}@example.com"
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        user = User(
            name="Migracion Fase 7",
            email=email,
            password_hash=hash_password(PASSWORD),
            timezone=BOGOTA,
        )
        sess.add(user)
        await sess.flush()
        med = Medication(user_id=user.id, name="Paracetamol")
        sess.add(med)
        await sess.flush()
        treatment = Treatment(user_id=user.id, title="Prueba", start_date=day)
        sess.add(treatment)
        await sess.flush()
        link = TreatmentMedication(
            user_id=user.id,
            treatment_id=treatment.id,
            medication_id=med.id,
            dose_amount=Decimal("500"),
            dose_unit="mg",
        )
        sess.add(link)
        await sess.flush()
        schedule = MedicationSchedule(
            user_id=user.id,
            treatment_medication_id=link.id,
            frequency="DIARIO",
            times=[time(8, 0)],
            start_date=day,
        )
        sess.add(schedule)
        await sess.flush()
        # Recordatorios pre-migración (sin cancel_reason en el esquema).
        stmt = text(
            "INSERT INTO medication_reminders "
            "(schedule_id, treatment_medication_id, user_id, scheduled_at, "
            "status, parent_reminder_id, postponed_count, version, "
            "current_attempt_id, claimed_at, next_attempt_at, attempt_count) "
            "VALUES (:schedule_id, :link_id, :user_id, :scheduled_at, "
            ":status, NULL, 0, 1, NULL, NULL, NULL, 0) "
            "RETURNING id"
        )
        taken_id = None
        for hour, status in ((8, "CANCELADA"), (9, "CANCELADA"), (10, "TOMADA")):
            row = (
                await sess.execute(
                    stmt,
                    {
                        "schedule_id": schedule.id,
                        "link_id": link.id,
                        "user_id": user.id,
                        "scheduled_at": _local(day, hour),
                        "status": status,
                    },
                )
            ).first()
            if status == "TOMADA":
                taken_id = row[0]
        # La toma de la TOMADA (la tabla medication_intakes no cambia).
        sess.add(
            MedicationIntake(
                reminder_id=taken_id,
                user_id=user.id,
                taken_at=_local(day, 10, 5),
                source="WEB",
            )
        )
        await sess.commit()
    return {
        "user_id": user.id,
        "email": email,
        "schedule_id": schedule.id,
        "link_id": link.id,
        "treatment_id": treatment.id,
        "medication_id": med.id,
    }


@pytest.fixture(scope="session")
def _migration_setup():
    """Crea la base aislada, migra, siembra y aplica la migración D-11."""
    import asyncio

    url = _migration_url()
    # Garantía 2: la URL apunta a la base aislada, nunca a otra.
    assert url.endswith("/" + MIGRATION_DB), f"URL inesperada: {url}"
    assert "dosisalerta_test" not in url.replace(MIGRATION_DB, ""), url
    created = False
    asyncio.run(_create_migration_db())
    created = True
    try:
        cfg = _alembic_cfg(url)
        command.upgrade(cfg, PRE_D11)
        engine = create_async_engine(url, poolclass=NullPool)
        seed = asyncio.run(_seed_pre_migration(engine))
        command.upgrade(cfg, "head")
        yield {"engine": engine, "url": url, "seed": seed}
    finally:
        # Garantía 5: la limpieza actúa solo sobre la base aislada.
        if created:
            asyncio.run(_drop_migration_db())
        os.environ.pop("ALEMBIC_DATABASE_URL", None)


@pytest.fixture(scope="session")
def test_engine(_migration_setup):
    return _migration_setup["engine"]


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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login_ok(client, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _seed_chain(session, user_id: int) -> dict:
    """Una cadena nueva (medicamento, tratamiento, vínculo, horario)."""
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


async def _seed_reminder(session, chain: dict, when: datetime, status: str, **kw) -> int:
    row = MedicationReminder(
        schedule_id=chain["schedule_id"],
        treatment_medication_id=chain["link_id"],
        user_id=chain["user_id"],
        scheduled_at=when,
        status=status,
        **kw,
    )
    session.add(row)
    await session.commit()
    return row.id


async def _cancel_reason_of(session, reminder_id: int) -> str | None:
    row = (
        await session.execute(
            select(MedicationReminder.cancel_reason).where(
                MedicationReminder.id == reminder_id
            )
        )
    ).scalar_one()
    return row


# ------------------------------------------------------------------
# S-29: migración sin backfill (D-11)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s29_migration_without_backfill(client, session, _migration_setup) -> None:
    """S-29: las filas anteriores a la migración quedan con NULL.

    Las 2 CANCELADA sembradas antes de la migración no reciben un
    motivo inventado; `cancelled_by_reason.unknown` las cuenta y el
    porcentaje las incluye en el denominador (Alt 3, aprobada).
    """
    seed = _migration_setup["seed"]
    token = await _login_ok(client, seed["email"])
    h = _headers(token)
    # 1 CANCELADA nueva con motivo (después de la migración).
    await _seed_reminder(
        session,
        seed,
        _local(date(2026, 11, 10), 11),
        "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    response = await client.get(
        "/api/v1/stats/compliance",
        headers=h,
        params={"from": "2026-11-10", "to": "2026-11-11"},
    )
    assert response.status_code == 200, response.text
    s = response.json()["summary"]
    assert s["scheduled"] == 4
    assert s["taken_on_time"] == 1
    assert s["cancelled"] == 3
    assert s["cancelled_by_reason"]["treatment_cancelled"] == 1
    assert s["cancelled_by_reason"]["unknown"] == 2
    assert s["cancelled_by_reason"]["treatment_paused"] == 0
    assert s["cancelled_by_reason"]["treatment_completed"] == 0
    assert s["cancelled_by_reason"]["medication_deactivated"] == 0
    assert s["cancelled_by_reason"]["link_removed"] == 0
    assert sum(s["cancelled_by_reason"].values()) == s["cancelled"]
    # Denominador 4 − 3 + 2 = 3 → 1/3 = 33.3 %.
    assert s["compliance_percentage"] == 33.3


# ------------------------------------------------------------------
# S-30: CHECK de coherencia estado-motivo (D-11)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s30_check_status_reason_coherence(session, _migration_setup) -> None:
    """S-30: un motivo en una fila que no está en CANCELADA se rechaza.

    El CHECK de coherencia rechaza escribir un motivo en una PENDIENTE;
    una CANCELADA con NULL se acepta (filas históricas).
    """
    seed = _migration_setup["seed"]
    chain = await _seed_chain(session, seed["user_id"])
    now = _utcnow()
    pending_id = await _seed_reminder(session, chain, now + timedelta(hours=1), "PENDIENTE")
    # Motivo en una PENDIENTE → IntegrityError (CHECK).
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE medication_reminders SET cancel_reason = "
                    "'TREATMENT_CANCELLED' WHERE id = :rid"
                ),
                {"rid": pending_id},
            )
            await session.flush()
    assert await _cancel_reason_of(session, pending_id) is None
    # CANCELADA con NULL → aceptada (filas históricas).
    cancelled_id = await _seed_reminder(
        session, chain, now + timedelta(hours=2), "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    assert await _cancel_reason_of(session, cancelled_id) == "TREATMENT_CANCELLED"


# ------------------------------------------------------------------
# S-78: trigger de integridad (D-11)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s78_trigger_integrity(session, _migration_setup) -> None:
    """S-78: el trigger rechaza cancelaciones nuevas sin motivo.

    (a) UPDATE a CANCELADA sin motivo → rechazado. (b) Borrar el motivo
    de una CANCELADA que lo tenía → rechazado. (c) Tocar una CANCELADA
    histórica con NULL (p. ej. updated_at) → aceptado. (d) La
    cancelación normal vía `cancel_pending_for_*` con motivo → pasa.
    """
    seed = _migration_setup["seed"]
    chain = await _seed_chain(session, seed["user_id"])
    now = _utcnow()
    # (a) UPDATE a CANCELADA sin motivo.
    pending_id = await _seed_reminder(session, chain, now + timedelta(hours=1), "PENDIENTE")
    with pytest.raises(Exception):
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE medication_reminders SET status = 'CANCELADA' "
                    "WHERE id = :rid"
                ),
                {"rid": pending_id},
            )
            await session.flush()
    # (b) Borrar el motivo de una CANCELADA que lo tenía.
    with_reason_id = await _seed_reminder(
        session, chain, now + timedelta(hours=2), "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    with pytest.raises(Exception):
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE medication_reminders SET cancel_reason = NULL "
                    "WHERE id = :rid"
                ),
                {"rid": with_reason_id},
            )
            await session.flush()
    assert (
        await _cancel_reason_of(session, with_reason_id) == "TREATMENT_CANCELLED"
    )
    # (c) Tocar una CANCELADA histórica con NULL (sin cambiar el motivo).
    historical_id = await _seed_unknown(session, chain, now + timedelta(hours=3))
    await session.execute(
        text(
            "UPDATE medication_reminders SET postponed_count = 1 "
            "WHERE id = :rid"
        ),
        {"rid": historical_id},
    )
    await session.commit()
    assert await _cancel_reason_of(session, historical_id) is None
    # (d) Cancelación normal vía la función con motivo.
    future_id = await _seed_reminder(session, chain, now + timedelta(hours=4), "PENDIENTE")
    await reminder_repository.cancel_pending_for_treatment(
        session, chain["treatment_id"], now, "TREATMENT_PAUSED"
    )
    row = (
        await session.execute(
            select(MedicationReminder).where(MedicationReminder.id == future_id)
        )
    ).scalar_one()
    assert row.status == "CANCELADA"
    assert row.cancel_reason == "TREATMENT_PAUSED"


async def _seed_unknown(session, chain: dict, when: datetime) -> int:
    """Siembra una CANCELADA con NULL desactivando el trigger (S-71)."""
    await session.execute(text("ALTER TABLE medication_reminders DISABLE TRIGGER trg_reminders_cancel_reason"))
    try:
        rid = await _seed_reminder(session, chain, when, "CANCELADA", cancel_reason=None)
    finally:
        await session.execute(text("ALTER TABLE medication_reminders ENABLE TRIGGER trg_reminders_cancel_reason"))
    await session.commit()
    return rid


# ------------------------------------------------------------------
# S-79: CHECK de dominio del motivo (D-11)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s79_check_reason_domain(session, _migration_setup) -> None:
    """S-79: el motivo debe ser NULL o uno de los cinco válidos.

    Escribir `TREATMENT_CANCELLED` en una CANCELADA → aceptado;
    escribir `MOTIVO_INVALIDO` → IntegrityError (CHECK de dominio);
    NULL sigue aceptado (filas históricas).
    """
    seed = _migration_setup["seed"]
    chain = await _seed_chain(session, seed["user_id"])
    now = _utcnow()
    ok_id = await _seed_reminder(
        session, chain, now + timedelta(hours=1), "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    assert await _cancel_reason_of(session, ok_id) == "TREATMENT_CANCELLED"
    bad_id = await _seed_reminder(
        session, chain, now + timedelta(hours=2), "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE medication_reminders SET cancel_reason = "
                    "'MOTIVO_INVALIDO' WHERE id = :rid"
                ),
                {"rid": bad_id},
            )
            await session.flush()
    assert await _cancel_reason_of(session, bad_id) == "TREATMENT_CANCELLED"
    null_id = await _seed_unknown(session, chain, now + timedelta(hours=3))
    assert await _cancel_reason_of(session, null_id) is None


# ------------------------------------------------------------------
# S-80: trigger — INSERT con CANCELADA sin motivo (D-11)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s80_trigger_insert_cancelled_without_reason(session, _migration_setup) -> None:
    """S-80: un INSERT de CANCELADA sin motivo es rechazado por el trigger.

    Insertar la fila con `cancel_reason=NULL` → rechazado; insertarla
    con `cancel_reason='TREATMENT_CANCELLED'` → aceptado.
    """
    seed = _migration_setup["seed"]
    chain = await _seed_chain(session, seed["user_id"])
    now = _utcnow()
    with pytest.raises(Exception):
        async with session.begin_nested():
            session.add(
                MedicationReminder(
                    schedule_id=chain["schedule_id"],
                    treatment_medication_id=chain["link_id"],
                    user_id=chain["user_id"],
                    scheduled_at=now + timedelta(hours=1),
                    status="CANCELADA",
                    cancel_reason=None,
                )
            )
            await session.flush()
    ok_id = await _seed_reminder(
        session, chain, now + timedelta(hours=2), "CANCELADA",
        cancel_reason="TREATMENT_CANCELLED",
    )
    assert await _cancel_reason_of(session, ok_id) == "TREATMENT_CANCELLED"


# ------------------------------------------------------------------
# S-88: downgrade de la migración (D-11)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s88_migration_downgrade(_migration_setup) -> None:
    """S-88: el downgrade quita la columna, los CHECK, la función y el trigger.

    Se siembra 1 CANCELADA con motivo válido, se aplica el downgrade y
    se verifica en `information_schema` que todo desapareció y que la
    fila CANCELADA sobrevive (sin motivo). Al final se vuelve a subir
    a la cabeza para dejar la base como estaba.

    No usa la fixture `session` (cuya transacción abierta bloquearía
    el DDL del downgrade); siembra y verifica con sesiones propias
    que se cierran antes de cada paso DDL.
    """
    seed = _migration_setup["seed"]
    url = _migration_setup["url"]
    engine = _migration_setup["engine"]
    now = _utcnow()
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        chain = await _seed_chain(sess, seed["user_id"])
        cancelled_id = await _seed_reminder(
            sess, chain, now + timedelta(hours=1), "CANCELADA",
            cancel_reason="TREATMENT_CANCELLED",
        )

    cfg = _alembic_cfg(url)
    # Alembic corre las migraciones con `asyncio.run()`; dentro de una
    # prueba async ya hay un bucle corriendo, así que el downgrade y el
    # upgrade van en un hilo aparte (sin bucle en ese hilo).
    await asyncio.to_thread(command.downgrade, cfg, PRE_D11)

    async with AsyncSession(engine, expire_on_commit=False) as check:
        col = await check.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE "
                "table_name = 'medication_reminders' AND "
                "column_name = 'cancel_reason'"
            )
        )
        assert col.scalar() is None, "la columna cancel_reason sigue existiendo"
        checks = await check.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name = 'medication_reminders' AND "
                "constraint_type = 'CHECK' AND "
                "constraint_name LIKE '%cancel_reason%'"
            )
        )
        assert checks.scalars().all() == [], "quedan CHECK de cancel_reason"
        fn = await check.execute(
            text(
                "SELECT 1 FROM information_schema.routines WHERE "
                "routine_name = 'fn_reminders_require_cancel_reason'"
            )
        )
        assert fn.scalar() is None, "la función del trigger sigue existiendo"
        trig = await check.execute(
            text(
                "SELECT 1 FROM information_schema.triggers WHERE "
                "trigger_name = 'trg_reminders_cancel_reason'"
            )
        )
        assert trig.scalar() is None, "el trigger sigue existiendo"
        row = (
            await check.execute(
                select(MedicationReminder.status).where(
                    MedicationReminder.id == cancelled_id
                )
            )
        ).scalar_one()
        assert row == "CANCELADA", "la fila CANCELADA no sobrevivió al downgrade"

    # Volver a la cabeza para dejar la base como estaba.
    await asyncio.to_thread(command.upgrade, cfg, "head")
