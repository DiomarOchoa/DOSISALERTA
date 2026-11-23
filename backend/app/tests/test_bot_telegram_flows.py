"""Pruebas de los flujos del bot de Telegram (Fase 6, RF15–RF19).

Contra PostgreSQL real, en la base de pruebas aislada
(`dosisalerta_test`) creada vacia y migrada con Alembic, igual
que la Fase 3. La base de desarrollo (`dosisalerta`) no recibe
filas de prueba: la siembra se hace con sesiones que confirman
(para que las sesiones propias de los handlers, en conexiones
distintas, vean las filas) y cada prueba borra sus filas al
final (por usuario unico).

Los handlers se llaman directamente con actualizaciones de
Telegram simuladas (``MagicMock``/``AsyncMock``), sin tocar la
red: la sesion que abre `linked_session` se dirige a la base de
pruebas mediante `app.database.AsyncSessionLocal`.

Criterios que se verifican (aceptacion de la Fase 6):
- /vincular con un codigo valido vincula la cuenta (RF15).
- Un codigo invalido devuelve el mensaje generico y queda
  registrado el intento (RF15).
- /start y las secciones muestran datos reales del usuario
  vinculado (RF16).
- Confirmar desde el boton crea la toma con source TELEGRAM y
  la toma aparece en el historial que sirve la API (RF11).
- Posponer desde el boton crea el hijo y marca POSPUESTA el
  original (RF12).
- Un chat sin vincular no recibe ningun dato (RF19).
- /vincular_cuidador registra el intento y deja el vinculo
  INVITADO pendiente de aceptacion (RF20).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.database as app_database
from app.core.config import get_settings
from app.models.caregivers import (
    CaregiverAuditLog,
    CaregiverLink,
    CaregiverLinkAttempt,
)
from app.models.medications import Medication, Treatment, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.models.schedules import MedicationSchedule
from app.models.telegram import TelegramAccount, TelegramLinkAttempt
from app.models.users import User
from app.bot.handlers import (
    caregivers as caregivers_handler,
)
from app.bot.handlers import (
    history as history_handler,
)
from app.bot.handlers import (
    intake as intake_handler,
)
from app.bot.handlers import (
    link as link_handler,
)
from app.bot.handlers import (
    medications as medications_handler,
)
from app.bot.handlers import (
    menu as menu_handler,
)
from app.bot.handlers import (
    reminders as reminders_handler,
)
from app.bot.handlers import (
    settings as settings_handler,
)
from app.bot.handlers import (
    start as start_handler,
)
from app.bot.handlers import (
    treatments as treatments_handler,
)
from app.services import caregiver_service, telegram_link_service

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "dosisalerta_test"
BOGOTA = "America/Bogota"

_CHAT_COUNTER = [100000]


def _next_chat_id() -> int:
    _CHAT_COUNTER[0] += 1
    return _CHAT_COUNTER[0]


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


@pytest_asyncio.fixture(autouse=True)
async def _bot_test_sessions(monkeypatch, test_engine):
    """Las sesiones del bot apuntan a la base de pruebas."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(app_database, "AsyncSessionLocal", factory)
    yield


# ------------------------------------------------------------------
# Siembra y limpieza
# ------------------------------------------------------------------


def _unique_email(prefix: str = "botflow") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _seed_user(test_engine, prefix: str = "botflow") -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            name="Prueba Bot",
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
            "medication_id": med.id,
            "treatment_id": treatment.id,
        }


async def _seed_reminder(
    test_engine, chain: dict, when: datetime, status: str
) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = MedicationReminder(
            schedule_id=chain["schedule_id"],
            treatment_medication_id=chain["link_id"],
            user_id=chain["user_id"],
            scheduled_at=when,
            status=status,
        )
        s.add(row)
        await s.flush()
        await s.commit()
        return row.id


async def _seed_telegram_account(
    test_engine, user_id: int, telegram_user_id: int, chat_id: int
) -> int:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        account = TelegramAccount(
            user_id=user_id,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            username="prueba_bot",
            status="VINCULADA",
            linked_at=_utcnow(),
        )
        s.add(account)
        await s.flush()
        await s.commit()
        return account.id


