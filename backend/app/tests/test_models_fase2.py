"""Pruebas de la Fase 2 contra PostgreSQL real.

No basta con que los modelos importen: las restricciones se
prueban contra PostgreSQL real, en una base de datos de pruebas
(`dosisalerta_test`) creada vacia y migrada con Alembic, para
probar tambien la migracion desde una base limpia. La base de
desarrollo (`dosisalerta`) no recibe filas de prueba: cada prueba
corre dentro de una transaccion que se revierte al final.

Cobertura (alcance autorizado de la Fase 2, §7):
creacion y relaciones, integridad referencial, aislamiento entre
usuarios, CHECK, UNIQUE e indices parciales, estados de
invitacion y revocacion, invitaciones pendientes con cuidador
NULL, revinculacion con fila nueva, auditoria antes y despues de
aceptar, rechazo de operaciones que violan las reglas de
permisos, JSONB y migracion desde base limpia.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import (
    CAREGIVER_PERMISSIONS,
    CaregiverAuditLog,
    CaregiverLink,
    Medication,
    MedicationIntake,
    MedicationReminder,
    MedicationSchedule,
    NotificationLog,
    RefreshToken,
    TelegramAccount,
    TelegramLinkAttempt,
    Treatment,
    TreatmentMedication,
    User,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"


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
    """Crea la base de pruebas vacia y aplica la migracion inicial."""
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
    # NullPool: cada conexion se crea en el bucle del test que la
    # usa y se cierra al devolverla. Con el pool por defecto, una
    # conexion creada en el bucle de un test se reutilizaria en el
    # bucle de otro (pytest-asyncio crea uno por test) y asyncpg
    # rechaza la operacion ("another operation is in progress").
    return create_async_engine(_test_url(), poolclass=NullPool)


@pytest_asyncio.fixture
async def session(test_engine):
    """Sesion por prueba, dentro de una transaccion que se revierte."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        sess = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield sess
        finally:
            await sess.close()
            await trans.rollback()


# ------------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------------


async def _flush(session: AsyncSession) -> None:
    await session.flush()


