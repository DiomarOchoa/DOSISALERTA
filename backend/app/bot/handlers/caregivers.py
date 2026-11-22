"""Seccion "Mi familiar o cuidador" (demostracion).

Muestra un cuidador ficticio y explica que puede ver y hacer.
La vinculacion real (codigo de un solo uso + aceptacion
explicita, 8 permisos independientes, revocacion) es de la
Fase 6 y usa los servicios centrales: en esta demostracion no
se invita ni se revoca a nadie de verdad.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE, get_caregiver_demo


def render_caregivers() -> tuple[str, object]:
    """Cuidador ficticio y explicacion de la funcion."""
    caregiver = get_caregiver_demo()
    text = (
        "👨‍👩‍👧 Mi familiar o cuidador\n\n"
        f"{DEMO_NOTICE}\n\n"
        f"• {caregiver.name} — {caregiver.relation}\n"
        f"  {caregiver.permissions_text}\n\n"
        "En la versión final podrás invitar a un cuidador con un "
        "código, elegir qué puede ver y hacer, y revocar su acceso "
        "cuando quieras. El cuidador nunca podrá cambiar tus dosis "
        "ni suspender tus tratamientos."
    )
    return text, with_home([])


async def show_caregivers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la seccion del cuidador (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_caregivers()
    await query.edit_message_text(text, reply_markup=keyboard)