async def _cleanup_user(test_engine, user_id: int, chat_ids: list[int]) -> None:
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
        await s.execute(
            delete(TelegramAccount).where(TelegramAccount.user_id == user_id)
        )
        if chat_ids:
            await s.execute(
                delete(TelegramLinkAttempt).where(
                    TelegramLinkAttempt.chat_id.in_(chat_ids)
                )
            )
            await s.execute(
                delete(CaregiverLinkAttempt).where(
                    CaregiverLinkAttempt.chat_id.in_(chat_ids)
                )
            )
        await s.execute(delete(User).where(User.id == user_id))
        await s.commit()


async def _reminder_row(test_engine, reminder_id: int) -> dict | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(
                MedicationReminder.status,
                MedicationReminder.parent_reminder_id,
                MedicationReminder.postponed_count,
                MedicationReminder.scheduled_at,
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
        }


async def _intake_row(test_engine, reminder_id: int) -> dict | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        row = await s.execute(
            select(MedicationIntake.source, MedicationIntake.taken_at)
            .where(MedicationIntake.reminder_id == reminder_id)
            .order_by(MedicationIntake.id)
        )
        found = row.one_or_none()
        if found is None:
            return None
        return {"source": found[0], "taken_at": found[1]}


async def _children(test_engine, parent_id: int) -> list[dict]:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        rows = await s.execute(
            select(MedicationReminder.id, MedicationReminder.scheduled_at)
            .where(MedicationReminder.parent_reminder_id == parent_id)
            .order_by(MedicationReminder.id)
        )
        return [
            {"id": r[0], "scheduled_at": r[1]} for r in rows.all()
        ]


async def _user_row(test_engine, user_id: int) -> User | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        return await s.get(User, user_id)


async def _account_row(test_engine, user_id: int) -> TelegramAccount | None:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        result = await s.execute(
            select(TelegramAccount).where(TelegramAccount.user_id == user_id)
        )
        return result.scalar_one_or_none()


async def _link_attempts(test_engine, chat_id: int, table) -> list:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        result = await s.execute(
            select(table).where(table.chat_id == chat_id).order_by(table.id)
        )
        return list(result.scalars().all())


def _today_0800_bogota() -> datetime:
    """Hoy a las 08:00 en Bogota, en UTC (siempre en la ventana)."""
    tz = ZoneInfo(BOGOTA)
    today = datetime.now(tz).date()
    return datetime.combine(today, time(8, 0), tzinfo=tz).astimezone(timezone.utc)


# ------------------------------------------------------------------
# Actualizaciones de Telegram simuladas
# ------------------------------------------------------------------


def _base_update(chat_id: int, telegram_user_id: int) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = telegram_user_id
    update.effective_user.username = "prueba_bot"
    return update


def _message_update(
    chat_id: int, telegram_user_id: int, text: str
) -> tuple[MagicMock, AsyncMock]:
    """Actualizacion de mensaje de texto (comandos y texto libre)."""
    update = _base_update(chat_id, telegram_user_id)
    message = AsyncMock()
    message.text = text
    message.chat.id = chat_id
    update.message = message
    update.callback_query = None
    update.effective_message = message
    return update, message


def _callback_update(
    chat_id: int, telegram_user_id: int, data: str
) -> tuple[MagicMock, AsyncMock]:
    """Actualizacion de boton (callback_query)."""
    update = _base_update(chat_id, telegram_user_id)
    query = AsyncMock()
    query.data = data
    query.message.chat.id = chat_id
    update.callback_query = query
    update.message = None
    update.effective_message = query.message
    return update, query


def _context(*, args: list[str] | None = None) -> MagicMock:
    context = MagicMock()
    context.args = args or []
    context.user_data = {}
    return context


async def _setup_patient(test_engine) -> dict:
    """Paciente con cadena, toma PENDIENTE hoy 08:00 y cuenta vinculada."""
    user_id = await _seed_user(test_engine, "botflow-paciente")
    chain = await _seed_chain(test_engine, user_id)
    reminder_id = await _seed_reminder(
        test_engine, chain, _today_0800_bogota(), "PENDIENTE"
    )
    chat_id = _next_chat_id()
    telegram_user_id = chat_id
    await _seed_telegram_account(test_engine, user_id, telegram_user_id, chat_id)
    return {
        "user_id": user_id,
        "chain": chain,
        "reminder_id": reminder_id,
        "chat_id": chat_id,
        "telegram_user_id": telegram_user_id,
    }


