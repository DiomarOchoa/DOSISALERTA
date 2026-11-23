"""Seccion "Mi historial" (Fase 6, RF16/RF13).

Muestra las tomas registradas reales del usuario, las mas
recientes primero, con fecha, hora y origen (WEB o TELEGRAM),
incluidas las perdidas y las pospuestas. Usa el mismo servicio
que la web (RF13, D-10): todos los estados, sin inventar nada.

El porcentaje de cumplimiento es de la Fase 7 (RF14) y ya existe
en la web; el bot lo muestra como resumen cuando hay datos.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

_STATUS_LABEL = {
    "PENDIENTE": "Pendiente",
    "ENVIANDO": "Enviando",
    "ENVIADA": "Enviada",
    "TOMADA": "Tomada",
    "POSPUESTA": "Pospuesta",
    "PERDIDA": "Perdida",
    "CANCELADA": "Cancelada",
    "FALLIDA": "Fallida",
}


def _when_text(scheduled_at: datetime, user_timezone: str) -> str:
    """Fecha y hora locales (DD/MM HH:MM)."""
    local = scheduled_at.astimezone(ZoneInfo(user_timezone))
    return local.strftime("%d/%m %H:%M")


def _entry_text(item, user_timezone: str) -> str:
    """Una linea del historial."""
    when = _when_text(item.scheduled_at, user_timezone)
    label = _STATUS_LABEL.get(item.status, item.status)
    text = f"• {when} — {item.medication_name} ({item.dose_amount} {item.dose_unit}): {label}"
    if item.status == "TOMADA" and item.taken_at is not None:
        taken = item.taken_at.astimezone(ZoneInfo(user_timezone)).strftime("%H:%M")
        origin = item.source or "—"
        text += f" a las {taken} ({origin})"
    elif item.status == "TOMADA":
        text += " (sin hora registrada)"
    return text


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Historial real (boton del menu o /historial)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    from app.services import stats_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        page = await stats_service.get_history(session, user, limit=15, offset=0)
        lines = ["📋 Mi historial", ""]
        if not page.items:
            lines.append("Aún no tienes tomas registradas.")
        else:
            for item in page.items:
                lines.append(_entry_text(item, user.timezone))
            if page.total > len(page.items):
                lines.append("")
                lines.append(
                    f"Mostrando {len(page.items)} de {page.total}. "
                    "El historial completo está en la web."
                )
        text = "\n".join(lines)
        keyboard = with_home([])
        if query is not None:
            await query.edit_message_text(text, reply_markup=keyboard)
        elif update.message is not None:
            await update.message.reply_text(text, reply_markup=keyboard)
