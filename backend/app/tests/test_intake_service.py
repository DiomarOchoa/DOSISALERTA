"""Pruebas de IntakeService: confirmar y posponer (Fase 5, Etapa 4).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3 y la Etapa 2. La base de desarrollo (`dosisalerta`)
no recibe filas de prueba: la siembra se hace con sesiones que
confirman (para que las sesiones propias del servicio, en
conexiones distintas, vean las filas) y cada prueba borra sus
filas al final (por usuario unico).

Criterios que se verifican (aceptacion de la Etapa 4):
- Confirmar crea una toma y marca TOMADA, en una transaccion.
- Confirmar dos veces (secuencial y simultaneo) crea una sola toma.
- Posponer crea el hijo y marca POSPUESTA el original, en una transaccion.
- El cuidador recibe 403 con auditoria ACCESS_DENIED; el extrano 403 sin ella.
- Transiciones validas e invalidas (409) por estado.
- Colision con el indice unico al crear el hijo -> 409 sin cambios.
- Aislamiento entre usuarios.
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
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models.caregivers import CaregiverAuditLog, CaregiverLink
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.users import User
from app.services import intake_service

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
    """Fabrica de sesiones del servicio, contra la base de pruebas."""

    def _factory():
        return AsyncSession(test_engine, expire_on_commit=False)

    return _factory


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "intake") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_user(test_engine, prefix: str = "intake") -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Intake",
            email=_unique_email(prefix),
            password_hash="x" * 60,
            timezone=BOGOTA,
        )
        s.add(user)
        await s.flush()
        await s.commit()
        return user.id


async def _seed_chain(test_engine, user_id: int) -> dict:
    """Medicamento + tratamiento + vinculo + horario de un usuario."""
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        med = Medication(user_id=user_id, name="Paracetamol")
        s.add(med)
        await s.flush()
        treatment = Treatment(
            user_id=user_id, title="Prueba", start_date=date.today()
        )
        s.add(treatment)
        await s.flush()
        link = TreatmentMedication(
            user_id=user_id,
            treatment_id=treatment.id,
            medication_id=med.id,
            dose_amount=Decimal("500"),
            dose_unit="mg",
        )
        s.add(link)
        await s.flush()
        schedule = MedicationSchedule(
            user_id=user_id,
            treatment_medication_id=link.id,
            frequency="DIARIO",
            times=[time(8, 0)],
            start_date=date.today(),
        )
        s.add(schedule)
        await s.flush()
        await s.commit()
        return {
            "user_id": user_id,
            "schedule_id": schedule.id,
            "link_id": link.id,
        }


async def _seed_caregiver_link(
    test_engine, *, patient_id: int, caregiver_id: int, status: str = "ACTIVO"
) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        s.add(
            CaregiverLink(
                patient_user_id=patient_id,
                caregiver_user_id=caregiver_id,
                status=status,
                invited_by=patient_id,
                # El CHECK de ACTIVO exige accepted_at no nulo.
                accepted_at=_utcnow() if status == "ACTIVO" else None,
            )
        )
        await s.commit()


async def _seed_reminder(
    test_engine,
    chain: dict,
    when: datetime,
    status: str,
    *,
    parent_id: int | None = None,
    postponed_count: int = 0,
    cancel_reason: str | None = None,
) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = MedicationReminder(
            schedule_id=chain["schedule_id"],
            treatment_medication_id=chain["link_id"],
            user_id=chain["user_id"],
            scheduled_at=when,
            status=status,
            cancel_reason=cancel_reason,
            parent_reminder_id=parent_id,
            postponed_count=postponed_count,
        )
        s.add(row)
        await s.flush()
        await s.commit()
        return row.id


async def _cleanup_user(test_engine, user_id: int) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        await s.execute(
            delete(MedicationIntake).where(MedicationIntake.user_id == user_id)
        )
        await s.execute(
            delete(CaregiverAuditLog).where(
                CaregiverAuditLog.patient_user_id == user_id
            )
        )
        await s.execute(
            delete(CaregiverAuditLog).where(
                CaregiverAuditLog.caregiver_user_id == user_id
            )
        )
        await s.execute(
            delete(CaregiverLink).where(
                CaregiverLink.patient_user_id == user_id
            )
        )
        await s.execute(
            delete(CaregiverLink).where(
                CaregiverLink.caregiver_user_id == user_id
            )
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
        await s.execute(delete(User).where(User.id == user_id))
        await s.commit()


async def _actor(session_factory, user_id: int) -> User:
    async with session_factory() as s:
        user = await s.get(User, user_id)
        assert user is not None
        return user


async def _reminder_row(test_engine, reminder_id: int) -> dict | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(
                MedicationReminder.status,
                MedicationReminder.parent_reminder_id,
                MedicationReminder.postponed_count,
                MedicationReminder.scheduled_at,
                MedicationReminder.version,
            ).where(MedicationReminder.id == reminder_id)
        )
        found = row.one_or_none()
        if found is None:
            return None
        return {
            "status": found[0],
            "parent_reminder_id": found[1],
            "postponed_count": found[2],
            "scheduled_at": found[3],
            "version": found[4],
        }


async def _intake_count(test_engine, reminder_id: int) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(func.count())
            .select_from(MedicationIntake)
            .where(MedicationIntake.reminder_id == reminder_id)
        )
        return row.scalar_one()


async def _children_count(test_engine, parent_id: int) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(func.count())
            .select_from(MedicationReminder)
            .where(MedicationReminder.parent_reminder_id == parent_id)
        )
        return row.scalar_one()


async def _audit_denied_count(
    test_engine, *, caregiver_id: int, patient_id: int
) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(func.count())
            .select_from(CaregiverAuditLog)
            .where(
                CaregiverAuditLog.caregiver_user_id == caregiver_id,
                CaregiverAuditLog.patient_user_id == patient_id,
                CaregiverAuditLog.action == "ACCESS_DENIED",
                CaregiverAuditLog.result == "DENEGADO",
            )
        )
        return row.scalar_one()


@pytest_asyncio.fixture
async def _setup(test_engine):
    """Usuario A (paciente) con cadena; B (cuidador) y C (extrano)."""
    user_a = await _seed_user(test_engine, "intake-a")
    user_b = await _seed_user(test_engine, "intake-b")
    user_c = await _seed_user(test_engine, "intake-c")
    chain = await _seed_chain(test_engine, user_a)
    await _seed_caregiver_link(
        test_engine, patient_id=user_a, caregiver_id=user_b
    )
    setup = {
        "user_a": user_a,
        "user_b": user_b,
        "user_c": user_c,
        "chain": chain,
    }
    try:
        yield setup
    finally:
        for user_id in (user_a, user_b, user_c):
            await _cleanup_user(test_engine, user_id)


# ------------------------------------------------------------------
# Confirmar
# ------------------------------------------------------------------


async def test_confirm_pending_creates_intake(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    actor = await _actor(session_factory, _setup["user_a"])
    before = _utcnow()
    async with session_factory() as s:
        response = await intake_service.confirm(
            s, actor, rid, source="WEB"
        )
    after = _utcnow()
    assert response.reminder_id == rid
    assert response.user_id == _setup["user_a"]
    assert response.source == "WEB"
    assert response.reminder_status == "TOMADA"
    assert before <= response.taken_at <= after
    assert response.id is not None
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "TOMADA"
    assert await _intake_count(test_engine, rid) == 1


async def test_confirm_from_each_valid_state(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    actor = await _actor(session_factory, _setup["user_a"])
    for i, status in enumerate(
        ("PENDIENTE", "ENVIANDO", "ENVIADA", "FALLIDA")
    ):
        rid = await _seed_reminder(
            test_engine,
            _setup["chain"],
            now - timedelta(seconds=10 + i),
            status,
        )
        async with session_factory() as s:
            response = await intake_service.confirm(
                s, actor, rid, source="WEB"
            )
        assert response.reminder_id == rid
        assert (await _reminder_row(test_engine, rid))["status"] == "TOMADA"
        assert await _intake_count(test_engine, rid) == 1


async def test_confirm_twice_returns_the_same_intake(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    actor = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        first = await intake_service.confirm(s, actor, rid, source="WEB")
    async with session_factory() as s:
        second = await intake_service.confirm(s, actor, rid, source="WEB")
    assert first.id == second.id
    assert first.taken_at == second.taken_at
    assert await _intake_count(test_engine, rid) == 1
    assert (await _reminder_row(test_engine, rid))["status"] == "TOMADA"


async def test_confirm_from_invalid_states_is_409(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    actor = await _actor(session_factory, _setup["user_a"])
    for i, status in enumerate(("POSPUESTA", "PERDIDA", "CANCELADA")):
        rid = await _seed_reminder(
            test_engine,
            _setup["chain"],
            now - timedelta(seconds=10 + i),
            status,
            cancel_reason="TREATMENT_CANCELLED" if status == "CANCELADA" else None,
        )
        async with session_factory() as s:
            with pytest.raises(HTTPException) as exc:
                await intake_service.confirm(s, actor, rid, source="WEB")
        assert exc.value.status_code == 409
        assert await _intake_count(test_engine, rid) == 0
        assert (await _reminder_row(test_engine, rid))["status"] == status


async def test_confirm_missing_is_404(test_engine, session_factory, _setup) -> None:
    actor = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await intake_service.confirm(s, actor, 999999999, source="WEB")
    assert exc.value.status_code == 404


async def test_confirm_other_users_reminder_is_403(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    # C (extrano, sin vinculo) intenta confirmar la dosis de A.
    actor = await _actor(session_factory, _setup["user_c"])
    async with session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await intake_service.confirm(s, actor, rid, source="WEB")
    assert exc.value.status_code == 403
    assert await _intake_count(test_engine, rid) == 0
    assert (await _reminder_row(test_engine, rid))["status"] == "ENVIADA"
    # Sin auditoria: C no es cuidador de A.
    assert (
        await _audit_denied_count(
            test_engine,
            caregiver_id=_setup["user_c"],
            patient_id=_setup["user_a"],
        )
        == 0
    )


async def test_caregiver_confirm_is_403_with_audit(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    # B es cuidador ACTIVO de A: 403 y registro ACCESS_DENIED.
    actor = await _actor(session_factory, _setup["user_b"])
    async with session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await intake_service.confirm(s, actor, rid, source="WEB")
    assert exc.value.status_code == 403
    assert await _intake_count(test_engine, rid) == 0
    assert (await _reminder_row(test_engine, rid))["status"] == "ENVIADA"
    assert (
        await _audit_denied_count(
            test_engine,
            caregiver_id=_setup["user_b"],
            patient_id=_setup["user_a"],
        )
        == 1
    )


# ------------------------------------------------------------------
# Posponer
# ------------------------------------------------------------------


async def test_postpone_creates_child(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    actor = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        response = await intake_service.postpone(
            s, actor, rid, delay_minutes=15, now=now
        )
    assert response.original.id == rid
    assert response.original.status == "POSPUESTA"
    assert response.child.parent_reminder_id == rid
    assert response.child.status == "PENDIENTE"
    assert response.child.postponed_count == 1
    assert response.child.scheduled_at == now + timedelta(minutes=15)
    assert response.child.schedule_id == _setup["chain"]["schedule_id"]
    assert response.child.treatment_medication_id == _setup["chain"]["link_id"]
    assert response.child.user_id == _setup["user_a"]
    row = await _reminder_row(test_engine, rid)
    assert row["status"] == "POSPUESTA"
    child_row = await _reminder_row(test_engine, response.child.id)
    assert child_row["status"] == "PENDIENTE"
    assert child_row["parent_reminder_id"] == rid


async def test_postpone_delays_30_and_60(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    actor = await _actor(session_factory, _setup["user_a"])
    for i, delay in enumerate((30, 60)):
        rid = await _seed_reminder(
            test_engine,
            _setup["chain"],
            now - timedelta(seconds=10 + i),
            "ENVIADA",
        )
        async with session_factory() as s:
            response = await intake_service.postpone(
                s, actor, rid, delay_minutes=delay, now=now
            )
        assert response.child.scheduled_at == now + timedelta(minutes=delay)


async def test_postpone_twice_second_is_409(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    actor = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        first = await intake_service.postpone(
            s, actor, rid, delay_minutes=15, now=now
        )
    assert first.child.status == "PENDIENTE"
    async with session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await intake_service.postpone(
                s, actor, rid, delay_minutes=15, now=now
            )
    assert exc.value.status_code == 409
    assert await _children_count(test_engine, rid) == 1
    assert (await _reminder_row(test_engine, rid))["status"] == "POSPUESTA"


async def test_postpone_child_creates_grandchild(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    actor = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        first = await intake_service.postpone(
            s, actor, rid, delay_minutes=15, now=now
        )
    child_id = first.child.id
    async with session_factory() as s:
        second = await intake_service.postpone(
            s, actor, child_id, delay_minutes=30, now=now
        )
    assert second.original.id == child_id
    assert second.original.status == "POSPUESTA"
    assert second.child.parent_reminder_id == child_id
    assert second.child.postponed_count == 2
    assert second.child.scheduled_at == now + timedelta(minutes=30)
    assert await _children_count(test_engine, child_id) == 1


async def test_postpone_from_invalid_states_is_409(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    actor = await _actor(session_factory, _setup["user_a"])
    for i, status in enumerate(("TOMADA", "POSPUESTA", "PERDIDA", "CANCELADA")):
        rid = await _seed_reminder(
            test_engine,
            _setup["chain"],
            now - timedelta(seconds=10 + i),
            status,
            cancel_reason="TREATMENT_CANCELLED" if status == "CANCELADA" else None,
        )
        async with session_factory() as s:
            with pytest.raises(HTTPException) as exc:
                await intake_service.postpone(
                    s, actor, rid, delay_minutes=15, now=now
                )
        assert exc.value.status_code == 409
        assert await _children_count(test_engine, rid) == 0
        assert (await _reminder_row(test_engine, rid))["status"] == status


async def test_postpone_collision_is_409_without_changes(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    chain = _setup["chain"]
    # B ocupa el instante al que caeria el hijo (now + 15 min).
    first_id = await _seed_reminder(
        test_engine, chain, now - timedelta(seconds=10), "PENDIENTE"
    )
    second_id = await _seed_reminder(
        test_engine, chain, now + timedelta(minutes=15), "PENDIENTE"
    )
    actor = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await intake_service.postpone(
                s, actor, first_id, delay_minutes=15, now=now
            )
    assert exc.value.status_code == 409
    # Rollback completo: el original sigue PENDIENTE y no hay hijo.
    assert (await _reminder_row(test_engine, first_id))["status"] == "PENDIENTE"
    assert (await _reminder_row(test_engine, second_id))["status"] == "PENDIENTE"
    assert await _children_count(test_engine, first_id) == 0


async def test_caregiver_postpone_is_403_with_audit(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )
    actor = await _actor(session_factory, _setup["user_b"])
    async with session_factory() as s:
        with pytest.raises(HTTPException) as exc:
            await intake_service.postpone(
                s, actor, rid, delay_minutes=15, now=now
            )
    assert exc.value.status_code == 403
    assert await _children_count(test_engine, rid) == 0
    assert (await _reminder_row(test_engine, rid))["status"] == "ENVIADA"
    assert (
        await _audit_denied_count(
            test_engine,
            caregiver_id=_setup["user_b"],
            patient_id=_setup["user_a"],
        )
        == 1
    )


# ------------------------------------------------------------------
# Concurrencia
# ------------------------------------------------------------------


async def test_concurrent_confirms_create_one_intake(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )

    async def _confirm_once():
        actor = await _actor(session_factory, _setup["user_a"])
        async with session_factory() as s:
            return await intake_service.confirm(s, actor, rid, source="WEB")

    first, second = await asyncio.gather(_confirm_once(), _confirm_once())
    assert first.id == second.id
    assert first.taken_at == second.taken_at
    assert await _intake_count(test_engine, rid) == 1
    assert (await _reminder_row(test_engine, rid))["status"] == "TOMADA"


async def test_concurrent_confirm_and_postpone_only_one_wins(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )

    async def _confirm_once():
        actor = await _actor(session_factory, _setup["user_a"])
        async with session_factory() as s:
            return await intake_service.confirm(s, actor, rid, source="WEB")

    async def _postpone_once():
        actor = await _actor(session_factory, _setup["user_a"])
        async with session_factory() as s:
            return await intake_service.postpone(
                s, actor, rid, delay_minutes=15, now=now
            )

    results = await asyncio.gather(
        _confirm_once(), _postpone_once(), return_exceptions=True
    )
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], HTTPException)
    assert failures[0].status_code == 409
    intakes = await _intake_count(test_engine, rid)
    children = await _children_count(test_engine, rid)
    assert intakes + children == 1
    status = (await _reminder_row(test_engine, rid))["status"]
    assert status in ("TOMADA", "POSPUESTA")
    assert (intakes == 1 and status == "TOMADA") or (
        children == 1 and status == "POSPUESTA"
    )


async def test_concurrent_postpones_create_one_child(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    rid = await _seed_reminder(
        test_engine, _setup["chain"], now - timedelta(seconds=10), "ENVIADA"
    )

    async def _postpone_once():
        actor = await _actor(session_factory, _setup["user_a"])
        async with session_factory() as s:
            return await intake_service.postpone(
                s, actor, rid, delay_minutes=15, now=now
            )

    results = await asyncio.gather(
        _postpone_once(), _postpone_once(), return_exceptions=True
    )
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], HTTPException)
    assert failures[0].status_code == 409
    assert await _children_count(test_engine, rid) == 1
    assert (await _reminder_row(test_engine, rid))["status"] == "POSPUESTA"


# ------------------------------------------------------------------
# Aislamiento entre usuarios
# ------------------------------------------------------------------


async def test_users_are_isolated(
    test_engine, session_factory, _setup
) -> None:
    now = _utcnow()
    chain_a = _setup["chain"]
    chain_b = await _seed_chain(test_engine, _setup["user_b"])
    rid_a = await _seed_reminder(
        test_engine, chain_a, now - timedelta(seconds=10), "ENVIADA"
    )
    rid_b = await _seed_reminder(
        test_engine, chain_b, now - timedelta(seconds=20), "ENVIADA"
    )
    actor_a = await _actor(session_factory, _setup["user_a"])
    async with session_factory() as s:
        response = await intake_service.confirm(s, actor_a, rid_a, source="WEB")
    assert response.reminder_id == rid_a
    # La dosis de B sigue intacta: ni toma ni cambio de estado.
    assert await _intake_count(test_engine, rid_b) == 0
    assert (await _reminder_row(test_engine, rid_b))["status"] == "ENVIADA"
    assert await _intake_count(test_engine, rid_a) == 1