# ------------------------------------------------------------------
# Vinculacion (RF15)
# ------------------------------------------------------------------


async def test_vincular_con_codigo_valido_vincula_la_cuenta(test_engine):
    """RF15: /vincular CODIGO vincula la cuenta de Telegram."""
    user_id = await _seed_user(test_engine, "botflow-link")
    chat_id = _next_chat_id()
    telegram_user_id = chat_id
    code = None
    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            user = await s.get(User, user_id)
            response = await telegram_link_service.create_link_code(s, user)
            code = response.code
        update, message = _message_update(
            chat_id, telegram_user_id, f"/vincular {code}"
        )
        await link_handler.handle_vincular(update, _context(args=[code]))
        text = message.reply_text.await_args.args[0]
        assert "Cuenta vinculada" in text
        account = await _account_row(test_engine, user_id)
        assert account is not None
        assert account.status == "VINCULADA"
        assert account.chat_id == chat_id
        assert account.telegram_user_id == telegram_user_id
    finally:
        await _cleanup_user(test_engine, user_id, [chat_id])


async def test_vincular_con_codigo_invalido_no_vincula_y_registra_intento(
    test_engine,
):
    """RF15: un codigo invalido da el mensaje generico y queda registrado."""
    user_id = await _seed_user(test_engine, "botflow-link-bad")
    chat_id = _next_chat_id()
    telegram_user_id = chat_id
    try:
        update, message = _message_update(
            chat_id, telegram_user_id, "/vincular AAAAAAAAAA"
        )
        await link_handler.handle_vincular(update, _context(args=["AAAAAAAAAA"]))
        text = message.reply_text.await_args.args[0]
        assert "Código no válido o expirado" in text
        account = await _account_row(test_engine, user_id)
        assert account is None
        attempts = await _link_attempts(test_engine, chat_id, TelegramLinkAttempt)
        assert len(attempts) == 1
        assert attempts[0].success is False
    finally:
        await _cleanup_user(test_engine, user_id, [chat_id])


async def test_vincular_sin_codigo_explica_como_conseguirlo():
    """/vincular sin codigo explica donde generarlo, sin tocar la BD."""
    update, message = _message_update(999001, 999001, "/vincular")
    await link_handler.handle_vincular(update, _context(args=[]))
    text = message.reply_text.await_args.args[0]
    assert "/vincular CÓDIGO" in text


# ------------------------------------------------------------------
# Menu y secciones con datos reales (RF16)
# ------------------------------------------------------------------


async def test_start_vinculado_muestra_bienvenida_y_menu(test_engine):
    """RF16: /start en un chat vinculado muestra la bienvenida y el menu."""
    setup = await _setup_patient(test_engine)
    try:
        update, message = _message_update(
            setup["chat_id"], setup["telegram_user_id"], "/start"
        )
        await start_handler.start(update, _context())
        message.reply_text.assert_awaited_once()
        text = message.reply_text.await_args.args[0]
        keyboard = message.reply_text.await_args.kwargs["reply_markup"]
        assert "DosisAlerta" in text
        assert "demostración" not in text
        assert len(keyboard.inline_keyboard) == 7
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_upcoming_muestra_tomas_reales_con_botones(test_engine):
    """RF16/RF09: Proximas tomas muestra la toma real con sus botones."""
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"], setup["telegram_user_id"], "menu:reminders"
        )
        await reminders_handler.show_upcoming(update, _context())
        query.edit_message_text.assert_awaited_once()
        text = query.edit_message_text.await_args.args[0]
        keyboard = query.edit_message_text.await_args.kwargs["reply_markup"]
        assert "Próximas tomas" in text
        assert "Paracetamol" in text
        assert "08:00" in text
        datas = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        assert f"intake:confirm:{setup['reminder_id']}" in datas
        assert f"intake:postpone:{setup['reminder_id']}" in datas
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_medicamentos_muestra_lista_real(test_engine):
    """RF16: Mis medicamentos muestra el medicamento real."""
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"], setup["telegram_user_id"], "menu:medications"
        )
        await medications_handler.show_medications(update, _context())
        text = query.edit_message_text.await_args.args[0]
        assert "Mis medicamentos" in text
        assert "Paracetamol" in text
        assert "demostración" not in text
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_historial_muestra_tomas_registradas(test_engine):
    """RF16/RF13: Mi historial muestra las tomas con su estado."""
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"], setup["telegram_user_id"], "menu:history"
        )
        await history_handler.show_history(update, _context())
        text = query.edit_message_text.await_args.args[0]
        assert "Mi historial" in text
        assert "Paracetamol" in text
        assert "Pendiente" in text
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


