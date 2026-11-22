"""Comando /start: bienvenida y menu principal.

El usuario nunca necesita escribir comandos para usar el bot:
``/start`` es solo la puerta de entrada. A partir de ahi todo
se hace con botones.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import build_main_menu
from app.bot.services.mock_data import DEMO_NOTICE


def render_welcome() -> tuple[str, object]:
    """Texto de bienvenida y teclado del menu principal."""
    text = (
        "¡Hola! Soy DosisAlerta, tu ayudante de medicamentos.\n\n"
        "👇 Elige una opción:\n\n"
        f"{DEMO_NOTICE}"
    )
    return text, build_main_menu()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responde a /start con la bienvenida y el menu principal."""
    if update.message is None:
        return
    text, keyboard = render_welcome()
    await update.message.reply_text(text, reply_markup=keyboard)
