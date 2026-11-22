"""Seccion "Proximas tomas" (demostracion).

Muestra las proximas tomas ficticias, ordenadas por hora, con
medicamento, dosis y tratamiento. A proposito NO incluye los
botones "✅ YA LO TOMÉ" ni "⏰ RECORDARME DESPUÉS": esos botones
pertenecen a la experiencia futura de recordatorios (Fases 5 y
6) y pulsarlos debe crear un registro real. En esta entrega de
demostracion no se simulan registros reales, asi que la pantalla
solo explica que esos botones apareceran en la version final.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE, list_upcoming_intakes


def render_upcoming() -> tuple[str, object]:
    """Proximas tomas ficticias, ordenadas por hora."""
    lines = ["⏰ Próximas tomas", "", DEMO_NOTICE, ""]
    for intake in list_upcoming_intakes():
        lines.append(f"• {intake.time} — {intake.medication_name} — {intake.dose_text}")
        lines.append(f"  Tratamiento: {intake.treatment_name}")
    lines.append("")
    lines.append(
        "En la versión final, cada toma tendrá los botones "
        "✅ YA LO TOMÉ y ⏰ RECORDARME DESPUÉS."
    )
    return "\n".join(lines), with_home([])


async def show_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra las proximas tomas (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_upcoming()
    await query.edit_message_text(text, reply_markup=keyboard)