# ------------------------------------------------------------------
# Confirmar y posponer desde el boton (RF11/RF12, aceptacion Fase 6)
# ------------------------------------------------------------------


async def test_confirm_desde_boton_crea_toma_telegram_visible_en_historial(
    test_engine,
):
    """RF11: confirmar desde el boton crea la toma (TELEGRAM).

    Aceptacion de la Fase 6: la toma aparece en el historial que
    sirve la API web (mismo servicio, misma base de datos).
    """
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"],
            setup["telegram_user_id"],
            f"intake:confirm:{setup['reminder_id']}",
        )
        await intake_handler.confirm_intake(update, _context())
        text = query.edit_message_text.await_args.args[0]
        assert "Tomada" in text
        row = await _reminder_row(test_engine, setup["reminder_id"])
        assert row is not None
        assert row["status"] == "TOMADA"
        intake = await _intake_row(test_engine, setup["reminder_id"])
        assert intake is not None
        assert intake["source"] == "TELEGRAM"
        assert intake["taken_at"] is not None
        # El historial que sirve la API la muestra como TOMADA/TELEGRAM.
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            from app.services import stats_service

            user = await s.get(User, setup["user_id"])
            page = await stats_service.get_history(s, user, limit=10, offset=0)
        assert page.total >= 1
        item = next(
            i for i in page.items if i.id == setup["reminder_id"]
        )
        assert item.status == "TOMADA"
        assert item.source == "TELEGRAM"
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_confirm_dos_veces_crea_una_sola_toma(test_engine):
    """RF11/spec §3.4: confirmar dos veces es idempotente."""
    setup = await _setup_patient(test_engine)
    try:
        for _ in range(2):
            update, query = _callback_update(
                setup["chat_id"],
                setup["telegram_user_id"],
                f"intake:confirm:{setup['reminder_id']}",
            )
            await intake_handler.confirm_intake(update, _context())
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            count = await s.execute(
                select(func.count())
                .select_from(MedicationIntake)
                .where(MedicationIntake.reminder_id == setup["reminder_id"])
            )
            assert count.scalar_one() == 1
        row = await _reminder_row(test_engine, setup["reminder_id"])
        assert row["status"] == "TOMADA"
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_postpone_desde_boton_crea_hijo_y_marca_original(test_engine):
    """RF12: posponer desde el boton crea el hijo (+30 min)."""
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"],
            setup["telegram_user_id"],
            f"intake:postpone:{setup['reminder_id']}",
        )
        await intake_handler.ask_postpone(update, _context())
        text = query.edit_message_text.await_args.args[0]
        keyboard = query.edit_message_text.await_args.kwargs["reply_markup"]
        datas = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        assert f"intake:delay:{setup['reminder_id']}:15" in datas
        assert f"intake:delay:{setup['reminder_id']}:30" in datas
        assert f"intake:delay:{setup['reminder_id']}:60" in datas

        before = _utcnow()
        update, query = _callback_update(
            setup["chat_id"],
            setup["telegram_user_id"],
            f"intake:delay:{setup['reminder_id']}:30",
        )
        await intake_handler.postpone_intake(update, _context())
        after = _utcnow()
        text = query.edit_message_text.await_args.args[0]
        assert "Pospuesta 30 minutos" in text
        row = await _reminder_row(test_engine, setup["reminder_id"])
        assert row["status"] == "POSPUESTA"
        # El contador de la cadena sube en el hijo, no en el original.
        assert row["postponed_count"] == 0
        children = await _children(test_engine, setup["reminder_id"])
        assert len(children) == 1
        # El hijo se programa en ahora + 30 min ("recuerdame en 30").
        assert before + timedelta(minutes=29) <= children[0][
            "scheduled_at"
        ] <= after + timedelta(minutes=31)
        child = await _reminder_row(test_engine, children[0]["id"])
        assert child["status"] == "PENDIENTE"
        assert child["postponed_count"] == 1
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


