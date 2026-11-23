"""Acciones sobre un recordatorio desde el bot (Fase 6, RF11/RF12/RF17).

Callbacks del aviso y de «Próximas tomas»:

- ``intake:confirm:<id>`` — ✅ YA LO TOMÉ: registra la toma con
  `source=TELEGRAM` (el mismo servicio que la web, RF11). La
  toma aparece en la API web sin ninguna accion adicional.
- ``intake:postpone:<id>`` — ⏰ RECORDARME DESPUÉS: muestra el
  selector de retraso (15, 30 o 60 minutos).
- ``intake:delay:<id>:<min>`` — pospone el recordatorio (RF12):
  el original queda POSPUESTA y nace un hijo.

Idempotencia (spec §3.4): confirmar dos veces devuelve la toma
existente sin crear otra; el mensaje se edita tras confirmar
para que no se pueda pulsar dos veces con efecto. Solo el
paciente confirma o pospone: un cuidador recibe 403 del
servicio (sin permiso de confirmacion) y el bot responde con un
mensaje generico.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

_DELAYS = (15, 30, 60)


def _local_time(when: datetime, timezone: str) -> str:
    """Hora local del usuario (HH:MM) en su zona."""
    return when.astimezone(ZoneInfo(timezone)).strftime("%H:%M")


def _parse_reminder_id(data: str, prefix: str) -> int | None:
    """El id numerico tras el prefijo, o None si no es valido."""
    rest = data.removeprefix(prefix)
    if not rest.isdigit():
        return None
    return int(rest)


def _delay_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Selector de retraso (15, 30 o 60 minutos)."""
    rows = [
        [
            InlineKeyboardButton(
                f"⏰ En {minutes} minutos",
                callback_data=f"intake:delay:{reminder_id}:{minutes}",
            )
        ]
        for minutes in _DELAYS
    ]
    rows.append(
        [InlineKeyboardButton("❌ Cancelar", callback_data="menu:reminders")]
    )
    return InlineKeyboardMarkup(rows)


def intake_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Botones del aviso: YA LO TOMÉ y RECORDARME DESPUÉS."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ YA LO TOMÉ",
                    callback_data=f"intake:confirm:{reminder_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⏰ RECORDARME DESPUÉS",
                    callback_data=f"intake:postpone:{reminder_id}",
                )
            ],
        ]
    )


async def confirm_intake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirma la toma (boton YA LO TOMÉ)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    reminder_id = _parse_reminder_id(query.data or "", "intake:confirm:")
    if reminder_id is None:
        await query.edit_message_text("No encontré ese recordatorio.")
        return
    from app.services import intake_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            intake = await intake_service.confirm(
                session, user, reminder_id, source="TELEGRAM"
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", "")
            if status == 409:
                await query.edit_message_text(f"⚠️ {detail}")
            elif status == 404:
                await query.edit_message_text("No encontré ese recordatorio.")
            elif status == 403:
                await query.edit_message_text(
                    "No tienes permiso para confirmar esta toma."
                )
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        taken = _local_time(intake.taken_at, user.timezone)
        await query.edit_message_text(f"✓ Tomada a las {taken}.")


async def ask_postpone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el selector de retraso (boton RECORDARME DESPUÉS)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    reminder_id = _parse_reminder_id(query.data or "", "intake:postpone:")
    if reminder_id is None:
        await query.edit_message_text("No encontré ese recordatorio.")
        return
    await query.edit_message_text(
        "¿Cuándo quieres que te lo recuerde?",
        reply_markup=_delay_keyboard(reminder_id),
    )


async def postpone_intake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pospone la toma el retraso elegido (boton de 15/30/60)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("intake:delay:")
    parts = rest.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await query.edit_message_text("No encontré ese recordatorio.")
        return
    reminder_id = int(parts[0])
    delay = int(parts[1])
    if delay not in _DELAYS:
        await query.edit_message_text("Ese retraso no es válido.")
        return
    from app.services import intake_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            result = await intake_service.postpone(
                session, user, reminder_id, delay_minutes=delay
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", "")
            if status == 409:
                await query.edit_message_text(f"⚠️ {detail}")
            elif status == 404:
                await query.edit_message_text("No encontré ese recordatorio.")
            elif status == 403:
                await query.edit_message_text(
                    "No tienes permiso para posponer esta toma."
                )
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        child_at = _local_time(result.child.scheduled_at, user.timezone)
        await query.edit_message_text(
            f"⏰ Pospuesta {delay} minutos. Te avisaré a las {child_at}.",
            reply_markup=with_home([]),
        )
