"""Seccion "Necesito ayuda" y comando /help (demostracion).

Ayuda de uso del bot, en lenguaje sencillo. No es soporte
medico: nunca da consejos de salud, solo explica como usar
el bot.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import with_home
from app.bot.services.mock_data import DEMO_NOTICE

HELP_TEXT = (
    "🆘 Necesito ayuda\n\n"
    "Soy DosisAlerta, tu ayudante de medicamentos.\n\n"
    "• Usa los botones para moverte, no hace falta escribir.\n"
    "• En «Próximas tomas» verás tus medicamentos de hoy.\n"
    "• En «Mi historial» verás las tomas que ya registraste.\n"
    "• Para vincular Telegram, usa la página web de DosisAlerta.\n\n"
    "No doy consejos de salud. Si te sientes mal, contacta con "
    "tu médico o con tu cuidador.\n\n"
    f"{DEMO_NOTICE}"
)


def render_help() -> tuple[str, object]:
    """Texto de ayuda y teclado con el boton de inicio."""
    return HELP_TEXT, with_home([])


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la ayuda (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text, keyboard = render_help()
    await query.edit_message_text(text, reply_markup=keyboard)


async def show_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la ayuda con el comando /help."""
    if update.message is None:
        return
    text, keyboard = render_help()
    await update.message.reply_text(text, reply_markup=keyboard)