# ------------------------------------------------------------------
# Rechazo de chats sin vincular (RF19)
# ------------------------------------------------------------------


async def test_chat_sin_vincular_no_recibe_datos(test_engine):
    """RF19: un chat sin vincular no ve medicamentos ni tomas."""
    setup = await _setup_patient(test_engine)
    unknown_chat = _next_chat_id()
    try:
        update, query = _callback_update(
            unknown_chat, unknown_chat, "menu:reminders"
        )
        await reminders_handler.show_upcoming(update, _context())
        # El handler responde con el mensaje de vinculacion, no
        # con datos: lo hace editando el mensaje del callback.
        query.edit_message_text.assert_awaited_once()
        text = query.edit_message_text.await_args.args[0]
        assert "vincula" in text.lower()
        assert "Paracetamol" not in text
        assert "08:00" not in text
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_start_sin_vincular_recibe_prompt_de_vinculacion():
    """RF19: /start sin vincular explica como vincular, sin datos."""
    update, message = _message_update(999002, 999002, "/start")
    await start_handler.start(update, _context())
    message.reply_text.assert_awaited_once()
    text = message.reply_text.await_args.args[0]
    assert "vincula" in text.lower()
    assert "DosisAlerta" in text


# ------------------------------------------------------------------
# Cuidadores desde el bot (RF20)
# ------------------------------------------------------------------


async def test_vincular_cuidador_registra_intento_y_deja_invitado(test_engine):
    """RF20: /vincular_cuidador con codigo valido deja el vinculo INVITADO."""
    patient_id = await _seed_user(test_engine, "botflow-paciente-cg")
    caregiver_id = await _seed_user(test_engine, "botflow-cuidador-cg")
    chat_id = _next_chat_id()
    telegram_user_id = chat_id
    code = None
    try:
        await _seed_telegram_account(
            test_engine, caregiver_id, telegram_user_id, chat_id
        )
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            patient = await s.get(User, patient_id)
            invite = await caregiver_service.create_invite(s, patient)
            code = invite.invite_code
        update, message = _message_update(
            chat_id, telegram_user_id, f"/vincular_cuidador {code}"
        )
        await link_handler.handle_vincular_cuidador(
            update, _context(args=[code])
        )
        text = message.reply_text.await_args.args[0]
        assert "Código aceptado" in text
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            result = await s.execute(
                select(CaregiverLink).where(
                    CaregiverLink.patient_user_id == patient_id
                )
            )
            link = result.scalar_one()
        assert link.status == "INVITADO"
        assert link.caregiver_user_id == caregiver_id
        attempts = await _link_attempts(test_engine, chat_id, CaregiverLinkAttempt)
        assert len(attempts) == 1
        assert attempts[0].success is True
    finally:
        await _cleanup_user(test_engine, patient_id, [chat_id])
        await _cleanup_user(test_engine, caregiver_id, [chat_id])


async def test_vincular_cuidador_codigo_invalido_registra_intento(test_engine):
    """RF20: un codigo de cuidador invalido da el mensaje generico."""
    caregiver_id = await _seed_user(test_engine, "botflow-cuidador-bad")
    chat_id = _next_chat_id()
    telegram_user_id = chat_id
    try:
        await _seed_telegram_account(
            test_engine, caregiver_id, telegram_user_id, chat_id
        )
        update, message = _message_update(
            chat_id, telegram_user_id, "/vincular_cuidador AAAAAAAAAA"
        )
        await link_handler.handle_vincular_cuidador(
            update, _context(args=["AAAAAAAAAA"])
        )
        text = message.reply_text.await_args.args[0]
        assert "Código no válido o expirado" in text
        attempts = await _link_attempts(test_engine, chat_id, CaregiverLinkAttempt)
        assert len(attempts) == 1
        assert attempts[0].success is False
        assert attempts[0].reason == "INVALIDO"
    finally:
        await _cleanup_user(test_engine, caregiver_id, [chat_id])