async def assert_integrity_error(session: AsyncSession, build) -> None:
    """Ejecuta `build()` dentro de un savepoint: debe fallar por
    restriccion de base de datos, y la sesion debe seguir usable."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            build()
            await session.flush()


async def make_user(session: AsyncSession, email: str) -> User:
    user = User(name="Prueba", email=email, password_hash="hash")
    session.add(user)
    await _flush(session)
    return user


async def make_chain(session: AsyncSession, user: User):
    """Medicamento + tratamiento + vinculo + horario + recordatorio."""
    med = Medication(user_id=user.id, name="Amoxicilina")
    session.add(med)
    treatment = Treatment(
        user_id=user.id, title="Infeccion", start_date=date(2026, 11, 11)
    )
    session.add(treatment)
    await _flush(session)
    link = TreatmentMedication(
        user_id=user.id,
        treatment_id=treatment.id,
        medication_id=med.id,
        dose_amount=1,
        dose_unit="capsula",
    )
    session.add(link)
    await _flush(session)
    schedule = MedicationSchedule(
        user_id=user.id,
        treatment_medication_id=link.id,
        frequency="DIARIO",
        times=[time(8, 0), time(20, 0)],
        start_date=date(2026, 11, 11),
    )
    session.add(schedule)
    await _flush(session)
    reminder = MedicationReminder(
        schedule_id=schedule.id,
        treatment_medication_id=link.id,
        user_id=user.id,
        scheduled_at=datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc),
    )
    session.add(reminder)
    await _flush(session)
    return med, treatment, link, schedule, reminder


# ------------------------------------------------------------------
# 1. Migracion desde base limpia y tablas existentes
# ------------------------------------------------------------------


async def test_migration_creates_13_tables(session: AsyncSession):
    rows = await session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "AND table_name <> 'alembic_version' ORDER BY table_name"
        )
    )
    tables = [row[0] for row in rows]
    assert tables == [
        "caregiver_audit_log",
        "caregiver_links",
        "medication_intakes",
        "medication_reminders",
        "medication_schedules",
        "medications",
        "notification_logs",
        "refresh_tokens",
        "telegram_accounts",
        "telegram_link_attempts",
        "treatment_medications",
        "treatments",
        "users",
    ]
    assert "caregiver_link_attempts" not in tables


async def test_alembic_version_is_head(session: AsyncSession):
    rows = await session.execute(text("SELECT version_num FROM alembic_version"))
    assert [row[0] for row in rows] == ["f2a17166bccd"]


# ------------------------------------------------------------------
# 2. Creacion y relaciones
# ------------------------------------------------------------------


async def test_create_full_chain_and_relationships(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    med, treatment, link, schedule, reminder = await make_chain(session, user)

    intake = MedicationIntake(
        reminder_id=reminder.id,
        user_id=user.id,
        taken_at=datetime(2026, 11, 11, 8, 5, tzinfo=timezone.utc),
        source="TELEGRAM",
    )
    session.add(intake)
    await _flush(session)

    # En async hay que cargar las relaciones con selectinload: el
    # acceso perezoso sincrono no funciona sin greenlet.
    stmt = (
        select(MedicationReminder)
        .where(MedicationReminder.id == reminder.id)
        .options(
            selectinload(MedicationReminder.intake),
            selectinload(MedicationReminder.schedule),
            selectinload(MedicationReminder.treatment_medication).selectinload(
                TreatmentMedication.treatment
            ),
            selectinload(MedicationReminder.treatment_medication).selectinload(
                TreatmentMedication.medication
            ),
        )
    )
    loaded = (await session.execute(stmt)).scalar_one()
    assert loaded.intake is not None
    assert loaded.intake.source == "TELEGRAM"
    assert loaded.schedule.id == schedule.id
    assert loaded.treatment_medication.dose_unit == "capsula"
    assert loaded.treatment_medication.treatment.title == "Infeccion"
    assert loaded.treatment_medication.medication.name == "Amoxicilina"

    user_stmt = (
        select(User)
        .where(User.id == user.id)
        .options(
            selectinload(User.medications),
            selectinload(User.treatments),
        )
    )
    loaded_user = (await session.execute(user_stmt)).scalar_one()
    assert len(loaded_user.medications) == 1
    assert len(loaded_user.treatments) == 1


# ------------------------------------------------------------------
# 3. Integridad referencial y aislamiento entre usuarios
# ------------------------------------------------------------------


async def test_cross_user_treatment_medication_rejected(session: AsyncSession):
    user_a = await make_user(session, "a@example.com")
    user_b = await make_user(session, "b@example.com")
    _, treatment_a, _, _, _ = await make_chain(session, user_a)
    med_b = Medication(user_id=user_b.id, name="Ibuprofeno")
    session.add(med_b)
    await _flush(session)

    def build():
        session.add(
            TreatmentMedication(
                user_id=user_a.id,
                treatment_id=treatment_a.id,
                medication_id=med_b.id,
                dose_amount=1,
                dose_unit="tableta",
            )
        )

    await assert_integrity_error(session, build)


async def test_reminder_cross_user_rejected(session: AsyncSession):
    user_a = await make_user(session, "a@example.com")
    user_b = await make_user(session, "b@example.com")
    _, _, _, schedule_a, _ = await make_chain(session, user_a)
    _, _, link_b, _, _ = await make_chain(session, user_b)

    def build():
        session.add(
            MedicationReminder(
                schedule_id=schedule_a.id,
                treatment_medication_id=link_b.id,
                user_id=user_b.id,
                scheduled_at=datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc),
            )
        )

    await assert_integrity_error(session, build)


async def test_user_isolation_by_user_id(session: AsyncSession):
    user_a = await make_user(session, "a@example.com")
    user_b = await make_user(session, "b@example.com")
    await make_chain(session, user_a)
    await make_chain(session, user_b)

    rows = await session.execute(
        text("SELECT count(*) FROM medications WHERE user_id = :uid"),
        {"uid": user_a.id},
    )
    assert rows.scalar_one() == 1
    rows = await session.execute(
        text("SELECT count(*) FROM medications WHERE user_id = :uid"),
        {"uid": user_b.id},
    )
    assert rows.scalar_one() == 1


# ------------------------------------------------------------------
# 4. CHECK
# ------------------------------------------------------------------


async def test_treatment_status_check(session: AsyncSession):
    user = await make_user(session, "a@example.com")

    def build():
        session.add(
            Treatment(
                user_id=user.id,
                title="X",
                start_date=date(2026, 11, 11),
                status="INVALIDO",
            )
        )

    await assert_integrity_error(session, build)


async def test_treatment_end_date_check(session: AsyncSession):
    user = await make_user(session, "a@example.com")

    def build():
        session.add(
            Treatment(
                user_id=user.id,
                title="X",
                start_date=date(2026, 11, 11),
                end_date=date(2026, 11, 10),
            )
        )

    await assert_integrity_error(session, build)


async def test_dose_amount_must_be_positive(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    med, treatment, _, _, _ = await make_chain(session, user)

    def build():
        session.add(
            TreatmentMedication(
                user_id=user.id,
                treatment_id=treatment.id,
                medication_id=med.id,
                dose_amount=0,
                dose_unit="capsula",
            )
        )

    await assert_integrity_error(session, build)


async def test_schedule_frequency_and_interval_checks(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, link, _, _ = await make_chain(session, user)

    def bad_frequency():
        session.add(
            MedicationSchedule(
                user_id=user.id,
                treatment_medication_id=link.id,
                frequency="CADA_HORA",
                times=[time(8, 0)],
                start_date=date(2026, 11, 11),
            )
        )

    await assert_integrity_error(session, bad_frequency)

    def bad_interval():
        session.add(
            MedicationSchedule(
                user_id=user.id,
                treatment_medication_id=link.id,
                frequency="INTERVALO_DIAS",
                interval_days=0,
                times=[time(8, 0)],
                start_date=date(2026, 11, 11),
            )
        )

    await assert_integrity_error(session, bad_interval)


async def test_reminder_status_check(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, _, schedule, _ = await make_chain(session, user)
    _, _, link, _, _ = await make_chain(session, user)

    def build():
        session.add(
            MedicationReminder(
                schedule_id=schedule.id,
                treatment_medication_id=link.id,
                user_id=user.id,
                scheduled_at=datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc),
                status="DESCONOCIDO",
            )
        )

    await assert_integrity_error(session, build)


async def test_intake_source_check(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, _, _, reminder = await make_chain(session, user)

    def build():
        session.add(
            MedicationIntake(
                reminder_id=reminder.id,
                user_id=user.id,
                taken_at=datetime(2026, 11, 11, 8, 5, tzinfo=timezone.utc),
                source="SMS",
            )
        )

    await assert_integrity_error(session, build)


# ------------------------------------------------------------------
# 5. UNIQUE e indices parciales
# ------------------------------------------------------------------


async def test_unique_email(session: AsyncSession):
    await make_user(session, "dup@example.com")

    def build():
        session.add(User(name="Otro", email="dup@example.com", password_hash="x"))

    await assert_integrity_error(session, build)


async def test_unique_reminder_schedule_time(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, link, schedule, _ = await make_chain(session, user)

    def build():
        session.add(
            MedicationReminder(
                schedule_id=schedule.id,
                treatment_medication_id=link.id,
                user_id=user.id,
                scheduled_at=datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc),
            )
        )

    await assert_integrity_error(session, build)


async def test_unique_intake_per_reminder(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, _, _, reminder = await make_chain(session, user)
    session.add(
        MedicationIntake(
            reminder_id=reminder.id,
            user_id=user.id,
            taken_at=datetime(2026, 11, 11, 8, 5, tzinfo=timezone.utc),
            source="WEB",
        )
    )
    await _flush(session)

    def build():
        session.add(
            MedicationIntake(
                reminder_id=reminder.id,
                user_id=user.id,
                taken_at=datetime(2026, 11, 11, 8, 6, tzinfo=timezone.utc),
                source="WEB",
            )
        )

    await assert_integrity_error(session, build)


async def test_partial_unique_active_treatment_medication(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    med, treatment, link, _, _ = await make_chain(session, user)

    def build_duplicate_active():
        session.add(
            TreatmentMedication(
                user_id=user.id,
                treatment_id=treatment.id,
                medication_id=med.id,
                dose_amount=2,
                dose_unit="capsula",
            )
        )

    await assert_integrity_error(session, build_duplicate_active)

    # Tras desactivar el vinculo, un vinculo nuevo si cabe.
    link.is_active = False
    await _flush(session)
    session.add(
        TreatmentMedication(
            user_id=user.id,
            treatment_id=treatment.id,
            medication_id=med.id,
            dose_amount=2,
            dose_unit="capsula",
        )
    )
    await _flush(session)


# ------------------------------------------------------------------
# 6. Cuidadores: invitacion, aceptacion, revocacion, revinculacion
# ------------------------------------------------------------------


async def make_invite(session: AsyncSession, patient: User) -> CaregiverLink:
    link = CaregiverLink(
        patient_user_id=patient.id,
        caregiver_user_id=None,
        status="INVITADO",
        invite_code_hash="a" * 64,
        invite_expires_at=datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc),
        invited_by=patient.id,
    )
    session.add(link)
    await _flush(session)
    return link


async def test_pending_invite_with_null_caregiver(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")
    link = await make_invite(session, patient)
    assert link.caregiver_user_id is None
    assert link.status == "INVITADO"
    assert link.accepted_at is None
    assert link.revoked_at is None


async def test_caregiver_accept_flow(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")
    caregiver = await make_user(session, "cuidador@example.com")
    link = await make_invite(session, patient)

    # Al presentar el codigo se vincula la identidad del cuidador.
    link.caregiver_user_id = caregiver.id
    link.status = "ACTIVO"
    link.accepted_at = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
    link.invite_code_hash = None
    link.invite_expires_at = None
    link.perm_view_medications = True
    await _flush(session)

    loaded = await session.get(CaregiverLink, link.id)
    assert loaded.status == "ACTIVO"
    assert loaded.caregiver_user_id == caregiver.id
    assert loaded.invite_code_hash is None


async def test_caregiver_activo_requires_caregiver(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")

    def build():
        session.add(
            CaregiverLink(
                patient_user_id=patient.id,
                caregiver_user_id=None,
                status="ACTIVO",
                invited_by=patient.id,
            )
        )

    await assert_integrity_error(session, build)


async def test_caregiver_self_link_rejected(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")

    def build():
        session.add(
            CaregiverLink(
                patient_user_id=patient.id,
                caregiver_user_id=patient.id,
                status="INVITADO",
                invited_by=patient.id,
            )
        )

    await assert_integrity_error(session, build)


async def test_caregiver_manage_requires_view(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")

    def build():
        session.add(
            CaregiverLink(
                patient_user_id=patient.id,
                status="INVITADO",
                perm_manage_medications=True,
                perm_view_medications=False,
                invited_by=patient.id,
            )
        )

    await assert_integrity_error(session, build)


async def test_caregiver_revoke_and_relink_new_row(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")
    caregiver = await make_user(session, "cuidador@example.com")
    link = await make_invite(session, patient)
    link.caregiver_user_id = caregiver.id
    link.status = "ACTIVO"
    link.accepted_at = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
    link.invite_code_hash = None
    link.invite_expires_at = None
    await _flush(session)

    # Revocar: la fila queda REVOCADA, con su historia intacta.
    link.status = "REVOCADO"
    link.revoked_at = datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)
    link.revoked_by = patient.id
    await _flush(session)

    # Revincular: fila NUEVA, nunca reactivar la anterior.
    new_link = await make_invite(session, patient)
    assert new_link.id != link.id
    old = await session.get(CaregiverLink, link.id)
    assert old.status == "REVOCADO"

    rows = await session.execute(
        text(
            "SELECT count(*) FROM caregiver_links "
            "WHERE patient_user_id = :p AND caregiver_user_id = :c "
            "AND status <> 'REVOCADO'"
        ),
        {"p": patient.id, "c": caregiver.id},
    )
    assert rows.scalar_one() == 0


async def test_caregiver_pending_unique_pair(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")
    caregiver = await make_user(session, "cuidador@example.com")
    session.add(
        CaregiverLink(
            patient_user_id=patient.id,
            caregiver_user_id=caregiver.id,
            status="INVITADO",
            invite_code_hash="b" * 64,
            invited_by=patient.id,
        )
    )
    await _flush(session)

    def build():
        session.add(
            CaregiverLink(
                patient_user_id=patient.id,
                caregiver_user_id=caregiver.id,
                status="INVITADO",
                invite_code_hash="c" * 64,
                invited_by=patient.id,
            )
        )

    await assert_integrity_error(session, build)


# ------------------------------------------------------------------
# 7. Auditoria de cuidadores y JSONB
# ------------------------------------------------------------------


async def test_caregiver_audit_before_accept(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")
    link = await make_invite(session, patient)
    session.add(
        CaregiverAuditLog(
            caregiver_user_id=None,
            patient_user_id=patient.id,
            action="INVITE_CREATED",
            result="OK",
        )
    )
    await _flush(session)
    assert link.status == "INVITADO"


async def test_caregiver_audit_after_accept_and_jsonb(session: AsyncSession):
    patient = await make_user(session, "paciente@example.com")
    caregiver = await make_user(session, "cuidador@example.com")
    session.add(
        CaregiverAuditLog(
            caregiver_user_id=caregiver.id,
            patient_user_id=patient.id,
            action="PERMISSION_GRANTED",
            target_type="permission",
            details={
                "permission": "perm_view_medications",
                "old": False,
                "new": True,
            },
            result="OK",
        )
    )
    await _flush(session)

    rows = await session.execute(
        text("SELECT details FROM caregiver_audit_log WHERE action = 'PERMISSION_GRANTED'")
    )
    details = rows.scalar_one()
    assert details == {
        "permission": "perm_view_medications",
        "old": False,
        "new": True,
    }
    # Minimizacion: nunca tokens, secretos ni dosis en la auditoria.
    assert "token" not in str(details).lower()
    assert "dosis" not in str(details).lower()


async def test_no_confirm_permission_exists():
    """No existe permiso para confirmar tomas: solo los 8 aprobados."""
    assert sorted(CAREGIVER_PERMISSIONS) == sorted(
        [
            "perm_view_medications",
            "perm_view_treatments",
            "perm_view_schedules",
            "perm_view_upcoming",
            "perm_view_history",
            "perm_receive_notifications",
            "perm_manage_medications",
            "perm_manage_schedules",
        ]
    )
    assert not hasattr(CaregiverLink, "perm_confirm_intakes")
    assert not hasattr(CaregiverLink, "perm_confirm")


# ------------------------------------------------------------------
# 8. Telegram y logs
# ------------------------------------------------------------------


async def test_telegram_account_unique_user_and_partial_unique(
    session: AsyncSession,
):
    user = await make_user(session, "a@example.com")
    session.add(TelegramAccount(user_id=user.id, telegram_user_id=111))
    await _flush(session)

    def build_second_account():
        session.add(TelegramAccount(user_id=user.id, telegram_user_id=222))

    await assert_integrity_error(session, build_second_account)

    # Dos cuentas sin telegram_user_id caben (el parcial solo aplica
    # cuando el valor no es NULL): una por usuario distinto.
    user2 = await make_user(session, "b@example.com")
    session.add(TelegramAccount(user_id=user2.id, telegram_user_id=None))
    await _flush(session)


async def test_telegram_link_attempt_without_user(session: AsyncSession):
    # Sin FK a users: se registra por chat_id aunque no exista.
    session.add(
        TelegramLinkAttempt(chat_id=999888, success=False, reason="INVALIDO")
    )
    await _flush(session)
    rows = await session.execute(
        text("SELECT count(*) FROM telegram_link_attempts WHERE chat_id = 999888")
    )
    assert rows.scalar_one() == 1


async def test_notification_log_enviada_requires_confirmation(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, _, _, reminder = await make_chain(session, user)

    def build_unconfirmed():
        session.add(
            NotificationLog(
                reminder_id=reminder.id,
                user_id=user.id,
                attempt_id=uuid.uuid4(),
                status="ENVIADA",
            )
        )

    await assert_integrity_error(session, build_unconfirmed)

    session.add(
        NotificationLog(
            reminder_id=reminder.id,
            user_id=user.id,
            attempt_id=uuid.uuid4(),
            sent_at=datetime(2026, 11, 11, 8, 1, tzinfo=timezone.utc),
            telegram_message_id=123,
            status="ENVIADA",
        )
    )
    await _flush(session)


async def test_notification_log_fallida_no_sent(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    _, _, _, _, reminder = await make_chain(session, user)

    def build():
        session.add(
            NotificationLog(
                reminder_id=reminder.id,
                user_id=user.id,
                attempt_id=uuid.uuid4(),
                sent_at=datetime(2026, 11, 11, 8, 1, tzinfo=timezone.utc),
                status="FALLIDA",
            )
        )

    await assert_integrity_error(session, build)


async def test_refresh_token_creation(session: AsyncSession):
    user = await make_user(session, "a@example.com")
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash="h" * 64,
            expires_at=datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc),
        )
    )
    await _flush(session)
    stmt = (
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.refresh_tokens))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    assert len(loaded.refresh_tokens) == 1
