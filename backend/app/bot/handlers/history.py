"""Seccion "Mi historial" (demostracion).

Muestra tomas pasadas ficticias con fecha, hora y origen
(``WEB`` o ``TELEGRAM``), incluidas las perdidas. El porcentaje
de cumplimiento es de la Fase 7 (RF14): el bot lo mostrara
cuando esa fase exista, no antes.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE, list_history


def render_history() -> tuple[str, object]:
    """Historial ficticio, el mas reciente primero."""
    lines = ["📋 Mi historial", "", DEMO_NOTICE, ""]
    for entry in list_history():
        lines.append(
            f"• {entry.date} {entry.time} — {entry.medication_name} "
            f"({entry.origin}): {entry.result}"
        )
    lines.append("")
    lines.append("El porcentaje de cumplimiento llegará con la Fase 7.")
    return "\n".join(lines), with_home([])


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el historial (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_history()
    await query.edit_message_text(text, reply_markup=keyboard)
