"""Seccion "Mis medicamentos" (demostracion).

Muestra la lista ficticia de medicamentos y el detalle de cada
uno. En la version final (Fase 6) esta pantalla usara el mismo
servicio que la web para listar, crear, editar y desactivar
medicamentos (RF16, RF18). En la demostracion no se crea ni se
modifica nada: solo se navega.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE, get_medication, list_medications


def render_medications() -> tuple[str, object]:
    """Lista ficticia de medicamentos con un boton por cada uno."""
    lines = ["💊 Mis medicamentos", "", DEMO_NOTICE, ""]
    rows: list[list[InlineKeyboardButton]] = []
    for medication in list_medications():
        lines.append(f"• {medication.name} {medication.concentration} — {medication.dose_text}")
        rows.append(
            [InlineKeyboardButton(f"Ver {medication.name}", callback_data=f"med:{medication.id}")]
        )
    lines.append("")
    lines.append("En la versión final podrás añadir y editar tus medicamentos aquí.")
    return "\n".join(lines), with_home(rows)


def render_medication_detail(medication_id: str) -> tuple[str, object]:
    """Detalle ficticio de un medicamento."""
    medication = get_medication(medication_id)
    if medication is None:
        text = "No encontré ese medicamento.\n\n" + DEMO_NOTICE
        rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton("⬅️ Mis medicamentos", callback_data="menu:medications")]
        ]
        return text, with_home(rows)
    text = (
        f"💊 {medication.name} {medication.concentration}\n\n"
        f"Presentación: {medication.presentation}\n"
        f"Unidad: {medication.unit}\n"
        f"Dosis: {medication.dose_text}\n\n"
        f"{DEMO_NOTICE}"
    )
    rows = [[InlineKeyboardButton("⬅️ Mis medicamentos", callback_data="menu:medications")]]
    return text, with_home(rows)


async def show_medications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de medicamentos (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_medications()
    await query.edit_message_text(text, reply_markup=keyboard)


async def show_medication_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el detalle de un medicamento (boton "Ver ...")."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    medication_id = (query.data or "").removeprefix("med:")
    text, keyboard = render_medication_detail(medication_id)
    await query.edit_message_text(text, reply_markup=keyboard)
