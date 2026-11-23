"""Seccion "Proximas tomas" (Fase 6, RF16/RF09/RF11/RF12).

Muestra los proximos recordatorios reales del usuario, ordenados
por hora, con medicamento, dosis prescrita y tratamiento. Cada
toma lleva los botones "✅ Tomada" y "⏰ Posponer" (RF11, RF12):
pulsarlos registra la toma o la pospone con el mismo servicio
que la web, y la toma aparece en la API web sin ninguna accion
adicional.

Por defecto, las tomas de hoy y manana (en la zona del usuario).
Sin tomas, el mensaje lo dice sin inventar ninguna.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.handlers.intake import intake_keyboard
from app.bot.keyboards import with_home


def _local_day_bounds(user_timezone: str) -> tuple[datetime, datetime]:
    """[hoy 00:00, pasado manana 00:00) en la zona del usuario, en UTC."""
    tz = ZoneInfo(user_timezone)
    now_local = datetime.now(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=2)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _dose_text(dose_amount: Decimal, dose_unit: str) -> str:
    return f"{dose_amount.normalize():f} {dose_unit}"


def _when_text(scheduled_at: datetime, user_timezone: str) -> str:
    """'Hoy, 08:00' o 'Mañana, 08:00' o '12/11, 08:00'."""
    tz = ZoneInfo(user_timezone)
    local = scheduled_at.astimezone(tz)
    today = datetime.now(tz).date()
    if local.date() == today:
        day = "Hoy"
    elif local.date() == today + timedelta(days=1):
        day = "Mañana"
    else:
        day = local.strftime("%d/%m")
    return f"{day}, {local.strftime('%H:%M')}"


async def show_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra las proximas tomas reales (boton del menu o /proximas)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    from app.models.medications import Treatment
    from app.repositories import reminder_repository

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        from_dt, to_dt = _local_day_bounds(user.timezone)
        reminders = await reminder_repository.list_upcoming(
            session, user.id, from_dt, to_dt, limit=10
        )
        if not reminders:
            text = (
                "⏰ Próximas tomas\n\n"
                "No tienes tomas programadas para hoy ni mañana."
            )
            keyboard = with_home([])
        else:
            lines = ["⏰ Próximas tomas", ""]
            rows: list[list[InlineKeyboardButton]] = []
            for reminder in reminders:
                link = reminder.treatment_medication
                medication = link.medication
                treatment = await session.get(Treatment, link.treatment_id)
                title = treatment.title if treatment is not None else ""
                dose = _dose_text(link.dose_amount, link.dose_unit)
                med_line = medication.name
                if medication.concentration:
                    med_line += f" {medication.concentration}"
                lines.append(
                    f"• {_when_text(reminder.scheduled_at, user.timezone)} — "
                    f"{med_line} — {dose}"
                )
                if title:
                    lines.append(f"  Tratamiento: {title}")
                rows.append(
                    [
                        InlineKeyboardButton(
                            "✅ Tomada",
                            callback_data=f"intake:confirm:{reminder.id}",
                        ),
                        InlineKeyboardButton(
                            "⏰ Posponer",
                            callback_data=f"intake:postpone:{reminder.id}",
                        ),
                    ]
                )
            text = "\n".join(lines)
            keyboard = with_home(rows)
        if query is not None:
            await query.edit_message_text(text, reply_markup=keyboard)
        elif update.message is not None:
            await update.message.reply_text(text, reply_markup=keyboard)
