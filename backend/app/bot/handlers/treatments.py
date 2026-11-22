"""Seccion "Mis tratamientos" (demostracion).

Muestra la lista ficticia de tratamientos y el detalle de cada
uno. En la version final (Fase 6) esta pantalla usara el mismo
servicio que la web (RF18): crear, pausar, reanudar y cancelar
tratamientos, siempre con confirmacion antes de cambiar algo.
En la demostracion no se cambia nada: solo se navega.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE, get_treatment, list_treatments


def render_treatments() -> tuple[str, object]:
    """Lista ficticia de tratamientos con un boton por cada uno."""
    lines = ["🗂️ Mis tratamientos", "", DEMO_NOTICE, ""]
    rows: list[list[InlineKeyboardButton]] = []
    for treatment in list_treatments():
        lines.append(f"• {treatment.name} — {treatment.status}")
        rows.append(
            [InlineKeyboardButton(f"Ver {treatment.name}", callback_data=f"treat:{treatment.id}")]
        )
    lines.append("")
    lines.append("En la versión final podrás crear, pausar y cancelar tratamientos aquí.")
    return "\n".join(lines), with_home(rows)


def render_treatment_detail(treatment_id: str) -> tuple[str, object]:
    """Detalle ficticio de un tratamiento."""
    treatment = get_treatment(treatment_id)
    if treatment is None:
        text = "No encontré ese tratamiento.\n\n" + DEMO_NOTICE
        rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton("⬅️ Mis tratamientos", callback_data="menu:treatments")]
        ]
        return text, with_home(rows)
    text = (
        f"🗂️ {treatment.name}\n\n"
        f"Estado: {treatment.status}\n"
        f"Inicio: {treatment.start_date}\n"
        f"Medicamentos: {treatment.medications_text}\n\n"
        f"{DEMO_NOTICE}"
    )
    rows = [[InlineKeyboardButton("⬅️ Mis tratamientos", callback_data="menu:treatments")]]
    return text, with_home(rows)


async def show_treatments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de tratamientos (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_treatments()
    await query.edit_message_text(text, reply_markup=keyboard)


async def show_treatment_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el detalle de un tratamiento (boton "Ver ...")."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    treatment_id = (query.data or "").removeprefix("treat:")
    text, keyboard = render_treatment_detail(treatment_id)
    await query.edit_message_text(text, reply_markup=keyboard)