async def test_caregivers_muestra_vinculos_reales(test_engine):
    """RF20: la seccion de cuidadores muestra el vinculo real."""
    patient_id = await _seed_user(test_engine, "botflow-paciente-list")
    caregiver_id = await _seed_user(test_engine, "botflow-cuidador-list")
    chat_id = _next_chat_id()
    telegram_user_id = chat_id
    try:
        await _seed_telegram_account(
            test_engine, patient_id, telegram_user_id, chat_id
        )
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            s.add(
                CaregiverLink(
                    patient_user_id=patient_id,
                    caregiver_user_id=caregiver_id,
                    status="ACTIVO",
                    invited_by=patient_id,
                    accepted_at=_utcnow(),
                )
            )
            await s.commit()
        update, query = _callback_update(
            chat_id, telegram_user_id, "menu:caregivers"
        )
        await caregivers_handler.show_caregivers(update, _context())
        text = query.edit_message_text.await_args.args[0]
        assert "Mi familiar o cuidador" in text
        assert "Prueba Bot" in text
        assert "ACTIVO" in text
    finally:
        await _cleanup_user(test_engine, patient_id, [chat_id])
        await _cleanup_user(test_engine, caregiver_id, [chat_id])


# ------------------------------------------------------------------
# Creacion guiada, tratamientos y configuracion (RF18/RF03)
# ------------------------------------------------------------------


async def test_crear_medicamento_guiado_completo(test_engine):
    """RF18: la creacion guiada crea el medicamento con el servicio web."""
    setup = await _setup_patient(test_engine)
    context = _context()
    try:
        update, query = _callback_update(
            setup["chat_id"], setup["telegram_user_id"], "med:create"
        )
        await medications_handler.start_create(update, context)
        text = query.edit_message_text.await_args.args[0]
        assert "Nuevo medicamento" in text

        steps = [
            ("Ibuprofeno", "Presentación"),
            ("—", "Concentración"),
            ("—", "Unidad"),
            ("—", "Alguna nota"),
            ("—", "Revisa los datos"),
        ]
        for answer, expected in steps:
            update, message = _message_update(
                setup["chat_id"], setup["telegram_user_id"], answer
            )
            consumed = await medications_handler.handle_create_text(
                update, context
            )
            assert consumed is True
            text = message.reply_text.await_args.args[0]
            assert expected in text
        assert "Ibuprofeno" in text

        update, query = _callback_update(
            setup["chat_id"], setup["telegram_user_id"], "med:create_confirm"
        )
        await medications_handler.confirm_create(update, context)
        text = query.edit_message_text.await_args.args[0]
        assert "Ibuprofeno" in text
        assert "creado" in text
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            result = await s.execute(
                select(Medication).where(
                    Medication.user_id == setup["user_id"],
                    Medication.name == "Ibuprofeno",
                )
            )
            assert result.scalar_one_or_none() is not None
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_tratamiento_pausar_desde_boton(test_engine):
    """RF18: pausar un tratamiento desde el boton cambia su estado."""
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"],
            setup["telegram_user_id"],
            f"treat:pause_confirm:{setup['chain']['treatment_id']}",
        )
        await treatments_handler.confirm_status_change(update, _context())
        text = query.edit_message_text.await_args.args[0]
        assert "pausado" in text
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            treatment = await s.get(
                Treatment, setup["chain"]["treatment_id"]
            )
        assert treatment.status == "PAUSADO"
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_cambiar_zona_horaria_desde_boton(test_engine):
    """RF03: cambiar la zona desde el boton actualiza el perfil."""
    setup = await _setup_patient(test_engine)
    try:
        update, query = _callback_update(
            setup["chat_id"],
            setup["telegram_user_id"],
            "tz:set:America/Mexico_City",
        )
        await settings_handler.set_timezone(update, _context())
        text = query.edit_message_text.await_args.args[0]
        assert "America/Mexico_City" in text
        user = await _user_row(test_engine, setup["user_id"])
        assert user.timezone == "America/Mexico_City"
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )


async def test_menu_texto_libre_muestra_menu_vinculado(test_engine):
    """RF16: escribir texto libre en un chat vinculado muestra el menu."""
    setup = await _setup_patient(test_engine)
    try:
        update, message = _message_update(
            setup["chat_id"], setup["telegram_user_id"], "hola"
        )
        context = _context()
        await menu_handler.handle_text(update, context)
        message.reply_text.assert_awaited_once()
        text = message.reply_text.await_args.args[0]
        assert "Menú principal" in text
    finally:
        await _cleanup_user(
            test_engine, setup["user_id"], [setup["chat_id"]]
        )
