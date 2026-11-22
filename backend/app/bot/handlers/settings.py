"""Seccion "Configuracion" (demostracion).

Muestra los ajustes ficticios actuales (zona horaria y avisos).
Cambiar la zona horaria recalcula solo los recordatorios
``PENDIENTE`` futuros (RNF04) y silenciar avisos solo retrasa
su envio: ambas acciones son de fases posteriores y en esta
demostracion no cambian nada.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE


def render_settings() -> tuple[str, object]:
    """Ajustes ficticios actuales."""
    text = (
        "⚙️ Configuración\n\n"
        f"{DEMO_NOTICE}\n\n"
        "🕐 Mi zona horaria: America/Bogota\n"
        "🔔 Avisos: activados\n\n"
        "En la versión final podrás cambiar tu zona horaria y "
        "silenciar los avisos por hoy desde aquí."
    )
    return text, with_home([])


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la configuracion (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_settings()
    await query.edit_message_text(text, reply_markup=keyboard)
